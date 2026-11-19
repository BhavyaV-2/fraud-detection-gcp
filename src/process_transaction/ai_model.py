"""Score transaction anomalies with Isolation Forest or fallback rules."""

import pickle
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")

try:
    with open(_MODEL_PATH, "rb") as _f:
        _model = pickle.load(_f)
    logger.info("[ai_model] Isolation Forest loaded from %s", _MODEL_PATH)
except FileNotFoundError:
    _model = None
    logger.warning(
        "[ai_model] model.pkl not found - using rule-based fallback scorer. "
        "Run src/train_model/train.py first."
    )

# This heuristic score is not a calibrated fraud probability.
THRESHOLD = 0.55


def _normalize(raw: float) -> float:
    """Clamp the inverted decision score to the range zero to one."""
    risk = 0.5 - raw
    return float(max(0.0, min(1.0, risk)))


def _rule_based_score(tx: dict) -> float:
    """Fallback when model.pkl is unavailable."""
    score = 0.0
    if float(tx.get("amount", 0)) > 50000:
        score += 0.4
    hour = int(tx.get("hour_of_day", 12))
    if hour < 5 or hour > 23:
        score += 0.2
    if int(tx.get("is_new_location", 0)):
        score += 0.2
    if int(tx.get("transaction_velocity", 1)) > 10:
        score += 0.2
    return min(score, 1.0)


def score_transaction(tx: dict) -> dict:
    """Add anomaly_score and is_flagged to the transaction."""
    if _model is not None:
        features = np.array([[
            float(tx.get("amount", 0)),
            float(tx.get("hour_of_day", 12)),
            float(tx.get("is_new_location", 0)),
            float(tx.get("transaction_velocity", 1)),
        ]])
        raw = _model.decision_function(features)[0]
        risk = _normalize(raw)
    else:
        risk = _rule_based_score(tx)

    tx["anomaly_score"] = round(risk, 4)
    tx["is_flagged"]    = bool(risk >= THRESHOLD)
    return tx
