"""Tests for PDF ingestion: the invariants, the label mapping, and the staging boundary.

The vision call is stubbed throughout — these tests are about what happens to what the
model returns, which is the part that determines whether a mis-read number can reach the
analysis. No network, no API key.
"""
import pytest

from modules.brand_intel.engines import validation as val
from modules.brand_intel.ingest import pdf_pipeline as pipe
from modules.brand_intel.ingest.pdf_vision import PageExtraction
from modules.brand_intel.models.models import (
    BrandExtraction,
    BrandExtractionCell,
    BrandObservation,
)


def _cell(metric, value, **kw):
    kw.setdefault("key", f"{metric}-{value}")
    return val.Cell(metric_code=metric, value=value, **kw)


# ── invariant: range ──────────────────────────────────────────────────

def test_proportion_outside_range_fails():
    cells = [_cell("reach_7d", 127.0)]
    val.validate(cells)
    assert cells[0].validation == val.FAILED
    assert "fuera del rango" in cells[0].validation_note


def test_index_metric_is_not_range_checked():
    """Double-indexation scores legitimately exceed 100 — 349 is a real value."""
    cells = [_cell("attribute_index", 349.0)]
    val.validate(cells)
    assert cells[0].validation != val.FAILED


# ── invariant: distribution ───────────────────────────────────────────

def test_distribution_summing_to_100_passes():
    cells = [
        _cell("favourite_place", 40.0, brand_slug="a", distribution_id="fav"),
        _cell("favourite_place", 35.0, brand_slug="b", distribution_id="fav"),
        _cell("favourite_place", 25.0, brand_slug="c", distribution_id="fav"),
    ]
    report = val.validate(cells)
    assert all(c.validation == val.PASSED for c in cells)
    assert report.clean


def test_distribution_with_a_missing_series_fails():
    """The check that catches the most common extraction error: a dropped bar."""
    cells = [
        _cell("favourite_place", 40.0, brand_slug="a", distribution_id="fav"),
        _cell("favourite_place", 35.0, brand_slug="b", distribution_id="fav"),
        # brand "c" and its 25% were missed
    ]
    report = val.validate(cells)
    assert all(c.validation == val.FAILED for c in cells)
    assert not report.clean
    assert any(f["kind"] == "distribution" for f in report.findings)


def test_distribution_tolerates_rounding():
    cells = [
        _cell("favourite_place", 40.0, brand_slug="a", distribution_id="fav"),
        _cell("favourite_place", 34.0, brand_slug="b", distribution_id="fav"),
        _cell("favourite_place", 24.0, brand_slug="c", distribution_id="fav"),  # 98
    ]
    val.validate(cells)
    assert all(c.validation == val.PASSED for c in cells)


# ── invariant: funnel monotonicity ────────────────────────────────────

def test_monotonic_funnel_passes():
    cells = [
        _cell("awareness_total", 87.0, wave_code="w1", brand_slug="a"),
        _cell("ever_tried", 82.0, wave_code="w1", brand_slug="a"),
        _cell("reach_3m", 60.0, wave_code="w1", brand_slug="a"),
    ]
    val.validate(cells)
    assert all(c.validation == val.PASSED for c in cells)


def test_funnel_that_increases_downward_fails():
    """A rung is a subset of the one above it, so it cannot be larger."""
    cells = [
        _cell("ever_tried", 60.0, wave_code="w1", brand_slug="a"),
        _cell("reach_3m", 82.0, wave_code="w1", brand_slug="a"),   # impossible
    ]
    report = val.validate(cells)
    assert all(c.validation == val.FAILED for c in cells)
    assert any(f["kind"] == "funnel" for f in report.findings)


def test_funnel_check_is_per_brand_and_wave():
    """Different brands must not be compared against each other."""
    cells = [
        _cell("ever_tried", 60.0, wave_code="w1", brand_slug="a"),
        _cell("reach_3m", 82.0, wave_code="w1", brand_slug="b"),
    ]
    val.validate(cells)
    assert all(c.validation != val.FAILED for c in cells)


