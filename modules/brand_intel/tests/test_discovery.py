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

def _fake_vision(brands_by_page):
    """El lector dedicado: devuelve solo los nombres impresos, no las cifras.

    `occurrences` = a cuántas cifras rotula esa marca en la lámina, que es la semántica
    que el umbral y la fusión de grafías comparaban antes contando celdas.
    """
    def render(content, first=None, last=None, **kw):
        return [b"png"]

    def read(image, page, **kw):
        return brands_by_page.get(page, [])

    return render, read


def test_brand_discovery_groups_spellings_of_one_brand():
    """A deck really does print "Little Ceasars" on one slide and "Little Caesars" on
    another; adopting both would split the series in two."""
    render, read = _fake_vision({
        1: [{"name": "Little Caesars", "occurrences": 1}, {"name": "McDonald's", "occurrences": 1}],
        2: [{"name": "Little Ceasars", "occurrences": 1}, {"name": "McDonald's", "occurrences": 1}],
    })
    brands, pages, err = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, reader=read)
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
    render, read = _fake_vision({
        1: [{"name": "Pizza Hut", "occurrences": 1}, {"name": "Papa John's Pizza", "occurrences": 1}],
        2: [{"name": "Pizza Hut", "occurrences": 1}, {"name": "Papa John's Pizza", "occurrences": 1}],
    })
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, reader=read)
    assert {b.name for b in brands} == {"Pizza Hut", "Papa John's Pizza"}


def test_short_names_are_never_merged():
    """Short names are too easy to confuse; the resolver refuses them and so does this."""
    render, read = _fake_vision({
        1: [{"name": "KFC", "occurrences": 1}, {"name": "KFD", "occurrences": 1}],
        2: [{"name": "KFC", "occurrences": 1}, {"name": "KFD", "occurrences": 1}],
    })
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, reader=read)
    assert {b.name for b in brands} == {"KFC", "KFD"}


def test_category_level_figures_do_not_become_a_brand():
    """A cell with no brand label is a category figure, not a nameless brand."""
    render, read = _fake_vision({1: [{"name": "", "occurrences": 1}, {"name": "  ", "occurrences": 1}]})
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10], sample=1, renderer=render, reader=read)
    assert brands == []


def test_a_brand_seen_once_on_one_slide_is_too_thin_to_propose():
    render, read = _fake_vision({1: [{"name": "Marca Fugaz", "occurrences": 1}]})
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10], sample=1, renderer=render, reader=read)
    assert brands == []


def test_one_unreadable_slide_does_not_lose_the_pass():
    def render(content, first=None, last=None, **kw):
        return [b"png"]

    def read(image, page, **kw):
        if page == 1:
            raise RuntimeError("ilegible")
        return [{"name": "McDonald's", "occurrences": 2}]

    brands, _, err = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10], sample=2, renderer=render, reader=read)
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
    # The workbook template prints `mcdonalds` as its own example for "McDonald's", and
    # this must agree with it: an apostrophe sits inside a word, so splitting there gives
    # `mcdonald-s` — a second entity for a brand the workbook already loaded, which
    # splits the series in two with nothing downstream able to notice.
    ("McDonald's", "mcdonalds"),
    ("Domino's Pizza", "dominos-pizza"),
    ("Wendy´s", "wendys"),
    ("Café Santo Domingo", "cafe-santo-domingo"),
])
def test_brand_slug_folds_accents_and_punctuation(name, expected):
    assert svc.brand_slug(name) == expected


def test_the_same_failure_on_every_slide_is_reported_once():
    """A wall of identical SDK messages is a panel the reviewer cannot read."""
    def render(content, first=None, last=None, **kw):
        return [b"png"]

    def read(image, page, **kw):
        raise RuntimeError("Could not resolve authentication method")

    _, _, err = dsc.discover_brands(
        b"x", ["a" * 10, "b" * 10, "c" * 10], sample=3, renderer=render, reader=read)
    assert err.count("Could not resolve authentication method") == 1
    assert "3 de 3" in err


# ── descubrimiento de métricas (estudios que no son trackers) ──────────

