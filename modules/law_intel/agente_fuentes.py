"""Le pregunta al modelo, POR INDICADOR, quién publica el dato que la ley manda medir.

**Por qué existe aparte del agente general.** `source_intel.run_research_agent` recorre las
brechas del readiness y propone hasta dos fuentes por brecha. El eje de leyes tiene UNA sola
brecha (`g1 · Datos`), así que los 90 indicadores colapsan en dos propuestas y el prompt sólo
puede decir «amplíe la fuente». La corrida real lo confirmó: dos propuestas, una de ellas
genérica y para un organismo disuelto.

Acá la unidad es el INDICADOR. Cada uno trae el nombre que el legislador le puso, su línea
base con su año y sus metas: con eso la pregunta deja de ser «¿cómo amplío la cobertura del
eje?» y pasa a ser «¿quién publica en RD la tasa de homicidios por cien mil habitantes?», que
es una pregunta con respuesta.

**Lo que NO hace.** No integra ni decide. Deja la propuesta en el mismo tablero de
`source_intel`, evaluada, con el eje y el gate anclados — el sistema propone, el dueño
dispone. Y no re-pregunta por un indicador que ya tiene propuesta abierta: la idempotencia
vive en el título, igual que en el agente general.

**El costo, MEDIDO y no estimado.** Una llamada por indicador. Contra el modelo real
(Sonnet 4.6) tres indicadores gastaron 5.704 tokens de entrada y 675 de salida: **US$0,76 los
84**. La estimación previa decía US$3 porque suponía cuatro veces más tokens de salida de los
que el modelo realmente usa — con `max_tokens=900` responde en ~225. El tope por corrida
existe igual, para que una corrida accidental no dispare 84 llamadas sin querer.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.registro import Indicador, cargar

logger = logging.getLogger("sdq.law_intel.agente_fuentes")

# Tope por corrida. Deliberadamente por debajo de los 84: una corrida completa se pide
# explícitamente subiendo el tope, no se dispara sin querer.
MAX_POR_CORRIDA = 20

# Hechos institucionales POSTERIORES al conocimiento del modelo. En la prueba real nombró
# tres veces al MEPyD, disuelto en julio de 2025: sin esto, el tablero se llena de propuestas
# dirigidas a un organismo que no existe, y quien las revisa las descarta una por una.
_HECHOS = (
    "Contexto institucional vigente (posterior a tu conocimiento, tomalo como cierto):\n"
    "· El MEPyD fue DISUELTO: la Ley 45-25 (2025-07-23) lo fusionó con Hacienda creando el "
    "Ministerio de Hacienda y Economía (MHE). No propongas al MEPyD como organismo actual; "
    "si la serie la producía él, nombrá al MHE y decilo.\n"
    "· La ONE sigue existiendo y sigue siendo el productor de estadística nacional.\n"
)

_SISTEMA = (
    "Sos analista de datos públicos de República Dominicana. Conocés qué organismo publica "
    "qué estadística y con qué periodicidad. Respondés SOLO JSON, sin texto alrededor.\n\n"
    + _HECHOS + "\n"
    "REGLA QUE NO SE NEGOCIA: no propongas el informe de seguimiento del propio órgano "
    "evaluado como fuente de medición. Su autoevaluación no sirve para evaluarlo — sí sirven "
    "las SERIES que ese órgano publica. Si la única fuente que se te ocurre es el informe de "
    "avance del evaluado, devolvé el arreglo vacío."
)


def _pregunta(ind: Indicador, norma: str) -> str:
    base = (f"línea base {ind.base_valor} en {ind.base_anio}"
            if ind.base_valor is not None and ind.base_anio else "sin línea base declarada")
    metas = ", ".join(f"{a}: {v}" for a, v in sorted(ind.metas.items())) or "sin metas numéricas"
    return (
        f"La {norma} fija el indicador {ind.id}: «{ind.nombre}».\n"
        f"{base}. Metas quinquenales — {metas}.\n\n"
        "¿Qué fuente PÚBLICA y OFICIAL de República Dominicana publica hoy esa magnitud, con "
        "esa misma definición y unidad? Si ninguna la publica con la definición exacta, decilo "
        "devolviendo el arreglo vacío en vez de ofrecer una aproximada.\n\n"
        "Devolvé SOLO este arreglo JSON (máximo 1 elemento): "
        "[{\"title\": \"organismo — nombre de la publicación o serie\", "
        "\"description\": \"qué magnitud publica exactamente, con qué periodicidad, y por qué "
        "corresponde a este indicador\"}]."
    )


def _parsear(texto: str) -> List[Dict[str, Any]]:
    t = texto.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("["):]
    ini, fin = t.find("["), t.rfind("]")
    if ini < 0 or fin < 0:
        return []
    try:
        datos = json.loads(t[ini:fin + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in datos if isinstance(d, dict) and (d.get("title") or "").strip()]


def sin_fuente(expediente_id: str) -> List[Indicador]:
    """Indicadores que ninguna fuente verificada mide y sobre los que tiene sentido preguntar.

    Se excluyen los descartados: su problema no es falta de fuente sino que la evaluada no
    mide lo que el eje afirma, y volver a preguntar re-abre una decisión ya documentada.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    return [i for i in exp.numerados
            if not ((b := bs.get(i.id)) and (b.cuenta or b.estado == "descartado"))]


