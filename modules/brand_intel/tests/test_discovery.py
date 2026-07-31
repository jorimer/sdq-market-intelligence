"""Structure discovery and adoption.

The gap these cover: an engagement is created with a client and a focal brand and no
waves or brands, while ``pdf_pipeline`` maps printed labels onto declared ones. Before
this path existed, a client holding slides and no workbook could create an engagement and
watch every cell get rejected — which is the first test here, kept as the regression it is.
"""
from datetime import date

import pytest

from modules.brand_intel import service as svc
from modules.brand_intel.ingest import discovery as dsc
from modules.brand_intel.ingest.pdf_pipeline import (
    IngestReport,
    _LabelResolver,
    _to_validation_cells,
)
from modules.brand_intel.models.models import BrandEngagement


def _row(brand, wave, value=17.0, metric="favourite_place"):
    return {"metric_code": metric, "brand_label": brand, "wave_label": wave,
            "segment": "total", "value": value, "base_n": 300, "distribution_id": ""}


# ── the regression ────────────────────────────────────────────────────

def test_empty_engagement_rejects_every_cell():
    """An engagement with no structure cannot place a single figure."""
    report = IngestReport()
    cells = _to_validation_cells(
        [(1, "Lugar favorito", _row("McDonald's", "Nov '25")),
         (1, "Lugar favorito", _row("Burger King", "Nov '25"))],
        _LabelResolver([], []), report,
    )
    assert cells == []
    assert len(report.rejected) == 2
    assert all(r["reason"] == "Marca no reconocida" for r in report.rejected)


def test_after_adoption_the_same_cells_resolve(db, engagement):
    """The point of the whole path: adopt, and the previously-rejected cells land."""
    eng = BrandEngagement(slug="nuevo", client_name="Cliente", focal_brand="McDonald's")
    db.add(eng)
    db.flush()

    svc.adopt_structure(
        db, eng,
        [{"code": "2025-11", "label": "Nov '25", "period_date": "2025-11-01"}],
        [{"name": "McDonald's", "is_focal": True}, {"name": "Burger King"}],
    )

    resolver = _LabelResolver(svc.brands(db, eng.id), svc.waves(db, eng.id))
    report = IngestReport()
    cells = _to_validation_cells(
        [(1, "Lugar favorito", _row("McDonald's", "Nov '25")),
         (1, "Lugar favorito", _row("Burger King", "Nov '25"))],
        resolver, report,
    )
    assert len(cells) == 2
    assert report.rejected == []


# ── wave discovery: no model call ─────────────────────────────────────

def test_waves_come_from_the_text_layer():
    pages = ["Preferencia May '25 Ago '25 Nov '25"] * 4
    waves, _ = dsc.discover_waves(pages)
    assert [w.code for w in waves] == ["2025-05", "2025-08", "2025-11"]
    assert waves[0].period_date == date(2025, 5, 1)


def test_spellings_of_one_wave_collapse_into_one_candidate():
    """"Mayo '25" and "May '25" are the same wave, not two."""
    waves, _ = dsc.discover_waves(["Mayo '25", "May '25", "May '25", "mayo 2025"])
    assert len(waves) == 1
    assert waves[0].code == "2025-05"
    assert waves[0].occurrences == 4
    assert len(waves[0].spellings) > 1


def test_four_digit_year_is_not_read_as_two():
    """Regression: a greedy two-digit alternative turns 2025 into the year 2020."""
    waves, _ = dsc.discover_waves(["Nov 2025"] * 3)
    assert [w.code for w in waves] == ["2025-11"]


def test_long_month_name_is_not_truncated_to_its_abbreviation():
    waves, _ = dsc.discover_waves(["Septiembre 2025"] * 3)
    assert [w.code for w in waves] == ["2025-09"]


def test_quarters_are_recognised_and_anchored_on_their_first_month():
    waves, _ = dsc.discover_waves(["Q1 2026"] * 3)
    assert waves[0].code == "2026-01"


def test_a_date_seen_once_is_dropped_but_reported():
    """A footnote is not a wave — and the reviewer is told it was dropped."""
    waves, dropped = dsc.discover_waves(["Nov '25 Nov '25 Nov '25", "Ene '19"])
    assert [w.code for w in waves] == ["2025-11"]
    assert len(dropped) == 1
    assert dropped[0]["occurrences"] == 1


def test_english_months_are_recognised_too():
    """The module must not be written for one market."""
    waves, _ = dsc.discover_waves(["March 2026"] * 3)
    assert waves[0].code == "2026-03"


def test_sample_pages_prefer_the_densest_slides():
    pages = ["", "corto", "x" * 500, "y" * 900, ""]
    assert dsc.pick_sample_pages(pages, k=2) == [3, 4]


# ── brand discovery: sampled vision pass ──────────────────────────────

class _FakeRead:
    def __init__(self, cells):
        self.cells = cells
        self.chart_title = "t"
        self.readable = True
        self.skip_reason = ""
        self.model_used = "fake"


def _fake_vision(cells_by_page):
    def render(content, first=None, last=None, **kw):
        return [b"png"]

    def extract(image, page, brands, waves):
        return _FakeRead(cells_by_page.get(page, []))

    return render, extract


def test_brand_discovery_groups_spellings_of_one_brand():
    """A deck really does print "Little Ceasars" on one slide and "Little Caesars" on
    another; adopting both would split the series in two."""
    render, extract = _fake_vision({
        1: [{"brand_label": "Little Caesars"}, {"brand_label": "McDonald's"}],
        2: [{"brand_label": "Little Ceasars"}, {"brand_label": "McDonald's"}],
    })
    brands, pages, err = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, extractor=extract)
    assert err == ""
    names = {b.name for b in brands}
    assert "McDonald's" in names
    # One chain, one candidate: adopting two would split its series in two.
    caesars = [b for b in brands if "aesars" in b.name or "easars" in b.name]
    assert len(caesars) == 1
    assert caesars[0].occurrences == 2
    assert set(caesars[0].spellings) == {"Little Caesars", "Little Ceasars"}


