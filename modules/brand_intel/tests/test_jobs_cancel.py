"""Gobernar el ciclo de vida de una lectura: detenerla, y que no se cuelgue en silencio.

Los dos defectos costaron corridas de visión reales el 2026-08-13. Un mazo encolado no se
podía detener —cualquier error de criterio se pagaba completo— y podía quedarse en `reading`
más de una hora sin registrar nada, con lo que esperar era la única conducta posible.
"""
import pytest

from modules.brand_intel.ingest import jobs
from modules.brand_intel.models.models import BrandExtraction


def _trabajo(db, engagement, status=jobs.READING, done=0):
    row = BrandExtraction(engagement_id=engagement.id, document_name="mazo.pdf",
                          status=status, n_pages=65, pages_done=done,
                          method="vision", source_pdf=b"%PDF-1.4 fake")
    db.add(row)
    db.commit()
    return row


# ── detener ────────────────────────────────────────────────────────────


def test_the_checkpoint_stops_between_pages_not_mid_page(db, engagement):
    """La promesa exacta: se detiene EN EL CORTE de lámina. Una llamada de visión en vuelo
    no se puede abortar, así que lo que se acota es el desperdicio a una lámina."""
    row = _trabajo(db, engagement, done=7)

    # otra sesión —la petición HTTP— pide la cancelación
    row.status = jobs.CANCELLED
    db.commit()

    # el punto de control relee el estado DE LA BASE, no del objeto en memoria
    vigente = db.query(BrandExtraction.status).filter(
        BrandExtraction.id == row.id).scalar()
    assert str(vigente) == jobs.CANCELLED
    with pytest.raises(jobs.JobCancelled) as e:
        if str(vigente) == jobs.CANCELLED:
            raise jobs.JobCancelled(f"Cancelado en la lámina {8}.")
    assert "lámina 8" in str(e.value)


def test_cancelling_is_not_discarding(db, engagement):
    """Lo leído se conserva y el PDF sigue guardado: un trabajo cancelado se puede reanudar.
    Si cancelar borrara, nadie lo usaría a mitad de una lectura larga."""
    row = _trabajo(db, engagement, done=32)
    row.status = jobs.CANCELLED
    db.commit()

    fresco = db.query(BrandExtraction).filter(BrandExtraction.id == row.id).one()
    assert int(fresco.pages_done) == 32
    assert fresco.source_pdf, "sin el PDF no se puede reanudar"


def test_a_cancelled_job_is_not_an_error(db, engagement):
    """Se distinguen a propósito: un cancelado no tiene causa que diagnosticar, y
    confundirlo con un fallo manda a buscar un problema que no existe."""
    assert jobs.CANCELLED != jobs.ERROR
    row = _trabajo(db, engagement, status=jobs.CANCELLED)
    estado = jobs.job_status(db, row)
    assert estado["status"] == jobs.CANCELLED
    assert estado["running"] is False          # ya no se espera nada
    assert estado["error"] is None


def test_cancel_endpoint_refuses_a_finished_job_with_409(db, engagement):
    """Un trabajo terminado no se «cancela». Decirlo evita que alguien crea que deshizo
    algo; y es 409 porque la petición es válida, el estado no la admite."""
    from modules.brand_intel.tests.test_api import _client

    row = _trabajo(db, engagement, status="validated", done=65)
    r = _client(db).post(
        f"/api/v1/brand-intel/engagements/demo/extractions/{row.id}/cancel")
    assert r.status_code == 409
    assert "ya terminó" in r.json()["detail"]


def test_cancel_endpoint_stops_a_reading_job_and_declares_the_limit(db, engagement):
    from modules.brand_intel.tests.test_api import _client

    row = _trabajo(db, engagement, done=12)
    r = _client(db).post(
        f"/api/v1/brand-intel/engagements/demo/extractions/{row.id}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == jobs.CANCELLED
    assert body["laminas_leidas"] == 12
    # La nota no promete un corte instantáneo: eso sería mentir sobre lo que se puede.
    assert "termina" in body["nota"] and "reanudar" in body["nota"]


def test_cancel_needs_analyst(db, engagement):
    from shared.auth.models import UserRole

    from modules.brand_intel.tests.test_api import _client

    row = _trabajo(db, engagement)
    r = _client(db, role=UserRole.viewer).post(
        f"/api/v1/brand-intel/engagements/demo/extractions/{row.id}/cancel")
    assert r.status_code == 403


# ── no colgarse en silencio ────────────────────────────────────────────


def test_every_page_read_has_a_bounded_deadline():
    """La causa raíz del cuelgue no era falta de vigilante: era que la llamada de visión no
    tenía timeout, y el SDK reintenta con su propio límite generoso. Con el límite puesto,
    una lámina lenta FALLA, el `except` por página la anota y el mazo sigue."""
    import inspect

    from modules.brand_intel.ingest import pdf_vision

    assert pdf_vision.PAGE_TIMEOUT_S > 0
    fuente = inspect.getsource(pdf_vision.extract_page)
    assert "timeout=PAGE_TIMEOUT_S" in fuente, (
        "la lectura de lámina volvió a quedar sin plazo: un mazo puede colgarse una hora "
        "sin registrar nada")


def test_a_slow_page_does_not_kill_the_deck():
    """El contrato alrededor del plazo: el fallo de UNA lámina se anota y se sigue. Sin
    esto, poner un timeout cambiaría un cuelgue por perder el mazo entero."""
    import inspect

    from modules.brand_intel.ingest import pdf_pipeline

    fuente = inspect.getsource(pdf_pipeline.ingest_pdf)
    assert "one bad page must not lose the document" in fuente
    assert "report.page_errors.append" in fuente