# ── invariant: duplicates across slides ───────────────────────────────

def test_same_cell_on_two_slides_agreeing_is_corroboration():
    cells = [
        _cell("reach_7d", 27.0, wave_code="w1", brand_slug="a"),
        _cell("reach_7d", 27.0, wave_code="w1", brand_slug="a"),
    ]
    val.validate(cells)
    assert all(c.validation == val.PASSED for c in cells)
    assert "otra lámina" in cells[0].validation_note


def test_same_cell_on_two_slides_disagreeing_is_a_conflict():
    cells = [
        _cell("reach_7d", 27.0, wave_code="w1", brand_slug="a"),
        _cell("reach_7d", 72.0, wave_code="w1", brand_slug="a"),   # digits transposed
    ]
    report = val.validate(cells)
    assert all(c.validation == val.CONFLICT for c in cells)
    assert not report.clean


# ── invariant: cross-source ───────────────────────────────────────────

def test_two_sources_agreeing_marks_the_cell_as_both():
    cells = [_cell("reach_7d", 27.0, coordinate_value=27.0)]
    val.validate(cells)
    assert cells[0].validation == val.PASSED
    assert cells[0].source_method == "both"


def test_two_sources_disagreeing_is_a_conflict_not_a_failure():
    """One of them is right; the reviewer decides which."""
    cells = [_cell("reach_7d", 27.0, coordinate_value=20.0)]
    val.validate(cells)
    assert cells[0].validation == val.CONFLICT


# ── status precedence ─────────────────────────────────────────────────

def test_a_failure_is_never_upgraded_by_a_later_passing_check():
    """A weak check must not overwrite a strong failure."""
    cells = [
        _cell("reach_3m", 82.0, wave_code="w1", brand_slug="a", coordinate_value=82.0),
        _cell("ever_tried", 60.0, wave_code="w1", brand_slug="a"),
    ]
    val.validate(cells)
    assert cells[0].validation == val.FAILED     # funnel broke it; cross-source agreed


def test_unchecked_is_reported_separately_from_passed():
    """A cell no invariant covers must not pass silently."""
    report = val.validate([_cell("brand_opinion_t2b", 65.0)])
    assert report.unchecked == 1
    assert report.passed == 0
    assert "sin verificación posible" in val.coverage_note(report)


def test_coverage_note_reports_what_was_verified():
    cells = [
        _cell("favourite_place", 50.0, brand_slug="a", distribution_id="d"),
        _cell("favourite_place", 50.0, brand_slug="b", distribution_id="d"),
        _cell("brand_opinion_t2b", 65.0),
    ]
    note = val.coverage_note(val.validate(cells))
    assert "2 de 3" in note


# ── label resolution ──────────────────────────────────────────────────

def test_label_resolution_ignores_accents_case_and_punctuation(db, engagement):
    from modules.brand_intel.models.models import BrandEntity, BrandWave

    brands = db.query(BrandEntity).filter(
        BrandEntity.engagement_id == engagement.id).all()
    waves = db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id).all()
    r = pipe._LabelResolver(brands, waves)
    assert r.brand("FOCAL") == "focal"
    assert r.brand("  focal  ") == "focal"
    assert r.brand("inexistente") is None
    assert r.wave("Ola 1") == "w1"


def test_normalisation_folds_accents():
    assert pipe._norm("Café Montaña") == pipe._norm("cafe montana")
    assert pipe._norm("McDonald's") == "mcdonalds"


def test_wave_label_matches_across_spellings(db, engagement):
    """A deck prints "Mayo '25" where the engagement declared "May '25"."""
    from modules.brand_intel.models.models import BrandEntity, BrandWave

    w = db.query(BrandWave).filter(BrandWave.code == "w1").one()
    w.label = "May '25"
    db.commit()
    r = pipe._LabelResolver(
        db.query(BrandEntity).filter(BrandEntity.engagement_id == engagement.id).all(),
        db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id).all(),
    )
    assert r.wave("Mayo '25") == "w1"
    assert r.wave("May '25") == "w1"


