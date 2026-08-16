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
dispone. Y no re-pregunta por un indicador que ya tiene propuesta ABIERTA: la idempotencia
vive en la marca de la descripción, porque el tablero no tiene dónde guardar un indicador.
Solo bloquean las abiertas: una rechazada o ya integrada debe poder volver a preguntarse, o
el indicador quedaría congelado en su primera respuesta.

**El costo, MEDIDO y no estimado.** Una llamada por indicador. Contra el modelo real
(Sonnet 4.6) tres indicadores gastaron 5.704 tokens de entrada y 675 de salida: **US$0,76 los
84**. La estimación previa decía US$3 porque suponía cuatro veces más tokens de salida de los
que el modelo realmente usa — con `max_tokens=900` responde en ~225. El tope por corrida
existe igual, para que una corrida accidental no dispare 84 llamadas sin querer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

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


# ── La marca: qué indicador respondió cada propuesta ──────────────────────────────────────
# El tablero de `source_intel` es común a todos los ejes y su único campo de eje es
# `target_axis`, que acá vale "law" para las 84. Sin el indicador escrito ADENTRO de la
# descripción, quien revisa ve 84 propuestas sin saber a qué meta responde cada una — y la
# corrida siguiente no puede saltar las ya propuestas.
#
# Por eso la marca es a la vez legible y parseable, y `marca`/`indicador_de` son inversas.
# Un test lo verifica sobre TODOS los indicadores del expediente: si alguien cambia el
# formato de un lado, la idempotencia se rompería en silencio y la segunda corrida volvería
# a preguntar (y a pagar) por los 84.
def marca(norma: str, ind: Indicador) -> str:
    return f"[{norma} · indicador {ind.id} — {ind.nombre}] "


_RE_MARCA = re.compile(r"^\[[^\]]*?· indicador ([0-9]+(?:\.[0-9]+)*) —")


def indicador_de(descripcion: str) -> Optional[str]:
    m = _RE_MARCA.match((descripcion or "").strip())
    return m.group(1) if m else None


