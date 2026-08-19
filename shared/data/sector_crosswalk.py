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


# ── TSS salary activities → BCRD-17 slugs ─────────────────────────────────────
# The TSS Power BI report exposes 18 detailed activities (``ACT_ECO2_BC``), finer
# than the ENCFT employment branches. Each BCRD-17 slug is fed by ≥1 TSS activity
# (keyed by :func:`shared.data.tss_salary.activity_key`):
#   * agropecuario aggregates 4 TSS sub-items (mean of their salaries — declared);
#   * manufactura_local / zonas_francas share "Manufactura" (TSS doesn't split ZF);
#   * otros_servicios / servicios_profesionales share "Otros Servicios".
# Everything else is 1:1. "No identificado" is dropped by the connector.
SLUG_TO_TSS_ACTIVITIES: Dict[str, List[str]] = {
    "agropecuario": ["cultivo_de_cereales", "cultivos_tradicionales",
                     "ganaderia_silvicultura_y_pesca", "servicios_agropecuarios"],
    "mineria": ["explotacion_de_minas_y_canteras"],
    "manufactura_local": ["manufactura"],
    "zonas_francas": ["manufactura"],
    "construccion": ["construccion"],
    "energia": ["electricidad_gas_y_agua"],
    "comercio": ["comercio"],
    "turismo": ["hoteles_bares_y_restaurantes"],
    "transporte": ["transporte_y_almacenamiento"],
    "comunicaciones": ["comunicaciones"],
    "financiero": ["intermediacion_financiera_seguros_y_otras"],
    "inmobiliario": ["alquiler_de_viviendas"],
    "ensenanza": ["servicios_de_ensenanza"],
    "salud": ["servicios_de_salud"],
    "administracion_publica": ["administracion_publica"],
    "otros_servicios": ["otros_servicios"],
    "servicios_profesionales": ["otros_servicios"],
}

# Same fail-closed partition guard: every BCRD-17 slug must be fed by the TSS map.
if set(SLUG_TO_TSS_ACTIVITIES) != _CATALOG_SLUGS:
    _miss = sorted(_CATALOG_SLUGS - set(SLUG_TO_TSS_ACTIVITIES))
    _extra = sorted(set(SLUG_TO_TSS_ACTIVITIES) - _CATALOG_SLUGS)
    raise RuntimeError(
        f"SLUG_TO_TSS_ACTIVITIES desalineado con BCRD-17 (faltan={_miss}, sobran={_extra})."
    )


def salary_by_slug(activity_salary: Dict[str, float]) -> Dict[str, Optional[float]]:
    """Map TSS per-activity salary → per-slug salary (the IAI ``operating_cost``).

    ``activity_salary`` is ``{activity_key: salary}``. For a slug fed by several TSS
    activities (agropecuario) the salaries are averaged (declared, unweighted — the
    difference vs the TSS worker-weighted aggregate is <2% and washes out under the
    index min-max). A slug whose activities are all absent maps to ``None`` (never
    fabricated). Slugs sharing an activity (manufactura/ZF) get the same value — a
    declared proxy, like the ENCFT bundle.
    """
    out: Dict[str, Optional[float]] = {}
    for slug, activities in SLUG_TO_TSS_ACTIVITIES.items():
        vals = [activity_salary[a] for a in activities
                if activity_salary.get(a) is not None]
        out[slug] = round(sum(vals) / len(vals), 2) if vals else None
    return out


# ── ENAE economic activity (ONE) → BCRD-17 sector crosswalk ───────────────────
# The ENAE (Encuesta Nacional de Actividad Económica) publishes structural-financial
# tables (income, costs, profit, profitability) at a **9-sector** resolution — a
# DIFFERENT cut than the ENCFT 10 branches: it splits transport from communications
# and electricity from water, but does NOT cover the whole economy. Verified against
# the real ONE tabulados (2026-06-21):
#
#   * 9 ENAE sectors map onto 9 BCRD-17 slugs. ``manufactura`` is a ``bundle``
#     (ENAE doesn't carve out the zonas-francas regime — same disclosure as the
#     ENCFT/TSS treatment of ZF). ``electricidad`` and ``agua`` are TWO ENAE sectors
#     that BOTH feed the single ``energia`` slug (combine downstream).
#   * 8 BCRD slugs are NOT in the ENAE frame at all: agropecuario, financiero,
#     inmobiliario, ensenanza, salud, administracion_publica, servicios_profesionales,
#     otros_servicios. ENAE is therefore a PARTIAL (not full-17) source — coverage is
#     declared via :func:`enae_coverage`, never imputed for the missing 8.
#
# Records are keyed by the ENAE sector identity (like ENCFT keys by branch); the
# 17-slug IAI never reads them directly — the per-slug derivation is a later phase.
class EnaeSector(NamedTuple):
    """One ENAE survey sector and the BCRD-17 slug(s) it feeds."""

    key: str                 # stable ENAE sector identifier (short, < VARCHAR(40))
    label: str               # ONE display label (as printed in the tabulado)
    members: List[str]       # BCRD-17 slugs this ENAE sector feeds (≥1)
    kind: str                # "direct" (1 slug) | "bundle" (>1 slug) | "partial" (shares a slug)
    note: Optional[str]      # disclosure, else None


