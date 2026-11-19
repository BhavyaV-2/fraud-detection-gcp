"""Score queued transactions and persist routing results in Firestore."""

import base64
import json
import logging
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone

import functions_framework

import ai_model
import firestore_client
from firestore_client import COLLECTION_APPROVED, COLLECTION_FLAGGED

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def process_transaction(request):
    """Handle a Pub/Sub push envelope and return its processing status."""
    try:
        envelope = request.get_json(silent=True)
        if not envelope or "message" not in envelope:
            logger.error("[worker] Invalid Pub/Sub envelope: %s", envelope)
            return ("Invalid Pub/Sub envelope", 400)

        pubsub_message = envelope["message"]
        raw_data = pubsub_message.get("data", "")
        message_id = pubsub_message.get("messageId", "unknown")

    except Exception as exc:
        logger.error("[worker] Failed to parse request: %s", exc)
        return ("Request parse error", 400)

    try:
        body_str = base64.b64decode(raw_data, validate=True).decode("utf-8")
        transaction = json.loads(body_str)
        if not isinstance(transaction, dict):
            raise ValueError("Expected a JSON object")
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("[worker] Cannot decode message %s: %s", message_id, exc)
        return ("Malformed message - acknowledged to prevent infinite retry", 200)

    if not transaction.get("transaction_id"):
        transaction["transaction_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, message_id))

    transaction["processed_at"]    = datetime.now(timezone.utc).isoformat()
    transaction["pubsub_message_id"] = message_id

    txn_id = transaction["transaction_id"]
    logger.info("[worker] Processing txn_id=%s", txn_id)

    try:
        transaction = ai_model.score_transaction(transaction)
    except Exception as exc:
        logger.error("[worker] AI scoring failed for %s: %s", txn_id, exc)
        transaction["anomaly_score"] = -1.0
        transaction["is_flagged"]    = True
        transaction["score_error"]   = str(exc)

    collection = COLLECTION_FLAGGED if transaction["is_flagged"] else COLLECTION_APPROVED

    try:
        firestore_client.write_transaction(transaction, collection)
    except Exception as exc:
        logger.error(
            "[worker] Firestore write failed for %s: %s - returning 500 to trigger retry",
            txn_id, exc,
        )
        return (f"Firestore write failed: {exc}", 500)

    outcome = "FLAGGED" if transaction["is_flagged"] else "APPROVED"
    logger.info(
        "%s [%s] txn_id=%s amount=%s score=%s",
        outcome, collection, txn_id,
        transaction.get("amount"),
        transaction.get("anomaly_score"),
    )

    return ("OK", 200)


@functions_framework.cloud_event
def process_transaction_event(cloud_event):
    """Process Eventarc Pub/Sub events and raise on retryable failures."""
    request = SimpleNamespace(get_json=lambda silent=True: cloud_event.data)
    body, status = process_transaction(request)
    if status >= 300:
        raise RuntimeError(body)