def test_two_genuinely_different_brands_are_not_merged():
    """The tolerance must not swallow real competitors that happen to look alike."""
    render, extract = _fake_vision({
        1: [{"brand_label": "Pizza Hut"}, {"brand_label": "Papa John's Pizza"}],
        2: [{"brand_label": "Pizza Hut"}, {"brand_label": "Papa John's Pizza"}],
    })
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, extractor=extract)
    assert {b.name for b in brands} == {"Pizza Hut", "Papa John's Pizza"}


def test_short_names_are_never_merged():
    """Short names are too easy to confuse; the resolver refuses them and so does this."""
    render, extract = _fake_vision({
        1: [{"brand_label": "KFC"}, {"brand_label": "KFD"}],
        2: [{"brand_label": "KFC"}, {"brand_label": "KFD"}],
    })
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, extractor=extract)
    assert {b.name for b in brands} == {"KFC", "KFD"}


def test_category_level_figures_do_not_become_a_brand():
    """A cell with no brand label is a category figure, not a nameless brand."""
    render, extract = _fake_vision({1: [{"brand_label": ""}, {"brand_label": "  "}]})
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10], sample=1, renderer=render, extractor=extract)
    assert brands == []


def test_a_brand_seen_once_on_one_slide_is_too_thin_to_propose():
    render, extract = _fake_vision({1: [{"brand_label": "Marca Fugaz"}]})
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10], sample=1, renderer=render, extractor=extract)
    assert brands == []


def test_one_unreadable_slide_does_not_lose_the_pass():
    def render(content, first=None, last=None, **kw):
        return [b"png"]

    def extract(image, page, brands, waves):
        if page == 1:
            raise RuntimeError("ilegible")
        return _FakeRead([{"brand_label": "McDonald's"}, {"brand_label": "McDonald's"}])

    brands, _, err = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, extractor=extract)
    assert [b.name for b in brands] == ["McDonald's"]
    assert err == ""      # partial success is success; the error only surfaces if nothing landed


# ── adoption ──────────────────────────────────────────────────────────

def test_adoption_orders_waves_chronologically_not_by_arrival(db):
    """sort_order drives every series: a wrong one silently reverses trends."""
    eng = BrandEngagement(slug="e", client_name="C", focal_brand="F")
    db.add(eng)
    db.flush()
    svc.adopt_structure(db, eng, [
        {"code": "2026-03", "label": "Mar '26", "period_date": "2026-03-01"},
        {"code": "2025-05", "label": "May '25", "period_date": "2025-05-01"},
        {"code": "2025-11", "label": "Nov '25", "period_date": "2025-11-01"},
    ], [])
    assert [w.code for w in svc.waves(db, eng.id)] == ["2025-05", "2025-11", "2026-03"]


def test_a_wave_adopted_later_slots_into_the_existing_chronology(db):
    eng = BrandEngagement(slug="e", client_name="C", focal_brand="F")
    db.add(eng)
    db.flush()
    svc.adopt_structure(db, eng, [
        {"code": "2025-05", "label": "May '25", "period_date": "2025-05-01"},
        {"code": "2026-03", "label": "Mar '26", "period_date": "2026-03-01"},
    ], [])
    svc.adopt_structure(db, eng, [
        {"code": "2025-11", "label": "Nov '25", "period_date": "2025-11-01"},
    ], [])
    assert [w.code for w in svc.waves(db, eng.id)] == ["2025-05", "2025-11", "2026-03"]


def test_re_adopting_updates_instead_of_duplicating(db):
    eng = BrandEngagement(slug="e", client_name="C", focal_brand="F")
    db.add(eng)
    db.flush()
    payload_w = [{"code": "2025-11", "label": "Nov '25", "period_date": "2025-11-01"}]
    svc.adopt_structure(db, eng, payload_w, [{"name": "McDonald's", "is_focal": True}])
    result = svc.adopt_structure(db, eng, payload_w,
                                 [{"name": "McDonald's", "is_focal": True},
                                  {"name": "Burger King"}])
    assert len(svc.waves(db, eng.id)) == 1
    assert len(svc.brands(db, eng.id)) == 2
    assert result["waves_updated"] == 1 and result["brands_created"] == 1


def test_adoption_warns_when_a_wave_has_no_reference_date(db):
    eng = BrandEngagement(slug="e", client_name="C", focal_brand="F")
    db.add(eng)
    db.flush()
    out = svc.adopt_structure(db, eng, [{"code": "2025-11", "label": "Nov '25"}], [])
    assert any("deflact" in w for w in out["warnings"])


def test_adoption_warns_when_no_brand_is_focal(db):
    eng = BrandEngagement(slug="e", client_name="C", focal_brand="F")
    db.add(eng)
    db.flush()
    out = svc.adopt_structure(db, eng, [], [{"name": "Burger King"}])
    assert any("focal" in w for w in out["warnings"])


@pytest.mark.parametrize("name,expected", [
    ("McDonald's", "mcdonald-s"),
    ("Domino's Pizza", "domino-s-pizza"),
    ("Café Santo Domingo", "cafe-santo-domingo"),
])
def test_brand_slug_folds_accents_and_punctuation(name, expected):
    assert svc.brand_slug(name) == expected
