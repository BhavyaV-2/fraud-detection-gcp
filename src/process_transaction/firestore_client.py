"""Write transaction documents using a cached Firestore client."""

import os
import logging

logger = logging.getLogger(__name__)

COLLECTION_APPROVED = "Approved_Transactions"
COLLECTION_FLAGGED = "Flagged_Transactions"

_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")

_db = None


def _get_db():
    """Return a cached Firestore client, creating it on first call."""
    global _db
    if _db is not None:
        return _db

    if not _PROJECT_ID:
        logger.warning(
            "[firestore] GCP_PROJECT_ID not set - writes will be logged only "
            "(local dev mode). Set GCP_PROJECT_ID in .env.local or Cloud Function env vars."
        )
        return None

    try:
        from google.cloud import firestore  # type: ignore
        _db = firestore.Client(project=_PROJECT_ID)
        logger.info("[firestore] Client initialised for project: %s", _PROJECT_ID)
    except Exception:
        logger.exception("[firestore] Failed to initialise client")
        raise

    return _db


def write_transaction(document: dict, collection_name: str) -> None:
    """Upsert a transaction by ID and propagate write failures."""
    db = _get_db()
    txn_id = document.get("transaction_id", "unknown")

    if db is None:
        logger.info(
            "[DEV] Would write to %s: id=%s score=%s flagged=%s",
            collection_name,
            txn_id,
            document.get("anomaly_score"),
            document.get("is_flagged"),
        )
        return

    try:
        doc_ref = db.collection(collection_name).document(txn_id)
        doc_ref.set(document)          # set() = upsert by document ID
        logger.info("[firestore] Written to %s: id=%s", collection_name, txn_id)
    except Exception as exc:
        logger.error(
            "[firestore] Write FAILED for %s / %s: %s",
            collection_name, txn_id, exc,
        )
        raise
