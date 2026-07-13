"""Tests for PASO 5 — ML Pipeline, SIB Client, and Features."""
import json
import os
import sys

import numpy as np
import pytest

# Check if XGBoost native libs are available (requires libomp on macOS)
try:
    from xgboost import XGBClassifier  # noqa: F401
    _xgboost_available = True
except Exception:
    _xgboost_available = False

_skip_xgb = pytest.mark.skipif(
    not _xgboost_available,
    reason="XGBoost native libs not available (libomp missing)",
)

# Ensure project root is on path
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.banking_score.scoring.engine import (
    BankingDataInput,
    run_scoring,
)
from modules.banking_score.scoring.weights import FEATURE_ORDER
from modules.banking_score.ml.features import (
    extract_feature_vector,
    scoring_result_to_features,
)
from modules.banking_score.ml.xgboost_model import SDQXGBoostModel, TIER_MIDPOINTS
from modules.banking_score.external.sib_client import (
    SuperintendenciaBancosClient,
)


# ── Test data ────────────────────────────────────────────────────

def _make_banking_data(**overrides) -> BankingDataInput:
    """Create a BankingDataInput with sensible defaults."""
    defaults = dict(
        patrimonio_tecnico=5_000,
        apr=30_000,
        capital_primario=4_000,
        exposicion_total=50_000,
        capital_tier1=4_000,
        contingentes=2_000,
        riesgo_mercado=1_000,
        provisiones=800,
        cartera_vencida_90d=500,
        activos_totales=80_000,
        cartera_bruta=50_000,
        cartera_categoria_a=45_000,
        cartera_total=50_000,
        suma_top10=12_000,
        hhi_sectorial_raw=1_800,
        castigos=200,
        exposicion_re=18_000,
        cartera_a_prev=44_000,
        utilidad_neta=1_500,
        activos_promedio=75_000,
        patrimonio_promedio=8_000,
        ingresos_financieros=6_000,
        gastos_financieros=2_000,
        activos_productivos_avg=60_000,
        gastos_operacionales=2_500,
        ingresos_operacionales=5_000,
        caja_valores=8_000,
        pasivos_cp=30_000,
        cartera_neta=48_000,
        depositos_totales=55_000,
        activos_liquidos=15_000,
        pasivos_exigibles=60_000,
        hhi_ingresos_raw=3_500,
    )
    defaults.update(overrides)
    return BankingDataInput(**defaults)


# ── Feature extraction tests ─────────────────────────────────────

class TestFeatures:
    def test_extract_feature_vector_length(self):
        scores = {feat: float(i * 5) for i, feat in enumerate(FEATURE_ORDER)}
        vec = extract_feature_vector(scores)
        assert len(vec) == 21

    def test_extract_feature_vector_order(self):
        scores = {feat: float(i + 1) for i, feat in enumerate(FEATURE_ORDER)}
        vec = extract_feature_vector(scores)
        assert vec[0] == 1.0  # solvencia
        assert vec[-1] == 21.0  # hhi_ingresos

    def test_missing_features_default_zero(self):
        vec = extract_feature_vector({})
        assert all(v == 0.0 for v in vec)
        assert len(vec) == 21

    def test_scoring_result_to_features(self):
        data = _make_banking_data()
        result = run_scoring(data)
        vec = scoring_result_to_features(result)
        assert len(vec) == 21
        assert all(isinstance(v, float) for v in vec)


# ── XGBoost model tests ─────────────────────────────────────────

