"""Registro de gasto del modelo: qué llamó, quién lo disparó y cuánto costó.

**El defecto que esto cierra.** El costo de cada llamada YA se calcula —``cost_estimate``
en ``NarrativeResult``— y se escribe al log. Nunca se guarda. Los logs de Railway solo
conservan el despliegue vigente, así que a las pocas horas la evidencia desaparece y la
única forma de saber en qué se fue el dinero era mirar la consola de Anthropic antes y
después de cada corrida. Pasó de verdad: una fuga de gasto que no se pudo atribuir, y una
auditoría entera para descubrir que una tarea diaria generaba 203 informes sin que nadie
los pidiera.

**Lo que hace que esto sirva es el DISPARADOR, no el costo.** Registrar «se generó una
narrativa de 1.200 tokens» no responde la pregunta; responderla exige saber que la
disparó ``prewarm-report-cache`` y no una persona. Por eso hay un contexto explícito que
la operación o el endpoint declaran, y que viaja con la llamada.

**Tres reglas.**

*Jamás tumba la llamada.* Un fallo al registrar se traga y se loguea. El registro es
observabilidad, no parte del contrato: preferimos perder una fila a perder un informe.

*Registra también los HIT de caché, con costo cero.* Sin ellos no se puede distinguir
«nadie pidió esto» de «lo pidieron cien veces y la caché lo absorbió», que es justo la
diferencia que decide si una caché vale lo que ocupa.

*El costo se guarda como lo estimó quien llamó.* No se recalcula acá: la tarifa vive en
el motor que conoce el modelo y sus precios, y duplicar esa tabla garantiza que un día
diverjan.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger("sdq.observability.llm_ledger")

#: Motivos por los que se llama al modelo. Sirve para separar el gasto de PRODUCIR de
#: el gasto de VERIFICAR, que hoy es la mitad del total y nadie lo veía por separado.
PURPOSE_NARRATIVE = "narrativa"
PURPOSE_GUARD = "guard_numerico"
PURPOSE_VISION = "vision"
PURPOSE_DIGEST = "digest"
PURPOSE_EXTRACTION = "extraccion"
PURPOSE_OTHER = "otro"

#: Quién disparó la llamada, cuando nadie lo declaró.
TRIGGER_UNKNOWN = "desconocido"


@dataclass(frozen=True)
class Caller:
    """Quién es responsable de la llamada que está por ocurrir."""

    kind: str            # "operacion" | "endpoint" | "script" | "desconocido"
    detail: str          # nombre de la operación, ruta del endpoint, etc.
    user_id: Optional[str] = None


_CALLER: contextvars.ContextVar[Optional[Caller]] = contextvars.ContextVar(
    "sdq_llm_caller", default=None,
)


@contextmanager
def attributed_to(kind: str, detail: str,
                  user_id: Optional[str] = None) -> Iterator[None]:
    """Marca todo lo que se llame dentro como disparado por ``kind``/``detail``.

    Es un ``contextvar``, no una global: el prewarm calienta reportes en paralelo con
    ``asyncio.gather`` y una global les mezclaría la atribución entre corrutinas.
    """
    token = _CALLER.set(Caller(kind=kind, detail=detail, user_id=user_id))
    try:
        yield
    finally:
        _CALLER.reset(token)


def current_caller() -> Caller:
    return _CALLER.get() or Caller(kind=TRIGGER_UNKNOWN, detail=TRIGGER_UNKNOWN)


def record_call(
    *,
    purpose: str,
    model: str,
    cost_usd: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    module: Optional[str] = None,
    template: Optional[str] = None,
    cache_hit: bool = False,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Guarda una llamada al modelo. Best-effort: nunca lanza.

    Abre su propia sesión corta. El motor de narrativa no recibe una sesión de base de
    datos —y no debe recibirla, porque tiene que seguir siendo probable sin ella—, así que
    la apertura vive acá y no en la ruta que genera.
    """
    try:
        from shared.database.session import SessionLocal
        from shared.observability.models import LLMCall

        caller = current_caller()
        db = SessionLocal()
        try:
            db.add(LLMCall(
                purpose=purpose,
                model=model,
                cost_usd=float(cost_usd or 0.0),
                tokens_in=int(tokens_in or 0),
                tokens_out=int(tokens_out or 0),
                module=module,
                template=template,
                cache_hit=bool(cache_hit),
                trigger_kind=caller.kind,
                trigger_detail=caller.detail,
                user_id=caller.user_id,
                detail=detail or None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — observabilidad jamás tumba la entrega
        logger.debug("No se pudo registrar la llamada al modelo", exc_info=True)


def account(
    response: Any,
    *,
    model: str,
    purpose: str,
    module: Optional[str] = None,
    template: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> float:
    """Contabiliza UNA respuesta del modelo: presupuesto diario + registro atribuido.

    **Existe porque separarlas ya falló.** De los quince sitios que llaman al modelo, solo
    seis contaban su gasto contra el techo diario: la visión —la llamada más cara de la
    plataforma— la extracción de PDF y las tres rutas del agente de investigación no
    entraban al contador. El techo de ``LLM_DAILY_BUDGET_USD`` no podía cortarlas nunca,
    gastaran lo que gastaran, porque para el contador no existían.

    Dos llamadas separadas en cada sitio es una invitación a que alguien ponga una y olvide
    la otra, que es exactamente lo que pasó. Acá van juntas o no van.

    Devuelve el costo estimado. Best-effort de punta a punta: jamás lanza.
    """
    try:
        from shared.llm.budget import record_usage

        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        cost = record_usage(model, tokens_in, tokens_out)
        record_call(purpose=purpose, model=model, cost_usd=cost,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                    module=module, template=template, detail=detail)
        return cost
    except Exception:  # noqa: BLE001 — la contabilidad jamás rompe la llamada
        logger.debug("No se pudo contabilizar la llamada al modelo", exc_info=True)
        return 0.0
