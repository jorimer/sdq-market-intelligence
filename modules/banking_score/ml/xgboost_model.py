"""Modelo XGBoost de Perfil SDQ — DOS REGRESORES, uno por eje.

Entrenamiento:  vectores de indicadores + los dos scores deterministas → 2 XGBRegressor
Inferencia:     vector → (ejecución, resiliencia)

**Por qué regresión y no clasificación sobre las bandas.** La banda de Ejecución es
RELATIVA al panel: sale de los cuartiles del tipo de entidad, así que se mueve cuando se
mueve el panel. Entrenar un clasificador contra una etiqueta que se desplaza enseña un
blanco móvil — el modelo aprendería la composición del panel de ese día, no el desempeño.
El score es estable y la banda se deriva de él aguas abajo, donde el corte vigente aplica.

**Por qué dos modelos y no uno multi-salida.** Los ejes son independientes por diseño
(§2 del spec): una entidad puede ser sólida y poco eficiente. Un modelo conjunto compartiría
representación entre los dos y volvería a acoplar lo que el índice separa.

La versión anterior era un clasificador de 10 clases sobre `SDQ-AAA…SDQ-D` que después
convertía probabilidades a un score continuo por punto medio ponderado — un rodeo para
llegar a un número que ahora se predice directo.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

# Lazy imports — XGBoost requires libomp which may not be installed
XGBRegressor = None


def _ensure_ml_libs():
    """Import heavy ML libs on first use so the server can start without them."""
    global XGBRegressor
    if XGBRegressor is None:
        from xgboost import XGBRegressor as _XGB

        XGBRegressor = _XGB


def _get_ml_metrics():
    """Métricas de REGRESIÓN. Accuracy/F1/kappa eran de la etapa de clasificación y no
    aplican: un error de 2 puntos y uno de 40 no son "ambos incorrectos"."""
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split

    return mean_absolute_error, r2_score, train_test_split

from modules.banking_score.ml.features import extract_feature_vector
from modules.banking_score.scoring.weights import XGBOOST_PARAMS
from shared.config.settings import settings

logger = logging.getLogger(__name__)

EJES = ("ejecucion", "resiliencia")

# Serialization format: JSON envelope { format, payload_b64, hmac } where the
# payload is { booster_b64 (XGBoost native JSON), classes, version, metrics }.
# XGBoost's native format cannot execute code on load (unlike pickle), and the
# HMAC rejects a blob that was altered at rest (DB row or disk file).
# v3: dos regresores por eje. Un blob v2 (clasificador de tiers) se RECHAZA en vez de
# intentar interpretarlo — predice otra cosa, y cargarlo daría números sin significado.
MODEL_FORMAT = "sdq-xgb-v3"
MODEL_FORMAT_LEGADO = "sdq-xgb-v2"


class ModelIntegrityError(RuntimeError):
    """Blob de modelo con formato desconocido o firma HMAC inválida."""


def _hmac_key() -> bytes:
    # Same derivation precedence as shared/settings/crypto.py.
    return (settings.SETTINGS_SECRET or settings.JWT_SECRET_KEY).encode("utf-8")


def _sign(payload: bytes) -> str:
    return hmac.new(_hmac_key(), payload, hashlib.sha256).hexdigest()


class SDQXGBoostModel:
    """Dos XGBRegressor —uno por eje— sobre el mismo vector de indicadores."""

    def __init__(self):
        # {"ejecucion": regresor, "resiliencia": regresor}. Independientes por diseño.
        self.modelos: Dict[str, Any] = {}
        self.version: Optional[str] = None
        self.metrics: Optional[Dict] = None
        self._model_path = os.path.join(
            settings.MODELS_DIR, "sdq_xgboost_latest.json"
        )

    # ── Training ──────────────────────────────────────────────────

    def train(
        self,
        features: List[List[float]],
        ejecucion: List[float],
        resiliencia: List[float],
        test_size: float = 0.25,
    ) -> Dict:
        """Entrena un regresor por eje sobre el mismo vector de indicadores.

        Args:
            features:    vectores de 21 dimensiones.
            ejecucion:   score determinista de Ejecución (0-100) de cada observación.
            resiliencia: ídem para Resiliencia.
            test_size:   fracción reservada para evaluar.
        """
        _ensure_ml_libs()
        mean_absolute_error, r2_score, train_test_split = _get_ml_metrics()

        if not (len(features) == len(ejecucion) == len(resiliencia)):
            raise ValueError("features, ejecucion y resiliencia deben tener el mismo largo")

        X = np.array(features)
        fit_params = {
            k: v for k, v in XGBOOST_PARAMS.items()
            if k not in ("num_class", "use_label_encoder", "objective")
        }

        met: Dict[str, Any] = {}
        for eje, y_raw in (("ejecucion", ejecucion), ("resiliencia", resiliencia)):
            y = np.array(y_raw, dtype=float)
            # El MISMO random_state en los dos: así ambos ejes se evalúan sobre las mismas
            # entidades y sus métricas son comparables entre sí.
            X_tr, X_te, y_tr, y_te = train_test_split(
                X, y, test_size=test_size, random_state=42)
            m = XGBRegressor(objective="reg:squarederror", **fit_params)
            m.fit(X_tr, y_tr)
            pred = np.clip(m.predict(X_te), 0.0, 100.0)
            self.modelos[eje] = m
            met[eje] = {
                "mae": float(mean_absolute_error(y_te, pred)),
                "r2": float(r2_score(y_te, pred)),
                "n_train": int(len(X_tr)),
                "n_test": int(len(X_te)),
            }

        self.metrics = {**met, "n_total": int(len(X))}
        self.version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._save()
        logger.info(
            "XGBoost (2 ejes) entrenado: v=%s  MAE ejec=%.2f  MAE resil=%.2f",
            self.version, met["ejecucion"]["mae"], met["resiliencia"]["mae"],
        )
        return self.metrics

    # ── Inference ─────────────────────────────────────────────────

    def predict(self, indicator_scores: Dict[str, float]) -> Dict[str, float]:
        """``{"ejecucion": x, "resiliencia": y}`` desde los scores de indicadores.

        Devuelve los dos scores y NO las bandas: la de Ejecución es relativa al panel y
        depende de contra quién se compare, así que se deriva aguas arriba con el corte
        vigente. El modelo predice la magnitud; la etiqueta la pone quien conoce el panel.
        """
        _ensure_ml_libs()
        if not self.modelos:
            self._load()

        X = np.array([extract_feature_vector(indicator_scores)])
        return {
            eje: float(np.clip(self.modelos[eje].predict(X)[0], 0.0, 100.0))
            for eje in EJES
        }

    # ── Serialization ─────────────────────────────────────────────
    # No pickle anywhere: a compromised blob must not be able to execute code.

    def _serialize(self) -> bytes:
        boosters = {}
        for eje in EJES:
            with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
                self.modelos[eje].save_model(tmp.name)
                boosters[eje] = base64.b64encode(open(tmp.name, "rb").read()).decode("ascii")
        payload = json.dumps({
            "boosters_b64": boosters,
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
        fmt = envelope.get("format") if isinstance(envelope, dict) else None
        if fmt == MODEL_FORMAT_LEGADO:
            # Un blob v2 predice TIERS, no ejes. Cargarlo daría números sin significado,
            # así que se rechaza con instrucción explícita en vez de degradar en silencio.
            raise ModelIntegrityError(
                "Modelo entrenado con la notación de letras (formato v2). Perfil SDQ "
                "predice dos ejes: hay que re-entrenar con POST /model/train.")
        if not isinstance(envelope, dict) or fmt != MODEL_FORMAT:
            raise ModelIntegrityError(f"Formato de modelo desconocido: {fmt or '?'}")
        payload = base64.b64decode(envelope.get("payload_b64", ""))
        if not hmac.compare_digest(_sign(payload), str(envelope.get("hmac", ""))):
            raise ModelIntegrityError(
                "Firma HMAC inválida: el blob del modelo fue alterado. Se rechaza."
            )
        data = json.loads(payload.decode("utf-8"))

        _ensure_ml_libs()
        modelos = {}
        for eje in EJES:
            m = XGBRegressor()
            with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
                tmp.write(base64.b64decode(data["boosters_b64"][eje]))
                tmp.flush()
                m.load_model(tmp.name)
            modelos[eje] = m

        self.modelos = modelos
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
        if not self.modelos:
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
        if self.modelos:
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
        available = bool(self.modelos) or os.path.exists(self._model_path)
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
