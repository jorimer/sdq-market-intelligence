"""Superintendencia de Pensiones (SIPEN) — connector for Dominican pension data.

SIPEN data has two natures, and this connector exposes both behind the platform's
``Record`` contract:

  * **System / national** series (the pension system as a whole): rentabilidad,
    comisiones, afiliados, cotizantes, patrimonio del fondo. These behave like
    :class:`MacroSeries` — one value per period.
  * **Entity** series (per AFP — the ~7 fund administrators): rentabilidad,
    comisiones, patrimonio gestionado, afiliados. Carried as ``Record`` with the
    AFP slug in ``dimension`` (the ONE/region pattern), so one spine serves both.

Four real publication channels exist (the integration plan ``tasks/PLAN_PENSIONES_SIPEN.md``):
  A) CKAN ``datos.gob.do`` (afiliados/cotizantes, CSV/JSON)            — live: Fase 1
  B) Estadística Previsional XLSX (valor cuota, rentabilidad, cartera) — live: Fase 1
  C) Boletines Trimestrales (PDF) → digest IA                          — live: Fase 1
  D) Estados financieros AFP + accionistas/capital pagado             — live: Fase 2

The portal ``sipen.gob.do`` blocks non-browser clients (403/473), so the platform
doctrine of fixture-first is doubly right here. F0 ships a small **real, cited**
sample (``sipen.json`` + ``sipen_entities.json``); the live wiring per channel
lands in later phases. Missing values stay ``None`` — never interpolated.
"""
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.sipen")

# ── AFP catalog ────────────────────────────────────────────────────────────
# The fund administrators currently in the Dominican system (ADAFP members +
# Atlántico). Slugs are stable keys used as ``Record.dimension`` and as the
# ``PensionEntity.slug``. Display names match SIPEN/ADAFP usage.
AFPS: List[Tuple[str, str]] = [
    ("afp_popular", "AFP Popular"),
    ("afp_crecer", "AFP Crecer"),
    ("afp_reservas", "AFP Reservas"),
    ("afp_siembra", "AFP Siembra"),
    ("afp_romana", "AFP Romana"),
    ("afp_jmmb_bdi", "AFP JMMB BDI"),
    ("afp_atlantico", "AFP Atlántico"),
]


def afp_catalog() -> List[Tuple[str, str]]:
    """``[(slug, display_name)]`` for seeding the AFP peer set."""
    return list(AFPS)


class SIPENClient(FixtureBackedClient):
    """SIPEN pension statistics. ``fixture`` reads the cited sample; ``live`` per channel.

    ``fetch`` returns the **system/national** series (standard fixture shape).
    Per-AFP series come from :meth:`fetch_entities` (``dimension`` = AFP slug).
    """

    source = "SIPEN"
    license = "datos públicos SIPEN — sistema dominicano de pensiones (uso con cita)"
    license_ok = True
    fixture_file = "sipen.json"
    entities_fixture_file = "sipen_entities.json"
    live_phase = "Fase 1 (CKAN datos.gob.do + XLSX Estadística Previsional)"

    # ── Entity (per-AFP) series ───────────────────────────────────────────
    def fetch_entities(
        self, series: Optional[str] = None, period: Optional[str] = None
    ) -> List[Record]:
        """Per-AFP observations as ``Record``\\ s (``dimension`` = AFP slug).

        Fixture shape::

            {"<afp_slug>": {"name": "AFP …",
                            "series": {"<metric>": {"unit": "%",
                                                    "observations": {"2025-02": 9.59}}}}}
        """
        self.check_license()
        if self.mode == "live":
            raise NotImplementedError(
                f"Conector {self.source} entidades en modo 'live' pendiente ({self.live_phase})"
            )
        fixture = self._load_fixture(self.entities_fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for slug, entity in fixture.items():
            for s_name, s in (entity.get("series") or {}).items():
                if series and s_name != series:
                    continue
                unit = s.get("unit")
                for p, v in (s.get("observations") or {}).items():
                    if period and p != period:
                        continue
                    out.append(Record(
                        series=s_name, period=p,
                        value=None if v is None else float(v),
                        lineage=lineage, unit=unit, dimension=slug,
                    ))
        return out

    def entity_names(self) -> Dict[str, str]:
        """``{slug: display_name}`` from the catalog (+ any extra in the fixture)."""
        names = {slug: name for slug, name in AFPS}
        fixture = self._load_fixture(self.entities_fixture_file)
        for slug, entity in fixture.items():
            if entity.get("name"):
                names.setdefault(slug, entity["name"])
        return names


sipen_client = SIPENClient()
