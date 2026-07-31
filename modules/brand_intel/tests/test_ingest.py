"""Ingest tests: the template round-trips, bad rows are rejected with a reason, and a
re-upload updates in place instead of duplicating.

Corrections are routine in tracker work, so the second upload of a fixed workbook is the
normal motion — it has to be safe.
"""
import io

import pytest
from openpyxl import Workbook, load_workbook

from modules.brand_intel.ingest.excel_ingest import ingest_workbook
from modules.brand_intel.ingest.template import build_template
from modules.brand_intel.models.models import (
    BrandEngagement,
    BrandEntity,
    BrandObservation,
    BrandWave,
)


def _workbook(waves, brands, observations) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Olas"
    ws.append(["codigo", "etiqueta", "orden", "fecha_referencia",
               "campo_inicio", "campo_fin", "base_nominal"])
    for row in waves:
        ws.append(row)

    ws = wb.create_sheet("Marcas")
    ws.append(["slug", "nombre", "es_focal", "en_set_categoria", "orden"])
    for row in brands:
        ws.append(row)

    ws = wb.create_sheet("Observaciones")
    ws.append(["ola", "marca", "metrica", "segmento", "valor", "base_n", "unidad", "fuente"])
    for row in observations:
        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def blank_engagement(db):
    eng = BrandEngagement(slug="nuevo", client_name="C", focal_brand="F", market="RD")
    db.add(eng)
    db.commit()
    return eng


def test_template_has_the_five_sheets():
    wb = load_workbook(io.BytesIO(build_template("demo", "Focal", "Cliente", "Proveedor")))
    assert set(wb.sheetnames) == {"Encargo", "Olas", "Marcas", "Observaciones", "Diccionario"}


def test_template_dictionary_lists_the_metric_vocabulary():
    wb = load_workbook(io.BytesIO(build_template()))
    codes = {r[0] for r in wb["Diccionario"].iter_rows(min_row=2, values_only=True)}
    assert "reach_7d" in codes
    assert "favourite_place" in codes


def test_ingest_loads_waves_brands_and_observations(db, blank_engagement):
    content = _workbook(
        waves=[["w1", "Ola 1", 1, "2025-01-01", None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
        observations=[["w1", "focal", "reach_7d", "total", 26, 300, "pct", "lámina 18"]],
    )
    report = ingest_workbook(db, blank_engagement, content)
    db.commit()

    assert report.waves_created == 1
    assert report.brands_created == 1
    assert report.observations_created == 1
    assert report.rejected == []
    obs = db.query(BrandObservation).one()
    assert obs.value == 26 and obs.base_n == 300 and obs.source == "lámina 18"


def test_unknown_metric_is_rejected_with_a_reason(db, blank_engagement):
    content = _workbook(
        waves=[["w1", "Ola 1", 1, "2025-01-01", None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
        observations=[["w1", "focal", "reach_siete_dias", "total", 26, 300, "pct", ""]],
    )
    report = ingest_workbook(db, blank_engagement, content)
    assert report.observations_created == 0
    assert len(report.rejected) == 1
    assert "Métrica desconocida" in report.rejected[0]["reason"]
    assert report.rejected[0]["row"] == 2


def test_unknown_wave_or_brand_is_rejected(db, blank_engagement):
    content = _workbook(
        waves=[["w1", "Ola 1", 1, "2025-01-01", None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
        observations=[
            ["w9", "focal", "reach_7d", "total", 26, 300, "pct", ""],
            ["w1", "fantasma", "reach_7d", "total", 26, 300, "pct", ""],
        ],
    )
    report = ingest_workbook(db, blank_engagement, content)
    assert report.observations_created == 0
    reasons = " ".join(r["reason"] for r in report.rejected)
    assert "Ola desconocida" in reasons and "Marca desconocida" in reasons


def test_non_numeric_value_is_rejected(db, blank_engagement):
    content = _workbook(
        waves=[["w1", "Ola 1", 1, "2025-01-01", None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
        observations=[["w1", "focal", "reach_7d", "total", "n/d", 300, "pct", ""]],
    )
    report = ingest_workbook(db, blank_engagement, content)
    assert report.observations_created == 0
    assert "no numérico" in report.rejected[0]["reason"]


def test_missing_base_is_loaded_but_flagged_downstream(db, blank_engagement):
    """A row without its base is data, not an error — it just cannot carry a verdict."""
    content = _workbook(
        waves=[["w1", "Ola 1", 1, "2025-01-01", None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
        observations=[["w1", "focal", "reach_7d", "total", 26, None, "pct", ""]],
    )
    report = ingest_workbook(db, blank_engagement, content)
    db.commit()
    assert report.observations_created == 1
    assert db.query(BrandObservation).one().base_n is None


def test_reupload_updates_in_place_and_does_not_duplicate(db, blank_engagement):
    base = dict(
        waves=[["w1", "Ola 1", 1, "2025-01-01", None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
    )
    ingest_workbook(db, blank_engagement, _workbook(
        observations=[["w1", "focal", "reach_7d", "total", 26, 300, "pct", ""]], **base))
    db.commit()

    report = ingest_workbook(db, blank_engagement, _workbook(
        observations=[["w1", "focal", "reach_7d", "total", 31, 300, "pct", ""]], **base))
    db.commit()

    assert report.observations_updated == 1
    assert report.observations_created == 0
    assert db.query(BrandObservation).count() == 1
    assert db.query(BrandObservation).one().value == 31
    assert db.query(BrandWave).count() == 1
    assert db.query(BrandEntity).count() == 1


def test_wave_without_reference_date_warns_about_deflation(db, blank_engagement):
    content = _workbook(
        waves=[["w1", "Ola 1", 1, None, None, None, 300]],
        brands=[["focal", "Focal", "SI", "SI", 1]],
        observations=[],
    )
    report = ingest_workbook(db, blank_engagement, content)
    assert any("deflactarse" in w for w in report.warnings)


def test_missing_sheet_is_reported_not_crashed(db, blank_engagement):
    wb = Workbook()
    wb.active.title = "Otra"
    buf = io.BytesIO()
    wb.save(buf)
    report = ingest_workbook(db, blank_engagement, buf.getvalue())
    assert any(r["reason"] == "Hoja ausente en el archivo." for r in report.rejected)
