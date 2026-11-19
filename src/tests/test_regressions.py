"""Cover input validation, cloud failures, and the Eventarc entry point."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import ingest_main
import worker_main
import firestore_client


def _request(payload, method="POST"):
    """Build an HTTP request with a JSON body."""
    return SimpleNamespace(method=method, get_data=lambda: json.dumps(payload).encode())


@pytest.mark.parametrize("payload", [
    [], None, "text", 42,
    {"user_id": "", "amount": 1},
    {"user_id": 12, "amount": 1},
    {"user_id": "u1", "amount": True},
    {"user_id": "u1", "amount": -1},
    {"user_id": "u1", "amount": float("nan")},
    {"user_id": "u1", "amount": float("inf")},
    {"user_id": "u1", "amount": "100"},
    {"user_id": "u1", "amount": 100, "hour_of_day": 24},
    {"user_id": "u1", "amount": 100, "is_new_location": 2},
    {"user_id": "u1", "amount": 100, "transaction_velocity": -1},
    {"user_id": "u1", "amount": 100, "transaction_id": "bad/id"},
    {"user_id": "u1", "amount": 100, "transaction_id": ".."},
])
def test_invalid_transaction_rejected(payload):
    _, status, _ = ingest_main.ingest_transaction(_request(payload))
    assert status == 400


def test_get_rejected():
    _, status, headers = ingest_main.ingest_transaction(_request({}, "GET"))
    assert status == 405
    assert "POST" in headers["Allow"]


def test_publisher_initialization_failure_returns_503(monkeypatch):
    def fail():
        raise RuntimeError("Credentials unavailable")

    monkeypatch.setattr(ingest_main, "_get_publisher", fail)
    _, status, _ = ingest_main.ingest_transaction(_request({"user_id": "u1", "amount": 100}))
    assert status == 503


def test_firestore_initialization_failure_propagates(monkeypatch):
    from google.cloud import firestore

    monkeypatch.setattr(firestore_client, "_PROJECT_ID", "test-project")
    monkeypatch.setattr(firestore_client, "_db", None)
    monkeypatch.setattr(firestore, "Client", MagicMock(side_effect=RuntimeError("No credentials")))
    with pytest.raises(RuntimeError, match="No credentials"):
        firestore_client.write_transaction({"transaction_id": "t1"}, "test")


def _event(payload):
    """Build an Eventarc-style Pub/Sub payload."""
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return SimpleNamespace(data={"message": {"data": data, "messageId": "stable-id"}})


def test_cloud_event_processes_and_reuses_document_id(monkeypatch):
    write = MagicMock()
    monkeypatch.setattr(firestore_client, "write_transaction", write)
    event = _event({"user_id": "u1", "amount": 100})
    worker_main.process_transaction_event(event)
    worker_main.process_transaction_event(event)
    assert write.call_count == 2
    assert write.call_args_list[0].args[0]["transaction_id"] == write.call_args_list[1].args[0]["transaction_id"]


def test_cloud_event_raises_on_storage_failure(monkeypatch):
    monkeypatch.setattr(firestore_client, "write_transaction", MagicMock(side_effect=RuntimeError("Storage unavailable")))
    with pytest.raises(RuntimeError, match="Firestore write failed"):
        worker_main.process_transaction_event(_event({"user_id": "u1", "amount": 100}))


def test_cloud_event_acknowledges_non_object_payload(monkeypatch):
    write = MagicMock()
    monkeypatch.setattr(firestore_client, "write_transaction", write)
    worker_main.process_transaction_event(_event([]))
    write.assert_not_called()
