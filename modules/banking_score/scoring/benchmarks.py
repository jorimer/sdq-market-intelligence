"""Benchmarks MEDIDOS del panel, del MISMO período del informe.

Por qué existe. Los "promedios del sistema" que citaban los informes salían de
``DEFAULT_BENCHMARKS`` — constantes declaradas en código. El cliente del SIB se construyó
con tres niveles (caché → JSON local → constantes), pero nadie llena los dos primeros: el
respaldo de emergencia quedó como el único camino, y el sistema dejó de distinguir "no pude
traerlo" de "esto es el dato".

Pero el defecto grave no era que estuvieran desactualizadas, sino que son ANUALES y se
comparaban contra cortes TRIMESTRALES. Verificado en prod: BPD al Q1-2026 tiene ROE 10.2%;
contra la constante anual de banca grande (20.1%) el informe concluía "rezago material en
rentabilidad" (−9.9 pp), cuando contra la mediana Q1 de su propio grupo (3.85%) BPD es el
**más rentable de los 16** (+6.35 pp). La misma cifra, dos bases, conclusiones opuestas.

De ahí las dos reglas de este módulo:

1. **Mismo corte a ambos lados.** El benchmark se computa en el período del informe. Si hay
   estacionalidad —el ROE de TODO el panel cae en Q1— se cancela al comparar Q1 contra Q1, y
   además queda VISIBLE en la mediana del grupo en vez de esconderse. No se suprime dato por
   ser desfavorable: se lo mide bien.
2. **Mediana, no media.** El panel tiene extremos reales (una sucursal extranjera con ROE
   40%+, entidades en pérdida): la media los deja mandar. La mediana describe al par típico.

Nunca fabrica: un indicador con menos de ``MIN_N`` observaciones se omite, y sin panel se
devuelven las constantes DECLARADAS con la procedencia marcada para que el informe pueda
decir que son referencia declarada, no medida.
"""
from __future__ import annotations

import logging
import statistics as st
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult
from shared.data.sib_client import DEFAULT_BENCHMARKS, INDICATOR_TO_BENCHMARK

logger = logging.getLogger("sdq.banking.benchmarks")

# Mínimo de observaciones para publicar un promedio. Por debajo, el "promedio" describe al
# puñado que reportó, no al grupo — y un benchmark que no representa es peor que ninguno.
MIN_N = 5

# UNIVERSO canónico de "Sistema Bancario" (decisión del dueño, 2026-08-06): las
# instituciones de CRÉDITO supervisadas. Quedan fuera los agentes de cambio y las
# fiduciarias — no captan depósitos ni tienen libro de crédito, así que no pertenecen al
# agregado que un comité entiende por "el sistema".
#
# Importa: al computar los promedios sobre las 89 supervisadas, dos corridas del mismo
# período mostraban eficiencia 52% y 77,85% sin que nada del cálculo hubiera cambiado —
# cambió la población. El detalle que el dato obligó a matizar: los agentes de cambio (47%
# del padrón) NO reportan métricas de cartera, así que solo movían ROE/ROA; el salto de
# eficiencia venía de las instituciones de crédito pequeñas (AAyP, ahorro y crédito,
# corporaciones), que operan con costos estructuralmente más altos por su menor escala.
# Por eso el universo se DECLARA en el informe: no basta con elegirlo bien.
SISTEMA_TIPOS = frozenset({
    "banca_multiple", "aap", "banco_ahorro_credito", "corporacion_credito",
})
SISTEMA_LABEL = "instituciones de crédito supervisadas por la SIB"

# Tipo de entidad → etiqueta legible del grupo de pares. Reemplaza a las listas de nombres
# fijas de las constantes ("BPD, BHD León, Popular, Reservas"), que envejecen con cada
# fusión: el grupo se deriva del catálogo.
PEER_GROUP_LABELS: Dict[str, str] = {
    "banca_multiple": "bancos múltiples",
    "aap": "asociaciones de ahorros y préstamos",
    "banco_ahorro_credito": "bancos de ahorro y crédito",
    "corporacion_credito": "corporaciones de crédito",
    "cambiaria": "agentes de cambio",
    "fiduciaria": "fiduciarias",
}


