"""Celery tasks for the macro_monitor module."""
from shared.tasks.celery_app import celery_app


@celery_app.task(name="macro.excel_batch", bind=True)
def excel_batch_task(self, **kwargs) -> dict:
    """Run the BCRD Excel batch over the catalog in the Celery worker.

    Publica «archivo N de M» con ``update_state``: la operación que la espera
    (``macro-excel-batch``) lo retransmite como fase de la consola.
    """
    from shared.database.session import SessionLocal
    from modules.macro_monitor.service import run_excel_batch

    def _avisar(frase: str) -> None:
        self.update_state(state="PROGRESS", meta={"phase": frase})

    db = SessionLocal()
    try:
        return run_excel_batch(db, progreso=_avisar, **kwargs)
    finally:
        db.close()


@celery_app.task(name="macro.ingest_canonical", bind=True)
def ingest_canonical_task(self, persist: bool = False) -> dict:  # noqa: ARG001
    """Ingest only the canonical series in the Celery worker."""
    from shared.data.bcrd_excel.canonical import PERSISTIBLES_VERIFICADOS
    from shared.database.session import SessionLocal
    from modules.macro_monitor.service import ingest_canonical

    db = SessionLocal()
    try:
        # El alcance se resuelve ACÁ y no viaja en el mensaje: una tarea encolada escribe con
        # la lista vigente al correr. Mismo alcance que `macro-canonical-sync`.
        return ingest_canonical(db, persist=persist, alcance=PERSISTIBLES_VERIFICADOS)
    finally:
        db.close()