def sin_fuente(expediente_id: str) -> List[Indicador]:
    """Indicadores que ninguna fuente verificada mide y sobre los que tiene sentido preguntar.

    Se excluyen los descartados: su problema no es falta de fuente sino que la evaluada no
    mide lo que el eje afirma, y volver a preguntar re-abre una decisión ya documentada.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    return [i for i in exp.numerados
            if not ((b := bs.get(i.id)) and (b.cuenta or b.estado == "descartado"))]


class Corrida(NamedTuple):
    """Lo propuesto Y lo consultado. Las dos cifras, porque no son la misma.

    El tope acota los INDICADORES CONSULTADOS, que es lo que cuesta — no las propuestas
    obtenidas. Acotar la salida dejaba el gasto sin techo: con respuestas vacías
    intercaladas, un tope de 20 propuestas podía costar 40 llamadas. Un guard de gasto que
    no acota el gasto es peor que no tenerlo, porque se lo cree.
    """
    propuestas: List[Dict[str, Any]]
    consultados: int
    #: Indicadores cuya llamada NO llegó a responder, con el motivo. Van aparte de los que
    #: respondieron vacío: «ninguna fuente publica esto» y «no pudimos preguntar» son cosas
    #: distintas, y confundirlas convierte una caída del proveedor en un hallazgo sobre el
    #: Estado dominicano. Es el mismo error que el módulo entero existe para no cometer.
    fallidos: Dict[str, str] = {}
    #: Todo lo consultado en la corrida, con propuesta o sin ella. Es lo que permite al
    #: llamador avanzar entre tandas.
    consultados_ids: List[str] = []


def proponer(expediente_id: str, preguntar: Callable[[str, str], str],
             max_indicadores: int = MAX_POR_CORRIDA,
             ya_propuestos: Optional[set] = None) -> Corrida:
    """Una propuesta por indicador. *preguntar* recibe (sistema, usuario) y devuelve texto.

    Se inyecta el interrogador para que este módulo no sepa de clientes de IA ni haga red en
    los tests — y para que el mismo barrido pueda correrse contra un modelo distinto sin
    tocarlo.
    """
    exp = cargar(expediente_id)
    vistos = set(ya_propuestos or ())
    salida: List[Dict[str, Any]] = []
    fallidos: Dict[str, str] = {}
    consultados_ids: List[str] = []
    for ind in sin_fuente(expediente_id):
        if len(consultados_ids) >= max_indicadores:
            break
        if ind.id in vistos:
            continue
        consultados_ids.append(ind.id)
        try:
            crudo = preguntar(_SISTEMA, _pregunta(ind, exp.norma))
        except Exception as e:  # noqa: BLE001 — un indicador que falla no aborta el barrido
            logger.warning("propuesta para %s falló: %s", ind.id, e)
            # Ya contó como consultado: no se reintenta dentro de la misma corrida. Pero se
            # REGISTRA con su motivo, para que la corrida siguiente sepa que este indicador
            # quedó sin preguntar y no dé por respondido lo que nunca se preguntó.
            fallidos[ind.id] = f"{type(e).__name__}: {e}"[:200]
            continue
        for p in _parsear(crudo)[:1]:
            salida.append({
                "indicador": ind.id,
                "nombre_indicador": ind.nombre,
                "eje": ind.eje,
                "title": (p.get("title") or "").strip()[:200],
                "description": (marca(exp.norma, ind)
                                + (p.get("description") or "").strip())[:1000],
            })
    return Corrida(salida, len(consultados_ids), fallidos, consultados_ids)


# ── Cableado al tablero ───────────────────────────────────────────────────────────────────

def _preguntar_al_modelo(sistema: str, usuario: str) -> str:
    """El interrogador real. Aparte de `proponer` para que los tests no toquen la red."""
    import anthropic

    from shared.config.settings import settings
    from shared.observability.llm_ledger import PURPOSE_OTHER, account

    cliente = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = cliente.messages.create(
        model=settings.ANTHROPIC_MODEL, max_tokens=900,
        system=sistema, messages=[{"role": "user", "content": usuario}])
    # Sin esto el gasto no cuenta contra LLM_DAILY_BUDGET_USD: un barrido de 84 llamadas
    # quedaría fuera del techo diario y nada podría cortarlo.
    account(resp, model=settings.ANTHROPIC_MODEL, purpose=PURPOSE_OTHER,
            module="law_intel", template="agente_por_indicador")
    # Se recorren los bloques en vez de tomar `content[0].text`: la respuesta puede traer
    # bloques que no son texto, y el índice cero dejaría de ser el texto sin previo aviso.
    return "".join(getattr(b, "text", "") for b in resp.content)


def ya_propuestos(db: Any) -> Set[str]:
    """Indicadores con propuesta ABIERTA en el tablero, leídos de la marca.

    Se miran solo las abiertas: una propuesta rechazada o ya integrada no debe bloquear que
    se vuelva a preguntar — lo contrario congelaría el indicador en su primera respuesta.
    """
    from shared.source_intel.models import (
        STATUS_APPROVED, STATUS_EVALUATED, STATUS_EVALUATING, STATUS_INTEGRATING,
        STATUS_PROPOSED, SourceSuggestion,
    )

    abiertos = (STATUS_PROPOSED, STATUS_EVALUATING, STATUS_EVALUATED,
                STATUS_APPROVED, STATUS_INTEGRATING)
    filas = (db.query(SourceSuggestion)
             .filter(SourceSuggestion.target_axis == "law",
                     SourceSuggestion.status.in_(abiertos)).all())
    return {i for f in filas if (i := indicador_de(f.description or ""))}


def barrer(db: Any, expediente_id: str = "end_2030",
           max_indicadores: int = MAX_POR_CORRIDA,
           preguntar: Optional[Callable[[str, str], str]] = None,
           omitir: Optional[Set[str]] = None) -> Dict[str, Any]:
    """Pregunta por los indicadores sin fuente y deja cada propuesta EVALUADA en el tablero.

    **Por qué existe `omitir`.** La idempotencia por tablero solo cubre lo que DEJÓ RASTRO: un
    indicador que respondió vacío no crea fila, así que la corrida siguiente vuelve a
    preguntarle. Con 83 indicadores y un techo de proxy de cinco minutos el barrido hay que
    partirlo en tandas — y sin `omitir` cada tanda re-consulta desde el principio los mismos
    vacíos y no avanza nunca. El llamador acumula `consultados_ids` y los devuelve acá.

    Se resuelve así, y no guardando el vacío en el tablero, porque una fila de sugerencia
    AFIRMA que hay una fuente propuesta. Registrar «no hay fuente» como sugerencia sería
    rellenar la brecha en vez de declararla; el lugar donde eso se declara es el expediente,
    que es un hecho comiteado y auditable.
    """
    from shared.source_intel.models import KIND_SOURCE, ORIGIN_AGENT
    from shared.source_intel.service import create_suggestion, evaluate

    vistos = ya_propuestos(db) | set(omitir or ())
    corrida = proponer(expediente_id, preguntar or _preguntar_al_modelo,
                       max_indicadores=max_indicadores, ya_propuestos=vistos)
    creados: List[str] = []
    for p in corrida.propuestas:
        s = create_suggestion(
            db, kind=KIND_SOURCE, title=p["title"], description=p["description"],
            # El gate se ancla acá y no lo elige el modelo: la brecha del eje de leyes es
            # `g1 · Datos` y anclarla mantiene la idempotencia entre corridas.
            origin=ORIGIN_AGENT, target_axis="law", target_gate="g1")
        try:
            evaluate(db, s["id"])
        except Exception as e:  # noqa: BLE001 — la eval no debe perder la sugerencia
            logger.warning("auto-eval de %s falló: %s", s["id"], e)
        creados.append(s["id"])

    pendientes = [i.id for i in sin_fuente(expediente_id) if i.id not in vistos]
    return {
        **resumen(corrida),
        # Lo consultado en ESTA tanda, para que el llamador lo acumule y lo devuelva en
        # `omitir`: sin esto las tandas siguientes re-preguntan los vacíos y no se avanza.
        "consultados_ids": corrida.consultados_ids,
        "indicadores_sin_fuente": len(pendientes),
        "creadas": len(creados),
        "ya_propuestos": len(vistos),
        # `capado` en vez de truncar en silencio: correr de nuevo cubre el resto, porque el
        # dedup por indicador salta lo ya propuesto.
        "capado": len(pendientes) > max_indicadores,
        "restantes": max(0, len(pendientes) - max_indicadores),
    }


# La prosa que distingue las dos cosas vive en constantes: incrustada en el dict se parte por
# ancho de línea y deja de existir en el fuente aunque el valor sea correcto.
NOTA_SIN_PROPUESTA = (
    "Un indicador sin propuesta significa que se preguntó y no se identificó fuente oficial "
    "con la MISMA definición. Es un resultado, no una falla."
)
NOTA_FALLIDOS = (
    "Un indicador FALLIDO no se preguntó: la llamada no llegó a responder. No dice nada "
    "sobre si existe la fuente. Volvé a correr el barrido para cubrirlos."
)


def resumen(corrida: Corrida) -> Dict[str, Any]:
    # `consultados` es lo REALMENTE consultado, no `min(total, tope)`: esa cuenta era una
    # predicción disfrazada de medición y se equivocaba en cuanto una llamada fallaba.
    respondieron = corrida.consultados - len(corrida.fallidos)
    return {
        "consultados": corrida.consultados,
        "respondieron": respondieron,
        "con_propuesta": len(corrida.propuestas),
        # Que el modelo devuelva vacío para un indicador NO es un fallo: es la respuesta
        # correcta cuando ninguna fuente publica esa magnitud con esa definición. Contarlo
        # como error empujaría a aflojar el prompt y a aceptar aproximaciones.
        # Sobre los que RESPONDIERON, no sobre los consultados: sumarle los fallidos haría
        # pasar una caída del proveedor por «el Estado no publica esto».
        "sin_propuesta": respondieron - len(corrida.propuestas),
        "fallidos": len(corrida.fallidos),
        "motivos_de_falla": corrida.fallidos,
        "nota": NOTA_SIN_PROPUESTA,
        "nota_fallidos": NOTA_FALLIDOS,
    }
