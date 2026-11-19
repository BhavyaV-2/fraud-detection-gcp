"""Test ingest behavior offline."""

import json
import pytest
from unittest.mock import MagicMock, patch


class FakeRequest:
    def __init__(self, body: dict | str | bytes, method="POST"):
        if isinstance(body, dict):
            self._data = json.dumps(body).encode()
        elif isinstance(body, str):
            self._data = body.encode()
        else:
            self._data = body
        self.method = method

    def get_data(self):
        return self._data

    def get_json(self, silent=False):
        try:
            return json.loads(self._data)
        except Exception:
            return None


@pytest.fixture(autouse=True)
def mock_pubsub(monkeypatch):
    """Prevent any real GCP calls during tests."""
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("PUBSUB_TOPIC_ID", "test-topic")

    import ingest_main
    monkeypatch.setattr(ingest_main, "_publisher", None)
    monkeypatch.setattr(ingest_main, "_topic_path", None)

    mock_publisher = MagicMock()
    future = MagicMock()
    future.result.return_value = "msg-id-123"
    mock_publisher.publish.return_value = future
    mock_publisher.topic_path.return_value = "projects/test-project/topics/test-topic"

    with patch("ingest_main.pubsub_v1", create=True) as mock_mod:
        mock_mod.PublisherClient.return_value = mock_publisher
        with patch.dict("sys.modules", {"google.cloud.pubsub_v1": mock_mod, "google.cloud": MagicMock()}):
            yield mock_publisher


class TestValidPayloads:
    def test_valid_minimal_payload_returns_202(self):
        import ingest_main as main
        req = FakeRequest({"user_id": "u1", "amount": 500})
        body, status, _ = main.ingest_transaction(req)
        assert status == 202

    def test_response_contains_transaction_id(self):
        import ingest_main as main
        req = FakeRequest({"user_id": "u1", "amount": 500})
        body, status, _ = main.ingest_transaction(req)
        data = json.loads(body)
        assert "transaction_id" in data
        assert len(data["transaction_id"]) == 36   # UUID length

    def test_response_status_is_accepted(self):
        import ingest_main as main
        req = FakeRequest({"user_id": "u1", "amount": 500})
        body, _, _ = main.ingest_transaction(req)
        data = json.loads(body)
        assert data["status"] == "accepted"

    def test_provided_transaction_id_preserved(self):
        import ingest_main as main
        tid = "my-custom-uuid-1234"
        req = FakeRequest({"user_id": "u1", "amount": 500, "transaction_id": tid})
        body, _, _ = main.ingest_transaction(req)
        data = json.loads(body)
        assert data["transaction_id"] == tid

    def test_full_payload_accepted(self):
        import ingest_main as main
        req = FakeRequest({
            "user_id": "u1", "amount": 1500, "location": "Mumbai",
            "hour_of_day": 14, "is_new_location": 0,
            "transaction_velocity": 2, "merchant_category": "grocery",
        })
        _, status, _ = main.ingest_transaction(req)
        assert status == 202


class TestInvalidPayloads:
    def test_missing_user_id_returns_400(self):
        import ingest_main as main
        req = FakeRequest({"amount": 500})
        _, status, _ = main.ingest_transaction(req)
        assert status == 400

    def test_missing_amount_returns_400(self):
        import ingest_main as main
        req = FakeRequest({"user_id": "u1"})
        _, status, _ = main.ingest_transaction(req)
        assert status == 400

    def test_empty_body_returns_400(self):
        import ingest_main as main
        req = FakeRequest({})
        _, status, _ = main.ingest_transaction(req)
        assert status == 400

    def test_invalid_json_returns_400(self):
        import ingest_main as main
        req = FakeRequest("this is not json")
        _, status, _ = main.ingest_transaction(req)
        assert status == 400

    def test_missing_fields_listed_in_response(self):
        import ingest_main as main
        req = FakeRequest({"amount": 500})   # missing user_id
        body, status, _ = main.ingest_transaction(req)
        assert status == 400
        data = json.loads(body)
        assert "missing" in data
        assert "user_id" in data["missing"]


class TestCORSPreflight:
    def test_options_returns_204(self):
        import ingest_main as main
        req = FakeRequest({}, method="OPTIONS")
        _, status, _ = main.ingest_transaction(req)
        assert status == 204

    def test_cors_header_present(self):
        import ingest_main as main
        req = FakeRequest({"user_id": "u1", "amount": 500})
        _, _, headers = main.ingest_transaction(req)
        assert "Access-Control-Allow-Origin" in headers


class TestDevMode:
    def test_no_project_id_still_returns_202(self, monkeypatch):
        import ingest_main as main
        monkeypatch.setenv("GCP_PROJECT_ID", "")
        monkeypatch.setattr(main, "_publisher", None)
        monkeypatch.setattr(main, "_topic_path", None)
        monkeypatch.setattr(main, "_PROJECT_ID", "")
        req = FakeRequest({"user_id": "u1", "amount": 500})
        _, status, _ = main.ingest_transaction(req)
        assert status == 202
