"""Contador de corridas de las herramientas comerciales. MIDE; no restringe.

**El hueco que cierra.** Research a Medida, Deal Scoring y Contexto de Marca son la única
capa del sistema con costo variable real por corrida —cada ejecución paga llamadas al modelo
que nadie pidió por adelantado— y ninguna de las tres tenía contador. «¿Cuántas veces se usó
Deal Scoring este mes?» no tenía respuesta, y sin ella cualquier decisión sobre su empaque
comercial es una impresión.

**Por qué no alcanza el ledger del modelo.** ``llm_calls`` cuenta LLAMADAS. La relación con
una corrida no es uno a uno: un informe de marca dispara decenas y un score sin narrativa no
dispara ninguna. Derivar corridas de llamadas exigiría inventar un criterio de agrupación,
y el resultado tendría cara de medición.

**Lo que esto NO es.** No hay cuota, ni gate, ni tier, ni cobro. Poner un techo es una
decisión comercial que no está tomada, y tomarla de refilón desde la instrumentación sería
decidirla sin datos — que es exactamente lo que este contador viene a evitar.

**Se cuentan también las corridas fallidas.** Una herramienta cara que falla la mitad de las
veces cuesta igual; contar solo los éxitos oculta justo eso. ``ok`` las separa.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import date, datetime, time as _time, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from shared.observability.models import ToolRun

logger = logging.getLogger("sdq.observability.uso_de_herramientas")

# ── Catálogo de herramientas ────────────────────────────────────────────────────
# Las claves son el dato persistido; las etiquetas, lo que lee el operador. Vive acá porque
# NO existe otra fuente para estos tres nombres: no son sectores del catálogo de productos
# ni operaciones de la consola. Una herramienta nueva se agrega acá y aparece sola en el
# panel, que es data-driven — no hay una segunda lista que se pueda olvidar.
RESEARCH = "research_a_medida"
DEAL_SCORING = "deal_scoring"
BRAND_INTEL = "contexto_de_marca"

HERRAMIENTAS: Dict[str, str] = {
    RESEARCH: "Research a Medida",
    DEAL_SCORING: "Deal Scoring",
    BRAND_INTEL: "Contexto de Marca",
}

#: Rango por defecto cuando no se pide uno: los últimos treinta días (igual que el gasto).
DEFAULT_DAYS = 30

#: Tope del sujeto persistido, alineado con el largo de la columna. Se recorta acá y no en
#: la base: SQLite no aplica el largo de un VARCHAR y Postgres sí, así que un sujeto largo
#: pasaría todos los tests y tumbaría el registro en producción.
_SUJETO_MAX = 200


def etiqueta_herramienta(clave: Optional[str]) -> str:
    """Nombre legible. Lo que no se reconoce se devuelve tal cual —feo pero cierto— en vez
    de esconderse bajo un «Otros» que lo mezcle con lo demás."""
    if not clave:
        return "Sin herramienta"
    return HERRAMIENTAS.get(clave, clave)


def id_de(user: Any) -> Optional[str]:
    """El id de quien corre, o ``None``. Defensivo A PROPÓSITO.

    ``user_id`` es nullable por diseño (una corrida puede llegar por un camino sin usuario
    resuelto), y leer el atributo en la ruta es lo único de esta instrumentación que ocurre
    FUERA del best-effort de ``registrar_uso``. Un ``AttributeError`` ahí tumbaría la entrega
    de la herramienta por culpa del contador, que es exactamente lo que no puede pasar.
    """
    valor = getattr(user, "id", None)
    return str(valor) if valor is not None else None


def _periodo(momento: datetime) -> str:
    return momento.strftime("%Y-%m")


def registrar_uso(
    *,
    herramienta: str,
    accion: str,
    user_id: Optional[str] = None,
    sujeto: Optional[str] = None,
    ok: bool = True,
    latency_ms: Optional[int] = None,
    detalle: Optional[Dict[str, Any]] = None,
) -> None:
    """Guarda UNA corrida. Best-effort: jamás lanza, jamás tumba la entrega.

    Abre su propia sesión corta en vez de reusar la de la petición: si la ruta falla después
    y su transacción se revierte, la corrida igual ocurrió y su costo ya se pagó. Un contador
    que se borra junto con el error no cuenta lo que más interesa contar.
    """
    try:
        from shared.database.session import SessionLocal

        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        db = SessionLocal()
        try:
            db.add(ToolRun(
                herramienta=herramienta,
                accion=accion,
                user_id=user_id,
                sujeto=(sujeto or "")[:_SUJETO_MAX] or None,
                periodo=_periodo(ahora),
                ok=bool(ok),
                latency_ms=latency_ms,
                detalle=detalle or None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — la instrumentación jamás rompe la herramienta
        # WARNING y no debug, a diferencia del ledger del modelo. Ahí una fila perdida es
        # una llamada que no se atribuye; acá es una corrida que NO OCURRIÓ para el panel, y
        # el síntoma —un número más bajo— se lee como «se usó menos», que es una conclusión
        # comercial equivocada e indistinguible de la verdadera. Se comprobó perdiendo una
        # corrida real por un `database is locked` de SQLite en dev: 200 en la ruta, cero
        # rastro en el contador y nada en ningún log. Un contador que subcuenta en silencio
        # es peor que no tenerlo.
        logger.warning("No se pudo registrar el uso de %s/%s: la corrida ocurrió y el "
                       "contador la perdió (el panel va a subcontar).",
                       herramienta, accion, exc_info=True)


@contextmanager
def medir_uso(*, herramienta: str, accion: str, user_id: Optional[str] = None,
              sujeto: Optional[str] = None,
              detalle: Optional[Dict[str, Any]] = None) -> Iterator[None]:
    """Envuelve una corrida: la cuenta al terminar, haya salido bien o mal, con su duración.

    Registrar al final del cuerpo de la ruta dejaría fuera las corridas que fallan, que son
    las que más caro salen por unidad de valor entregado.
    """
    inicio = time.perf_counter()
    ok = True
    try:
        yield
    except BaseException:
        ok = False
        raise
    finally:
        registrar_uso(herramienta=herramienta, accion=accion, user_id=user_id,
                      sujeto=sujeto, ok=ok, detalle=detalle,
                      latency_ms=int((time.perf_counter() - inicio) * 1000))


def _rango(desde: Optional[date], hasta: Optional[date]):
    """``hasta`` es INCLUSIVO del día completo: quien pide «hasta el 16» quiere lo del 16.
    Tomar la fecha tal cual dejaría fuera el último día —el que más se mira— y el error
    sería invisible porque el total seguiría siendo un número plausible."""
    fin_dia = hasta or datetime.now(timezone.utc).date()
    ini_dia = desde or (fin_dia - timedelta(days=DEFAULT_DAYS))
    return (datetime.combine(ini_dia, _time.min), datetime.combine(fin_dia, _time.max))


def resumen_de_uso(db: Session, desde: Optional[date] = None,
                   hasta: Optional[date] = None) -> Dict[str, Any]:
    """Cuántas veces se corrió cada herramienta en el rango, y quiénes la corrieron.

    Cada clave nombra su población: ``corridas_de_la_herramienta`` y no ``corridas``,
    ``usuarios_distintos_de_la_herramienta`` y no ``usuarios``. Un conteo que no dice sobre
    qué se contó se reatribuye al sujeto más cercano en cuanto sale de esta función.
    """
    ini, fin = _rango(desde, hasta)
    filas = (
        db.query(
            ToolRun.herramienta.label("herramienta"),
            func.count(ToolRun.id).label("corridas"),
            func.sum(func.cast(ToolRun.ok, Integer)).label("exitosas"),
            func.count(func.distinct(ToolRun.user_id)).label("usuarios"),
        )
        .filter(ToolRun.created_at >= ini, ToolRun.created_at <= fin)
        .group_by(ToolRun.herramienta)
        .all()
    )
    por_herramienta: List[Dict[str, Any]] = sorted(
        (
            {
                "herramienta": r.herramienta,
                "etiqueta": etiqueta_herramienta(r.herramienta),
                "corridas_de_la_herramienta": int(r.corridas or 0),
                "corridas_fallidas_de_la_herramienta":
                    int(r.corridas or 0) - int(r.exitosas or 0),
                "usuarios_distintos_de_la_herramienta": int(r.usuarios or 0),
            }
            for r in filas
        ),
        key=lambda d: -d["corridas_de_la_herramienta"],
    )

    acciones = (
        db.query(
            ToolRun.herramienta.label("herramienta"),
            ToolRun.accion.label("accion"),
            func.count(ToolRun.id).label("corridas"),
        )
        .filter(ToolRun.created_at >= ini, ToolRun.created_at <= fin)
        .group_by(ToolRun.herramienta, ToolRun.accion)
        .all()
    )

    # Las herramientas SIN corridas se listan en cero en vez de desaparecer: un catálogo que
    # solo muestra lo que se usó no distingue «nadie la usó» de «no existe», y son las dos
    # respuestas comercialmente opuestas.
    vistas = {d["herramienta"] for d in por_herramienta}
    for clave, etiqueta in HERRAMIENTAS.items():
        if clave not in vistas:
            por_herramienta.append({
                "herramienta": clave, "etiqueta": etiqueta,
                "corridas_de_la_herramienta": 0,
                "corridas_fallidas_de_la_herramienta": 0,
                "usuarios_distintos_de_la_herramienta": 0,
            })

    return {
        "desde": ini.date().isoformat(),
        "hasta": fin.date().isoformat(),
        "corridas_totales_de_las_herramientas": sum(
            d["corridas_de_la_herramienta"] for d in por_herramienta),
        "por_herramienta": por_herramienta,
        "por_accion": sorted(
            ({"herramienta": r.herramienta,
              "etiqueta": etiqueta_herramienta(r.herramienta),
              "accion": r.accion,
              "corridas_de_la_accion": int(r.corridas or 0)} for r in acciones),
            key=lambda d: -d["corridas_de_la_accion"]),
    }
