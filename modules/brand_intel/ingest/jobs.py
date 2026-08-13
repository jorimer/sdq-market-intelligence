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
#: Pedido por una persona, no por un fallo. Se distingue de `error` a propósito: un trabajo
#: cancelado no tiene nada que diagnosticar, y confundirlos manda a buscar una causa que no
#: existe. Conserva el PDF, así que se puede reanudar.
CANCELLED = "cancelled"


class JobCancelled(Exception):
    """Alguien pidió detener la lectura. Se lanza ENTRE láminas, nunca a mitad de una."""


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

        content = bytes(extraction.source_pdf)
        _read_conclusions(db, extraction, content)

        def _progress(done: int) -> None:
            # El total ya se conoce desde que se encoló (`page_count`), así que la
            # pantalla enseña "7 de 59" desde el primer segundo y no un contador que
            # solo existe al final.
            extraction.pages_done = done
            db.commit()
            # Y en el mismo punto se atiende la cancelación. El estado lo escribe OTRA
            # sesión (la petición HTTP), así que hay que releerlo de la base en vez de
            # confiar en el objeto en memoria. Entre láminas y no a mitad: una llamada de
            # visión en vuelo no se puede abortar, así que lo que se promete es acotar el
            # desperdicio a UNA lámina, no cortar al instante.
            vigente = db.query(BrandExtraction.status).filter(
                BrandExtraction.id == extraction.id).scalar()
            if str(vigente) == CANCELLED:
                raise JobCancelled(f"Cancelado en la lámina {done}.")

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

    except JobCancelled as exc:
        # Lo leído hasta acá se conserva: son celdas válidas en revisión, y el PDF sigue
        # guardado para poder reanudar. Cancelar no es descartar.
        db.rollback()
        row = (db.query(BrandExtraction)
               .filter(BrandExtraction.id == extraction_id).first())
        if row is not None:
            row.status = CANCELLED                     # type: ignore[assignment]
            row.error = None                           # type: ignore[assignment]
            row.note = str(exc)                        # type: ignore[assignment]
            row.finished_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            db.commit()
        logger.info("Lectura del mazo %s cancelada: %s", extraction_id, exc)
        return {"status": CANCELLED, "extraction_id": str(extraction_id)}

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


def _read_conclusions(db: Session, extraction: BrandExtraction, content: bytes) -> None:
    """Recoge lo que el estudio AFIRMA, antes de leer sus cifras.

    Va primero por dos razones. Cuesta una sola llamada sobre la capa de texto, frente a
    una por lámina de la pasada de visión: si el trabajo muere a mitad, lo barato ya está
    guardado. Y es lo que el informe necesita para explicar en vez de describir, así que
    conviene que exista aunque las cifras se queden a medias.

    Nunca tumba el trabajo. Las cifras son la carga principal y un mazo sin capa de texto
    —escaneado como imágenes— es un caso legítimo: se anota y se sigue.
    """
    from modules.brand_intel import service as svc
    from modules.brand_intel.ingest import conclusions as conc
    from modules.brand_intel.ingest.discovery import _page_texts

    try:
        vocab = svc.vocabulary_for(db, str(extraction.engagement_id))
        found = conc.read_conclusions(_page_texts(content), vocab=vocab)
        resumen = conc.store_conclusions(db, str(extraction.engagement_id), found,
                                         extraction_id=str(extraction.id))
        db.commit()
        logger.info("Conclusiones leídas en %s: %s", extraction.document_name, resumen)
    except Exception as exc:  # noqa: BLE001 — las cifras mandan; esto es aditivo
        logger.exception("No se pudieron leer las conclusiones de %s",
                         extraction.document_name)
        db.rollback()
        nota = f"Las cifras se leyeron; las conclusiones del estudio no: {str(exc)[:300]}"
        extraction.note = nota  # type: ignore[assignment]
        db.commit()


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
