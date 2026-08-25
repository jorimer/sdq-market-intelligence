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

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.law_intel.bindings import Binding, aplicar_transformacion, direccion_de_metas
from modules.law_intel.registro import Indicador

#: Precisión publicada del valor observado y de su distancia a la meta. Cuatro decimales
#: sostienen cualquier unidad del expediente —tasas por mil incluidas— sin arrastrar el
#: residuo de una división.
_DECIMALES = 4

# Un veredicto por indicador. `no_evaluable` no es una falla: es la respuesta correcta cuando
# la ley fija la meta en una escala que no se resta.
VEREDICTOS = {
    "alcanzada": "el dato cumple la meta del período",
    "no_alcanzada": "el dato no cumple la meta del período",
    "en_trayectoria": "con dos o más observaciones, la pendiente llega antes del corte",
    "no_alcanzara": "con dos o más observaciones, la pendiente NO llega",
    "retrocede": "el indicador se aleja de la meta",
    "estancada": "el indicador no se mueve, y la meta que lo espera sí",
    "sin_dato": "hay binding pero no hay observación utilizable",
    "sin_medicion": "no hay binding verificado que mida este indicador",
    "medido_sin_certificar": ("hay serie y observación, y la distancia a la meta se computa; "
                              "lo que NO se certificó es que el nivel sea comparable con la "
                              "línea base que la ley fija"),
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
        if self.veredicto in ("no_alcanzada", "no_alcanzara", "retrocede", "estancada"):
            return False
        return None


def _meta_vigente(ind: Indicador, corte: str) -> Tuple[Optional[str], Any]:
    """La meta que ya venció al corte dado. Es contra ella que se juzga.

    Comparar el dato de hoy contra la meta de 2030 diría que casi todo está incumplido y no
    informa nada: la ley fija cortes quinquenales y cada uno se juzga cuando le toca.

    Para los indicadores de UMBRAL la meta es una cadena («< 4»), así que el filtro no puede
    exigir que sea numérica: exigirlo dejaba fuera justo a los que ahora sí se pueden juzgar,
    y el veredicto salía «ninguna meta vence al corte» sobre un indicador con cuatro metas
    escritas en la ley. Quién sabe leer cada forma es responsabilidad de quien juzga, no de
    quien selecciona el período.
    """
    # Las escalas cuya meta se escribe en TEXTO y aun así se puede leer: un umbral («< 4») y
    # un escalar rotulado («Matemáticas : 63.0»). Exigir que la meta fuera numérica dejaba
    # fuera justo a los indicadores que sí se juzgan, y el veredicto salía «ninguna meta vence
    # al corte» sobre uno con cuatro metas escritas en la ley.
    #
    # Quién sabe leer cada forma es responsabilidad de quien JUZGA, no de quien selecciona el
    # período: acá se admite la meta y más abajo se decide si es interpretable.
    admisible = (lambda v: v is not None) if ind.escala in ("umbral", "redactada") \
        else (lambda v: isinstance(v, (int, float)))
    vencidas = [(a, v) for a, v in sorted(ind.metas.items()) if a <= corte and admisible(v)]
    return vencidas[-1] if vencidas else (None, None)


def evaluar(ind: Indicador, binding: Optional[Binding],
            observaciones: Sequence[Observacion], corte: str) -> Veredicto:
    """Veredicto de un indicador al corte dado.

    `observaciones` va ordenada por período. Se exige el binding —y verificado— porque un
    dato sin binding declarado es una serie que alguien supuso que medía el indicador.
    """
    if not ind.admite_delta and ind.escala != "umbral":
        # Una meta REDACTADA puede ser un escalar rotulado —«Matemáticas : 63.0»— y esas sí se
        # juzgan. Se comprueba antes de rendirse; si no lo es, el veredicto no cambia.
        #
        # Y puede ser DIRECTAMENTE UN NÚMERO. La escala describe el CONJUNTO de metas del
        # indicador y el veredicto se emite contra UNA: el 2.36 tiene tres metas que son el
        # número 100 y una sola escrita en prosa —«100 al 2016»—, y esa celda bastaba para
        # que el motor se negara a juzgar las otras tres. La peor celda no decide por las
        # demás; quien juzga mira la meta que vence.
        if not (ind.escala == "redactada"
                and (_tiene_meta_rotulada(ind, corte)
                     or isinstance(_meta_vigente(ind, corte)[1], (int, float)))):
            return Veredicto(ind.id, "no_evaluable",
                             motivo=f"la meta es de escala '{ind.escala}': se cumple o no, "
                                    f"no se resta")
    if binding is None or not binding.cuenta:
        # Un binding que DECLARA por qué no certifica no es lo mismo que no medir. El 2.33
        # tiene dieciocho años de serie y el 3.30 seis: decir «no lo medimos» sobre ellos
        # regala el hallazgo — y el hallazgo es que la línea base de la LEY no reproduce
        # contra la serie de su propio Estado. Se publica la observación y la distancia, con
        # la salvedad al lado y sin contar como cumplimiento.
        motivo_declarado = getattr(binding, "sin_veredicto_por", None) if binding else None
        if motivo_declarado == "linea_base_no_reproduce":
            p_meta, m = _meta_vigente(ind, corte)
            obs_utiles = [o for o in observaciones if isinstance(o[1], (int, float))]
            if m is not None and isinstance(m, (int, float)) and obs_utiles:
                p_obs, valor = obs_utiles[-1]
                return Veredicto(
                    ind.id, "medido_sin_certificar", meta_periodo=p_meta, meta=m,
                    observado=round(float(valor), _DECIMALES), periodo_observado=p_obs,
                    distancia=round(float(valor) - float(m), _DECIMALES),
                    motivo=("la serie mide el indicador con el término de la ley y no "
                            "reproduce su línea base; la distancia a la meta se publica con "
                            "esa salvedad y no cuenta como cumplimiento"))
        estado = binding.estado if binding else "sin binding"
        detalle = f"; motivo declarado: {motivo_declarado}" if motivo_declarado else ""
        return Veredicto(ind.id, "sin_medicion",
                         motivo=f"binding en estado '{estado}'; no cuenta como medición"
                                f"{detalle}")

    periodo_meta, meta = _meta_vigente(ind, corte)
    if meta is None:
        return Veredicto(ind.id, "no_evaluable",
                         motivo=f"ninguna meta de la ley vence al corte {corte}")
    obs = [o for o in observaciones if isinstance(o[1], (int, float))]
    if not obs:
        return Veredicto(ind.id, "sin_dato", meta_periodo=periodo_meta, meta=meta,
                         motivo="el binding está verificado y la serie no devolvió valor")

    p_obs, valor = obs[-1]
    if ind.escala == "umbral":
        return _veredicto_de_umbral(ind, meta, periodo_meta, valor, p_obs)
    # Una meta redactada que ES un número se juzga como número. Mandarla al lector de
    # escalares rotulados devolvería `no_evaluable` sobre un 100 perfectamente legible.
    if ind.escala == "redactada" and not isinstance(meta, (int, float)):
        return _veredicto_rotulado(ind, binding, meta, periodo_meta, valor, p_obs)
    # Se publica con la MISMA precisión que la distancia. El 2.44 salía como
    # `37.3684210526316`: trece decimales que son el residuo de una división (71 escaños
    # entre 190), no una medición. Esa cifra viaja al informe tal cual y la precisión
    # espuria desacredita al resto de la tabla, donde las metas tienen un decimal.
    valor = round(valor, _DECIMALES)
    mejor_menor = binding.mejor == "menor"
    cumple = valor <= meta if mejor_menor else valor >= meta
    # La distancia se firma SIEMPRE hacia «cuánto falta»: positiva es déficit, negativa es
    # holgura. Sin esa convención, el signo se lee al revés en la mitad de los indicadores.
    distancia = round((valor - meta) if mejor_menor else (meta - valor), _DECIMALES)

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
                         trayectoria=_trayectoria(avance))
    if avance == 0:
        # Estancarse NO es retroceder, y decir que sí es una falsedad COMPROBABLE: el
        # Senado lleva 12,5% desde 2020 y el motivo rezaba «el indicador se mueve en contra
        # de la meta» sobre una serie que no se mueve. El lector que verifica esa frase deja
        # de creerle al resto de la tabla.
        #
        # Tampoco es inocuo, y por eso no cuenta como cumplir: la meta sí avanza con los
        # años, así que quedarse quieto ensancha la brecha. Son dos diagnósticos distintos
        # que piden dos acciones distintas, y con una sola observación eran indistinguibles.
        return Veredicto(ind.id, "estancada", meta_periodo=periodo_meta, meta=meta,
                         observado=valor, periodo_observado=p_obs, distancia=distancia,
                         trayectoria="plana",
                         motivo=f"sin variación entre {p0} y {p1}; la meta no espera")
    if avance < 0:
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