class TestXGBoostModel:
    def _generate_training_data(self, n=60):
        """Generate synthetic training data."""
        features = []
        tiers = []
        tier_list = [
            "SDQ-AAA", "SDQ-AA+", "SDQ-AA", "SDQ-AA-", "SDQ-A+",
            "SDQ-A", "SDQ-A-", "SDQ-BBB+", "SDQ-BBB", "SDQ-D",
        ]
        rng = np.random.RandomState(42)
        for _ in range(n):
            vec = rng.uniform(20, 95, size=21).tolist()
            avg = np.mean(vec)
            # Assign tier based on average score
            tier_idx = min(9, max(0, int((100 - avg) / 10)))
            tiers.append(tier_list[tier_idx])
            features.append(vec)
        return features, tiers

    @_skip_xgb
    def test_train_and_predict(self, tmp_path):
        model = SDQXGBoostModel()
        model._model_path = str(tmp_path / "test_model.json")

        features, tiers = self._generate_training_data(60)
        metrics = model.train(features, tiers)

        assert "accuracy" in metrics
        assert "kappa" in metrics
        assert metrics["n_train"] > 0
        assert metrics["n_test"] > 0
        assert model.version is not None

        # Test prediction
        test_scores = {feat: 75.0 for feat in FEATURE_ORDER}
        score, tier, probs = model.predict(test_scores)
        assert 0 <= score <= 100
        assert tier.startswith("SDQ-")
        assert isinstance(probs, dict)
        assert len(probs) > 0

    @_skip_xgb
    def test_model_persistence(self, tmp_path):
        model1 = SDQXGBoostModel()
        model1._model_path = str(tmp_path / "persist_model.json")

        features, tiers = self._generate_training_data(60)
        model1.train(features, tiers)

        # Load in a new instance
        model2 = SDQXGBoostModel()
        model2._model_path = str(tmp_path / "persist_model.json")
        model2._load()

        assert model2.version == model1.version
        assert model2.metrics is not None

        # Predictions should match
        test_scores = {feat: 60.0 for feat in FEATURE_ORDER}
        s1, t1, _ = model1.predict(test_scores)
        s2, t2, _ = model2.predict(test_scores)
        assert abs(s1 - s2) < 0.01
        assert t1 == t2

    def test_model_not_found_raises(self, tmp_path):
        model = SDQXGBoostModel()
        model._model_path = str(tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError):
            model._load()

    def test_get_status_no_model(self, tmp_path):
        model = SDQXGBoostModel()
        model._model_path = str(tmp_path / "no_model.json")
        status = model.get_status()
        assert status["model_available"] is False

    def test_tier_midpoints(self):
        assert len(TIER_MIDPOINTS) == 10
        assert TIER_MIDPOINTS["SDQ-AAA"] == 97.5
        assert TIER_MIDPOINTS["SDQ-D"] == 22.495


# ── SIB Client tests ────────────────────────────────────────────

class TestSIBClient:
    def test_get_sector_benchmarks_defaults(self):
        client = SuperintendenciaBancosClient()
        benchmarks = client.get_sector_benchmarks()
        assert "sector_averages" in benchmarks
        assert "peer_groups" in benchmarks
        assert "regulatory_limits" in benchmarks
        assert benchmarks["sector_averages"]["car"] == 16.5

    def test_get_peer_comparison(self):
        client = SuperintendenciaBancosClient()
        result = client.get_peer_comparison(
            "BPD", {"car": 15.0, "npl": 2.0, "roa": 2.5},
        )
        assert result["bank"] == "BPD"
        assert result["peer_group"] == "large_banks"
        assert "car" in result["comparison"]
        assert result["comparison"]["car"]["difference"] == -1.5

    def test_peer_comparison_unknown_bank(self):
        client = SuperintendenciaBancosClient()
        result = client.get_peer_comparison(
            "Unknown Bank", {"car": 12.0},
        )
        assert result["peer_group"] is None

    def test_validate_regulatory_compliance_pass(self):
        client = SuperintendenciaBancosClient()
        result = client.validate_regulatory_compliance({
            "car": 15.0, "npl": 1.5, "liquidity_ratio": 25.0, "leverage_ratio": 12.0,
        })
        assert result["compliant"] is True
        assert len(result["violations"]) == 0

    def test_validate_regulatory_compliance_fail(self):
        client = SuperintendenciaBancosClient()
        result = client.validate_regulatory_compliance({
            "car": 8.0, "npl": 6.0,
        })
        assert result["compliant"] is False
        assert len(result["violations"]) == 2  # CAR + NPL

    def test_compare_to_sector(self):
        client = SuperintendenciaBancosClient()
        result = client.compare_to_sector({
            "solvencia": 85.0, "morosidad": 90.0, "roa": 70.0,
        })
        assert "solvencia" in result
        assert "sector_benchmark" in result["solvencia"]

    def test_cache_works(self):
        client = SuperintendenciaBancosClient()
        b1 = client.get_sector_benchmarks()
        b2 = client.get_sector_benchmarks()
        assert b1 is b2  # Same object from cache

    def test_local_json_fallback(self, tmp_path):
        client = SuperintendenciaBancosClient()
        json_path = str(tmp_path / "sib_benchmarks.json")
        client._local_path = json_path

        custom = {
            "sector_averages": {"car": 20.0},
            "peer_groups": {},
            "regulatory_limits": {},
        }
        import json
        with open(json_path, "w") as f:
            json.dump(custom, f)

        client._cache = {}  # Clear cache
        client._cache_ts = 0.0
        result = client.get_sector_benchmarks()
        assert result["sector_averages"]["car"] == 20.0


# ── Integration: scoring → features → (would-be) ML ─────────────