# Order follows the ONE tabulado's row order.
ENAE_SECTORS: List[EnaeSector] = [
    EnaeSector("minas", "Explotación de minas y canteras", ["mineria"], "direct", None),
    EnaeSector("manufactura", "Industrias manufactureras",
               ["manufactura_local", "zonas_francas"], "bundle",
               "La ENAE no separa la manufactura local de las zonas francas."),
    EnaeSector("electricidad", "Suministro de electricidad", ["energia"], "partial",
               "«energia» combina electricidad y agua (dos sectores ENAE)."),
    EnaeSector("agua", "Suministro de agua", ["energia"], "partial",
               "«energia» combina electricidad y agua (dos sectores ENAE)."),
    EnaeSector("construccion", "Construcción", ["construccion"], "direct", None),
    EnaeSector("comercio", "Comercio", ["comercio"], "direct", None),
    EnaeSector("transporte", "Transporte y almacenamiento", ["transporte"], "direct", None),
    EnaeSector("alojamiento", "Alojamiento y comida", ["turismo"], "direct", None),
    EnaeSector("informacion", "Información y comunicaciones", ["comunicaciones"], "direct", None),
]

ENAE_KEYS: List[str] = [s.key for s in ENAE_SECTORS]
_ENAE_BY_KEY: Dict[str, EnaeSector] = {s.key: s for s in ENAE_SECTORS}
_ENAE_LABEL_TO_KEY: Dict[str, str] = {norm(s.label): s.key for s in ENAE_SECTORS}

# Partition guard (fail-closed at import): every ENAE member must be a real BCRD-17
# slug. Unlike the ENCFT/TSS maps this is a SUBSET (ENAE doesn't cover all 17), so we
# only assert membership validity — not full coverage.
_ENAE_MEMBER_SLUGS = {s for sec in ENAE_SECTORS for s in sec.members}
_ENAE_EXTRA = _ENAE_MEMBER_SLUGS - _CATALOG_SLUGS
if _ENAE_EXTRA:
    raise RuntimeError(
        f"Crosswalk ENAE: slug(s) inexistente(s) en el catálogo BCRD-17: {sorted(_ENAE_EXTRA)}"
    )


def map_enae_label(raw_label: object) -> Optional[str]:
    """ONE ENAE row label → ENAE sector key (``None`` if not one of the 9 sectors).

    Tolerant to accents/case/spacing. The ``"Total"`` row and note rows → ``None``.
    """
    return _ENAE_LABEL_TO_KEY.get(norm(raw_label))


def enae_members(key: str) -> List[str]:
    """BCRD-17 slugs fed by ENAE sector *key* (``[]`` if unknown)."""
    s = _ENAE_BY_KEY.get(key)
    return list(s.members) if s else []


def enae_coverage() -> Dict[str, object]:
    """Declared ENAE coverage for the real-vs-rubric disclosure.

    ``covered`` = BCRD-17 slugs the ENAE frame reaches; ``uncovered`` = the slugs it
    does not (stay rubric / other sources). The union is the full BCRD-17.
    """
    covered = sorted(_ENAE_MEMBER_SLUGS)
    uncovered = sorted(_CATALOG_SLUGS - _ENAE_MEMBER_SLUGS)
    return {
        "n_enae_sectors": len(ENAE_SECTORS),
        "n_slugs_covered": len(covered),
        "covered": covered,
        "uncovered": uncovered,
    }