def proponer(expediente_id: str, preguntar: Callable[[str, str], str],
             max_indicadores: int = MAX_POR_CORRIDA,
             ya_propuestos: Optional[set] = None) -> List[Dict[str, Any]]:
    """Una propuesta por indicador. *preguntar* recibe (sistema, usuario) y devuelve texto.

    Se inyecta el interrogador para que este módulo no sepa de clientes de IA ni haga red en
    los tests — y para que el mismo barrido pueda correrse contra un modelo distinto sin
    tocarlo.
    """
    exp = cargar(expediente_id)
    vistos = set(ya_propuestos or ())
    salida: List[Dict[str, Any]] = []
    for ind in sin_fuente(expediente_id):
        if len(salida) >= max_indicadores:
            break
        if ind.id in vistos:
            continue
        try:
            crudo = preguntar(_SISTEMA, _pregunta(ind, exp.norma))
        except Exception as e:  # noqa: BLE001 — un indicador que falla no aborta el barrido
            logger.warning("propuesta para %s falló: %s", ind.id, e)
            continue
        for p in _parsear(crudo)[:1]:
            salida.append({
                "indicador": ind.id,
                "nombre_indicador": ind.nombre,
                "eje": ind.eje,
                "title": (p.get("title") or "").strip()[:200],
                # El indicador viaja DENTRO de la descripción: la sugerencia vive en el
                # tablero general, donde el único campo de eje es `target_axis="law"`. Sin
                # esto, quien la revise no sabe a qué meta responde.
                "description": (f"[Ley 1-12 · indicador {ind.id} — {ind.nombre}] "
                                f"{(p.get('description') or '').strip()}")[:1000],
            })
    return salida


def resumen(props: List[Dict[str, Any]], total_sin_fuente: int) -> Dict[str, Any]:
    return {
        "indicadores_sin_fuente": total_sin_fuente,
        "consultados": min(total_sin_fuente, MAX_POR_CORRIDA),
        "con_propuesta": len(props),
        # Que el modelo devuelva vacío para un indicador NO es un fallo: es la respuesta
        # correcta cuando ninguna fuente publica esa magnitud con esa definición. Contarlo
        # como error empujaría a aflojar el prompt y a aceptar aproximaciones.
        "sin_propuesta": min(total_sin_fuente, MAX_POR_CORRIDA) - len(props),
        "nota": ("Un indicador sin propuesta significa que no se identificó fuente oficial "
                 "con la MISMA definición. Es un resultado, no una falla."),
    }
