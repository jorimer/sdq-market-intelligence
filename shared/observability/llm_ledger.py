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
disparó ``market-brief`` y no una persona. Por eso hay un contexto explícito que
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
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger("sdq.observability.llm_ledger")

#: Motivos por los que se llama al modelo. Sirve para separar el gasto de PRODUCIR de
#: el gasto de VERIFICAR, que hoy es la mitad del total y nadie lo veía por separado.
PURPOSE_NARRATIVE = "narrativa"
PURPOSE_GUARD = "guard_numerico"
PURPOSE_VISION = "vision"
PURPOSE_DIGEST = "digest"
PURPOSE_EXTRACTION = "extraccion"
#: Clasificación previa a producir: ruteo de dominios, pertinencia de entidad, relevancia de
#: un pasaje. Son llamadas baratas y MUCHAS —una por pregunta y por sub-pregunta—, así que
#: sumadas al motivo «otro» su peso queda invisible justo cuando lo que se quiere saber es
#: cuánto cuesta operar el motor de research por corrida.
PURPOSE_ROUTING = "ruteo"
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


@dataclass
class Cuenta:
    """Lo que costó un tramo de trabajo, con lo que NO se pudo convertir declarado al lado.

    **Por qué no es un float.** ``estimate_cost`` cae a la tarifa Sonnet para un modelo fuera
    de la tabla de precios, y esa caída devuelve un número con la misma cara que una medición.
    Un total que la absorbe en silencio es una suposición vestida de cifra. Acá el importe y
    lo no convertido viajan juntos: ``costo_es_exacto`` es False en cuanto una sola llamada
    salió de una tarifa supuesta, y quien publique el número tiene que decirlo.

    ``hits_de_cache`` va aparte porque un tramo servido desde caché cuesta cero DE VERDAD, y
    eso no es lo mismo que un cero por no haber medido.
    """

    costo_usd: float = 0.0
    llamadas: int = 0
    llamadas_sin_tarifa: int = 0
    hits_de_cache: int = 0

    @property
    def costo_es_exacto(self) -> bool:
        return self.llamadas_sin_tarifa == 0

    def _sumar(self, *, costo: float, sin_tarifa: bool, hit: bool) -> None:
        self.costo_usd += float(costo or 0.0)
        self.llamadas += 1
        if sin_tarifa:
            self.llamadas_sin_tarifa += 1
        if hit:
            self.hits_de_cache += 1


#: Cuentas abiertas en este contexto. Es una TUPLA y no una lista mutable global para que
#: anidar dos tramos no se pisen y para que una corrutina hija herede las de su padre: un
#: ``asyncio.gather`` copia el contexto, así que las llamadas de cada rama suman a los mismos
#: objetos ``Cuenta`` sin que las ramas se vean entre sí.
_CUENTAS: contextvars.ContextVar[Tuple["Cuenta", ...]] = contextvars.ContextVar(
    "sdq_llm_cuentas", default=(),
)
_CUENTAS_LOCK = threading.Lock()


@contextmanager
def contar_llamadas() -> Iterator[Cuenta]:
    """Cuenta lo que se le gasta al modelo DENTRO del bloque, sin consultar la base.

    Existe porque medir el costo de un tramo consultando ``llm_calls`` por ventana de tiempo
    obliga a inventar un criterio de corte, y dos corridas simultáneas se contaminarían. Acá
    la atribución es exacta por construcción: solo suma lo que pasó por este contexto.
    """
    cuenta = Cuenta()
    token = _CUENTAS.set(_CUENTAS.get() + (cuenta,))
    try:
        yield cuenta
    finally:
        _CUENTAS.reset(token)


def _anotar_en_las_cuentas(*, model: str, cost_usd: float, cache_hit: bool) -> None:
    """Suma la llamada a los tramos abiertos. Best-effort y aparte del guardado en base:
    que falle Postgres no debe borrar lo que sí sabemos que se gastó en este proceso."""
    cuentas = _CUENTAS.get()
    if not cuentas:
        return
    try:
        from shared.llm.budget import modelo_tarifado

        sin_tarifa = not cache_hit and not modelo_tarifado(model)
        with _CUENTAS_LOCK:
            for c in cuentas:
                c._sumar(costo=cost_usd, sin_tarifa=sin_tarifa, hit=cache_hit)
    except Exception:  # noqa: BLE001 — la contabilidad jamás rompe la llamada
        logger.debug("No se pudo anotar la llamada en las cuentas abiertas", exc_info=True)


@contextmanager
def attributed_to(kind: str, detail: str,
                  user_id: Optional[str] = None) -> Iterator[None]:
    """Marca todo lo que se llame dentro como disparado por ``kind``/``detail``.

    Es un ``contextvar``, no una global: una operación que genera en paralelo con
    ``asyncio.gather`` mezclaría la atribución entre corrutinas si fuera una global.
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
    _anotar_en_las_cuentas(model=model, cost_usd=float(cost_usd or 0.0),
                           cache_hit=bool(cache_hit))
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
