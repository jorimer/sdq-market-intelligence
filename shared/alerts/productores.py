"""El productor TRANSVERSAL — lo que se puede avisar de un eje sin conocer ese eje.

Banca tiene su propio adaptador porque tiene un motor de precursores calibrado. Los otros
quince no, y escribir quince adaptadores sería quince veces la misma traducción. Lo que sí
tienen todos es el CONTRATO de producto, y de ahí salen tres disparadores sin conocer una
sola métrica de sector:

| Disparador   | De dónde sale | A cuántos ejes alcanza |
|---|---|---|
| `frescura`   | `shared.validation.frescura` (motores registrados) | los que registran motor |
| `publicacion`| `shared/publications` + `ReportSpec.sectors` | los que tienen fuente recurrente |
| `posicion`   | `canonical_scores` + `rank_comparable` | los que publican scores canónicos |

**La cobertura se DECLARA, no se insinúa.** :func:`cobertura` la computa y la expone en
`GET /alerts/rules`, para que la UI pueda decirle al cliente qué le va a llegar de cada eje
en vez de dejarlo esperando. Un eje del catálogo que hoy no aporta nada es una brecha
honesta; presentarlo como vigilable es la mentira.

**Ningún productor de acá inventa un «antes».** Las tres reglas son de transición y su
estado previo sale de `shared/alerts/observaciones.py`: sin observación previa, callan.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from shared.alerts import observaciones
from shared.alerts.models import TODO_EL_EJE
from shared.alerts.motor import Produccion, register_producer
from shared.alerts.reglas import (AlertEvent, rule_frescura, rule_posicion,
                                  rule_publicacion)
from shared.products.registry import CATALOG_BY_KEY, get_product, registered_sectors

logger = logging.getLogger("sdq.alerts.productores")

BASIS_FRESCURA = ("La frescura de un reporte de validación se computa contra la HUELLA de su "
                  "insumo, no contra el reloj: producción sirvió 19 días un Gini calculado "
                  "con un score que ya no existía.")
BASIS_PUBLICACION = ("Ingesta de ediciones recurrentes (shared/publications). Avisa que el "
                     "dato del eje se movió, no que un organismo publicó algo.")
BASIS_POSICION = ("Ranking dentro del universo comparable "
                  "(shared.narrative.derived.universo_comparable): solo se ordena lo que "
                  "mide lo mismo.")

# Cuántos puestos tiene que moverse un sujeto para que valga un aviso. Uno solo es ruido en
# paneles grandes, donde el orden baila por decimales.
SALTOS_MINIMOS = 2


# ── Frescura de la validación ────────────────────────────────────────────────

def _eventos_frescura(db: Session, sector_key: str, label: str,
                      producto: Any) -> Tuple[List[AlertEvent], Set[str]]:
    """Aviso de que la validación de un eje dejó de estar vigente.

    **El motor NO se busca por la clave del eje.** ``MOTORES`` se indexa por MÓDULO
    (`banking_score`, `trade_intel`) y el catálogo por SECTOR (`banking`, `trade`): de ocho
    motores registrados, una sola clave coincide por casualidad (`social_dev`). Buscar por
    `sector_key` no falla —devuelve `None`— y el eje queda mudo para siempre, que es
    exactamente cómo un binding a algo inexistente se vuelve invisible.

    El puente lo declara el propio producto en ``ESTADO_BACKTEST.eje_motor``, y se lee de la
    CLASE y no del ``ValidationState`` que devuelve el método: varios ejes tienen ramas de
    retorno distintas y el hueco entra por la que alguien olvidó. Es el mismo camino que usa
    `shared/products/credenciales.py`; duplicar el criterio lo haría divergir.
    """
    from shared.validation import frescura as fr

    estado_backtest = getattr(type(producto), "ESTADO_BACKTEST", None) if producto else None
    clave_motor = getattr(estado_backtest, "eje_motor", None)
    motor = fr.MOTORES.get(clave_motor) if clave_motor else None
    if motor is None:
        return [], set()

    reporte = _leer_json(db, str(motor.clave))
    if reporte is None:
        # Sin reporte persistido no hay validación cuya vigencia juzgar. No es lo mismo que
        # «vencida», y confundirlos avisaría de un problema inexistente en cada eje que
        # todavía no corrió su motor.
        return [], set()

    estado = fr.con_frescura(dict(reporte), str(motor.eje), db)
    clave = observaciones.clave(sector_key, TODO_EL_EJE, "validacion_stale")
    previo = observaciones.transicion(db, clave, estado.get("stale"))

    ev = rule_frescura(
        sector_key=sector_key, eje_label=label, periodo=str(estado.get("period") or ""),
        stale_actual=estado.get("stale"), stale_previo=previo,
        motivo=str(estado.get("stale_reason") or ""), basis=BASIS_FRESCURA)
    return ([ev] if ev is not None else []), {f"{sector_key}:{TODO_EL_EJE}:frescura:validacion"}


# ── Publicaciones ingeridas ──────────────────────────────────────────────────

def _eventos_publicacion(db: Session, sector_key: str) -> Tuple[List[AlertEvent], Set[str]]:
    from shared.publications import catalog as pub_catalog
    from shared.publications.models import Publication

    eventos: List[AlertEvent] = []
    evaluadas: Set[str] = set()
    for key in pub_catalog.report_keys():
        spec = pub_catalog.REPORTS[key]
        if sector_key not in (spec.sectors or ()):
            continue
        ultima = (db.query(Publication.period)
                  .filter(Publication.report_key == key, Publication.status == "ok")
                  .order_by(Publication.created_at.desc().nullslast())
                  .first())
        actual = str(ultima[0]) if ultima and ultima[0] else None
        if actual is None:
            continue
        clave = observaciones.clave(sector_key, TODO_EL_EJE, f"publicacion:{key}")
        previo = observaciones.transicion(db, clave, actual)
        evaluadas.add(f"{sector_key}:{TODO_EL_EJE}:publicacion:{key}")
        ev = rule_publicacion(
            sector_key=sector_key, publicacion_label=str(spec.name), periodo=actual,
            edicion_actual=actual, edicion_previa=previo, basis=BASIS_PUBLICACION)
        if ev is not None:
            eventos.append(ev)
    return eventos, evaluadas


# ── Posición en el universo comparable ───────────────────────────────────────

def _eventos_posicion(db: Session, sector_key: str, producto: Any
                      ) -> Tuple[List[AlertEvent], Set[str]]:
    from shared.narrative.derived import rank_comparable, universo_comparable

    scores_fn = getattr(producto, "canonical_scores", None)
    obs_fn = getattr(producto, "score_observations", None)
    if scores_fn is None or obs_fn is None:
        # Descriptor sin lector (o al revés) es un ranking que se anuncia y nadie puede
        # leer: el manifiesto de la Data API ya trata ese caso como cuarentena.
        return [], set()

    eventos: List[AlertEvent] = []
    evaluadas: Set[str] = set()
    for desc in scores_fn() or []:
        codigo = str(getattr(desc, "code", "") or "")
        periodo = str(getattr(desc, "period_latest", "") or "")
        if not codigo or not periodo:
            continue
        try:
            filas = list(obs_fn(codigo, start=periodo, end=periodo) or [])
        except Exception as e:  # noqa: BLE001 — un score ilegible no aborta el eje
            logger.warning("alerts: no se pudo leer '%s' de '%s': %s", codigo, sector_key, e)
            continue

        panel = [{"slug": str(f.subject), "overall_score": f.score,
                  "coverage": _coverage(f)} for f in filas if f.score is not None]
        if len(panel) < 2:
            continue  # sin panel no hay orden que afirmar
        universo = universo_comparable(panel, clave_score="overall_score")

        for fila in panel:
            slug = str(fila["slug"])
            pos = rank_comparable(slug, universo)
            clave = observaciones.clave(sector_key, slug, f"posicion:{codigo}")
            previo = observaciones.transicion(db, clave, pos.get("rank"))
            evaluadas.add(f"{sector_key}:{slug}:posicion:{codigo}")
            ev = rule_posicion(
                sector_key=sector_key, subject=slug, sujeto_label=slug, periodo=periodo,
                rank_actual=pos.get("rank"), rank_previo=previo,
                n_comparables=pos.get("n_comparables"), criterio=str(pos.get("criterio") or ""),
                basis=BASIS_POSICION, saltos_minimos=SALTOS_MINIMOS,
                procedencia={codigo: "live"}, frescura=True)
            if ev is not None:
                eventos.append(ev)
    return eventos, evaluadas


def _coverage(fila: Any) -> Optional[float]:
    """Cobertura de la observación, si la trae. ``None`` = completa, por la misma razón que
    en ``universo_comparable``: un motor que no expone cobertura no debe perder su ranking
    por una clave que nunca escribió."""
    dims = getattr(fila, "dimensions", None)
    if isinstance(dims, dict) and dims.get("coverage") is not None:
        try:
            return float(dims["coverage"])
        except (TypeError, ValueError):
            return None
    return None


# ── El productor ─────────────────────────────────────────────────────────────

def producir(db: Session, sector_key: str) -> Produccion:
    entry = CATALOG_BY_KEY.get(sector_key)
    label = entry.display_name if entry else sector_key
    producto = get_product(sector_key, db)

    eventos: List[AlertEvent] = []
    evaluadas: Set[str] = set()
    for fn in (lambda: _eventos_frescura(db, sector_key, label, producto),
               lambda: _eventos_publicacion(db, sector_key),
               lambda: (_eventos_posicion(db, sector_key, producto)
                        if producto is not None else ([], set()))):
        try:
            evs, evals = fn()
        except Exception as e:  # noqa: BLE001 — un disparador que falla no aborta los otros
            logger.warning("alerts: disparador transversal falló en '%s': %s", sector_key, e)
            continue
        eventos.extend(evs)
        evaluadas |= evals
    return Produccion(eventos=eventos, evaluadas=evaluadas)


def cobertura(db: Optional[Session] = None) -> Dict[str, List[str]]:
    """Qué disparadores aporta HOY cada eje. Se computa, no se declara a mano.

    Es lo que hace que la UI pueda decir «este eje te avisa de X e Y» en vez de prometer
    los seis en todos lados. Un eje sin nada listado no está roto: no aporta todavía, y eso
    es una brecha declarada.
    """
    from shared.publications import catalog as pub_catalog
    from shared.validation import frescura as fr

    con_publicacion = {s for key in pub_catalog.report_keys()
                       for s in (pub_catalog.REPORTS[key].sectors or ())}
    out: Dict[str, List[str]] = {}
    for sector_key in CATALOG_BY_KEY:
        codigos: List[str] = []
        producto = get_product(sector_key, db) if db is not None else None
        # Mismo puente que en `_eventos_frescura`: el motor se declara en ESTADO_BACKTEST,
        # no se adivina por la clave del eje.
        estado_backtest = getattr(type(producto), "ESTADO_BACKTEST", None) if producto else None
        clave_motor = getattr(estado_backtest, "eje_motor", None)
        if clave_motor and clave_motor in fr.MOTORES:
            codigos.append("frescura")
        if sector_key in con_publicacion:
            codigos.append("publicacion")
        if producto is not None and getattr(producto, "canonical_scores", None) is not None:
            codigos.append("posicion")
        out[sector_key] = codigos
    return out


def register(exceptuar: Tuple[str, ...] = ("banking",)) -> List[str]:
    """Engancha el productor transversal a cada eje IMPLEMENTADO que no tenga el suyo.

    ``exceptuar`` lleva los ejes con adaptador propio: banca ya aporta `umbral`, `banda` y
    `brecha` desde su motor de precursores, y registrar el transversal encima lo reemplazaría
    —el registro es uno por eje—, perdiendo justamente las señales más específicas que hay.

    Devuelve los ejes enganchados, para que el arranque pueda registrarlo y no haya que
    adivinar la cobertura leyendo código.
    """
    enganchados: List[str] = []
    for sector_key in registered_sectors():
        if sector_key in exceptuar:
            continue
        register_producer(sector_key, _fabricar(sector_key))
        enganchados.append(sector_key)
    logger.info("alerts: productor transversal en %d eje(s): %s",
                len(enganchados), ", ".join(enganchados) or "ninguno")
    return enganchados


def _fabricar(sector_key: str):
    """Cierra sobre el eje. Sin esto, los N productores compartirían la última clave del
    bucle — el clásico de las lambdas en un `for`."""
    def _producir(db: Session) -> Produccion:
        return producir(db, sector_key)

    _producir.__name__ = f"producir_{sector_key}"
    return _producir


def _leer_json(db: Session, clave: str) -> Optional[Dict[str, Any]]:
    import json

    from shared.settings.models import AppSetting

    try:
        row = db.query(AppSetting).filter(AppSetting.key == clave).first()
        return json.loads(str(row.value)) if row and row.value else None
    except Exception:  # noqa: BLE001 — un reporte ilegible no rompe el barrido
        db.rollback()
        return None
