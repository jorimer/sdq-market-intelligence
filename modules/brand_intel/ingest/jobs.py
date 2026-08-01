"""La lectura de un mazo como TRABAJO, no como petición.

Leer un mazo real son decenas de llamadas de visión: el de Ipsos son 59 láminas y media
hora larga. Eso no cabe en una petición HTTP, y la primera versión lo intentó: moría
contra el presupuesto de tiempo del proxy **después de haber pagado todas las llamadas
que alcanzó a hacer**, sin dejar ni una cifra.

La fila de ``BrandExtraction`` es el trabajo. Guarda su propio PDF mientras dura, cuenta
las láminas hechas, y se reanuda por donde iba. La petición solo lo encola y devuelve el
identificador; la pantalla pregunta por el avance.

**Por qué el PDF vive en la base y no en un bucket:** es dato privado de un cliente, y
``engagement_id`` es lo único que gobierna su acceso en todo el módulo. Un bucket
necesitaría su propio control de acceso, que es exactamente la clase de frontera duplicada
que acaba divergiendo. Se borra al terminar, así que la base no lo carga de por vida.

El despacho sigue el patrón de la casa (ver ``banking_score.sib_sync``): Celery cuando hay
worker, hilo cuando no. Con Celery el trabajo sobrevive a un reinicio del web y
``task_acks_late`` lo reencola si el worker muere — y como es reanudable, la reencola no
repite las láminas ya leídas.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modules.brand_intel.models.models import (
    BrandEngagement,
    BrandExtraction,
    BrandExtractionCell,
)

logger = logging.getLogger("sdq.brand_intel.jobs")

#: Estados por los que pasa el trabajo. `validated`/`rejected` son terminales y ya
#: existían; los tres primeros son del trabajo, no del resultado.
QUEUED, READING, ERROR = "queued", "reading", "error"


def queue_extraction(
    db: Session,
    engagement: BrandEngagement,
    content: bytes,
    document_name: str,
    max_pages: Optional[int] = None,
) -> BrandExtraction:
    """Registra el trabajo y lo despacha. No lee ni una lámina."""
    from modules.brand_intel.ingest.pdf_vision import page_count

    try:
        total = page_count(content)
    except Exception as exc:  # noqa: BLE001 — un PDF ilegible se dice ahora, no luego
        raise ValueError(f"No se pudo abrir el PDF: {exc}") from exc

    extraction = BrandExtraction(
        engagement_id=engagement.id,
        document_name=document_name,
        n_pages=min(total, max_pages) if max_pages else total,
        pages_done=0,
        status=QUEUED,
        method="vision",
        source_pdf=content,
        max_pages=max_pages,
    )
    db.add(extraction)
    db.commit()
    _dispatch(str(extraction.id))
    return extraction


def _dispatch(extraction_id: str) -> str:
    """Celery si hay worker; si no, un hilo. Devuelve por dónde salió."""
    from shared.config.settings import settings

    if settings.USE_CELERY and settings.REDIS_URL:
        try:
            from modules.brand_intel.tasks import read_deck_task

            read_deck_task.delay(extraction_id)
            return "celery"
        except Exception:  # noqa: BLE001 — sin broker, el hilo sigue siendo mejor que nada
            logger.exception("No se pudo encolar en Celery; usando hilo")

    threading.Thread(target=run_extraction, args=(extraction_id,), daemon=True).start()
    return "thread"


def run_extraction(extraction_id: str) -> Dict[str, Any]:
    """Lee el mazo del trabajo. Abre su propia sesión: corre fuera de la petición.

    Reanudable: si la fila ya tiene láminas hechas, se retoman desde ahí y las celdas ya
    guardadas se conservan. Es lo que hace seguro que ``task_acks_late`` reencole el
    trabajo cuando el worker muere — la reencola no vuelve a pagar lo ya leído.
    """
    from shared.database.session import SessionLocal
    from modules.brand_intel.ingest.pdf_pipeline import ingest_pdf

    db = SessionLocal()
    try:
        extraction = (db.query(BrandExtraction)
                      .filter(BrandExtraction.id == extraction_id).first())
        if extraction is None:
            logger.warning("Trabajo %s ya no existe", extraction_id)
            return {"status": "missing"}
        if extraction.status in ("validated", "rejected", "confirmed"):
            return {"status": str(extraction.status)}          # ya terminó
        if not extraction.source_pdf:
            _fail(db, extraction, "El trabajo ya no conserva el PDF: vuelve a subirlo.")
            return {"status": ERROR}

        engagement = (db.query(BrandEngagement)
                      .filter(BrandEngagement.id == extraction.engagement_id).first())
        if engagement is None:
            _fail(db, extraction, "El encargo del trabajo ya no existe.")
            return {"status": ERROR}

        extraction.status = READING
        extraction.started_at = extraction.started_at or datetime.now(timezone.utc)
        extraction.error = None
        db.commit()

        def _progress(done: int) -> None:
            # El total ya se conoce desde que se encoló (`page_count`), así que la
            # pantalla enseña "7 de 59" desde el primer segundo y no un contador que
            # solo existe al final.
            extraction.pages_done = done
            db.commit()

        content = bytes(extraction.source_pdf)
        report = ingest_pdf(db, engagement, content, str(extraction.document_name),
                            max_pages=extraction.max_pages, on_page=_progress,
                            into=extraction)

        # Una sola fila por documento, de `queued` a `validated`. El PDF se suelta aquí:
        # ya cumplió su función y no tiene por qué pesar en la base para siempre.
        extraction.report = report.as_dict()
        extraction.finished_at = datetime.now(timezone.utc)
        extraction.source_pdf = None
        db.commit()
        return {"status": str(extraction.status), "extraction_id": str(extraction.id)}

    except Exception as exc:  # noqa: BLE001 — el trabajo debe morir diciendo por qué
        logger.exception("Falló la lectura del mazo %s", extraction_id)
        db.rollback()
        row = (db.query(BrandExtraction)
               .filter(BrandExtraction.id == extraction_id).first())
        if row is not None:
            _fail(db, row, str(exc) or exc.__class__.__name__)
        return {"status": ERROR, "error": str(exc)}
    finally:
        db.close()


def _fail(db: Session, extraction: BrandExtraction, message: str) -> None:
    """Deja el trabajo en error, con el motivo y sin el PDF colgando."""
    extraction.status = ERROR
    extraction.error = message[:2000]
    extraction.finished_at = datetime.now(timezone.utc)
    extraction.source_pdf = None
    db.commit()


def job_status(db: Session, extraction: BrandExtraction) -> Dict[str, Any]:
    """Lo que la pantalla necesita para saber si esperar, revisar o reintentar."""
    done = int(extraction.pages_done or 0)
    total = int(extraction.n_pages or 0)
    staged = (db.query(BrandExtractionCell)
              .filter(BrandExtractionCell.extraction_id == extraction.id).count())
    return {
        "extraction_id": extraction.id,
        "document": extraction.document_name,
        "status": extraction.status,
        "running": extraction.status in (QUEUED, READING),
        "pages_done": done,
        "pages_total": total,
        "cells_staged": staged,
        "error": extraction.error,
        "report": extraction.report,
        "note": extraction.note,
    }
