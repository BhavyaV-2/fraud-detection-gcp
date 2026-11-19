"""Test firestore client behavior offline."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    """Reset the module-level _db before each test."""
    import firestore_client
    monkeypatch.setattr(firestore_client, "_db", None)
    monkeypatch.setattr(firestore_client, "_PROJECT_ID", "")


class TestDevMode:
    def test_no_project_id_logs_only(self, caplog, monkeypatch):
        import firestore_client
        doc = {"transaction_id": "t1", "amount": 500, "anomaly_score": 0.1, "is_flagged": False}
        firestore_client.write_transaction(doc, firestore_client.COLLECTION_APPROVED)

    def test_no_exception_raised_in_dev_mode(self, monkeypatch):
        import firestore_client
        doc = {"transaction_id": "t1", "amount": 500, "anomaly_score": 0.1, "is_flagged": False}
        try:
            firestore_client.write_transaction(doc, firestore_client.COLLECTION_APPROVED)
        except Exception as exc:
            pytest.fail(f"write_transaction raised unexpectedly: {exc}")


class TestWithMockedFirestore:
    def test_write_calls_set_on_correct_collection(self, monkeypatch):
        import firestore_client

        mock_doc_ref = MagicMock()
        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection

        monkeypatch.setattr(firestore_client, "_db", mock_db)
        monkeypatch.setattr(firestore_client, "_PROJECT_ID", "test-proj")

        doc = {"transaction_id": "tx-abc", "amount": 500, "anomaly_score": 0.1, "is_flagged": False}
        firestore_client.write_transaction(doc, firestore_client.COLLECTION_APPROVED)

        mock_db.collection.assert_called_once_with(firestore_client.COLLECTION_APPROVED)
        mock_collection.document.assert_called_once_with("tx-abc")
        mock_doc_ref.set.assert_called_once_with(doc)

    def test_write_to_flagged_collection(self, monkeypatch):
        import firestore_client

        mock_doc_ref = MagicMock()
        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection
        monkeypatch.setattr(firestore_client, "_db", mock_db)
        monkeypatch.setattr(firestore_client, "_PROJECT_ID", "test-proj")

        doc = {"transaction_id": "tx-xyz", "amount": 150000, "anomaly_score": 0.9, "is_flagged": True}
        firestore_client.write_transaction(doc, firestore_client.COLLECTION_FLAGGED)

        mock_db.collection.assert_called_once_with(firestore_client.COLLECTION_FLAGGED)

    def test_firestore_exception_propagates(self, monkeypatch):
        import firestore_client

        mock_doc_ref = MagicMock()
        mock_doc_ref.set.side_effect = Exception("Firestore quota exceeded")
        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection
        monkeypatch.setattr(firestore_client, "_db", mock_db)
        monkeypatch.setattr(firestore_client, "_PROJECT_ID", "test-proj")

        doc = {"transaction_id": "tx-fail", "amount": 500, "anomaly_score": 0.1, "is_flagged": False}
        with pytest.raises(Exception, match="Firestore quota exceeded"):
            firestore_client.write_transaction(doc, firestore_client.COLLECTION_APPROVED)

    def test_document_id_is_transaction_id(self, monkeypatch):
        import firestore_client

        mock_doc_ref = MagicMock()
        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_doc_ref
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection
        monkeypatch.setattr(firestore_client, "_db", mock_db)
        monkeypatch.setattr(firestore_client, "_PROJECT_ID", "test-proj")

        tid = "specific-transaction-id-999"
        doc = {"transaction_id": tid, "amount": 300, "anomaly_score": 0.05, "is_flagged": False}
        firestore_client.write_transaction(doc, firestore_client.COLLECTION_APPROVED)

        mock_collection.document.assert_called_once_with(tid)


class TestCollectionConstants:
    def test_approved_collection_name(self):
        from firestore_client import COLLECTION_APPROVED
        assert COLLECTION_APPROVED == "Approved_Transactions"

    def test_flagged_collection_name(self):
        from firestore_client import COLLECTION_FLAGGED
        assert COLLECTION_FLAGGED == "Flagged_Transactions"
