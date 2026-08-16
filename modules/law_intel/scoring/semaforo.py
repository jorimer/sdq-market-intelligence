"""Meta contra dato real, sin el eufemismo.

**Por qué el vocabulario importa acá más que en otros motores.** El informe de avance oficial
define «avance moderado» como *«la trayectoria indica que NO se alcanzará la meta»* — y
después agrupa esa categoría bajo lenguaje de progreso. El producto existe para no hacer eso:
si la trayectoria no llega, el veredicto se llama `no_alcanzara` y no admite lectura amable.

**Un veredicto de trayectoria exige DOS observaciones.** Con una sola se puede decir a qué
distancia está del objetivo, nunca hacia dónde va. Emitir tendencia desde un punto es
inventar una pendiente, y es exactamente el error que vuelve refutable un informe entero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from modules.law_intel.bindings import Binding, aplicar_transformacion, direccion_de_metas
from modules.law_intel.registro import Indicador

# Un veredicto por indicador. `no_evaluable` no es una falla: es la respuesta correcta cuando
# la ley fija la meta en una escala que no se resta.
VEREDICTOS = {
    "alcanzada": "el dato cumple la meta del período",
    "no_alcanzada": "el dato no cumple la meta del período",
    "en_trayectoria": "con dos o más observaciones, la pendiente llega antes del corte",
    "no_alcanzara": "con dos o más observaciones, la pendiente NO llega",
    "retrocede": "el indicador se aleja de la meta",
    "sin_dato": "hay binding pero no hay observación utilizable",
    "sin_medicion": "no hay binding verificado que mida este indicador",
    "no_evaluable": "la meta no está en una escala que admita diferencia",
}

Observacion = Tuple[str, float]     # (período, valor)


@dataclass(frozen=True)
class Veredicto:
    indicador: str
    veredicto: str
    meta_periodo: Optional[str] = None
    meta: Optional[float] = None
    observado: Optional[float] = None
    periodo_observado: Optional[str] = None
    distancia: Optional[float] = None
    trayectoria: Optional[str] = None
    motivo: Optional[str] = None

    @property
    def cumple(self) -> Optional[bool]:
        if self.veredicto in ("alcanzada", "en_trayectoria"):
            return True
        if self.veredicto in ("no_alcanzada", "no_alcanzara", "retrocede"):
            return False
        return None


def _meta_vigente(ind: Indicador, corte: str) -> Tuple[Optional[str], Optional[float]]:
    """La meta que ya venció al corte dado. Es contra ella que se juzga.

    Comparar el dato de hoy contra la meta de 2030 diría que casi todo está incumplido y no
    informa nada: la ley fija cortes quinquenales y cada uno se juzga cuando le toca.
    """
    vencidas = [(a, v) for a, v in sorted(ind.metas.items())
                if a <= corte and isinstance(v, (int, float))]
    return vencidas[-1] if vencidas else (None, None)


def evaluar(ind: Indicador, binding: Optional[Binding],
            observaciones: Sequence[Observacion], corte: str) -> Veredicto:
    """Veredicto de un indicador al corte dado.

    `observaciones` va ordenada por período. Se exige el binding —y verificado— porque un
    dato sin binding declarado es una serie que alguien supuso que medía el indicador.
    """
    if not ind.admite_delta:
        return Veredicto(ind.id, "no_evaluable",
                         motivo=f"la meta es de escala '{ind.escala}': se cumple o no, no se resta")
    if binding is None or not binding.cuenta:
        estado = binding.estado if binding else "sin binding"
        return Veredicto(ind.id, "sin_medicion",
                         motivo=f"binding en estado '{estado}'; no cuenta como medición")

    periodo_meta, meta = _meta_vigente(ind, corte)
    if meta is None:
        return Veredicto(ind.id, "no_evaluable",
                         motivo=f"ninguna meta de la ley vence al corte {corte}")
    obs = [o for o in observaciones if isinstance(o[1], (int, float))]
    if not obs:
        return Veredicto(ind.id, "sin_dato", meta_periodo=periodo_meta, meta=meta,
                         motivo="el binding está verificado y la serie no devolvió valor")

    p_obs, valor = obs[-1]
    mejor_menor = binding.mejor == "menor"
    cumple = valor <= meta if mejor_menor else valor >= meta
    # La distancia se firma SIEMPRE hacia «cuánto falta»: positiva es déficit, negativa es
    # holgura. Sin esa convención, el signo se lee al revés en la mitad de los indicadores.
    distancia = round((valor - meta) if mejor_menor else (meta - valor), 4)

    if len(obs) < 2:
        return Veredicto(ind.id, "alcanzada" if cumple else "no_alcanzada",
                         meta_periodo=periodo_meta, meta=meta, observado=valor,
                         periodo_observado=p_obs, distancia=distancia, trayectoria=None,
                         motivo=("una sola observación: se puede decir la distancia a la meta, "
                                 "no la trayectoria"))

    (p0, v0), (p1, v1) = obs[-2], obs[-1]
    avance = (v0 - v1) if mejor_menor else (v1 - v0)
    if cumple:
        return Veredicto(ind.id, "alcanzada", meta_periodo=periodo_meta, meta=meta,
                         observado=valor, periodo_observado=p_obs, distancia=distancia,
                         trayectoria="mejora" if avance > 0 else "se aleja")
    if avance <= 0:
        return Veredicto(ind.id, "retrocede", meta_periodo=periodo_meta, meta=meta,
                         observado=valor, periodo_observado=p_obs, distancia=distancia,
                         trayectoria="se aleja",
                         motivo="el indicador se mueve en contra de la meta")
    # Hay avance: ¿alcanza el ritmo para el próximo corte que la ley fija?
    siguiente = next((a for a in sorted(ind.metas) if a > (periodo_meta or "")), None)
    falta = abs(distancia)
    return Veredicto(
        ind.id, "no_alcanzara", meta_periodo=periodo_meta, meta=meta, observado=valor,
        periodo_observado=p_obs, distancia=distancia, trayectoria="mejora",
        motivo=(f"avanza {avance:.4g} por período y le faltan {falta:.4g} para la meta de "
                f"{periodo_meta}" + (f"; el próximo corte es {siguiente}" if siguiente else "")))


def panel(indicadores: Sequence[Indicador], bindings: Dict[str, Binding],
          series: Dict[str, Sequence[Observacion]], corte: str) -> List[Veredicto]:
    """La transformación se aplica POR BINDING, no por serie.

    Dos indicadores pueden compartir la misma variable con transformaciones distintas —
    alfabetización cruda para uno y su complemento para otro—, así que un diccionario
    indexado por serie no puede llevarla. Pertenece al binding porque es una propiedad de la
    relación entre la variable y ESE indicador.
    """
    out: List[Veredicto] = []
    for i in indicadores:
        b = bindings.get(i.id)
        crudas = series.get(b.serie, ()) if b else ()
        obs = [(p, aplicar_transformacion(b, v)) for p, v in crudas] if b else []
        out.append(evaluar(i, b, obs, corte))
    return out


def resumen(veredictos: Sequence[Veredicto]) -> Dict[str, object]:
    """Conteo por veredicto, con el universo evaluado separado del total.

    Un porcentaje de cumplimiento sobre el total de la ley mezcla «no cumple» con «no lo
    medimos», que es la confusión que vuelve inútil la cifra. Se publican los dos
    denominadores y ninguna cifra derivada elige en silencio.
    """
    conteo: Dict[str, int] = {}
    for v in veredictos:
        conteo[v.veredicto] = conteo.get(v.veredicto, 0) + 1
    evaluados = [v for v in veredictos if v.cumple is not None]
    return {
        "total": len(veredictos),
        "evaluados": len(evaluados),
        "cumplen": sum(1 for v in evaluados if v.cumple),
        "pct_sobre_evaluados": (round(100.0 * sum(1 for v in evaluados if v.cumple)
                                      / len(evaluados), 1) if evaluados else None),
        "por_veredicto": dict(sorted(conteo.items())),
        "nota": ("El porcentaje se computa sobre los EVALUADOS, no sobre el total de la ley: "
                 "«no cumple» y «no lo medimos» son cosas distintas."),
    }


def direccion_declarada_coincide(ind: Indicador, binding: Binding) -> bool:
    """Se reexpone acá porque el veredicto entero depende de esto y conviene poder afirmarlo
    en el informe, no solo hacerlo cumplir al cargar."""
    computada = direccion_de_metas(ind)
    return computada not in ("menor", "mayor") or computada == binding.mejor
