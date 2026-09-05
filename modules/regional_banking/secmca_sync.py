"""Persiste los cuadros EMFA del CMCA en `rb_country_aggregates`.

Sistemas nacionales, nunca entidades. La `norma_contable` que se estampa —«EMFA
armonizado»— es lo que después habilita comparar tasas entre países; sin ella el guard de
no-comparabilidad no tiene sobre qué decidir.
"""
import logging
from datetime import date
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.regional_banking.models.models import CountryBankingAggregate

logger = logging.getLogger("sdq.regional_banking.secmca")


def secmca_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
                client=None) -> Dict:
    """Trae los cuadros EMFA y los persiste. Devuelve un resumen con `errors[]`.

    *client* se inyecta en los tests; por defecto sale a la red.
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.secmca_client import SECMCAClient

    propio = client is None
    client = client or SECMCAClient(mode="live")

    set_phase("descargando cuadros EMFA (secmca.org)")
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — best-effort: se reporta, no se fabrica
        logger.warning("SECMCA sync falló: %s", e)
        return {"error": f"SECMCA no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} observaciones")
    synced, errores = 0, []
    cortes_por_pais: Dict[str, date] = {}

    for r in records:
        iso3 = r.dimension
        if not iso3 or not r.period:
            errores.append(f"observación sin país o corte: {r.series}")
            continue
        try:
            corte = date.fromisoformat(r.period)
        except ValueError:
            errores.append(f"corte ilegible para {iso3}: {r.period!r}")
            continue

        # El corte MÁS RECIENTE por país: el boletín lo declara país por país, porque las
        # plazas publican con rezagos muy distintos y un corte único desperdiciaría la
        # frescura de las rápidas para acomodar a la más lenta.
        if r.value is not None:
            previo = cortes_por_pais.get(iso3)
            if previo is None or corte > previo:
                cortes_por_pais[iso3] = corte

        fila = (db.query(CountryBankingAggregate)
                  .filter_by(iso_code=iso3, period_end=corte, metric=r.series,
                             source=client.source)
                  .first())
        if fila is None:
            fila = CountryBankingAggregate(
                iso_code=iso3, period_end=corte, metric=r.series, source=client.source)
            db.add(fila)
        fila.value = r.value
        fila.license = r.lineage.license if r.lineage else client.license
        fila.fetched_at = r.lineage.fetched_at if r.lineage else date.today()
        fila.norma_contable = client.NORMA_CONTABLE
        fila.meta = {
            "unit": r.unit,
            # Lo que EMFA armoniza es la metodología, no la unidad: las tasas se comparan
            # entre países y los saldos de crédito NO, porque van en moneda local y el
            # cuadro deja la unidad en blanco.
            "comparable_entre_paises": r.series.split("::")[0] in client.COMPARABLE_ENTRE_PAISES,
            "reason": r.reason,
        }
        synced += 1

    db.commit()
    return {
        "synced": synced,
        "countries": sorted({r.dimension for r in records if r.dimension}),
        "cortes_por_pais": {k: v.isoformat() for k, v in sorted(cortes_por_pais.items())},
        "cuadros": sorted({r.series.split("::")[0] for r in records}),
        "mode": getattr(client, "mode", "?") if propio else "inyectado",
        "errors": errores,
    }