#: Gramática CERRADA de un umbral: un operador y un número decimal simple. Deliberadamente
#: estrecha — cualquier otra cosa NO se interpreta, se declara `no_evaluable`.
#:
#: En particular NO se acepta el separador de miles: «>1,700» es ambiguo en notación española
#: (¿1700 o 1,7?) y resolverlo por plausibilidad —«1,7 no tiene sentido para inversión
#: extranjera»— es exactamente el tipo de inferencia que produce cifras inventadas. El único
#: indicador con esa forma (3.23) no está medido hoy, así que rechazarlo no cuesta nada y
#: adivinarlo costaría una cifra falsa el día que se mida.
#: Los DOS extremos de la tubería tienen que entender la misma notación, y no la entendían:
#: el clasificador del extractor reconoce `≥` (el glifo que trae el PDF) y este lector solo
#: entendía `>=`. Una meta podía quedar clasificada como umbral y después resultar ilegible
#: para quien la juzga — `no_evaluable` sobre una meta que la ley escribió con toda claridad.
#: Se admiten las dos formas de cada lado y se normalizan a una.
_UMBRAL = re.compile(r"^\s*(<=|>=|≤|≥|<|>)\s*(\d+(?:\.\d+)?)\s*%?\s*$")
_EQUIVALE = {"≤": "<=", "≥": ">="}


