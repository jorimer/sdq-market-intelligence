"""Presupuesto diario de gasto LLM con corte SUAVE.

El DD marcó como brecha que el gasto en Claude no tiene techo: un bucle de generación
o un pico de research pueden quemar presupuesto sin que nadie lo vea. Este módulo
da (a) contabilidad central — cada llamada al API registra tokens y costo estimado —
y (b) un techo diario configurable EN CALIENTE desde Configuración (solo admin), con
``LLM_DAILY_BUDGET_USD`` como valor de arranque cuando nadie lo fijó (0 = deshabilitado).

Corte SUAVE, no duro: al superar el techo NADA lanza excepción ni devuelve 500.
Cada consumidor degrada a su fallback ya existente (narrativa → caché/estático,
router → contexto curado, juez LLM → capa determinista) y se loguea un warning
por hora para el operador. El servicio sigue respondiendo siempre.

El contador vive en Redis (compartido entre workers, clave por día UTC, TTL 48h)
con fallback in-memory por proceso cuando Redis no está — en ese caso el techo se
aplica por-worker (menos exacto, pero el orden de magnitud se conserva).

Precios (USD por millón de tokens, 2026-07): tabla local editable. Un modelo fuera
de la tabla usa la tarifa Sonnet (conservador). El costo es ESTIMADO — sirve para
el techo operativo, no para facturación.
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

from shared.cache import cache_get, cache_incr_float
from shared.config.settings import settings

logger = logging.getLogger("sdq.llm.budget")

# USD por 1M de tokens (input, output). Fuente: tarifario Anthropic vigente.
PRICING_PER_MTOK: Dict[str, Tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-6": (5.0, 25.0),
}
_DEFAULT_PRICING = (3.0, 15.0)  # tarifa Sonnet para modelos no listados

_SPEND_KEY_PREFIX = "llm:spend:"
_SPEND_TTL_SECONDS = 48 * 3600

# Fallback in-memory (por proceso) cuando Redis no está.
_mem_lock = threading.Lock()
_mem_day = ""
_mem_spent = 0.0

# Anti-spam: un warning de presupuesto excedido por hora, no por request.
_last_over_budget_log = 0.0

# Techo vigente, memorizado unos segundos. `budget_allows()` corre ANTES de cada llamada al
# modelo: sin memo, cada generación abriría una conexión a Postgres solo para releer un
# número que cambia una vez al mes. El TTL es corto porque el momento en que se baja el techo
# es el momento en que el gasto ya está corriendo; y un guardado desde Configuración invalida
# el memo de una (`invalidate_limit_cache`), así que el TTL solo cubre a los OTROS workers.
_LIMIT_TTL_SECONDS = 30
_limit_lock = threading.Lock()
_limit_value: float = 0.0
_limit_expires_at: float = 0.0


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICING_PER_MTOK.get(model, _DEFAULT_PRICING)
    return (input_tokens * inp / 1_000_000) + (output_tokens * out / 1_000_000)


def record_usage(model: str, input_tokens: int, output_tokens: int) -> float:
    """Registra el gasto de UNA llamada al API y devuelve su costo estimado.

    Best-effort: nunca lanza. Se llama desde todos los puntos que consumen el API
    (generación de narrativa, router semántico, juez del guardrail)."""
    global _mem_day, _mem_spent
    cost = estimate_cost(model, input_tokens, output_tokens)
    try:
        day = _today()
        total = cache_incr_float(_SPEND_KEY_PREFIX + day, cost, _SPEND_TTL_SECONDS)
        if total is None:  # sin Redis → contador por worker
            with _mem_lock:
                if _mem_day != day:
                    _mem_day, _mem_spent = day, 0.0
                _mem_spent += cost
                total = _mem_spent
        logger.info(
            "LLM usage: model=%s in=%d out=%d cost=$%.4f day_total=$%.2f",
            model, input_tokens, output_tokens, cost, total,
        )
    except Exception as e:  # noqa: BLE001 — la contabilidad jamás rompe la llamada
        logger.warning("record_usage falló (se ignora): %s", e)
    return cost


def spent_today() -> float:
    """Gasto acumulado del día (Redis si hay; si no, el contador del worker)."""
    day = _today()
    raw = cache_get(_SPEND_KEY_PREFIX + day)
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    with _mem_lock:
        return _mem_spent if _mem_day == day else 0.0


def invalidate_limit_cache() -> None:
    """Olvida el techo memorizado: la próxima consulta lo relee de Configuración."""
    global _limit_expires_at
    with _limit_lock:
        _limit_expires_at = 0.0


def current_limit() -> float:
    """Techo diario vigente en USD (0 = sin techo).

    Manda lo que el admin fijó en Configuración; si no fijó nada, el valor de entorno
    ``LLM_DAILY_BUDGET_USD``. Si la base no responde, se usa el del entorno — NUNCA 0:
    quedarse sin techo porque falló una consulta es el peor momento para no tenerlo.
    """
    global _limit_value, _limit_expires_at
    ahora = time.time()
    with _limit_lock:
        if ahora < _limit_expires_at:
            return _limit_value
    del_entorno = float(getattr(settings, "LLM_DAILY_BUDGET_USD", 0.0) or 0.0)
    try:
        from shared.database.session import SessionLocal
        from shared.settings.service import get_llm_daily_budget
        db = SessionLocal()
        try:
            valor = get_llm_daily_budget(db)
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — sin base (tests, arranque, corte) manda el entorno
        logger.debug("Techo LLM no legible desde Configuración; se usa el del entorno.",
                     exc_info=True)
        valor = del_entorno
    with _limit_lock:
        _limit_value = valor
        _limit_expires_at = ahora + _LIMIT_TTL_SECONDS
    return valor


def budget_allows() -> bool:
    """¿Hay presupuesto para una llamada LLM nueva? (corte suave: el caller degrada).

    True si no hay techo vigente (<= 0, ver ``current_limit``) o si el gasto del día
    está por debajo del techo."""
    global _last_over_budget_log
    limit = current_limit()
    if limit <= 0:
        return True
    spent = spent_today()
    if spent < limit:
        return True
    now = time.time()
    if now - _last_over_budget_log > 3600:
        _last_over_budget_log = now
        logger.warning(
            "Presupuesto LLM diario EXCEDIDO: gastado=$%.2f techo=$%.2f — corte suave "
            "activo (narrativa→caché/estático, router→contexto curado, juez→determinista).",
            spent, limit,
        )
    return False