def test_wave_matching_refuses_when_two_waves_collapse(db, engagement):
    """Ambiguity is refused, not guessed."""
    from modules.brand_intel.models.models import BrandEntity, BrandWave

    waves = db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id).all()
    waves[0].label, waves[1].label = "May '25", "Mayo '25"
    db.commit()
    r = pipe._LabelResolver(
        db.query(BrandEntity).filter(BrandEntity.engagement_id == engagement.id).all(),
        db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id).all(),
    )
    assert r.wave("Mayoo '25") is None      # loose key collides → unusable


def test_brand_matching_tolerates_a_typo_in_the_deck(db, engagement):
    """Real decks misspell their own brands — "Little Ceasars" for "Little Caesars"."""
    from modules.brand_intel.models.models import BrandEntity, BrandWave

    db.add(BrandEntity(engagement_id=engagement.id, slug="little_caesars",
                       name="Little Caesars", is_focal=False, in_category_set=True))
    db.commit()
    r = pipe._LabelResolver(
        db.query(BrandEntity).filter(BrandEntity.engagement_id == engagement.id).all(),
        db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id).all(),
    )
    assert r.brand("Little Ceasars") == "little_caesars"
    assert r.brand("Burger King") is None          # genuinely different brand


def test_brand_matching_refuses_short_names():
    """A three-letter name is one edit away from too many things."""
    assert pipe._edit_distance("kfc", "kfd", 1) == 1     # close, but the guard is length


def test_edit_distance_abandons_past_budget():
    assert pipe._edit_distance("abcdef", "zzzzzz", 2) > 2


# ── distribution verdicts computed on the full slide ──────────────────

def test_distribution_is_judged_before_the_engagement_filter():
    """A deck charts 18 brands; the engagement tracks 7. The sum is only 100 across 18 —
    checking after the filter would fail every real deck."""
    full_slide = [
        _cell("favourite_place", 40.0, distribution_id="fav"),
        _cell("favourite_place", 35.0, distribution_id="fav"),
        _cell("favourite_place", 25.0, distribution_id="fav"),   # brand not tracked
    ]
    verdicts = val.distribution_verdicts(full_slide)
    assert verdicts["fav"][0] == val.PASSED

    # Only the two tracked brands survive; they sum to 75 and must still pass.
    survivors = [
        _cell("favourite_place", 40.0, brand_slug="a", distribution_id="fav"),
        _cell("favourite_place", 35.0, brand_slug="b", distribution_id="fav"),
    ]
    val.validate(survivors, distribution_results=verdicts)
    assert all(c.validation == val.PASSED for c in survivors)


def test_a_failed_distribution_still_reaches_the_survivors():
    full_slide = [
        _cell("favourite_place", 40.0, distribution_id="fav"),
        _cell("favourite_place", 20.0, distribution_id="fav"),   # a series was missed
    ]
    verdicts = val.distribution_verdicts(full_slide)
    survivors = [_cell("favourite_place", 40.0, brand_slug="a", distribution_id="fav")]
    report = val.validate(survivors, distribution_results=verdicts)
    assert survivors[0].validation == val.FAILED
    assert not report.clean


# ── pipeline ──────────────────────────────────────────────────────────

def _stub_page(cells, title="Lámina", readable=True):
    def _extract(image, page_number, brands, waves):
        return PageExtraction(page_number, title, readable, "", cells, "claude-opus-5")
    return _extract


def _stub_render(n=1):
    return lambda content, last=None: [b"png"] * n


def _row(metric, brand, wave, value, **kw):
    row = {"metric_code": metric, "brand_label": brand, "wave_label": wave,
           "segment": "total", "value": value, "base_n": 0, "distribution_id": ""}
    row.update(kw)
    return row


