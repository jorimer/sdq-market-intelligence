"""¿El proceso que se reporta cumplido movió el resultado? (oráculo de incoherencia).

**Por qué existe.** Un pacto, un plan o una estrategia se mide por ACTIVIDAD: compromisos
concluidos, reuniones celebradas, documentos firmados. El indicador mide RESULTADO. Cada
lectura por separado es defendible, y por eso un sistema que solo mide actividad puede
reportar éxito indefinidamente mientras el indicador se deteriora.

El caso que lo motiva está en el expediente: el Pacto Eléctrico reporta 148 de 167
compromisos concluidos o en ejecución —88,6% de cumplimiento formal— y las pérdidas del
sector están donde estaban en 2008. Las dos afirmaciones son ciertas y juntas dicen algo que
ninguna dice sola.

**Qué NO es.** No es una medición del desempeño ni ajusta ningún veredicto. Dice «estas dos
lecturas no pueden ser ambas satisfactorias» y deja la explicación al analista. Y no marca lo
que no corresponde: un instrumento con bajo cumplimiento de proceso y mal resultado no es una
incoherencia — es simplemente algo que no se ejecutó, que es un hallazgo distinto y más
sencillo. Un oráculo que marcara los dos no discriminaría nada.

Es el mismo patrón que `insurance_intel.scoring.coherencia_resultado`, que cruza el combined
ratio contra el estado de resultados de la misma acta. Allí probó que discrimina: marcó tres
compañías con razón estructural y no marcó las que tenían deterioro real.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from modules.law_intel.registro import Indicador

# Cumplimiento de proceso por encima del cual el instrumento AFIRMA haberse ejecutado. Se
# elige alto a propósito: por debajo, el mal resultado se explica sin drama porque el
# instrumento no se ejecutó, y marcar ahí sería ruido.
CUMPLIMIENTO_ALTO = 0.75

# Fracción de la brecha (línea base → meta) que el resultado debe haber cerrado para
# considerarse en movimiento. Cero sería el corte natural, pero una oscilación mínima no es
# avance: se exige que el instrumento haya movido algo reconocible.
AVANCE_MINIMO = 0.10

VEREDICTOS = {
    "contradiccion": "alto cumplimiento de proceso con el resultado sin moverse",
    "coherente": "el proceso y el resultado apuntan en el mismo sentido",
    "no_ejecutado": "bajo cumplimiento de proceso; el mal resultado no es una incoherencia",
    "no_evaluable": "falta una de las dos mitades del cruce",
    # Cero compromisos no es un cumplimiento bajo: es que el instrumento nunca existió. El
    # Pacto Fiscal jamás se convocó, y llamarlo «no ejecutado» sugiere que hubo algo que
    # ejecutar. El hallazgo es la ausencia del instrumento, no una incoherencia entre dos
    # lecturas — porque hay una sola.
    "instrumento_ausente": "el instrumento nunca se constituyó: no hay proceso que cruzar",
}


@dataclass(frozen=True)
class Hallazgo:
    instrumento: str
    indicador: str
    veredicto: str
    cumplimiento_proceso: Optional[float] = None
    base: Optional[float] = None
    meta: Optional[float] = None
    observado: Optional[float] = None
    brecha_cerrada: Optional[float] = None
    motivo: Optional[str] = None

    def frase(self) -> str:
        if self.veredicto != "contradiccion":
            return VEREDICTOS[self.veredicto] + (f" — {self.motivo}." if self.motivo else ".")
        # Una brecha «cerrada» negativa significa que el indicador se ALEJÓ de la meta.
        # Decirlo como «cerró −241,6%» es aritméticamente cierto e ilegible.
        cerrada = self.brecha_cerrada or 0.0
        movimiento = (f"cerró {cerrada:.1%} de la brecha" if cerrada >= 0 else
                      f"se ALEJÓ de la meta, hasta {abs(cerrada):.1%} de la brecha original "
                      f"en sentido contrario")
        return (f"El instrumento reporta {self.cumplimiento_proceso:.1%} de compromisos "
                f"cumplidos y el indicador {self.indicador} {movimiento} entre su línea base "
                f"({self.base:g}) y su meta ({self.meta:g}). Alto cumplimiento de proceso con "
                f"fracaso de resultado: las dos lecturas no pueden ser ambas satisfactorias.")


def _fraccion_cerrada(base: float, meta: float, observado: float) -> Optional[float]:
    """Qué parte del camino de la línea base a la meta recorrió el indicador.

    Se computa sobre la brecha y no sobre el valor absoluto porque un punto porcentual
    significa cosas distintas según cuánto había que recorrer: mover las pérdidas eléctricas
    0,1 puntos cuando faltaban 30,4 no es lo mismo que moverlas 0,1 cuando faltaba medio.
    """
    recorrido_total = meta - base
    if recorrido_total == 0:
        return None                       # meta plana: sostener no se mide como avance
    return (observado - base) / recorrido_total


def evaluar(instrumento_id: str, cumplimiento: Optional[float], ind: Indicador,
            observado: Optional[float], corte: str, total_compromisos: Optional[int] = None
            ) -> Hallazgo:
    if total_compromisos == 0:
        return Hallazgo(instrumento_id, ind.id, "instrumento_ausente",
                        motivo="cero compromisos registrados, nunca se convocó")
    if cumplimiento is None:
        return Hallazgo(instrumento_id, ind.id, "no_evaluable",
                        motivo="no hay conteo público de compromisos cumplidos")
    if observado is None or ind.base_valor is None or not ind.admite_delta:
        return Hallazgo(instrumento_id, ind.id, "no_evaluable", cumplimiento_proceso=cumplimiento,
                        motivo="el resultado no está medido en una escala que admita brecha")
    metas = [(a, v) for a, v in sorted(ind.metas.items())
             if a <= corte and isinstance(v, (int, float))]
    if not metas:
        return Hallazgo(instrumento_id, ind.id, "no_evaluable", cumplimiento_proceso=cumplimiento,
                        motivo=f"ninguna meta vence al corte {corte}")
    _, meta = metas[-1]
    base = float(ind.base_valor)
    cerrada = _fraccion_cerrada(base, float(meta), float(observado))
    if cerrada is None:
        return Hallazgo(instrumento_id, ind.id, "no_evaluable", cumplimiento_proceso=cumplimiento,
                        base=base, meta=float(meta), observado=observado,
                        motivo="la meta es plana: sostener no se mide como avance")

    # Se arma cada Hallazgo con sus argumentos nombrados en vez de desempaquetar un dict:
    # el `**comun` escondía los tipos y mypy no podía comprobar ninguno de los cinco campos.
    def _h(veredicto: str, motivo: Optional[str] = None) -> Hallazgo:
        return Hallazgo(instrumento_id, ind.id, veredicto, cumplimiento_proceso=cumplimiento,
                        base=base, meta=float(meta), observado=float(observado),
                        brecha_cerrada=cerrada, motivo=motivo)

    if cumplimiento < CUMPLIMIENTO_ALTO:
        return _h("no_ejecutado",
                  f"cumplimiento de proceso {cumplimiento:.1%}, por debajo del umbral; el "
                  f"resultado malo no necesita otra explicación")
    if cerrada >= AVANCE_MINIMO:
        return _h("coherente", f"la brecha se cerró {cerrada:.1%}")
    return _h("contradiccion")


def revisar(expediente_id: str, indicadores: Dict[str, Indicador],
            corte: str = "2025") -> List[Hallazgo]:
    """Cruza cada instrumento del expediente contra los resultados que debía mover."""
    out: List[Hallazgo] = []
    for inst in cargar_instrumentos(expediente_id):
        cp = inst.get("cumplimiento_de_proceso") or {}
        total = cp.get("total_compromisos")
        hechos = cp.get("concluidos_o_en_ejecucion")
        cumplimiento = (float(hechos) / float(total)) if (total and hechos is not None) else None
        obs = {o["indicador"]: o for o in (inst.get("observaciones_declaradas") or [])}
        for ind_id in inst.get("resultados_esperados") or []:
            ind = indicadores.get(ind_id)
            if ind is None:
                continue
            o = obs.get(ind_id)
            out.append(evaluar(inst["id"], cumplimiento, ind,
                               o.get("valor") if o else None, corte, total))
    return out


def cargar_instrumentos(expediente_id: str) -> List[Dict[str, Any]]:
    import yaml  # type: ignore[import-untyped]

    from modules.law_intel.registro import RAIZ
    ruta = RAIZ / expediente_id.replace("/", "") / "instrumentos_de_proceso.yaml"
    if not ruta.exists():
        return []
    return list((yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("instrumentos") or [])


def resumen(hallazgos: Sequence[Hallazgo]) -> Dict[str, Any]:
    por_veredicto: Dict[str, int] = {}
    for h in hallazgos:
        por_veredicto[h.veredicto] = por_veredicto.get(h.veredicto, 0) + 1
    return {
        "total": len(hallazgos),
        "por_veredicto": dict(sorted(por_veredicto.items())),
        "contradicciones": [{"instrumento": h.instrumento, "indicador": h.indicador,
                             "lectura": h.frase()}
                            for h in hallazgos if h.veredicto == "contradiccion"],
        "umbrales": {"cumplimiento_alto": CUMPLIMIENTO_ALTO, "avance_minimo": AVANCE_MINIMO},
        "nota": ("`no_ejecutado` no es una contradicción: un instrumento que no se ejecutó "
                 "explica su mal resultado sin necesidad de otra lectura."),
    }
