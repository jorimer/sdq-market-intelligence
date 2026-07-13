"""SDQ XGBoost multi-class rating model.

Training:   feature vectors + deterministic tiers → XGBClassifier (multi:softprob)
Inference:  feature vector → predict_proba → weighted midpoint → continuous score → tier

Extracted from financial-analysis-agent/banking_scoring_service.py.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

# Lazy imports — XGBoost requires libomp which may not be installed
XGBClassifier = None
LabelEncoder = None


def _ensure_ml_libs():
    """Import heavy ML libs on first use so the server can start without them."""
    global XGBClassifier, LabelEncoder
    if XGBClassifier is None:
        from xgboost import XGBClassifier as _XGB
        from sklearn.preprocessing import LabelEncoder as _LE

        XGBClassifier = _XGB
        LabelEncoder = _LE


def _get_ml_metrics():
    from sklearn.metrics import (
        accuracy_score,
        cohen_kappa_score,
        f1_score,
        mean_absolute_error,
    )
    from sklearn.model_selection import train_test_split

    return accuracy_score, cohen_kappa_score, f1_score, mean_absolute_error, train_test_split

from modules.banking_score.ml.features import extract_feature_vector
from modules.banking_score.scoring.rating_scale import (
    RATING_SCALE,
    map_rating_tier,
)
from modules.banking_score.scoring.weights import XGBOOST_PARAMS
from shared.config.settings import settings

logger = logging.getLogger(__name__)

# Tier midpoints for converting probabilities → continuous score
TIER_MIDPOINTS: Dict[str, float] = {
    tier: (lo + hi) / 2 for tier, lo, hi in RATING_SCALE
}

# Serialization format: JSON envelope { format, payload_b64, hmac } where the
# payload is { booster_b64 (XGBoost native JSON), classes, version, metrics }.
# XGBoost's native format cannot execute code on load (unlike pickle), and the
# HMAC rejects a blob that was altered at rest (DB row or disk file).
MODEL_FORMAT = "sdq-xgb-v2"


class ModelIntegrityError(RuntimeError):
    """Blob de modelo con formato desconocido o firma HMAC inválida."""


def _hmac_key() -> bytes:
    # Same derivation precedence as shared/settings/crypto.py.
    return (settings.SETTINGS_SECRET or settings.JWT_SECRET_KEY).encode("utf-8")


def _sign(payload: bytes) -> str:
    return hmac.new(_hmac_key(), payload, hashlib.sha256).hexdigest()


class SDQXGBoostModel:
    """Wrapper around XGBClassifier for 10-tier credit-rating prediction."""

    def __init__(self):
        self.model: Optional[XGBClassifier] = None
        self.label_encoder: Optional[LabelEncoder] = None
        self.version: Optional[str] = None
        self.metrics: Optional[Dict] = None
        self._model_path = os.path.join(
            settings.MODELS_DIR, "sdq_xgboost_latest.json"
        )

    # ── Training ──────────────────────────────────────────────────

    def train(
        self,
        features: List[List[float]],
        tiers: List[str],
        test_size: float = 0.25,
    ) -> Dict:
        """Train XGBoost on feature vectors and tier labels.

        Args:
            features: List of 21-dim feature vectors.
            tiers:    Corresponding tier labels (e.g. ``"SDQ-AA+"``).
            test_size: Fraction reserved for evaluation.

        Returns:
            Dict with accuracy, MAE, F1, kappa, and split sizes.
        """
        _ensure_ml_libs()
        accuracy_score, cohen_kappa_score, f1_score, mean_absolute_error, train_test_split = _get_ml_metrics()

        X = np.array(features)

        # LabelEncoder maps sparse tier names → contiguous [0..N-1]
        self.label_encoder = LabelEncoder()
        y = self.label_encoder.fit_transform(tiers)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42,
        )

        # Build classifier — separate constructor args from hyperparams
        fit_params = {
            k: v
            for k, v in XGBOOST_PARAMS.items()
            if k not in ("num_class", "use_label_encoder")
        }

        self.model = XGBClassifier(
            num_class=len(self.label_encoder.classes_),
            use_label_encoder=False,
            **fit_params,
        )
        self.model.fit(X_train, y_train)

        # Evaluate
        y_pred = self.model.predict(X_test)
        self.metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "mae": float(mean_absolute_error(y_test, y_pred)),
            "f1_weighted": float(
                f1_score(y_test, y_pred, average="weighted", zero_division=0)
            ),
            "kappa": float(cohen_kappa_score(y_test, y_pred)),
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "n_classes": int(len(self.label_encoder.classes_)),
        }

        self.version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._save()
        logger.info(
            "XGBoost trained: v=%s  acc=%.3f  kappa=%.3f",
            self.version, self.metrics["accuracy"], self.metrics["kappa"],
        )
        return self.metrics

    # ── Inference ─────────────────────────────────────────────────

    def predict(
        self, indicator_scores: Dict[str, float],
    ) -> Tuple[float, str, Dict[str, float]]:
        """Predict continuous score and tier from indicator scores.

        Returns:
            ``(score, tier, tier_probabilities)``
        """
        _ensure_ml_libs()
        if self.model is None:
            self._load()

        features = extract_feature_vector(indicator_scores)
        X = np.array([features])

        probas = self.model.predict_proba(X)[0]
        class_labels = self.label_encoder.inverse_transform(
            range(len(probas))
        )

        # Weighted average of tier midpoints
        score = sum(
            probas[i] * TIER_MIDPOINTS.get(class_labels[i], 50.0)
            for i in range(len(probas))
        )
        score = max(0.0, min(100.0, float(score)))
        tier = map_rating_tier(score)

        tier_probs = {
            class_labels[i]: float(probas[i]) for i in range(len(probas))
        }
        return score, tier, tier_probs

    # ── Serialization ─────────────────────────────────────────────
    # No pickle anywhere: a compromised blob must not be able to execute code.

    def _serialize(self) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
            self.model.save_model(tmp.name)
            booster_bytes = open(tmp.name, "rb").read()
        payload = json.dumps({
            "booster_b64": base64.b64encode(booster_bytes).decode("ascii"),
            "classes": [str(c) for c in self.label_encoder.classes_],
            "version": self.version,
            "metrics": self.metrics,
        }, sort_keys=True).encode("utf-8")
        envelope = {
            "format": MODEL_FORMAT,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "hmac": _sign(payload),
        }
        return json.dumps(envelope).encode("utf-8")

    def _deserialize(self, blob: bytes) -> None:
        try:
            envelope = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ModelIntegrityError(
                "Blob de modelo en formato legado (pickle) o corrupto; se ignora "
                "por seguridad. Re-entrenar con POST /model/train."
            ) from e
        if not isinstance(envelope, dict) or envelope.get("format") != MODEL_FORMAT:
            raise ModelIntegrityError(
                f"Formato de modelo desconocido: {envelope.get('format') if isinstance(envelope, dict) else '?'}"
            )
        payload = base64.b64decode(envelope.get("payload_b64", ""))
        if not hmac.compare_digest(_sign(payload), str(envelope.get("hmac", ""))):
            raise ModelIntegrityError(
                "Firma HMAC inválida: el blob del modelo fue alterado. Se rechaza."
            )
        data = json.loads(payload.decode("utf-8"))

        _ensure_ml_libs()
        model = XGBClassifier()
        with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
            tmp.write(base64.b64decode(data["booster_b64"]))
            tmp.flush()
            model.load_model(tmp.name)
        encoder = LabelEncoder()
        encoder.classes_ = np.array(data["classes"])

        self.model = model
        self.label_encoder = encoder
        self.version = data.get("version")
        self.metrics = data.get("metrics")

    def _save(self):
        os.makedirs(os.path.dirname(self._model_path), exist_ok=True)
        with open(self._model_path, "wb") as f:
            f.write(self._serialize())
        logger.info("Model saved to %s", self._model_path)

    def _load(self):
        if not os.path.exists(self._model_path):
            raise FileNotFoundError(
                f"No trained model found at {self._model_path}. "
                "Run /model/train first."
            )
        with open(self._model_path, "rb") as f:
            self._deserialize(f.read())
        logger.info("Model loaded: v=%s", self.version)

    # ── Durable persistence (Postgres) ───────────────────────────
    # The disk file lives on the ephemeral container FS and vanishes on
    # redeploy. The newest ml_models row is the durable source of truth, loaded
    # into memory on cold start.

    def save_to_db(self, db, trained_by: Optional[str] = None) -> None:
        """Persist the in-memory model as a new ml_models row (durable)."""
        from modules.banking_score.models.models import MlModel
        if self.model is None:
            raise RuntimeError("No hay modelo en memoria para guardar.")
        db.add(MlModel(
            module="banking_score",
            version=self.version,
            model_blob=self._serialize(),
            metrics=self.metrics,
            trained_by=trained_by,
        ))
        db.commit()
        logger.info("Model persisted to DB: v=%s", self.version)

    def _latest_row(self, db):
        from modules.banking_score.models.models import MlModel
        return (
            db.query(MlModel)
            .filter(MlModel.module == "banking_score")
            .order_by(MlModel.created_at.desc())
            .first()
        )

    def load_from_db(self, db) -> bool:
        """Load the most recent model from the DB into memory. Returns success.

        A legacy-pickle or tampered blob is refused (never deserialized) and
        reported as "no model": the deterministic engine keeps serving and
        /model/train produces a fresh row in the current format.
        """
        row = self._latest_row(db)
        if not row:
            return False
        _ensure_ml_libs()
        try:
            self._deserialize(row.model_blob)
        except ModelIntegrityError as e:
            logger.warning("Modelo en DB rechazado (v=%s): %s", row.version, e)
            return False
        logger.info("Model loaded from DB: v=%s", self.version)
        return True

    def ensure_loaded(self, db=None) -> bool:
        """Make a usable model available in memory: in-memory → disk → DB."""
        if self.model is not None:
            return True
        if os.path.exists(self._model_path):
            try:
                self._load()
                return True
            except Exception as e:  # noqa: BLE001 — fall through to DB
                logger.warning("Disk model load failed: %s", e)
        if db is not None:
            return self.load_from_db(db)
        return False

    # ── Status ────────────────────────────────────────────────────

    def get_status(self, db=None) -> Dict:
        available = self.model is not None or os.path.exists(self._model_path)
        version = self.version
        metrics = self.metrics
        if db is not None:
            row = self._latest_row(db)
            if row:
                available = True
                version = version or row.version
                metrics = metrics or row.metrics
        return {
            "model_available": available,
            "version": version,
            "metrics": metrics,
            "model_path": self._model_path,
        }


# Singleton
xgboost_model = SDQXGBoostModel()