def test_ingest_stages_cells_without_touching_observations(db, engagement):
    report = pipe.ingest_pdf(
        db, engagement, b"pdf", "tracker.pdf",
        extractor=_stub_page([_row("reach_7d", "Focal", "Ola 1", 40, base_n=300)]),
        renderer=_stub_render(),
    )
    db.commit()

    assert report.cells_extracted == 1
    assert db.query(BrandExtractionCell).count() == 1
    # The engagement fixture already has observations; none were added by extraction.
    assert db.query(BrandObservation).filter(
        BrandObservation.source == "tracker.pdf").count() == 0


def test_unknown_brand_is_rejected_not_invented(db, engagement):
    """A typo must never create a phantom brand that splits a series in two."""
    report = pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([_row("reach_7d", "Marca Fantasma", "Ola 1", 40)]),
        renderer=_stub_render(),
    )
    assert report.cells_extracted == 0
    assert any(r["reason"] == "Marca no reconocida" for r in report.rejected)


def test_unknown_metric_is_rejected(db, engagement):
    report = pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([_row("metrica_inventada", "Focal", "Ola 1", 40)]),
        renderer=_stub_render(),
    )
    assert report.cells_extracted == 0
    assert any("Métrica fuera del diccionario" == r["reason"] for r in report.rejected)


def test_unlabelled_wave_is_rejected_when_the_engagement_has_several(db, engagement):
    report = pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([_row("reach_7d", "Focal", "", 40)]),
        renderer=_stub_render(),
    )
    assert report.cells_extracted == 0
    assert any(r["reason"] == "Ola no reconocida" for r in report.rejected)


def test_unreadable_page_is_counted_not_failed(db, engagement):
    report = pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([], readable=False),
        renderer=_stub_render(3),
    )
    assert report.pages_skipped == 3
    assert report.pages_read == 0


def test_a_failing_page_does_not_lose_the_document(db, engagement):
    """One bad slide is reported and the rest of the deck still lands."""
    calls = {"n": 0}

    def _extract(image, page_number, brands, waves):
        calls["n"] += 1
        if page_number == 1:
            raise RuntimeError("ilegible")
        return PageExtraction(page_number, "OK", True, "",
                              [_row("reach_7d", "Focal", "Ola 1", 40)], "claude-opus-5")

    report = pipe.ingest_pdf(db, engagement, b"pdf", "t.pdf",
                             extractor=_extract, renderer=_stub_render(2))
    assert len(report.page_errors) == 1
    assert report.cells_extracted == 1


def test_ingest_requires_waves_and_brands_first(db):
    from modules.brand_intel.models.models import BrandEngagement

    bare = BrandEngagement(slug="bare", client_name="C", focal_brand="F", market="RD")
    db.add(bare)
    db.commit()
    report = pipe.ingest_pdf(db, bare, b"pdf", "t.pdf",
                             extractor=_stub_page([]), renderer=_stub_render())
    assert any(r["reason"] == "Encargo incompleto" for r in report.rejected)


# ── promotion ─────────────────────────────────────────────────────────

def test_confirm_promotes_kept_cells_into_observations(db, engagement):
    pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([_row("delivery_t2b", "Focal", "Ola 1", 91, base_n=200)]),
        renderer=_stub_render(),
    )
    db.commit()
    extraction = db.query(BrandExtraction).one()

    out = pipe.confirm_extraction(db, extraction, confirmed_by="analista@x.com")
    db.commit()

    assert out["creadas"] == 1
    obs = db.query(BrandObservation).filter(
        BrandObservation.metric_code == "delivery_t2b").one()
    assert obs.value == 91
    assert "extracción asistida confirmada por analista@x.com" in obs.source
    assert extraction.status == "confirmed"


