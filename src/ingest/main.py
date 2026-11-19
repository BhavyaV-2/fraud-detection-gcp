"""Validate HTTP transactions and publish them to Pub/Sub."""

import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone

import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"user_id", "amount"}

_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
_TOPIC_ID = os.environ.get("PUBSUB_TOPIC_ID", "transaction-topic")

_publisher = None
_topic_path = None


def _get_publisher():
    """Return a cached Pub/Sub publisher client."""
    global _publisher, _topic_path
    if _publisher is not None:
        return _publisher, _topic_path

    if not _PROJECT_ID:
        logger.warning(
            "[ingest] GCP_PROJECT_ID not set - running in dev/log-only mode. "
            "Messages will NOT be published to Pub/Sub."
        )
        return None, None

    try:
        from google.cloud import pubsub_v1  # type: ignore
        _publisher = pubsub_v1.PublisherClient()
        _topic_path = _publisher.topic_path(_PROJECT_ID, _TOPIC_ID)
        logger.info("[ingest] Pub/Sub publisher ready -> %s", _topic_path)
    except Exception:
        logger.exception("[ingest] Failed to create Pub/Sub publisher")
        raise

    return _publisher, _topic_path


@functions_framework.http
def ingest_transaction(request):
    """Validate a transaction and return its ingestion status."""
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin" : "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type",
        }
        return ("", 204, headers)

    response_headers = {"Access-Control-Allow-Origin": "*"}

    if request.method != "POST":
        return (json.dumps({"error": "Method not allowed"}), 405,
                {**response_headers, "Content-Type": "application/json", "Allow": "POST, OPTIONS"})

    try:
        body_bytes = request.get_data()
        body_str = body_bytes.decode("utf-8")
        transaction = json.loads(body_str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("[ingest] Invalid JSON: %s", exc)
        return (
            json.dumps({"error": "Invalid JSON", "detail": str(exc)}),
            400,
            {**response_headers, "Content-Type": "application/json"},
        )

    if not isinstance(transaction, dict):
        return (json.dumps({"error": "Expected a JSON object"}), 400,
                {**response_headers, "Content-Type": "application/json"})

    missing = REQUIRED_FIELDS - set(transaction.keys())
    if missing:
        logger.warning("[ingest] Missing fields: %s", missing)
        return (
            json.dumps({"error": "Missing required fields", "missing": sorted(missing)}),
            400,
            {**response_headers, "Content-Type": "application/json"},
        )

    try:
        if not isinstance(transaction["user_id"], str) or not transaction["user_id"].strip():
            raise ValueError("user_id must be a nonempty string")
        amount = transaction["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            raise ValueError("amount must be a finite nonnegative number")
        for field, low, high in (("hour_of_day", 0, 23), ("is_new_location", 0, 1),
                                 ("transaction_velocity", 0, None)):
            if field in transaction:
                value = transaction[field]
                if type(value) is not int or value < low or (high is not None and value > high):
                    raise ValueError(f"Invalid {field}")
        txn_id = transaction.get("transaction_id")
        if txn_id is not None and (not isinstance(txn_id, str) or not txn_id.strip()
                                   or "/" in txn_id or txn_id in (".", "..")
                                   or len(txn_id.encode("utf-8")) > 1500
                                   or (txn_id.startswith("__") and txn_id.endswith("__"))):
            raise ValueError("Invalid transaction_id")
    except (ValueError, OverflowError) as exc:
        return (json.dumps({"error": str(exc)}), 400,
                {**response_headers, "Content-Type": "application/json"})

    if not transaction.get("transaction_id"):
        transaction["transaction_id"] = str(uuid.uuid4())

    transaction["ingested_at"] = datetime.now(timezone.utc).isoformat()

    if "hour_of_day" not in transaction:
        transaction["hour_of_day"] = datetime.now(timezone.utc).hour

    txn_id = transaction["transaction_id"]

    try:
        publisher, topic_path = _get_publisher()
    except Exception:
        return (json.dumps({"error": "Queue unavailable"}), 503,
                {**response_headers, "Content-Type": "application/json"})

    if publisher is None:
        logger.info("[DEV] Would publish txn_id=%s amount=%s", txn_id, transaction["amount"])
    else:
        try:
            message_bytes = json.dumps(transaction).encode("utf-8")
            future = publisher.publish(topic_path, message_bytes)
            future.result(timeout=10)   # block until confirmed by GCP
            logger.info("[ingest] Published txn_id=%s to %s", txn_id, topic_path)
        except Exception as exc:
            logger.error("[ingest] Pub/Sub publish FAILED: %s", exc)
            return (
                json.dumps({"error": "Queue publish failed", "detail": str(exc)}),
                500,
                {**response_headers, "Content-Type": "application/json"},
            )

    return (
        json.dumps({
            "status": "accepted",
            "transaction_id": txn_id,
            "message": "Transaction queued for processing",
        }),
        202,
        {**response_headers, "Content-Type": "application/json"},
    )
