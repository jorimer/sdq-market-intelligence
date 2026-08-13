"""Ingesta de comercio bilateral ABIERTO POR CAPÍTULO (Comtrade).

**Por qué existe.** El motor de Research declaró fuera de alcance la pregunta "¿qué le
importamos a China, desglosado por bien?". No lo estaba: el cliente de Comtrade pedía
producto × mundo y socio × total, nunca las dos juntas, y la misma API responde el cruce en
una llamada. Era un límite de la CONSULTA, no del sistema — y el informe además INFIRIÓ la
composición ("bienes de consumo masivo, insumos industriales…") pudiendo medirla.

El Excel de la DGA no puede suplirlo: publica capítulo × valor SIN país de origen.
"""
import logging
from typing import Any, Dict, List, Optional, cast

from sqlalchemy.orm import Session

from modules.trade_intel.models.models import TradeDirection, TradePartnerChapter

logger = logging.getLogger("sdq.trade_intel.partner_chapters")

RD_M49 = "214"
FUENTE = "UN Comtrade"
LICENCIA = "https://comtrade.un.org/db/help/licenseagreement.aspx"

# Socios a ingerir. Acotado a propósito: cada socio × año es una llamada con rate limit, y
# traer los ~200 socios no aporta — la pregunta de negocio es por los que concentran la
# corriente. Se declara cuáles son para que nadie lea el panel como si fuera exhaustivo.
SOCIOS = {"156": "China", "842": "Estados Unidos", "76": "Brasil",
          "484": "México", "724": "España"}


def _upsert(db: Session, *, period: str, partner: str, partner_code: str,
            direction: TradeDirection, chapter: str, value: Optional[float]) -> bool:
    row = (db.query(TradePartnerChapter)
           .filter_by(period=period, partner=partner, direction=direction, chapter=chapter)
           .first())
    creada = row is None
    if row is None:
        row = TradePartnerChapter(period=period, partner=partner, direction=direction,
                                  chapter=chapter)
        db.add(row)
    # cast: SQLAlchemy tipa las columnas como Column[...]; el driver convierte el valor.
    row.partner_code = cast(Any, partner_code)
    row.value = cast(Any, value)
    row.source = cast(Any, FUENTE)
    row.license = cast(Any, LICENCIA)
    return creada


def sync_partner_chapters(db: Session, years: List[int],
                          socios: Optional[Dict[str, str]] = None,
                          set_phase=None) -> Dict[str, Any]:
    """Ingiere ``{socio × capítulo}`` para *years*. Idempotente por (período, socio, capítulo).

    Un socio que la fuente no devuelve NO se rellena ni se borra: se cuenta como vacío y se
    reporta. Un fallo de red en un socio no aborta los demás.
    """
    from shared.data.comtrade_client import fetch_partner_chapters

    set_phase = set_phase or (lambda _m: None)
    socios = socios or SOCIOS
    creadas = actualizadas = 0
    vacios: List[str] = []
    fallidos: List[str] = []

    for code, nombre in socios.items():
        set_phase(f"{nombre} ({len(years)} años)")
        try:
            por_año = fetch_partner_chapters(RD_M49, code, years, flow="M")
        except Exception as e:  # noqa: BLE001 — un socio caído no tumba la ingesta
            logger.warning("Comtrade socio %s no disponible: %s", nombre, e)
            fallidos.append(nombre)
            continue
        if not por_año:
            vacios.append(nombre)
            continue
        for period, capitulos in por_año.items():
            for chapter, value in capitulos.items():
                if _upsert(db, period=period, partner=nombre, partner_code=code,
                           direction=TradeDirection.import_, chapter=chapter, value=value):
                    creadas += 1
                else:
                    actualizadas += 1
        db.commit()

    return {"socios": list(socios.values()), "años": years,
            "filas_creadas": creadas, "filas_actualizadas": actualizadas,
            # Brechas declaradas, no silenciadas.
            "socios_sin_dato": vacios, "socios_fallidos": fallidos}


def importaciones_por_capitulo(db: Session, partner: str,
                               period: Optional[str] = None) -> Dict[str, Any]:
    """Lo que el motor de Research necesita: ``{period, partner, total, capitulos:[…]}``.

    Sin dato devuelve ``capitulos: []`` y ``period: None`` — la brecha se declara, no se
    rellena con el agregado del mundo, que mediría otra cosa.
    """
    q = db.query(TradePartnerChapter).filter(
        TradePartnerChapter.partner == partner,
        TradePartnerChapter.direction == TradeDirection.import_)
    if period:
        q = q.filter(TradePartnerChapter.period == period)
    else:
        ult = (db.query(TradePartnerChapter.period)
               .filter(TradePartnerChapter.partner == partner)
               .order_by(TradePartnerChapter.period.desc()).first())
        if not ult:
            return {"partner": partner, "period": None, "total_usd_mm": None,
                    "capitulos": [], "fuente": FUENTE}
        period = ult[0]
        q = q.filter(TradePartnerChapter.period == period)

    filas = [r for r in q.all() if r.value is not None]
    total = sum(float(cast(Any, r.value)) for r in filas)
    caps: List[Dict[str, Any]] = [
        {"capitulo": str(r.chapter), "usd_mm": round(float(cast(Any, r.value)), 2),
         "pct": (round(float(cast(Any, r.value)) / total * 100, 2) if total else None)}
        for r in filas]
    caps.sort(key=lambda d: -float(d["usd_mm"]))
    return {"partner": partner, "period": period,
            "total_usd_mm": round(total, 2) if filas else None,
            "n_capitulos": len(caps), "capitulos": caps, "fuente": FUENTE}