# ── IED del BCRD (Inversión Extranjera Directa por actividad) ────────────────────
#
# La tercera lente sobre los mismos 17 slugs, y la que le faltaba al Gate E sectorial.
# El IAI es un índice de ATRACTIVO DE INVERSIÓN, y hasta ahora se validaba contra
# crecimiento del EMPLEO — un desenlace que el índice no pretende anticipar, y contra el
# que dio nulo/negativo (IC medio anual −0,03). La IED por actividad es el desenlace que
# el índice sí targetea: inversión realizada.
#
# Fuente: BCRD, "Flujos de la Inversión Extranjera Directa por actividad económica"
# (`inversion_ext_sector_6.xls`, hoja anual, 2010→). Nueve actividades, que NO son los 17
# sectores ni las 10 ramas de la ENCFT: es una tercera resolución, y como las otras se
# declara en vez de repartirse.
#
# COBERTURA PARCIAL, a diferencia de la ENCFT: la IED no llega a agropecuario,
# construcción, administración pública, enseñanza, salud ni servicios profesionales. Esos
# slugs quedan FUERA del panel de este desenlace — no se imputan con cero, que sería
# afirmar que no recibieron inversión cuando lo que pasa es que la fuente no los publica.
IED_ACTIVITIES: List[Branch] = [
    Branch("turismo", "Turismo", ["turismo"], "direct", None),
    Branch("comercio_industria", "Comercio / Industria",
           ["comercio", "manufactura_local"], "bundle",
           "El BCRD agrupa comercio e industria local en una sola actividad de IED."),
    Branch("telecomunicaciones", "Telecomunicaciones", ["comunicaciones"], "direct", None),
    Branch("energia", "Energía", ["energia"], "direct", None),
    Branch("financiero", "Financiero", ["financiero"], "direct", None),
    Branch("zonas_francas", "Zonas Francas", ["zonas_francas"], "direct", None),
    Branch("minero", "Minero", ["mineria"], "direct", None),
    Branch("inmobiliario", "Inmobiliario", ["inmobiliario"], "direct", None),
    Branch("transporte", "Transporte", ["transporte"], "direct", None),
]

IED_KEYS: List[str] = [b.key for b in IED_ACTIVITIES]
_IED_BY_KEY: Dict[str, Branch] = {b.key: b for b in IED_ACTIVITIES}
_IED_LABEL_TO_KEY: Dict[str, str] = {norm(b.label): b.key for b in IED_ACTIVITIES}

# Guard fail-closed al importar: todo miembro tiene que ser un slug real del BCRD-17. Es
# un SUBCONJUNTO (la IED no cubre los 17), así que se valida pertenencia, no cobertura.
_IED_MEMBER_SLUGS = {s for a in IED_ACTIVITIES for s in a.members}
_IED_EXTRA = _IED_MEMBER_SLUGS - _CATALOG_SLUGS
if _IED_EXTRA:
    raise RuntimeError(
        f"Crosswalk IED: slug(s) inexistente(s) en el catálogo BCRD-17: {sorted(_IED_EXTRA)}"
    )


def map_ied_label(raw_label: object) -> Optional[str]:
    """Etiqueta de fila del cuadro de IED → clave de actividad (``None`` si no lo es).

    Tolerante a acentos, mayúsculas y espacios. Las filas ``Otros``, ``Total`` y las notas
    al pie devuelven ``None``: no son actividades, y tratarlas como tales metería un
    agregado dentro del panel que se ordena.
    """
    return _IED_LABEL_TO_KEY.get(norm(raw_label))


def ied_members(key: str) -> List[str]:
    """Slugs BCRD-17 que alimenta la actividad de IED *key* (``[]`` si no existe)."""
    a = _IED_BY_KEY.get(key)
    return list(a.members) if a else []


def ied_coverage() -> Dict[str, object]:
    """Cobertura declarada de la IED sobre los 17 slugs.

    ``uncovered`` no es una omisión: son los sectores que el BCRD no desagrega en su
    cuadro de IED, y por eso quedan fuera del panel de este desenlace.
    """
    covered = sorted(_IED_MEMBER_SLUGS)
    return {
        "n_actividades": len(IED_ACTIVITIES),
        "n_slugs_covered": len(covered),
        "covered": covered,
        "uncovered": sorted(_CATALOG_SLUGS - _IED_MEMBER_SLUGS),
    }
