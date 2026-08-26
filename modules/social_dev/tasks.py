"""Tareas del panel social que corren en el WORKER, no en el proceso web."""
from modules.social_dev.digepres_sync import run_digepres_salud
from shared.tasks.celery_app import celery_app


@celery_app.task(name="social.digepres_salud_funcional", bind=True)
def digepres_salud_funcional_task(self, force: bool = False) -> dict:
    """Serie del 2.33 (gasto en salud del Gobierno Central) leída de los PDF del emisor.

    Son ~400 MB de documentos y hasta 980 páginas cada uno: acá hay memoria y tiempo, y una
    muerte no se lleva puesta la API. `task_acks_late` la vuelve a encolar si el worker cae,
    y como cada año se persiste apenas se lee, el reintento sigue donde quedó en vez de
    volver a bajar todo.

    El progreso se publica en el estado de la tarea para que el console muestre en qué año
    va: sin esto, veinte minutos de trabajo se ven igual que un cuelgue.
    """
    def _avisar(frase: str) -> None:
        self.update_state(state="PROGRESS", meta={"phase": frase})

    return run_digepres_salud(force=force, progreso=_avisar)


@celery_app.task(name="social.tramites_registro_unico", bind=True)
def tramites_registro_unico_task(self, force: bool = True) -> dict:
    """Catálogo de trámites del Portal Único de Servicios, mensual.

    Va al worker por el mismo motivo que el 2.33, aunque no pese lo mismo: son ~711 llamadas
    HTTP contra un portal público —una del listado y una del detalle de cada trámite— con
    una pausa entre cada una, y eso no va en el proceso que atiende la API.

    `force=True` por defecto y es deliberado: la agenda es mensual y el catálogo es un
    estado VIVO, así que si en un mes hay dos corridas, la más reciente es la afirmación más
    verdadera sobre el catálogo. El guard de «ya existe» sigue protegiendo la corrida manual,
    que es donde no querés reescribir sin decirlo.
    """
    def _avisar(frase: str) -> None:
        self.update_state(state="PROGRESS", meta={"phase": frase})

    from modules.social_dev.tramites_sync import run_tramites

    return run_tramites(force=force, progreso=_avisar)
