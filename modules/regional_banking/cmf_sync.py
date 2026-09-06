"""Persiste los indicadores del sistema bancario chileno en `rb_country_aggregates`."""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.regional_banking.models.models import CountryBankingAggregate

logger = logging.getLogger("sdq.regional_banking.cmf")

ISO3 = "CHL"


def cmf_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
             client=None) -> Dict:
    """Trae los indicadores del sistema chileno y los persiste.

    A diferencia de Colombia, acá NO agregamos nada: el reporte mensual de la CMF publica los
    indicadores del sistema ya calculados, con su fórmula contable al costado. Lo nuestro es
    leerlos sin transformarlos, y por eso la derivación se declara `verbatim`.
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.cmf_client import NOMBRES, CMFClient

    client = client or CMFClient(mode="live")

    set_phase("leyendo el reporte mensual del sistema bancario chileno (CMF)")
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — se reporta, no se fabrica
        logger.warning("CMF sync falló: %s", e)
        return {"error": f"CMF no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} indicadores")
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
        # DOS normas en el mismo país, y a propósito: la solvencia se computa bajo la Ley
        # General de Bancos reformada (Basilea III) y el resto bajo el Compendio de Normas
        # Contables. Una sola etiqueta por país mentiría sobre la mitad de las cifras.
        fila.norma_contable = client.norma_de(r.series)
        fila.meta = {
            "unit": r.unit,
            # El SUJETO viaja con el número. Sin esto el modelo lee «consumo: 2,39 %» y no
            # puede saber si es el saldo, la mora o la provisión de esa cartera — y lo va a
            # resolver por el vecino más cercano, que es como se publicó «cuatro compañías
            # concentran el 87,1%» cuando eran cuatro ramos.
            "nombre": NOMBRES.get(r.series),
            # NUNCA contra otros países. Chile computa bajo su Compendio de Normas Contables
            # y define su corte de mora en 90 días; otro supervisor define otra cosa con el
            # mismo nombre. Chile además no está en EMFA, así que no hay capa armonizada que
            # lo alcance: se narra como trayectoria DENTRO de su sistema.
            "comparable_entre_paises": False,
            # El emisor publica el ratio ya calculado: lo copiamos, no lo derivamos.
            "derivacion": client.DERIVACION,
            "reason": r.reason,
        }
        synced += 1

    db.commit()
    return {"synced": synced, "country": ISO3,
            "cortes": sorted(c.isoformat() for c in cortes),
            "series": sorted({r.series for r in records}),
            "mode": getattr(client, "mode", "?"), "errors": errores}