class TestIntegration:
    def test_scoring_to_features_pipeline(self):
        data = _make_banking_data()
        result = run_scoring(data)

        # Extract features
        vec = scoring_result_to_features(result)
        assert len(vec) == 21

        # All scores should be in [0, 100]
        for v in vec:
            assert 0.0 <= v <= 100.0, f"Feature value {v} out of range"

    @_skip_xgb
    def test_full_train_from_synthetic_data(self, tmp_path):
        """Seed → Score → Feature extraction → Train → Predict."""
        model = SDQXGBoostModel()
        model._model_path = str(tmp_path / "integration_model.json")

        rng = np.random.RandomState(123)
        features = []
        tiers = []

        # Generate 60 synthetic banks
        for _ in range(60):
            data = _make_banking_data(
                patrimonio_tecnico=rng.uniform(3000, 8000),
                apr=rng.uniform(20000, 50000),
                provisiones=rng.uniform(300, 1200),
                cartera_vencida_90d=rng.uniform(100, 1000),
                utilidad_neta=rng.uniform(500, 3000),
            )
            result = run_scoring(data)
            vec = scoring_result_to_features(result)
            tier = result["rating_tier"]
            features.append(vec)
            tiers.append(tier)

        metrics = model.train(features, tiers)
        assert metrics["accuracy"] > 0

        # Predict on new data
        new_data = _make_banking_data()
        new_result = run_scoring(new_data)
        flat_scores = {k: v["score"] for k, v in new_result["indicators"].items()}
        score, tier, probs = model.predict(flat_scores)
        assert 0 <= score <= 100
        assert tier.startswith("SDQ-")


@_skip_xgb
class TestModelDurability:
    """The trained model must survive a redeploy (disk file gone): it is
    persisted in Postgres (ml_models) and loaded from DB on cold start."""

    def _db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from shared.database.base import Base
        from shared.auth.models import User  # noqa: F401 — register FK target
        import modules.banking_score.models.models  # noqa: F401 — register tables
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        return sessionmaker(bind=engine)()

    def test_save_and_load_from_db_when_disk_gone(self, tmp_path):
        db = self._db()
        gen = TestXGBoostModel()._generate_training_data(60)

        trainer = SDQXGBoostModel()
        trainer._model_path = str(tmp_path / "m.json")
        trainer.train(*gen)
        trainer.save_to_db(db)

        # Simulate redeploy: fresh instance, NO disk file present.
        revived = SDQXGBoostModel()
        revived._model_path = str(tmp_path / "gone.json")  # does not exist
        assert revived.ensure_loaded(db) is True
        assert revived.version == trainer.version
        assert revived.get_status(db)["model_available"] is True

        # Predictions match the original.
        scores = {feat: 70.0 for feat in FEATURE_ORDER}
        s1, t1, _ = trainer.predict(scores)
        s2, t2, _ = revived.predict(scores)
        assert abs(s1 - s2) < 0.01 and t1 == t2

    def test_status_reports_unavailable_without_disk_or_db(self, tmp_path):
        db = self._db()
        model = SDQXGBoostModel()
        model._model_path = str(tmp_path / "none.json")
        assert model.get_status(db)["model_available"] is False


@_skip_xgb
class TestModelIntegrity:
    """The model blob must not execute code on load, and a tampered blob (disk
    or DB) must be refused rather than trusted."""

    def _trained(self, tmp_path):
        model = SDQXGBoostModel()
        model._model_path = str(tmp_path / "m.json")
        model.train(*TestXGBoostModel()._generate_training_data(60))
        return model

    def test_blob_is_not_pickle(self, tmp_path):
        # A JSON envelope, never a pickle stream (which would start with b'\x80').
        blob = self._trained(tmp_path)._serialize()
        assert blob.lstrip()[:1] == b"{"
        env = json.loads(blob)
        assert env["format"] == "sdq-xgb-v2" and "hmac" in env

    def test_tampered_blob_is_rejected(self, tmp_path):
        from modules.banking_score.ml.xgboost_model import ModelIntegrityError
        model = self._trained(tmp_path)
        blob = bytearray(model._serialize())
        blob[-3] ^= 0x01  # flip a bit inside the payload/hmac region
        revived = SDQXGBoostModel()
        with pytest.raises(ModelIntegrityError):
            revived._deserialize(bytes(blob))

    def test_legacy_pickle_blob_is_rejected_not_executed(self, tmp_path):
        import pickle
        from modules.banking_score.ml.xgboost_model import ModelIntegrityError
        legacy = pickle.dumps({"model": None, "label_encoder": None})
        revived = SDQXGBoostModel()
        with pytest.raises(ModelIntegrityError):
            revived._deserialize(legacy)

    def test_db_load_skips_tampered_row(self, tmp_path):
        # A tampered DB blob → load_from_db returns False (deterministic keeps serving),
        # it does NOT raise or execute.
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from shared.database.base import Base
        from shared.auth.models import User  # noqa: F401
        import modules.banking_score.models.models  # noqa: F401
        from modules.banking_score.models.models import MlModel
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()

        model = self._trained(tmp_path)
        blob = bytearray(model._serialize())
        blob[-3] ^= 0x01
        db.add(MlModel(module="banking_score", version="bad", model_blob=bytes(blob)))
        db.commit()

        revived = SDQXGBoostModel()
        revived._model_path = str(tmp_path / "absent.json")
        assert revived.load_from_db(db) is False
        assert revived.model is None