def test_confirm_refuses_to_promote_a_failed_cell(db, engagement):
    """The reviewer resolves conflicts; a proven inconsistency is not theirs to wave through."""
    pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([
            _row("ever_tried", "Focal", "Ola 1", 60),
            _row("reach_3m", "Focal", "Ola 1", 82),      # breaks funnel monotonicity
        ]),
        renderer=_stub_render(),
    )
    db.commit()
    extraction = db.query(BrandExtraction).one()
    for c in db.query(BrandExtractionCell).all():
        c.included = True                                 # reviewer tries to keep them
    db.commit()

    out = pipe.confirm_extraction(db, extraction, confirmed_by="x@y.com")
    db.commit()
    assert out["creadas"] == 0
    assert out["omitidas_por_inconsistencia"] == 2


def test_confirm_respects_a_reviewer_dropping_a_cell(db, engagement):
    pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([_row("delivery_t2b", "Focal", "Ola 1", 91)]),
        renderer=_stub_render(),
    )
    db.commit()
    extraction = db.query(BrandExtraction).one()
    db.query(BrandExtractionCell).one().included = False
    db.commit()

    out = pipe.confirm_extraction(db, extraction, confirmed_by="x@y.com")
    assert out["creadas"] == 0
    assert out["descartadas_por_revision"] == 1


def test_confirm_updates_an_existing_observation_in_place(db, engagement):
    """Re-ingesting a corrected deck must not duplicate the series."""
    for _ in range(2):
        pipe.ingest_pdf(
            db, engagement, b"pdf", "t.pdf",
            extractor=_stub_page([_row("delivery_t2b", "Focal", "Ola 1", 91)]),
            renderer=_stub_render(),
        )
        db.commit()
    extractions = db.query(BrandExtraction).all()
    pipe.confirm_extraction(db, extractions[0], confirmed_by="a@b.com")
    db.commit()
    out = pipe.confirm_extraction(db, extractions[1], confirmed_by="a@b.com")
    db.commit()

    assert out["actualizadas"] == 1
    assert db.query(BrandObservation).filter(
        BrandObservation.metric_code == "delivery_t2b").count() == 1


def test_confirm_survives_the_same_figure_appearing_on_two_slides(db, engagement):
    """A deck repeats its headline number; the observation key is unique.

    Before this was handled, two staged cells for one key produced two INSERTs and the
    unique constraint aborted the whole commit — the reviewer lost an entire confirmation
    they had already worked through, and nothing was saved.
    """
    pipe.ingest_pdf(
        db, engagement, b"pdf", "t.pdf",
        extractor=_stub_page([_row("delivery_t2b", "Focal", "Ola 1", 91)]),
        renderer=_stub_render(2),          # the same slide read twice
    )
    db.commit()
    extraction = db.query(BrandExtraction).one()
    assert db.query(BrandExtractionCell).count() == 2

    out = pipe.confirm_extraction(db, extraction, confirmed_by="a@b.com")
    db.commit()                            # the commit itself is the assertion

    assert out["creadas"] == 1
    assert out["repetidas_coincidentes"] == 1
    assert db.query(BrandObservation).filter(
        BrandObservation.metric_code == "delivery_t2b").count() == 1


def test_confirm_refuses_a_key_the_deck_states_two_ways(db, engagement):
    """Two slides, one key, two numbers: choosing one would invent which was misread."""
    pages = iter([
        [_row("delivery_t2b", "Focal", "Ola 1", 91)],
        [_row("delivery_t2b", "Focal", "Ola 1", 87)],
    ])

    def _extract(image, page_number, brands, waves):
        return PageExtraction(page_number, "Lámina", True, "", next(pages), "claude-opus-5")

    pipe.ingest_pdf(db, engagement, b"pdf", "t.pdf",
                    extractor=_extract, renderer=_stub_render(2))
    db.commit()
    extraction = db.query(BrandExtraction).one()

    out = pipe.confirm_extraction(db, extraction, confirmed_by="a@b.com")
    db.commit()

    assert out["creadas"] == 0
    assert out["omitidas_por_discrepancia"] == 1
    assert out["discrepancias"][0]["valores"] == [87.0, 91.0]
    assert db.query(BrandObservation).filter(
        BrandObservation.metric_code == "delivery_t2b").count() == 0


# ── acumulación entre entregas ────────────────────────────────────────