#: Gramática CERRADA de un escalar ROTULADO: «<sujeto> : <número>». Tan estrecha como la del
#: umbral y por la misma razón — cualquier otra cosa no se interpreta, se declara.
#:
#: El sujeto NO es ruido de formato: es el sujeto. La ley escribe «Matemáticas : 63.0» porque
#: el indicador 2.17 nombra TRES materias —lectura, matemáticas y ciencias— y solo le fija
#: meta a una. Quitar la etiqueta para dejar un 63.0 pelado borraría justamente el dato que
#: deja ver que se está juzgando una de tres, y violaría la regla que este repo hace cumplir
#: en todos lados: el sujeto viaja con el número.
#:
#: Por eso la etiqueta no se descarta al leer — viaja al veredicto.
_ROTULADO = re.compile(r"^\s*([^:\d][^:]*?)\s*:\s*(\d+(?:\.\d+)?)\s*$")


def leer_rotulado(meta: Any) -> Optional[Tuple[str, float]]:
    """`(sujeto, valor)` de una meta rotulada, o `None` si la forma no es reconocible.

    No es un parser de prosa: es un escalar con su sujeto pegado, que es como la ley escribe
    los indicadores multi-materia. «Pertenecer al nivel II» devuelve `None` y se sigue
    declarando `no_evaluable`, porque ahí sí hay que juzgar y no medir.
    """
    m = _ROTULADO.match(str(meta))
    return (m.group(1).strip(), float(m.group(2))) if m else None


def leer_umbral(meta: Any) -> Optional[Tuple[str, float]]:
    """`(operador, valor)` de una meta de umbral, o `None` si la forma no es reconocible.

    Devolver `None` es una respuesta legítima y frecuente: la ley escribe algunas metas en
    prosa («Se cumple con tiempos establecidos legalmente») y esas no se juzgan.
    """
    m = _UMBRAL.match(str(meta))
    if not m:
        return None
    op = m.group(1)
    return (_EQUIVALE.get(op, op), float(m.group(2)))


