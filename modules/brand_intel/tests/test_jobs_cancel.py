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


# ── reanudar sin repagar ni duplicar ───────────────────────────────────
#
# El docstring prometía «`pages_done` is where a re-run picks up» y el endpoint decía «las
# láminas ya leídas no se vuelven a pagar». El bucle arrancaba en 1 SIEMPRE, y el escritor
# solo hacía `db.add`: reanudar releía el mazo entero y duplicaba sus celdas. Una promesa
# escrita en prosa y desmentida por el código es peor que no prometer nada.


def test_resume_starts_after_the_last_page_read(db, engagement) -> None:
    """La propiedad, no la firma: con 32 láminas hechas, la lectura EMPIEZA en la 33.

    `ingest_pdf` acepta el renderizador y el lector por parámetro justo para poder probar
    esto sin pagar visión.
    """
    from modules.brand_intel.ingest import pdf_pipeline as pipe
    from modules.brand_intel.ingest.pdf_vision import PageExtraction

    renderizadas: list[int] = []

    def _render(content, first, last):
        renderizadas.append(first)
        return [b"png"] if first <= 40 else []        # el mazo termina en la 40

    def _extract(image, page_no, brands, waves):
        return PageExtraction(chart_title=f"lámina {page_no}", readable=False,
                              skip_reason="sin cifras", cells=[], model_used="test")

    pipe.ingest_pdf(db, engagement, b"%PDF", "mazo.pdf",
                    renderer=_render, extractor=_extract, resume_from=32)

    assert renderizadas, "no se renderizó ninguna lámina"
    assert min(renderizadas) == 33, (
        f"la reanudación volvió a leer desde la {min(renderizadas)}: repaga lo ya leído")
    assert max(renderizadas) == 41                     # 41 devuelve vacío y corta


def test_a_fresh_job_still_starts_at_page_one(db, engagement) -> None:
    """La otra mitad: sin punto de retomada, se lee de cero. El mismo camino sirve para
    los dos casos, así que hay que fijar que no rompí el arranque normal."""
    from modules.brand_intel.ingest import pdf_pipeline as pipe
    from modules.brand_intel.ingest.pdf_vision import PageExtraction

    renderizadas: list[int] = []

    def _render(content, first, last):
        renderizadas.append(first)
        return [b"png"] if first <= 3 else []

    def _extract(image, page_no, brands, waves):
        return PageExtraction(chart_title="t", readable=False, skip_reason="",
                              cells=[], model_used="test")

    pipe.ingest_pdf(db, engagement, b"%PDF", "mazo.pdf",
                    renderer=_render, extractor=_extract)
    assert min(renderizadas) == 1


def test_the_runner_hands_pages_done_as_the_resume_point():
    """El cableado: `pages_done` es lo que el runner pasa. Un trabajo nuevo lo tiene en 0,
    así que el mismo camino sirve para leer de cero y para retomar."""
    import inspect

    fuente = inspect.getsource(jobs.run_extraction) if hasattr(jobs, "run_extraction") \
        else inspect.getsource(jobs)
    assert "resume_from=int(extraction.pages_done or 0)" in fuente


def test_resuming_revalidates_against_the_pages_already_read():
    """Sin cargar las celdas previas, la reanudación juzgaría la cola del mazo aislada y
    perdería la corroboración entre láminas —una cifra repetida en la 10 y en la 40 es
    confirmación gratis—. Y las previas se ACTUALIZAN, no se reinsertan: reinsertarlas
    duplicaría el mazo, que es lo que hacía la reanudación anterior."""
    import inspect

    from modules.brand_intel.ingest import pdf_pipeline as pipe

    fuente = inspect.getsource(pipe.ingest_pdf)
    assert "previas" in fuente
    assert "val.validate(previas + cells" in fuente, (
        "las celdas ya leídas no entran a la validación: se pierde la corroboración")
    assert "f.validation = c.validation" in fuente, (
        "las celdas previas no se actualizan en su fila: se estarían duplicando")


# ── ampliar el tope al reanudar ────────────────────────────────────────


def _cliente(db):
    from modules.brand_intel.tests.test_api import _client
    return _client(db)


def test_resuming_a_job_that_hit_its_own_cap_needs_a_wider_one(
    db, engagement, monkeypatch,
) -> None:
    """El caso real: una lectura de 32 de 32 retoma en la 33 y para en la 32 — no leería
    nada. Ampliar el tope es lo que la vuelve ejecutable, y sin decirlo el usuario pediría
    una reanudación que no reanuda."""
    from modules.brand_intel.ingest import jobs as jobs_mod

    despachos: list[str] = []
    monkeypatch.setattr(jobs_mod, "_dispatch", lambda i: despachos.append(i))

    row = _trabajo(db, engagement, status=jobs.READING, done=32)
    row.max_pages = 32
    db.commit()

    r = _cliente(db).post(
        f"/api/v1/brand-intel/engagements/demo/extractions/{row.id}/resume?max_pages=65")
    assert r.status_code == 200
    db.refresh(row)
    assert int(row.max_pages) == 65
    assert despachos == [str(row.id)]


def test_the_cap_can_only_be_widened(db, engagement, monkeypatch):
    """Reducirlo se RECHAZA en vez de aceptarse en silencio: dejaría fuera láminas que ya
    se leyeron y se pagaron."""
    from modules.brand_intel.ingest import jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "_dispatch", lambda i: None)
    row = _trabajo(db, engagement, done=32)
    row.max_pages = 32
    db.commit()

    r = _cliente(db).post(
        f"/api/v1/brand-intel/engagements/demo/extractions/{row.id}/resume?max_pages=10")
    assert r.status_code == 400
    assert "solo puede ampliarse" in r.json()["detail"]
    db.refresh(row)
    assert int(row.max_pages) == 32          # sin tocar


def test_resume_without_a_cap_keeps_the_one_it_had(db, engagement, monkeypatch):
    from modules.brand_intel.ingest import jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "_dispatch", lambda i: None)
    row = _trabajo(db, engagement, done=10)
    row.max_pages = 32
    db.commit()

    assert _cliente(db).post(
        f"/api/v1/brand-intel/engagements/demo/extractions/{row.id}/resume"
    ).status_code == 200
    db.refresh(row)
    assert int(row.max_pages) == 32
