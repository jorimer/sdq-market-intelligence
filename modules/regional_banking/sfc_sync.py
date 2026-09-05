"""Persiste los agregados del sistema bancario colombiano en `rb_country_aggregates`."""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.regional_banking.models.models import CountryBankingAggregate

logger = logging.getLogger("sdq.regional_banking.sfc")

ISO3 = "COL"


def sfc_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
             client=None) -> Dict:
    """Trae los agregados del sistema colombiano y los persiste."""
    set_phase = set_phase or (lambda _m: None)
    from shared.data.sfc_client import SFCClient

    client = client or SFCClient(mode="live")

    set_phase("agregando el sistema colombiano (SFC vía datos.gov.co)")
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — se reporta, no se fabrica
        logger.warning("SFC sync falló: %s", e)
        return {"error": f"SFC no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} agregados")
    synced, errores, cortes = 0, [], set()
    for r in records:
        try:
            corte = date.fromisoformat(r.period)
        except ValueError:
            errores.append(f"corte ilegible: {r.period!r}")
            continue
        cortes.add(corte)
        fila = (db.query(CountryBankingAggregate)
                  .filter_by(iso_code=ISO3, period_end=corte, metric=r.series,
                             source=client.source)
                  .first())
        if fila is None:
            fila = CountryBankingAggregate(iso_code=ISO3, period_end=corte,
                                           metric=r.series, source=client.source)
            db.add(fila)
        fila.value = r.value
        fila.license = r.lineage.license if r.lineage else client.license
        fila.fetched_at = r.lineage.fetched_at if r.lineage else date.today()
        fila.norma_contable = client.NORMA_CONTABLE
        fila.meta = {
            "unit": r.unit,
            # NUNCA contra otros países: la norma es CUIF colombiana, no EMFA. Solvencia
            # bajo CUIF y bajo la Res. CMN 4966 brasileña no son la misma medición, y el
            # boletín narra estos indicadores como trayectoria DENTRO de cada sistema.
            "comparable_entre_paises": False,
            # El agregado lo calculamos nosotros sobre el dato por entidad del emisor: por
            # eso el share-alike de la fuente no retiene lo que publica el boletín.
            "derivacion": client.DERIVACION,
            "reason": r.reason,
        }
        synced += 1

    db.commit()
    return {"synced": synced, "country": ISO3,
            "cortes": sorted(c.isoformat() for c in cortes),
            "series": sorted({r.series for r in records}),
            "mode": getattr(client, "mode", "?"), "errors": errores}