def _raw_values(rows: List[Dict[str, Any]], indicador: str) -> List[float]:
    out: List[float] = []
    for r in rows:
        blob = (r.get("ind") or {}).get(indicador)
        if not isinstance(blob, dict) or not blob.get("available", True):
            continue
        v = blob.get("raw")
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _medians(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """``{clave_benchmark: mediana}`` de los indicadores con suficientes observaciones."""
    out: Dict[str, float] = {}
    for indicador, bkey in INDICATOR_TO_BENCHMARK.items():
        vals = _raw_values(rows, indicador)
        if len(vals) >= MIN_N:
            out[bkey] = round(st.median(vals), 2)
    return out


def panel_benchmarks(db: Session, period_end: Optional[date],
                     excluir_bank_id: Optional[str] = None) -> Dict[str, Any]:
    """Promedios del sistema y de los grupos de pares MEDIDOS en *period_end*.

    **`excluir_bank_id` saca a la entidad evaluada de su propia referencia.** Sin eso, un
    banco se compara en parte CONTRA SÍ MISMO: su observación entra en la mediana que debía
    juzgarlo y la arrastra hacia él, de modo que su brecha sale sistemáticamente encogida. El
    sesgo va SIEMPRE en la misma dirección —hacia «no está tan lejos del grupo»—, que es lo
    que lo vuelve un defecto y no ruido.

    Medido sobre los dieciséis bancos múltiples de producción: la mediana de ROE pasa de
    12,653 con la entidad a 13,229 sin ella, y la de cost-to-income de 53,611 a 54,462. Es
    menor que en el mapa sectorial —donde el promedio ponderado por deuda daba 3,3 puntos
    sobre una brecha de 10— porque una mediana sobre dieciséis se mueve poco al quitar una
    observación. Pequeño no es cero, y la dirección es la misma.

    Se declara en `procedencia` para que la narrativa pueda decir contra qué se comparó.

    Mantiene la forma que consumen los informes (``sector_averages``, ``peer_groups`` con
    claves ``{indicador}_avg``, ``regulatory_limits``) y añade ``procedencia`` para que la
    narrativa pueda declarar si la referencia fue medida o declarada.

    Los ``regulatory_limits`` siguen siendo constantes a propósito: son mínimos normativos
    declarados por el regulador, no un promedio observable.
    """
    declarados = {
        "sector_averages": dict(DEFAULT_BENCHMARKS["sector_averages"]),
        "peer_groups": {k: dict(v) for k, v in DEFAULT_BENCHMARKS["peer_groups"].items()},
        "regulatory_limits": dict(DEFAULT_BENCHMARKS["regulatory_limits"]),
        "procedencia": {
            "medido": False,
            "nota": ("Referencia DECLARADA (constantes de configuración), no medida del "
                     "panel: no hay dato suficiente en el período."),
        },
    }
    if period_end is None:
        return declarados

    try:
        rows = [
            {"tipo": (b.bank_type.value if b.bank_type else ""), "ind": rr.indicator_details}
            for rr, b in (db.query(RatingResult, Bank)
                          .join(Bank, Bank.id == RatingResult.bank_id)
                          .filter(RatingResult.period_end == period_end,
                                  RatingResult.model_type == ModelType.deterministic)
                          .all())
            if excluir_bank_id is None or str(rr.bank_id) != str(excluir_bank_id)
        ]
    except Exception as e:  # noqa: BLE001 — el informe nunca se cae por el benchmark
        logger.warning("Panel de benchmarks no disponible (%s): se declaran constantes.", e)
        return declarados

    # El agregado del SISTEMA se computa SOLO sobre instituciones de crédito; los grupos de
    # pares siguen cubriendo todos los tipos, para que cualquier entidad encuentre el suyo.
    del_sistema = [r for r in rows if r["tipo"] in SISTEMA_TIPOS]
    sector = _medians(del_sistema)
    if not sector:
        logger.info("Sin observaciones suficientes en %s: benchmarks declarados.", period_end)
        return declarados

    grupos: Dict[str, Dict[str, Any]] = {}
    for tipo in {r["tipo"] for r in rows if r["tipo"]}:
        del_tipo = [r for r in rows if r["tipo"] == tipo]
        med = _medians(del_tipo)
        if not med:
            continue
        grupos[tipo] = {f"{k}_avg": v for k, v in med.items()}
        grupos[tipo]["label"] = PEER_GROUP_LABELS.get(tipo, tipo)
        grupos[tipo]["n"] = len(del_tipo)

    return {
        "sector_averages": sector,
        "peer_groups": grupos,
        # Mínimos normativos: declarados por el regulador, no observables del panel.
        "regulatory_limits": dict(DEFAULT_BENCHMARKS["regulatory_limits"]),
        "procedencia": {
            "medido": True,
            "period": str(period_end),
            # Contra QUÉ se comparó. Sin este campo, la narrativa no puede distinguir una
            # referencia que excluye al sujeto de una que lo incluye, y son cosas distintas.
            "excluye_a_la_entidad_evaluada": excluir_bank_id is not None,
            "n_sistema": len(del_sistema),
            "n_supervisadas": len(rows),
            "universo": SISTEMA_LABEL,
            "composicion": {t: sum(1 for r in del_sistema if r["tipo"] == t)
                            for t in sorted({r["tipo"] for r in del_sistema})},
            "estadistico": "mediana",
            "nota": (f"Promedios MEDIDOS al {period_end} sobre {len(del_sistema)} "
                     f"{SISTEMA_LABEL} (mediana). El universo se declara porque dos "
                     "poblaciones distintas producen cifras distintas para el mismo período: "
                     "quedan fuera los agentes de cambio y las fiduciarias, que no tienen "
                     "libro de crédito. Comparan el MISMO corte que el informe, así que la "
                     "estacionalidad se cancela a ambos lados. Los límites regulatorios son "
                     "mínimos normativos declarados."),
        },
    }