def _veredicto_de_umbral(ind: Indicador, meta: Any, periodo_meta: Optional[str],
                         valor: float, p_obs: str) -> Veredicto:
    """Una meta de umbral NO admite delta pero SÍ admite veredicto.

    Es la distinción que faltaba. «< 4%» no dice cuánto falta —no hay un objetivo puntual del
    que restar— pero sí dice si se cumple: 5,97 no es menor que 4. El motor conocía la
    semántica («se cumple o no, no se resta») y aun así devolvía `no_evaluable`, así que el
    informe callaba un incumplimiento que podía afirmar.

    `distancia` queda en `None` a propósito: publicar 1,97 sugeriría que la meta es 4 y que
    falta poco, cuando lo que la ley fijó es un techo.
    """
    leido = leer_umbral(meta)
    if leido is None:
        return Veredicto(ind.id, "no_evaluable", meta_periodo=periodo_meta, meta=meta,
                         observado=round(valor, _DECIMALES), periodo_observado=p_obs,
                         motivo=("la meta es un umbral escrito en una forma que no se "
                                 "interpreta; se declara en vez de adivinarla"))
    op, limite = leido
    cumple = {"<": valor < limite, "<=": valor <= limite,
              ">": valor > limite, ">=": valor >= limite}[op]
    return Veredicto(
        ind.id, "alcanzada" if cumple else "no_alcanzada",
        meta_periodo=periodo_meta, meta=meta, observado=round(valor, _DECIMALES),
        periodo_observado=p_obs, distancia=None,
        motivo=(f"umbral «{op} {limite:g}»: {valor:g} {'lo cumple' if cumple else 'NO lo cumple'}. "
                f"Un umbral no admite distancia — la ley fijó un techo, no un objetivo puntual."))


def _tiene_meta_rotulada(ind: Indicador, corte: str) -> bool:
    _, meta = _meta_vigente(ind, corte)
    return meta is not None and leer_rotulado(meta) is not None


def _veredicto_rotulado(ind: Indicador, binding: Binding, meta: Any,
                        periodo_meta: Optional[str], valor: float, p_obs: str) -> Veredicto:
    """Veredicto de una meta escrita como «<sujeto> : <número>».

    El SUJETO viaja al motivo. No es decoración: el 2.17 nombra tres materias y la ley solo le
    fija meta a matemáticas, así que un veredicto que dijera «97,84% contra 63,0%» a secas
    escondería que se está juzgando una de tres. El rótulo es lo que deja verlo.
    """
    leido = leer_rotulado(meta)
    if leido is None:
        return Veredicto(ind.id, "no_evaluable", meta_periodo=periodo_meta, meta=meta,
                         observado=round(valor, _DECIMALES), periodo_observado=p_obs,
                         motivo=f"la meta es de escala '{ind.escala}': requiere juicio")
    sujeto, objetivo = leido
    mejor_menor = binding.mejor == "menor"
    valor = round(valor, _DECIMALES)
    cumple = valor <= objetivo if mejor_menor else valor >= objetivo
    distancia = round((valor - objetivo) if mejor_menor else (objetivo - valor), _DECIMALES)
    return Veredicto(
        ind.id, "alcanzada" if cumple else "no_alcanzada", meta_periodo=periodo_meta,
        meta=meta, observado=valor, periodo_observado=p_obs, distancia=distancia,
        motivo=f"{sujeto}: {valor:g} contra una meta de {objetivo:g}. "
               f"{'La cumple' if cumple else 'NO la cumple'}.")


def _trayectoria(avance: float) -> str:
    """Tres estados, no dos. «Plana» existe porque una serie que no se mueve no «se aleja»:
    afirmar movimiento donde no lo hay es una falsedad que el lector puede comprobar."""
    return "mejora" if avance > 0 else ("plana" if avance == 0 else "se aleja")


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
