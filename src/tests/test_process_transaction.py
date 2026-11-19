"""Test process transaction behavior offline."""
import base64
import json
import uuid

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone


def _make_pubsub_request(payload: dict) -> MagicMock:
    """Build a request containing a base64-encoded Pub/Sub message."""
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    envelope = {
        "message": {
            "data": encoded,
            "messageId": "test-msg-" + str(uuid.uuid4())[:8],
            "publishTime": datetime.now(timezone.utc).isoformat(),
        },
        "subscription": "projects/test-project/subscriptions/test-sub",
    }
    req = MagicMock()
    req.get_json.return_value = envelope
    return req


def _make_bad_request(raw_envelope=None) -> MagicMock:
    """Return a request whose envelope is invalid."""
    req = MagicMock()
    req.get_json.return_value = raw_envelope
    return req


@pytest.fixture(autouse=True)
def mock_gcp_services(monkeypatch):
    """Replace cloud clients and install a deterministic test model."""
    import firestore_client
    monkeypatch.setattr(firestore_client, "_db", MagicMock())

    from sklearn.ensemble import IsolationForest
    import numpy as np
    data = np.array([
        [500,  14, 0, 2],
        [300,  10, 0, 1],
        [700,  16, 0, 3],
        [600,  12, 0, 2],
        [400,   9, 0, 1],
        [150000, 3, 1, 25],
        [120000, 2, 1, 20],
    ])
    tiny_model = IsolationForest(n_estimators=10, contamination=0.25, random_state=0)
    tiny_model.fit(data)

    import ai_model
    monkeypatch.setattr(ai_model, "_model", tiny_model)


@pytest.fixture()
def mock_write(monkeypatch):
    """Return a mock that replaces write_transaction and tracks calls."""
    import firestore_client
    m = MagicMock()
    monkeypatch.setattr(firestore_client, "write_transaction", m)
    return m


