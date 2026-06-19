"""ENCFT labour activity ↔ BCRD-17 sector crosswalk (single source of truth).

The ONE annual employment series (*Población ocupada por actividad económica*,
ENFT 2008-2016 + ENCFT 2017-2024) publishes **10 activity branches**, NOT the 17
national-accounts sectors the IAI is built on. Verified against the real workbook
(2026-06-19):

* **7 branches map 1:1** to a BCRD slug (``direct``): agropecuario, energia,
  construccion, comercio, turismo, financiero, administracion_publica.
* **3 branches are aggregates** (``bundle``) the survey does not split — stated in
  the workbook's own footnotes:
    - *Industrias Manufactureras* ("¹ Incluye minas y canteras") =
      manufactura_local + zonas_francas + mineria.
    - *Transporte y Comunicaciones* = transporte + comunicaciones.
    - *Otros Servicios* ("² Incluye enseñanza, salud y asistencia social") =
      otros_servicios + ensenanza + salud + inmobiliario + servicios_profesionales.

So **all 17 slugs are covered, but at a 10-branch resolution** — no sector is
dropped, none is imputed. Splitting a bundle's employment across its member slugs
would be fabrication; instead the Gate-E backtest aggregates the IAI to these 10
branches (size-weighted) to match the outcome's real resolution.

``zonas_francas`` therefore belongs to the ``industrias`` bundle here (a CNZFE
split is a later phase) — unlike the TSS-based plan that left it uncovered. This
crosswalk is the shared map for every labour source (ENCFT, later salary/TSS),
keyed by the ONE branch identity, with the BCRD sector slugs as members.
"""
import re
from typing import Dict, List, NamedTuple, Optional

from shared.data._text import norm
from shared.data.bcrd_sectors import sector_catalog


class Branch(NamedTuple):
    """One ONE activity branch and the BCRD-17 slugs it contains."""

    key: str                 # stable branch identifier (= the ONE rama identity)
    label: str               # ONE display label (as printed in the workbook)
    members: List[str]       # BCRD-17 slugs this branch aggregates (≥1)
    kind: str                # "direct" (1 slug) | "bundle" (>1 slug)
    note: Optional[str]      # disclosure for a bundle, else None


# Order follows the ONE workbook's row order. ``members`` use the canonical BCRD
# slugs from ``shared.data.bcrd_sectors.SECTORS`` (the partition is asserted below).
ENCFT_BRANCHES: List[Branch] = [
    Branch("agricultura", "Agricultura y Ganadería", ["agropecuario"], "direct", None),
    Branch("industrias", "Industrias Manufactureras",
           ["manufactura_local", "zonas_francas", "mineria"], "bundle",
           "La ENCFT no separa manufactura local, zonas francas ni minería "
           "(nota del cuadro: «Incluye minas y canteras»)."),
    Branch("energia", "Electricidad, Gas y Agua", ["energia"], "direct", None),
    Branch("construccion", "Construcción", ["construccion"], "direct", None),
    Branch("comercio", "Comercio al por Mayor y Menor", ["comercio"], "direct", None),
    Branch("turismo", "Hoteles, Bares y Restaurantes", ["turismo"], "direct", None),
    Branch("transporte_comunicaciones", "Transporte y Comunicaciones",
           ["transporte", "comunicaciones"], "bundle",
           "La ENCFT agrupa transporte y comunicaciones en una sola rama."),
    Branch("financiero", "Intermediación Financiera y Seguros", ["financiero"], "direct", None),
    Branch("administracion_publica", "Administración Pública y Defensa",
           ["administracion_publica"], "direct", None),
    Branch("otros_servicios", "Otros Servicios",
           ["otros_servicios", "ensenanza", "salud", "inmobiliario", "servicios_profesionales"],
           "bundle",
           "«Otros Servicios» absorbe enseñanza, salud, inmobiliario y servicios "
           "profesionales (nota del cuadro: «Incluye enseñanza, salud y asistencia social»)."),
]

