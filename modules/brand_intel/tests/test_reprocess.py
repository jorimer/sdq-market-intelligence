"""Separar lo CARO de lo CORREGIBLE: la lectura se paga una vez, se interpreta muchas.

Dos mazos completos se releyeron en producción por defectos que estaban enteramente aguas
abajo de la lectura —las etiquetas de ola no casaban; el atributo llegaba y se descartaba—
y en los dos casos la respuesta del modelo era correcta. Guardarla cuesta ~360 KB por mazo.
"""
from modules.brand_intel.ingest import pdf_pipeline as pipe
from modules.brand_intel.ingest.pdf_vision import EXTRACTION_SCHEMA_VERSION, PageExtraction
from modules.brand_intel.models.models import (
    BrandExtraction, BrandExtractionCell, BrandExtractionPage)


def _fila(metric="reach_7d", brand="Focal", wave="Ola 1", value=27.0, **extra):
    fila = {"metric_code": metric, "brand_label": brand, "wave_label": wave,
            "segment": "total", "attribute": "", "value": value, "base_n": 300,
            "distribution_id": ""}
    fila.update(extra)
    return fila


def _leer(db, engagement, filas, monkeypatch, paginas=1):
    """Corre una ingesta con el modelo simulado y devuelve la extracción."""
    def _render(content, first, last):
        return [b"png"] if first <= paginas else []

    def _extract(image, page_no, brands, waves):
        return PageExtraction(page_number=page_no, chart_title=f"lámina {page_no}",
                              readable=True, skip_reason="", cells=filas,
                              model_used="test")

    row = BrandExtraction(engagement_id=engagement.id, document_name="mazo.pdf",
                          method="vision", n_pages=paginas, pages_done=0,
                          status="queued", source_pdf=b"%PDF")
    db.add(row)
    db.flush()
    pipe.ingest_pdf(db, engagement, b"%PDF", "mazo.pdf",
                    renderer=_render, extractor=_extract, into=row)
    db.commit()
    return row


def test_the_models_answer_is_kept_before_it_is_interpreted(db, engagement, monkeypatch):
    row = _leer(db, engagement, [_fila()], monkeypatch)

    paginas = db.query(BrandExtractionPage).filter(
        BrandExtractionPage.extraction_id == row.id).all()
    assert len(paginas) == 1
    p = paginas[0]
    assert p.payload and p.payload[0]["metric_code"] == "reach_7d"
    assert p.chart_title == "lámina 1"
    # La versión del esquema viaja con la lectura: sin ella, re-procesar una respuesta
    # vieja daría por vacíos los campos que ese esquema no pedía.
    assert p.schema_version == EXTRACTION_SCHEMA_VERSION


def test_reprocessing_rebuilds_the_cells_without_touching_the_model(db, engagement,
                                                                   monkeypatch):
    """La propiedad que justifica todo: se re-interpreta sin pagar visión. Si el
    re-procesado llamara al modelo, el renderizador falso lo delataría."""
    row = _leer(db, engagement, [_fila(), _fila(metric="reach_1m", value=43.0)],
                monkeypatch)
    antes = db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).count()
    assert antes == 2

    def _explota(*a, **k):
        raise AssertionError("el re-procesado NO puede leer láminas")

    monkeypatch.setattr("modules.brand_intel.ingest.pdf_vision.render_pages", _explota)
    monkeypatch.setattr("modules.brand_intel.ingest.pdf_vision.extract_page", _explota)

    out = pipe.reprocess_extraction(db, row)
    db.commit()

    assert out["laminas"] == 1 and out["celdas"] == 2
    assert "no se pagó ninguna llamada de visión" in out["nota"]
    assert db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).count() == 2


def test_reprocessing_replaces_cells_instead_of_duplicating(db, engagement, monkeypatch):
    """Las celdas son una interpretación DERIVADA: conservar la anterior junto a la nueva
    dejaría dos verdades para la misma coordenada."""
    row = _leer(db, engagement, [_fila()], monkeypatch)
    pipe.reprocess_extraction(db, row)
    pipe.reprocess_extraction(db, row)
    db.commit()
    assert db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).count() == 1


def test_a_page_read_with_an_older_schema_is_declared_not_silently_reused(
    db, engagement, monkeypatch,
):
    """Una respuesta leída con un esquema que no pedía cierto campo NO lo gana al
    re-procesarse. Esas láminas son las únicas que sí exigen releer, y se cuentan aparte en
    vez de dejar creer que quedó todo al día."""
    row = _leer(db, engagement, [_fila()], monkeypatch)
    p = db.query(BrandExtractionPage).filter(
        BrandExtractionPage.extraction_id == row.id).one()
    p.schema_version = "2026-01-01-viejo"
    db.commit()

    out = pipe.reprocess_extraction(db, row)
    assert out["laminas_con_esquema_viejo"] == [1]


def test_an_extraction_from_before_this_feature_says_so(db, engagement):
    """Sin lectura cruda guardada no se puede re-procesar, y el resultado lo DICE en vez de
    devolver cero celdas como si el mazo estuviera vacío."""
    row = BrandExtraction(engagement_id=engagement.id, document_name="viejo.pdf",
                          method="vision", n_pages=10, pages_done=10, status="validated")
    db.add(row)
    db.commit()

    out = pipe.reprocess_extraction(db, row)
    assert out["sin_lectura_cruda"] is True
    assert "exigiría volver a leer" in out["nota"]


def test_the_attribute_defect_would_have_been_fixed_for_free(db, engagement, monkeypatch):
    """El caso REAL: el modelo mandaba el atributo y la conversión lo tiraba. Con la lectura
    guardada, arreglar la conversión y re-procesar lo recupera sin pagar nada."""
    row = _leer(db, engagement,
                [_fila(metric="attribute_index", value=181.0,
                       attribute="Es muy bueno para ir a tomar un café")],
                monkeypatch)

    celda = db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).one()
    assert celda.attribute == "Es muy bueno para ir a tomar un café"

    # y la respuesta cruda lo conserva aunque la celda se borre
    db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).delete()
    db.commit()
    pipe.reprocess_extraction(db, row)
    db.commit()
    recuperada = db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == row.id).one()
    assert recuperada.attribute == "Es muy bueno para ir a tomar un café"
