"""Manifiesto de exposición — la pieza que hace la API auto-extensible.

Regla de arquitectura (docs/SPEC_API_DATOS_PROPIETARIOS.md §3): **ningún endpoint conoce
una serie ni un indicador concreto**. Este módulo recorre el catálogo de productos y
pregunta a cada uno qué publica (``canonical_series``), igual que ``shared/registry``
pregunta por ``variable_signals``. Cablear una serie nueva en un módulo la publica sola;
nadie edita la capa API.

Anti-Frankenstein: como todo ``shared/*``, este paquete NUNCA importa un módulo de
sector — llega a ellos por el contrato.

**Cuarentena calculada, no lista curada.** Un activo se retiene por una condición
verificable, y se libera solo cuando la condición deja de aplicar. Nadie tiene que
acordarse de aprobar nada; ese era el punto de la decisión de amplitud.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.products.activation import ACTIVATION_THRESHOLD
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented
from shared.products.tiers import ProductTier

logger = logging.getLogger("sdq.data_api")

# ─── Razones de cuarentena (canónicas: viajan al cliente en `/catalog`) ──
Q_NO_LICENSE = "no_license"                  # sin licencia declarada → no se redistribuye
Q_NOT_ACTIVATED = "sector_not_activated"     # el sector no está publicado
Q_LOW_READINESS = "readiness_below_threshold"
Q_NO_READER = "no_reader"                    # descriptor sin lector: se anuncia y no se lee
# La fuente restringe la REDISTRIBUCIÓN (no-comercial / share-alike). Aplica solo a lo
# verbatim: el cálculo propio sobre ese insumo es obra nuestra y no se retiene.
Q_LICENSE_RESTRICTS = "license_restricts_redistribution"
# NOTA: "código no interpretable" NO es razón de cuarentena. Retener dato válido porque
# nuestro extractor no supo nombrarlo sería degradar el producto para tapar una carencia
# propia (decisión del dueño, 2026-07-23): el arreglo es mejorar el extractor, no esconder
# su salida. Se declara como `label_quality` —visible para el cliente y contable en el
# manifiesto interno— y así funciona como COLA DE TRABAJO en vez de basurero.

# Doctrina del dueño (2026-07-22): "calculamos, no revendemos la misma info". El eje que
# decide no es la fuente sino QUÉ se sirve — el valor del emisor, o un cálculo de casa.
DERIVATION_VERBATIM = "verbatim"
DERIVATION_DERIVED = "derived"

# Licencia de los activos de cálculo propio (scores/índices/señales): la marca SDQ.
SDQ_OWN_LICENSE = ("Cálculo propietario de SDQ Market Intelligence — uso según los "
                   "términos de la llave; atribuir a SDQ al citar.")

# Marcas de licencias que restringen redistribuir el dato tal cual. Se detectan por
# patrón sobre lo que el conector declara: ITU es CC BY-NC-SA (no-comercial), y
# SIS/SISALRIL declaran ODbL (share-alike sobre bases derivadas).
_RESTRICTIVE_MARKERS = ("nc-", "-nc", "non-commercial", "no comercial", "nocommercial",
                        "sharealike", "share-alike", "-sa", "sa ", "odbl")


# Un código cuya hoja final es puro número —o trae una corrida larga de dígitos— no es
# un nombre: es un artefacto del extractor (valor de celda leído como identificador).
# Publicarlo es publicar ruido con apariencia de dato. El guard vive ACÁ y no en el módulo
# del BCRD a propósito: el motor de Excel es genérico y el defecto reaparece con cualquier
# fuente que se incorpore por planilla.
_DIGIT_RUN = re.compile(r"\d{6,}")
_ONLY_SYMBOLS = re.compile(r"^[\d_.\-]+$")


LABEL_NAMED = "named"
LABEL_UNNAMED = "unnamed"      # el extractor no pudo nombrarla: hay trabajo pendiente


def code_is_uninterpretable(code: str) -> bool:
    """¿El código deja saber qué mide la serie? Conservador: solo marca lo indefendible.

    Marcar NO es retener: la serie se sirve igual. Es una señal de que el extractor tiene
    trabajo pendiente con ese archivo, no un permiso para descartar el dato."""
    leaf = str(code or "").split(".")[-1].strip()
    if not leaf:
        return True
    return bool(_ONLY_SYMBOLS.match(leaf) or _DIGIT_RUN.search(leaf))


def license_restricts_redistribution(license_: Optional[str]) -> bool:
    """¿La licencia declarada impide reexportar el dato TAL CUAL a un tercero?

    Heurística deliberadamente amplia (falso positivo = una serie retenida que alguien
    revisa; falso negativo = redistribuir algo que no podíamos). No sustituye leer los
    términos: marca para revisión, no dictamina.
    """
    text = (license_ or "").strip().lower()
    if not text:
        return False        # la ausencia la cubre Q_NO_LICENSE, no esta regla
    return any(marker in text for marker in _RESTRICTIVE_MARKERS)

# Un activo con pocas observaciones se sirve igual, pero ROTULADO: el cliente que
# automatiza necesita saber que la historia es corta antes de meterla en un modelo.
THIN_OBS = 8


@dataclass(frozen=True)
class ExposedAsset:
    """Un activo publicable de la Data API, con su veredicto de exposición."""

    key: str                    # "macro:series:gdp_growth"
    kind: str                   # "series" (F1) · "score" | "index" | "signal" (F2)
    sector_key: str
    code: str
    label: str
    unit: Optional[str] = None
    frequency: str = "unknown"
    source: str = ""
    license: Optional[str] = None
    period_first: Optional[str] = None
    period_latest: Optional[str] = None
    n_obs: int = 0
    stability: str = "stable"   # "stable" | "thin" (historia corta)
    derivation: str = DERIVATION_VERBATIM   # "verbatim" (dato del emisor) | "derived"
    # Curada = elegida y nombrada por un analista (citable en un informe). No curada =
    # extracción masiva de planilla: dato real, pero sin nombre defendible ante un cliente.
    curated: bool = False
    # Naturaleza estadística: flow | stock | rate | index | unknown. Decide qué
    # transformación admite la serie — una `rate` YA es un porcentaje y su variación se
    # mide en puntos. Ver shared/data/series_nature.py.
    nature: str = "unknown"
    # "unnamed" = el extractor no logró nombrar la serie (el código es un artefacto de la
    # planilla). El dato SE SIRVE igual; la marca dice que el nombre no es confiable y
    # que hay trabajo pendiente en el extractor.
    label_quality: str = LABEL_NAMED
    quarantine: Tuple[str, ...] = field(default=())
    note: str = ""

    @property
    def exposed(self) -> bool:
        return not self.quarantine

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["quarantine"] = list(self.quarantine)
        d["exposed"] = self.exposed
        return d


@dataclass(frozen=True)
class Manifest:
    """Inventario completo resuelto contra el registro, en un instante."""

    generated_at: str
    assets: Tuple[ExposedAsset, ...] = ()

    def exposed_assets(self) -> Tuple[ExposedAsset, ...]:
        return tuple(a for a in self.assets if a.exposed)

    def find(self, sector_key: str, code: str, kind: str = "series") -> Optional[ExposedAsset]:
        for a in self.assets:
            if a.sector_key == sector_key and a.code == code and a.kind == kind:
                return a
        return None

    def find_by_code(self, code: str, kind: str = "series") -> List[ExposedAsset]:
        """Todos los activos con ese código (puede repetirse entre sectores)."""
        return [a for a in self.assets if a.code == code and a.kind == kind]

    @property
    def summary(self) -> Dict[str, Any]:
        exposed = self.exposed_assets()
        reasons: Dict[str, int] = {}
        for a in self.assets:
            for r in a.quarantine:
                reasons[r] = reasons.get(r, 0) + 1
        return {
            "total": len(self.assets),
            "exposed": len(exposed),
            "quarantined": len(self.assets) - len(exposed),
            "quarantine_reasons": reasons,
            # Cola de trabajo del extractor: series servidas cuyo nombre no es confiable.
            # No se descartan; se arreglan.
            "unnamed": sum(1 for a in self.assets if a.label_quality == LABEL_UNNAMED),
            "sectors": sorted({a.sector_key for a in exposed}),
        }


# ─── Estado de publicación por sector (insumo de cuarentena) ──────────


def _sector_publication_state(db: Optional[Session]) -> Dict[str, Dict[str, Any]]:
    """``{sector_key: {"activated": bool, "readiness_ok": bool, …}}``.

    Sin sesión de DB no se puede verificar publicación: se devuelve vacío y el
    resolvedor pone en cuarentena TODO (fail-closed). Es la postura correcta — ante la
    duda, no se redistribuye.
    """
    if db is None:
        return {}
    state: Dict[str, Dict[str, Any]] = {}
    try:
        active_rows = (
            db.query(ProductActivation)
            .filter(ProductActivation.is_active.is_(True))
            .all()
        )
        readiness_rows = db.query(ProductReadiness).all()
    except Exception as exc:  # tabla ausente / transacción abortada
        logger.warning("data_api: no se pudo leer el estado de publicación: %s", exc)
        try:
            db.rollback()   # no envenenar la transacción siguiente (Postgres)
        except Exception:
            pass
        return {}

    # ``str(...)`` en la frontera: los modelos de productos usan el estilo legacy de
    # SQLAlchemy, cuyo tipo estático es ``Column[str]`` y no ``str``.
    readiness_by: Dict[Tuple[str, str], float] = {
        (str(r.sector_key), str(r.tier)): float(r.readiness or 0.0) for r in readiness_rows
    }
    for row in active_rows:
        sector_key, tier_value = str(row.sector_key), str(row.tier)
        entry = state.setdefault(
            sector_key, {"activated": True, "readiness_ok": False, "tiers": []}
        )
        entry["tiers"].append(tier_value)
        try:
            tier = ProductTier(tier_value)
        except ValueError:
            continue
        threshold = ACTIVATION_THRESHOLD.get(tier, 1.0)
        if readiness_by.get((sector_key, tier_value), 0.0) >= threshold:
            entry["readiness_ok"] = True
    return state


def _quarantine_for(
    sector_key: str,
    *,
    license_: Optional[str],
    has_reader: bool,
    pub_state: Dict[str, Dict[str, Any]],
    derivation: str = DERIVATION_VERBATIM,
    allow_restricted: bool = False,
) -> Tuple[str, ...]:
    """Razones por las que un activo NO se sirve. Vacío = se sirve."""
    reasons: List[str] = []
    if not (license_ or "").strip():
        reasons.append(Q_NO_LICENSE)
    # Servir el valor del emisor tal cual ES redistribuir; servir un cálculo propio, no.
    # Por eso la restricción de la fuente solo retiene lo verbatim.
    elif (not allow_restricted
          and derivation == DERIVATION_VERBATIM
          and license_restricts_redistribution(license_)):
        reasons.append(Q_LICENSE_RESTRICTS)
    if not has_reader:
        reasons.append(Q_NO_READER)
    sector = pub_state.get(sector_key)
    if not sector or not sector.get("activated"):
        reasons.append(Q_NOT_ACTIVATED)
    elif not sector.get("readiness_ok"):
        reasons.append(Q_LOW_READINESS)
    return tuple(reasons)


# ─── Construcción del manifiesto ──────────────────────────────────────


def _series_assets(db: Optional[Session], entry, pub_state,
                   allow_restricted: bool = False) -> List[ExposedAsset]:
    """Series que declara UN producto. Un producto que no implemente el par
    ``canonical_series`` / ``series_observations`` no aporta series — brecha honesta,
    no error."""
    if not is_implemented(entry.sector_key):
        return []
    try:
        product = get_product(entry.sector_key, db)
    except Exception as exc:
        logger.warning("data_api: no se pudo instanciar '%s': %s", entry.sector_key, exc)
        return []
    if product is None:
        return []

    describe = getattr(product, "canonical_series", None)
    if not callable(describe):
        return []
    has_reader = callable(getattr(product, "series_observations", None))

    try:
        described = list(describe() or ())
    except Exception as exc:
        logger.warning(
            "data_api: '%s' falló al describir sus series: %s", entry.sector_key, exc
        )
        try:
            db.rollback() if db is not None else None
        except Exception:
            pass
        return []

    out: List[ExposedAsset] = []
    for s in described:
        n_obs = int(getattr(s, "n_obs", 0) or 0)
        derivation = getattr(s, "derivation", DERIVATION_VERBATIM) or DERIVATION_VERBATIM
        out.append(
            ExposedAsset(
                key=f"{entry.sector_key}:series:{s.code}",
                kind="series",
                sector_key=entry.sector_key,
                code=s.code,
                label=getattr(s, "label", "") or s.code,
                unit=getattr(s, "unit", None),
                frequency=getattr(s, "frequency", "unknown") or "unknown",
                source=getattr(s, "source", "") or "",
                license=getattr(s, "license", None),
                period_first=getattr(s, "period_first", None),
                period_latest=getattr(s, "period_latest", None),
                n_obs=n_obs,
                stability="thin" if n_obs < THIN_OBS else "stable",
                derivation=derivation,
                curated=bool(getattr(s, "curated", False)),
                nature=str(getattr(s, "nature", "unknown") or "unknown"),
                label_quality=(LABEL_UNNAMED if code_is_uninterpretable(s.code)
                               else LABEL_NAMED),
                quarantine=_quarantine_for(
                    entry.sector_key,
                    license_=getattr(s, "license", None),
                    has_reader=has_reader,
                    pub_state=pub_state,
                    derivation=derivation,
                    allow_restricted=allow_restricted,
                ),
                note=getattr(s, "note", "") or "",
            )
        )
    return out


def _score_assets(db: Optional[Session], entry, pub_state) -> List[ExposedAsset]:
    """Scores/índices que declara UN producto (Fase 2), mismo patrón que las series.

    Un score es cálculo de casa — obra propia — así que no lleva licencia de emisor ni
    entra al filtro de redistribución: su cuarentena es solo activación + readiness +
    lector presente. La ``license`` del activo se fija a la marca SDQ para que el campo
    nunca viaje vacío (y el fail-closed de licencia no lo retenga por un tecnicismo).
    """
    if not is_implemented(entry.sector_key):
        return []
    try:
        product = get_product(entry.sector_key, db)
    except Exception as exc:
        logger.warning("data_api: no se pudo instanciar '%s': %s", entry.sector_key, exc)
        return []
    if product is None:
        return []

    describe = getattr(product, "canonical_scores", None)
    if not callable(describe):
        return []
    has_reader = callable(getattr(product, "score_observations", None))

    try:
        described = list(describe() or ())
    except Exception as exc:
        logger.warning(
            "data_api: '%s' falló al describir sus scores: %s", entry.sector_key, exc
        )
        try:
            db.rollback() if db is not None else None
        except Exception:
            pass
        return []

    out: List[ExposedAsset] = []
    for s in described:
        n_obs = int(getattr(s, "n_obs", 0) or 0)
        out.append(
            ExposedAsset(
                key=f"{entry.sector_key}:score:{s.code}",
                kind="score",
                sector_key=entry.sector_key,
                code=s.code,
                label=getattr(s, "label", "") or s.code,
                unit=getattr(s, "scale", None),
                frequency="unknown",
                source="SDQ Market Intelligence (cálculo propio)",
                license=SDQ_OWN_LICENSE,
                period_latest=getattr(s, "period_latest", None),
                n_obs=n_obs,
                stability="thin" if n_obs < THIN_OBS else "stable",
                derivation=DERIVATION_DERIVED,
                curated=True,     # un score es cálculo de casa: curado por definición
                quarantine=_quarantine_for(
                    entry.sector_key,
                    license_=SDQ_OWN_LICENSE,
                    has_reader=has_reader,
                    pub_state=pub_state,
                    derivation=DERIVATION_DERIVED,
                ),
                note=" · ".join(p for p in (
                    getattr(s, "direction", "") or "",
                    f"sujetos: {getattr(s, 'subject_kind', 'entity')}",
                    getattr(s, "note", "") or "",
                ) if p),
            )
        )
    return out


def _forecast_assets(db: Optional[Session], entry, pub_state) -> List[ExposedAsset]:
    """Modelos de pronóstico que declara UN producto (Fase 3).

    Como los scores, son cálculo de casa. El ``note`` del activo carga el track record
    resumido para que aparezca ya en el catálogo: quien navega el inventario debe ver el
    acierto ANTES de pedir el recurso."""
    if not is_implemented(entry.sector_key):
        return []
    try:
        product = get_product(entry.sector_key, db)
    except Exception as exc:
        logger.warning("data_api: no se pudo instanciar '%s': %s", entry.sector_key, exc)
        return []
    if product is None:
        return []

    describe = getattr(product, "canonical_forecasts", None)
    if not callable(describe):
        return []
    has_reader = callable(getattr(product, "forecast_observations", None))

    try:
        described = list(describe() or ())
    except Exception as exc:
        logger.warning(
            "data_api: '%s' falló al describir sus pronósticos: %s", entry.sector_key, exc
        )
        try:
            db.rollback() if db is not None else None
        except Exception:
            pass
        return []

    out: List[ExposedAsset] = []
    for f in described:
        n_scored = int(getattr(f, "n_scored", 0) or 0)
        hit = getattr(f, "hit_rate", None)
        track = f"acierto {hit:.0%} en {n_scored} puntuados" if hit is not None else \
            f"{n_scored} pronóstico(s) puntuado(s)"
        out.append(
            ExposedAsset(
                key=f"{entry.sector_key}:forecast:{f.code}",
                kind="forecast",
                sector_key=entry.sector_key,
                code=f.code,
                label=getattr(f, "label", "") or f.code,
                unit=None,
                frequency=getattr(f, "horizon", "") or "unknown",
                source="SDQ Market Intelligence (modelo propio)",
                license=SDQ_OWN_LICENSE,
                n_obs=n_scored,
                # Un modelo con pocos pronósticos puntuados es "thin" en el sentido que
                # importa: su tasa de acierto todavía no dice mucho.
                stability="thin" if n_scored < THIN_OBS else "stable",
                derivation=DERIVATION_DERIVED,
                curated=True,
                quarantine=_quarantine_for(
                    entry.sector_key, license_=SDQ_OWN_LICENSE, has_reader=has_reader,
                    pub_state=pub_state, derivation=DERIVATION_DERIVED,
                ),
                note=" · ".join(p for p in (
                    getattr(f, "target", "") or "", track,
                    getattr(f, "baseline", "") or "",
                ) if p),
            )
        )
    return out


def build_manifest(db: Optional[Session] = None, *,
                   allow_restricted: bool = False) -> Manifest:
    """El inventario completo, resuelto contra el registro en este instante.

    No se cachea a propósito en esta fase: el punto de la auto-extensión es que un
    activo nuevo aparezca sin intervención, y una caché mal invalidada lo demoraría
    justo donde importa. Si el costo se vuelve visible, cachear con TTL corto y
    exponer la edad de la caché en ``meta`` — nunca en silencio.
    """
    pub_state = _sector_publication_state(db)
    assets: List[ExposedAsset] = []
    for entry in PRODUCT_CATALOG:
        assets.extend(_series_assets(db, entry, pub_state, allow_restricted))
        assets.extend(_score_assets(db, entry, pub_state))
        assets.extend(_forecast_assets(db, entry, pub_state))
    return Manifest(
        generated_at=datetime.now(timezone.utc).isoformat(),
        assets=tuple(assets),
    )