BRANCH_KEYS: List[str] = [b.key for b in ENCFT_BRANCHES]
_BY_KEY: Dict[str, Branch] = {b.key: b for b in ENCFT_BRANCHES}
# Normalized ONE label (footnote digit stripped) → branch key, for tolerant matching.
_LABEL_TO_KEY: Dict[str, str] = {norm(b.label): b.key for b in ENCFT_BRANCHES}
# slug → branch key (every BCRD-17 slug belongs to exactly one branch).
_SLUG_TO_BRANCH: Dict[str, str] = {s: b.key for b in ENCFT_BRANCHES for s in b.members}


def _strip_footnote(label: object) -> str:
    """Normalized label with a trailing footnote marker removed.

    The workbook appends footnote digits to a cell (e.g. ``Industrias
    Manufactureras1``, ``Otros Servicios2``); strip a trailing run of digits so the
    label still matches its table entry. None of the real labels legitimately end
    in a digit, so this is safe.
    """
    return re.sub(r"\d+$", "", norm(label)).strip()


# ── Partition guard (fail-closed at import) ───────────────────────────────────
# The union of branch members must be EXACTLY the BCRD-17 sectors. If the BCRD
# renames/adds a sector (so ``sector_catalog`` drifts), this raises at import
# rather than letting the crosswalk silently cover the wrong set.
_CATALOG_SLUGS = {slug for slug, _name in sector_catalog()}
_MEMBER_SLUGS = set(_SLUG_TO_BRANCH)
if _MEMBER_SLUGS != _CATALOG_SLUGS:
    missing = sorted(_CATALOG_SLUGS - _MEMBER_SLUGS)
    extra = sorted(_MEMBER_SLUGS - _CATALOG_SLUGS)
    raise RuntimeError(
        "Crosswalk ENCFT desalineado con el catálogo BCRD-17 "
        f"(faltan={missing}, sobran={extra}): revisa ENCFT_BRANCHES."
    )
if len(_MEMBER_SLUGS) != sum(len(b.members) for b in ENCFT_BRANCHES):
    raise RuntimeError("Crosswalk ENCFT: un slug aparece en más de una rama.")


def map_label(raw_label: object) -> Optional[str]:
    """ONE row label → branch key (``None`` if it isn't one of the 10 branches).

    Tolerant to accents/case/spacing and to a trailing footnote digit. The
    national ``"Total"`` row and any note row map to ``None`` deliberately.
    """
    return _LABEL_TO_KEY.get(_strip_footnote(raw_label))


def branch_members(key: str) -> List[str]:
    """BCRD-17 slugs aggregated by branch *key* (``[]`` if unknown)."""
    b = _BY_KEY.get(key)
    return list(b.members) if b else []


def branch_label(key: str) -> Optional[str]:
    """ONE display label for branch *key* (``None`` if unknown)."""
    b = _BY_KEY.get(key)
    return b.label if b else None


def slug_branch(slug: str) -> Optional[str]:
    """Branch key a BCRD-17 *slug* belongs to (``None`` if not a known slug)."""
    return _SLUG_TO_BRANCH.get(slug)


def coverage() -> Dict[str, object]:
    """Declared coverage of the crosswalk for the real-vs-rubric disclosure.

    ``direct`` = slugs in a 1:1 branch; ``bundled`` = {branch_key: [slugs]} for the
    aggregate branches. The union is the full BCRD-17 (asserted at import).
    """
    direct = [b.members[0] for b in ENCFT_BRANCHES if b.kind == "direct"]
    bundled = {b.key: list(b.members) for b in ENCFT_BRANCHES if b.kind == "bundle"}
    return {
        "n_branches": len(ENCFT_BRANCHES),
        "n_slugs": len(_MEMBER_SLUGS),
        "direct": sorted(direct),
        "bundled": bundled,
    }
