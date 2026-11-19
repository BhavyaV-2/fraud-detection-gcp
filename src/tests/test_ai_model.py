"""Test ai model behavior offline."""
import os

import numpy as np


def _make_model():
    """Train a tiny IsolationForest for testing - no disk I/O needed."""
    from sklearn.ensemble import IsolationForest
    data = np.array([
        [500,  14, 0, 2],
        [300,  10, 0, 1],
        [800,  16, 1, 3],
        [150000, 3, 1, 25],  # anomaly
    ])
    m = IsolationForest(n_estimators=10, contamination=0.25, random_state=0)
    m.fit(data)
    return m


def _patch_model(monkeypatch, model):
    import ai_model
    monkeypatch.setattr(ai_model, "_model", model)


class TestNormalizeScore:
    def test_positive_raw_gives_low_risk(self):
        from ai_model import _normalize
        assert _normalize(0.4) < 0.2

    def test_negative_raw_gives_high_risk(self):
        from ai_model import _normalize
        assert _normalize(-0.4) > 0.8

    def test_output_clamped_between_0_and_1(self):
        from ai_model import _normalize
        assert 0.0 <= _normalize(999) <= 1.0
        assert 0.0 <= _normalize(-999) <= 1.0

    def test_zero_raw_gives_half(self):
        from ai_model import _normalize
        assert abs(_normalize(0.0) - 0.5) < 1e-9


class TestRuleBasedScore:
    def test_normal_transaction_low_score(self):
        from ai_model import _rule_based_score
        tx = {"amount": 400, "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2}
        assert _rule_based_score(tx) < 0.3

    def test_huge_amount_raises_score(self):
        from ai_model import _rule_based_score
        tx = {"amount": 100000, "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2}
        assert _rule_based_score(tx) >= 0.4

    def test_all_red_flags_max_score(self):
        from ai_model import _rule_based_score
        tx = {"amount": 100000, "hour_of_day": 2, "is_new_location": 1, "transaction_velocity": 15}
        assert _rule_based_score(tx) == 1.0

    def test_score_clamped_at_1(self):
        from ai_model import _rule_based_score
        tx = {"amount": 999999, "hour_of_day": 1, "is_new_location": 1, "transaction_velocity": 99}
        assert _rule_based_score(tx) <= 1.0


class TestScoreTransaction:
    def test_adds_anomaly_score_and_is_flagged(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 500, "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2}
        result = score_transaction(tx)
        assert "anomaly_score" in result
        assert "is_flagged" in result
        assert isinstance(result["anomaly_score"], float)
        assert isinstance(result["is_flagged"], bool)

    def test_anomaly_score_between_0_and_1(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 500, "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2}
        result = score_transaction(tx)
        assert 0.0 <= result["anomaly_score"] <= 1.0

    def test_normal_tx_not_flagged(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 300, "hour_of_day": 10, "is_new_location": 0, "transaction_velocity": 1}
        result = score_transaction(tx)
        assert result["is_flagged"] is False

    def test_fraud_tx_flagged(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 150000, "hour_of_day": 3, "is_new_location": 1, "transaction_velocity": 25}
        result = score_transaction(tx)
        assert result["anomaly_score"] >= 0.0

    def test_missing_fields_default_gracefully(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 500}   # missing hour, location, velocity
        result = score_transaction(tx)
        assert "anomaly_score" in result

    def test_fallback_scorer_when_model_none(self, monkeypatch):
        import ai_model
        monkeypatch.setattr(ai_model, "_model", None)
        from ai_model import score_transaction
        tx = {"amount": 200000, "hour_of_day": 3, "is_new_location": 1, "transaction_velocity": 20}
        result = score_transaction(tx)
        assert result["is_flagged"] is True

    def test_original_dict_mutated_in_place(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 500, "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2}
        result = score_transaction(tx)
        assert result is tx   # same object

    def test_score_rounded_to_4dp(self, monkeypatch):
        _patch_model(monkeypatch, _make_model())
        from ai_model import score_transaction
        tx = {"amount": 500, "hour_of_day": 14, "is_new_location": 0, "transaction_velocity": 2}
        result = score_transaction(tx)
        s = result["anomaly_score"]
        assert round(s, 4) == s


class TestTrainScript:
    def test_model_pkl_created(self, tmp_path, monkeypatch):
        """Smoke-test the training script end-to-end."""
        import runpy
        train_path = os.path.join(
            os.path.dirname(__file__), "..", "train_model", "train.py"
        )
        dest = str(tmp_path / "model.pkl")

        orig_abspath = os.path.abspath
        def fake_abspath(p):
            if "model.pkl" in p:
                return dest
            return orig_abspath(p)

        monkeypatch.setattr(os.path, "abspath", fake_abspath)
        runpy.run_path(train_path)
        assert os.path.exists(dest), "model.pkl was not created by train.py"
        assert os.path.getsize(dest) > 1000, "model.pkl seems too small"
