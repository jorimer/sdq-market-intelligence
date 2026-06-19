"""Tests for the ENCFT ↔ BCRD-17 sector crosswalk."""
from shared.data.bcrd_sectors import sector_catalog
from shared.data.sector_crosswalk import (
    BRANCH_KEYS,
    ENCFT_BRANCHES,
    SLUG_TO_TSS_ACTIVITIES,
    branch_members,
    coverage,
    map_label,
    salary_by_slug,
    slug_branch,
)


def test_partition_covers_exactly_the_17_slugs():
    """Every BCRD-17 slug belongs to exactly one branch; no extras, no gaps."""
    catalog = {slug for slug, _name in sector_catalog()}
    members = [s for b in ENCFT_BRANCHES for s in b.members]
    assert set(members) == catalog
    assert len(members) == len(catalog) == 17  # no slug in two branches


def test_ten_branches_seven_direct_three_bundle():
    assert len(ENCFT_BRANCHES) == 10
    direct = [b for b in ENCFT_BRANCHES if b.kind == "direct"]
    bundle = [b for b in ENCFT_BRANCHES if b.kind == "bundle"]
    assert len(direct) == 7 and len(bundle) == 3
    assert all(len(b.members) == 1 for b in direct)
    assert all(len(b.members) > 1 for b in bundle)
    assert all(b.note for b in bundle)  # bundles disclose the aggregation


def test_bundles_contain_the_expected_slugs():
    assert set(branch_members("industrias")) == {"manufactura_local", "zonas_francas", "mineria"}
    assert set(branch_members("transporte_comunicaciones")) == {"transporte", "comunicaciones"}
    assert set(branch_members("otros_servicios")) == {
        "otros_servicios", "ensenanza", "salud", "inmobiliario", "servicios_profesionales",
    }


def test_zonas_francas_is_bundled_not_dropped():
    """Unlike the TSS plan (ZF→None), ENCFT covers ZF inside the industrias bundle."""
    assert slug_branch("zonas_francas") == "industrias"
    assert slug_branch("ensenanza") == "otros_servicios"
    assert slug_branch("salud") == "otros_servicios"


def test_map_label_tolerant_to_footnotes_accents_spacing():
    # footnote digits the workbook appends to the cell
    assert map_label("Industrias Manufactureras1") == "industrias"
    assert map_label("Otros Servicios2") == "otros_servicios"
    # trailing space + plain
    assert map_label("Construcción ") == "construccion"
    # accents / case insensitive
    assert map_label("administracion publica y defensa") == "administracion_publica"
    assert map_label("ELECTRICIDAD, GAS Y AGUA") == "energia"
    assert map_label("Hoteles, Bares y Restaurantes") == "turismo"


def test_map_label_returns_none_for_non_branches():
    assert map_label("Total ") is None
    assert map_label("Actividad económica") is None
    assert map_label("1 Incluye minas y canteras.") is None
    assert map_label(None) is None


def test_coverage_shape():
    cov = coverage()
    assert cov["n_branches"] == 10
    assert cov["n_slugs"] == 17
    assert len(cov["direct"]) == 7
    assert set(cov["bundled"]) == {"industrias", "transporte_comunicaciones", "otros_servicios"}


def test_branch_keys_unique_and_ordered():
    assert len(BRANCH_KEYS) == len(set(BRANCH_KEYS)) == 10
    assert BRANCH_KEYS[0] == "agricultura"  # workbook row order preserved


# ── TSS salary activities → 17 slugs ──────────────────────────────
def test_tss_map_covers_the_17_slugs():
    catalog = {slug for slug, _name in sector_catalog()}
    assert set(SLUG_TO_TSS_ACTIVITIES) == catalog == set(SLUG_TO_TSS_ACTIVITIES.keys())
    assert all(acts for acts in SLUG_TO_TSS_ACTIVITIES.values())  # every slug fed


def test_salary_by_slug_aggregates_and_shares():
    activity_salary = {
        "cultivo_de_cereales": 10.0, "cultivos_tradicionales": 20.0,
        "ganaderia_silvicultura_y_pesca": 30.0, "servicios_agropecuarios": 40.0,
        "explotacion_de_minas_y_canteras": 80000.0,
        "manufactura": 36000.0, "otros_servicios": 33000.0,
    }
    out = salary_by_slug(activity_salary)
    assert out["agropecuario"] == 25.0                       # mean of the 4 agro sub-items
    assert out["mineria"] == 80000.0
    # shared activity → both slugs get the same value (declared proxy)
    assert out["manufactura_local"] == out["zonas_francas"] == 36000.0
    assert out["otros_servicios"] == out["servicios_profesionales"] == 33000.0


def test_salary_by_slug_missing_is_none_never_fabricated():
    out = salary_by_slug({"comercio": 34000.0})              # only one activity present
    assert out["comercio"] == 34000.0
    assert out["mineria"] is None                            # absent → None, not guessed
    assert out["agropecuario"] is None                       # none of its 4 present