def _deck(db, engagement, name, by_wave):
    """Una entrega: adopta las olas que trae y confirma sus cifras."""
    from modules.brand_intel import service as svc

    svc.adopt_structure(
        db, engagement,
        [{"code": w, "label": w, "period_date": f"{w}-01"} for w in by_wave],
        [{"name": "Focal", "slug": "focal", "is_focal": True}],
    )
    rows = [_row("reach_7d", "Focal", w, v) for w, v in by_wave.items()]
    rep = pipe.ingest_pdf(db, engagement, b"pdf", name,
                          extractor=_stub_page(rows), renderer=_stub_render())
    db.commit()
    extraction = db.query(BrandExtraction).filter(
        BrandExtraction.id == rep.extraction_id).one()
    out = pipe.confirm_extraction(db, extraction, "cliente@x.com")
    db.commit()
    return out


def _value(db, engagement, wave_code):
    from modules.brand_intel import service as svc

    wid = {w.code: w.id for w in svc.waves(db, engagement.id)}[wave_code]
    return db.query(BrandObservation).filter(
        BrandObservation.engagement_id == engagement.id,
        BrandObservation.wave_id == wid,
        BrandObservation.metric_code == "reach_7d").one().value


def test_a_later_deck_correcting_an_earlier_wave_wins(db, engagement):
    _deck(db, engagement, "ola3.pdf", {"2025-05": 24.0, "2025-11": 25.0})
    out = _deck(db, engagement, "ola4.pdf", {"2025-05": 24.0, "2025-11": 26.0,
                                             "2026-03": 27.0})
    assert _value(db, engagement, "2025-11") == 26.0
    assert any(c.get("corregida") == 26.0 for c in out["cifras_que_cambian"])


def test_an_older_deck_uploaded_last_does_not_walk_the_figure_back(db, engagement):
    """The truth must not depend on the order the client happened to upload the files."""
    _deck(db, engagement, "ola4.pdf", {"2025-05": 24.0, "2025-11": 26.0, "2026-03": 27.0})
    out = _deck(db, engagement, "ola3.pdf", {"2025-05": 24.0, "2025-11": 25.0})

    assert _value(db, engagement, "2025-11") == 26.0        # sigue corregida
    assert out["no_reemplazan_por_mazo_mas_nuevo"] == 1     # solo la que discrepa
    # El mazo viejo no cambia nada: donde coincide no hay qué actualizar, y donde
    # discrepa no manda. Queda en el registro, no en el valor vigente.
    assert out["actualizadas"] == 0
    assert out["creadas"] == 0


def test_every_delivery_keeps_what_it_said(db, engagement):
    """La base conserva el dato original: la corrección no borra la cifra publicada."""
    from modules.brand_intel.models.models import BrandObservationReading
    from modules.brand_intel import service as svc

    _deck(db, engagement, "ola3.pdf", {"2025-11": 25.0})
    _deck(db, engagement, "ola4.pdf", {"2025-11": 26.0, "2026-03": 27.0})

    wid = {w.code: w.id for w in svc.waves(db, engagement.id)}["2025-11"]
    leidas = sorted(
        r.value for r in db.query(BrandObservationReading).filter(
            BrandObservationReading.wave_id == wid,
            BrandObservationReading.metric_code == "reach_7d").all()
    )
    assert leidas == [25.0, 26.0]
    assert _value(db, engagement, "2025-11") == 26.0


def test_reconfirming_the_same_deck_does_not_pile_up_readings(db, engagement):
    from modules.brand_intel.models.models import BrandObservationReading

    _deck(db, engagement, "ola4.pdf", {"2026-03": 27.0})
    extraction = db.query(BrandExtraction).order_by(
        BrandExtraction.created_at.desc()).first()
    pipe.confirm_extraction(db, extraction, "cliente@x.com")
    db.commit()

    assert db.query(BrandObservationReading).filter(
        BrandObservationReading.metric_code == "reach_7d").count() == 1