class TestHappyPath:
    def test_normal_tx_returns_200(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({
            "user_id": "u1", "amount": 500,
            "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2,
        })
        body, status = main.process_transaction(req)
        assert status == 200

    def test_write_called_once(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({
            "user_id": "u1", "amount": 500,
            "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2,
        })
        main.process_transaction(req)
        mock_write.assert_called_once()

    def test_normal_tx_goes_to_approved(self, mock_write):
        import worker_main as main
        from firestore_client import COLLECTION_APPROVED
        req = _make_pubsub_request({
            "user_id": "u1", "amount": 400,
            "hour_of_day": 10, "is_new_location": 0, "transaction_velocity": 1,
        })
        main.process_transaction(req)
        _, collection = mock_write.call_args[0]
        assert collection == COLLECTION_APPROVED

    def test_fraud_tx_goes_to_flagged(self, mock_write, monkeypatch):
        """Force is_flagged=True via the rule-based fallback."""
        import ai_model
        import worker_main as main
        from firestore_client import COLLECTION_FLAGGED
        monkeypatch.setattr(ai_model, "_model", None)   # use rule-based fallback
        req = _make_pubsub_request({
            "user_id": "u1", "amount": 150000,
            "hour_of_day": 3, "is_new_location": 1, "transaction_velocity": 20,
        })
        main.process_transaction(req)
        _, collection = mock_write.call_args[0]
        assert collection == COLLECTION_FLAGGED

    def test_transaction_id_auto_generated_when_missing(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert "transaction_id" in written_doc
        assert len(written_doc["transaction_id"]) == 36   # UUID format

    def test_provided_transaction_id_preserved(self, mock_write):
        import worker_main as main
        tid = "my-specific-uuid-abc"
        req = _make_pubsub_request({
            "transaction_id": tid, "user_id": "u1", "amount": 500,
        })
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert written_doc["transaction_id"] == tid

    def test_processed_at_timestamp_added(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert "processed_at" in written_doc

    def test_anomaly_score_added_to_document(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({
            "user_id": "u1", "amount": 500,
            "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2,
        })
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert "anomaly_score" in written_doc
        assert 0.0 <= written_doc["anomaly_score"] <= 1.0

    def test_is_flagged_field_is_bool(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert isinstance(written_doc["is_flagged"], bool)

    def test_pubsub_message_id_stored(self, mock_write):
        import worker_main as main
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert "pubsub_message_id" in written_doc


class TestMalformedMessages:
    def test_missing_envelope_returns_400(self):
        import worker_main as main
        req = _make_bad_request(raw_envelope=None)
        _, status = main.process_transaction(req)
        assert status == 400

    def test_envelope_without_message_key_returns_400(self):
        import worker_main as main
        req = _make_bad_request(raw_envelope={"subscription": "foo"})
        _, status = main.process_transaction(req)
        assert status == 400

    def test_invalid_base64_data_returns_200(self):
        """Acknowledge malformed base64 to prevent repeated delivery."""
        import worker_main as main
        req = MagicMock()
        req.get_json.return_value = {
            "message": {"data": "!!!not_valid_base64!!!", "messageId": "m1"},
            "subscription": "s",
        }
        _, status = main.process_transaction(req)
        assert status == 200

    def test_non_json_body_returns_200(self):
        """Acknowledge non-JSON messages without retrying."""
        import worker_main as main
        bad_data = base64.b64encode(b"this is not json").decode()
        req = MagicMock()
        req.get_json.return_value = {
            "message": {"data": bad_data, "messageId": "m1"},
            "subscription": "s",
        }
        _, status = main.process_transaction(req)
        assert status == 200

    def test_write_not_called_for_malformed_json(self, mock_write):
        import worker_main as main
        bad_data = base64.b64encode(b"not json").decode()
        req = MagicMock()
        req.get_json.return_value = {
            "message": {"data": bad_data, "messageId": "m1"},
            "subscription": "s",
        }
        main.process_transaction(req)
        mock_write.assert_not_called()


class TestErrorHandling:
    def test_firestore_failure_returns_500(self, mock_write):
        """Firestore error to 500 to Pub/Sub retries."""
        import worker_main as main
        mock_write.side_effect = Exception("Firestore unavailable")
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        _, status = main.process_transaction(req)
        assert status == 500

    def test_ai_scoring_failure_routes_to_flagged(self, mock_write, monkeypatch):
        """If AI scorer throws, message is safety-routed to Flagged."""
        import ai_model
        import worker_main as main
        from firestore_client import COLLECTION_FLAGGED

        def bad_scorer(tx):
            raise ValueError("model exploded")

        monkeypatch.setattr(ai_model, "score_transaction", bad_scorer)
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        main.process_transaction(req)
        _, collection = mock_write.call_args[0]
        assert collection == COLLECTION_FLAGGED

    def test_ai_failure_sets_score_error_field(self, mock_write, monkeypatch):
        import ai_model
        import worker_main as main

        def bad_scorer(tx):
            raise ValueError("boom")

        monkeypatch.setattr(ai_model, "score_transaction", bad_scorer)
        req = _make_pubsub_request({"user_id": "u1", "amount": 500})
        main.process_transaction(req)
        written_doc = mock_write.call_args[0][0]
        assert "score_error" in written_doc
        assert "boom" in written_doc["score_error"]


class TestIdempotency:
    def test_same_transaction_id_written_same_document(self, mock_write):
        """Reuse the document ID when a transaction is delivered twice."""
        import worker_main as main
        tid = "idempotency-test-uuid"
        payload = {"transaction_id": tid, "user_id": "u1", "amount": 500}

        main.process_transaction(_make_pubsub_request(payload))
        main.process_transaction(_make_pubsub_request(payload))

        assert mock_write.call_count == 2
        doc1 = mock_write.call_args_list[0][0][0]
        doc2 = mock_write.call_args_list[1][0][0]
        assert doc1["transaction_id"] == doc2["transaction_id"] == tid