def _fake_metric_reader(by_page):
    def render(content, first=None, last=None, **kw):
        return [b"png"]

    def read(image, page, **kw):
        return by_page.get(page, [])
    return render, read


def test_metric_discovery_proposes_code_label_and_kind():
    render, read = _fake_metric_reader({1: [
        {"code": "clima_t2b", "label": "Clima laboral (T2B)", "kind": "proportion",
         "evidence": "porcentaje con base n=300", "confident": True},
    ]})
    out, err = dsc.discover_metrics(b"x", ["a" * 10], sample=1,
                                   renderer=render, reader=read)
    assert err == ""
    assert [(m.code, m.kind, m.confident) for m in out] == [
        ("clima_t2b", "proportion", True)]
    assert out[0].as_dict()["supports_bands"] is True


def test_two_slides_typing_a_metric_differently_fall_back_to_no_bands():
    """`proportion` es el único tipo que habilita banda: ante duda, no se concede.

    Quedarse con el tipo más permisivo fabricaría intervalos de confianza a partir de un
    desacuerdo, que es exactamente la precisión que este módulo se niega a inventar.
    """
    render, read = _fake_metric_reader({
        1: [{"code": "nps", "label": "NPS", "kind": "proportion",
             "evidence": "%", "confident": True}],
        2: [{"code": "nps", "label": "NPS", "kind": "index",
             "evidence": "escala -100 a 100", "confident": True}],
    })
    out, _ = dsc.discover_metrics(b"x", ["a" * 10, "b" * 10], sample=2,
                                  renderer=render, reader=read)
    assert out[0].kind == "index"
    assert out[0].confident is False
    assert out[0].as_dict()["supports_bands"] is False


def test_a_metric_with_an_unknown_kind_is_not_proposed():
    render, read = _fake_metric_reader({1: [
        {"code": "raro", "label": "Raro", "kind": "porcentaje",
         "evidence": "", "confident": True},
    ]})
    out, _ = dsc.discover_metrics(b"x", ["a" * 10], sample=1,
                                  renderer=render, reader=read)
    assert out == []


def test_a_tracker_deck_does_not_pay_for_the_metric_pass_by_default():
    """El pase de métricas es una llamada de visión más por lámina muestreada.

    Un tracker se valida contra el diccionario canónico y no lo necesita, así que el
    coste tiene que estar apagado salvo que el estudio lo pida.
    """
    import inspect

    assert inspect.signature(
        dsc.discover_structure).parameters["with_metrics"].default is False


def test_brand_discovery_does_not_ask_for_the_slides_figures():
    """El pase de marcas no puede pagar una transcripción completa por lámina.

    Reutilizar el extractor ordinario producía cientos de celdas contra un esquema de 16k
    tokens para quedarse con ~15 nombres, y el muestreo elige a propósito las láminas más
    densas: con el mazo real de 59 láminas el pase corría durante minutos y moría contra
    el presupuesto de la petición antes de devolver nada.
    """
    import inspect

    from modules.brand_intel.ingest import pdf_vision

    # El lector por defecto es el dedicado, no el extractor de cifras.
    assert inspect.signature(
        dsc.discover_brands).parameters["reader"].default is None
    fuente = inspect.getsource(dsc.discover_brands)
    assert "discover_brands_on_page" in fuente
    assert "extract_page" not in fuente

    # Y su esquema no tiene dónde devolver una cifra.
    campos = pdf_vision.BRAND_DISCOVERY_SCHEMA["properties"]["brands"]["items"]["properties"]
    assert set(campos) == {"name", "occurrences"}


def test_occurrences_keep_counting_figures_not_slides():
    """El umbral y la fusión de grafías comparaban celdas: la semántica no puede cambiar.

    Si `occurrences` pasara a contar láminas, una marca que rotula ocho cifras en una sola
    lámina caería por debajo del umbral y desaparecería de la propuesta.
    """
    render, read = _fake_vision({1: [{"name": "Barra Payán", "occurrences": 8}]})
    brands, _, _ = dsc.discover_brands(
        b"x", ["a" * 10], sample=1, renderer=render, reader=read)
    assert [(b.name, b.occurrences) for b in brands] == [("Barra Payán", 8)]
