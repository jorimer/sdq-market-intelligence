"""Convierte una obligación de DICTAR UNA NORMA en un hecho con fecha.

Hoy el estado de las siete obligaciones de la Ley 1-12 se declara a mano y su evidencia se
escribe en prosa. Para las que consisten en dictar una norma, eso puede computarse: JurisAI
responde si existe, cuándo se promulgó y en qué Gaceta.

**La regla que gobierna este módulo, heredada de `obligaciones.py`.** `incumplida` afirma
que algo NO se hizo; `sin_registro_publico` dice que no se encontró rastro. No son lo mismo,
y acá la diferencia la decide UN campo del emisor: `alcance.vacio_es_concluyente`. Sin él en
`true`, una lista vacía es «no lo encontramos» y nada más.

**Ningún fallo se traduce a incumplimiento.** Si el API no responde, si la credencial es
rechazada o si el alcance declara un hueco, el veredicto es `no_verificable` y el estado
declarado a mano queda intacto. El error más caro que este módulo puede cometer es acusar al
Estado de incumplir por culpa de nuestra clave.

**Lo que este módulo NO hace: decidir.** Devuelve el veredicto computado y su evidencia; la
promoción del estado en el expediente sigue siendo un hecho comiteado y revisado, igual que
la de los bindings. Si la cobertura pudiera cambiar en caliente, dejaría de ser auditable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sdq.law_intel.normativa")

#: Veredictos que este módulo puede emitir. Son un subconjunto de los estados de
#: `obligaciones.ESTADOS` más `no_verificable`, que NO es un estado de la obligación sino
#: una declaración sobre nuestra capacidad de comprobarla — y por eso no se persiste.
VEREDICTOS = {
    "cumplida": "la norma existe y se dictó dentro del plazo",
    "cumplida_tarde": "la norma existe y se dictó DESPUÉS del plazo",
    "incumplida": "el corpus es concluyente en el rango y la norma no existe",
    "sin_registro_publico": "no se encontró, y el alcance NO permite afirmar que no exista",
    "no_verificable": "no se pudo consultar; el estado declarado queda intacto",
}


def antiguedad_de_la_evidencia(alcance: Dict[str, Any]) -> Optional[str]:
    """`medido_al`: la medición MÁS VIEJA de las celdas que sostienen esta respuesta.

    ⚠️ NO es «cuándo se comprobó por última vez», y confundirlo cuesta caro. Se leyó así al
    integrarlo y el emisor lo corrigió con evidencia de producción: en unas horas su corpus
    creció 546 normas y `medido_al` no se movió ni un segundo.

        medido_al      2026-08-18T03:40:48 → 2026-08-18T03:40:48   (sin cambio)
        normas_leidas  9.983 → 10.529                              (+546)

    Se comporta así a propósito: la remedición automática cubre el año en curso y el anterior,
    y los años cerrados conservan su medición original porque el pasado no cambia. En una
    consulta amplia queda fijada por la celda más vieja del rango y puede no moverse en meses.

    Sirve para responder «cuán vieja es la evidencia más débil que sostiene esto», que es una
    pregunta legítima y distinta. Para DETECTAR DERIVA hay que usar `huella_del_corpus`.
    """
    return (alcance or {}).get("medido_al") or None


def huella_del_corpus(alcance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """`instantanea`: el estado del corpus, calculado EN VIVO al responder.

    Es el campo que detecta deriva, y el que hay que guardar junto a un veredicto para poder
    explicar después por qué la cifra de un informe viejo ya no coincide con la actual —
    exactamente lo que la doctrina de este repo exige poder explicar.

    El campo intuitivo (`medido_al`) es justamente el que NO sirve para esto: una detección de
    deriva montada sobre él nunca dispararía. Se documenta acá porque el error ya se cometió.
    """
    inst = (alcance or {}).get("instantanea")
    return dict(inst) if isinstance(inst, dict) and inst else None


def _procedencia_del_corpus(alcance: Dict[str, Any]) -> str:
    """La frase que acompaña a una acusación: qué sostiene el corpus y cómo auditarlo.

    Lleva los DOS campos porque responden preguntas distintas y guardar uno solo deja ciega a
    la mitad: la huella dice si el corpus cambió desde el informe anterior; `medido_al` dice
    cuán vieja es la evidencia más débil que sostiene esta respuesta.
    """
    if not alcance:
        # El emisor no llegó a responder: no hay corpus del que hablar, y fabricar una frase
        # sobre su cobertura sería inventar procedencia donde no hubo consulta.
        return ""
    huella = huella_del_corpus(alcance)
    viejo = antiguedad_de_la_evidencia(alcance)
    partes = []
    if huella:
        detalle = ", ".join(f"{k}={v}" for k, v in sorted(huella.items()))
        partes.append(f" Huella del corpus al responder: {detalle}.")
    else:
        partes.append(" El emisor no declara la huella del corpus: no se podrá detectar si "
                      "cambió cuando este veredicto se reemita.")
    if viejo:
        partes.append(f" La evidencia más vieja que lo sostiene se midió el {viejo}.")
    return "".join(partes)


def _comprobacion(oid: str, veredicto: str, evidencia: str,
                  norma: Optional[Dict[str, Any]] = None,
                  alcance: Optional[Dict[str, Any]] = None) -> "Comprobacion":
    """TODA comprobación viaja con la procedencia de su corpus. Único constructor.

    La procedencia acompañaba solo a las acusaciones, y la asimetría era defendible a medias:
    `incumplida` es lo que alguien puede refutar, así que ahí pesa más. Pero un
    `cumplida_tarde` también se publica en un informe que se vende, y también hay que poder
    explicar después por qué su cifra ya no coincide con la de hoy — que es lo que la doctrina
    de este repo exige de cualquier dato publicado, no solo de los que acusan.

    Se hace con un constructor y no llamando a la procedencia en cada `return` porque eso ya
    estaba desincronizado: cinco salidas, una sola con procedencia. Un test estructural exige
    que ningún `return` de `comprobar_obligacion` arme un `Comprobacion` a mano.
    """
    return Comprobacion(oid, veredicto, evidencia + _procedencia_del_corpus(alcance or {}),
                        norma, alcance)


@dataclass(frozen=True)
class Comprobacion:
    obligacion: str
    veredicto: str
    evidencia: str
    norma: Optional[Dict[str, Any]] = None
    #: Lo que el emisor declaró sobre su propia cobertura. Viaja siempre: es lo que sostiene
    #: —o desarma— un veredicto de incumplimiento ante quien lo discuta.
    alcance: Optional[Dict[str, Any]] = None

    @property
    def acusa(self) -> bool:
        return self.veredicto == "incumplida"


#: Tipos cuyo corpus el emisor declara COMPLETO en algún rango, y por tanto los únicos
#: sobre los que un vacío puede llegar a afirmar «no se dictó».
#:
#: `reglamento` ENTRA (2026-08-19). Estuvo fuera mientras la pregunta seguía abierta —costaba
#: un `sin_registro_publico` de más, y al revés habría costado una acusación falsa—. El
#: emisor la respondió con evidencia contra producción, no con una deducción:
#:
#:     tipo=decreto     2012-2026 → concluyente=true · sin huecos · medido_al 2026-08-18
#:     tipo=reglamento  2012-2026 → concluyente=true · sin huecos · medido_al 2026-08-18
#:
#: Los dos alcances son idénticos campo a campo: resuelven al mismo instrumento y se apoyan
#: en las mismas celdas de cobertura. Fuera de ese rango los dos responden `false`, y de eso
#: se encarga el propio `vacio_es_concluyente` — este conjunto no reemplaza esa comprobación,
#: la acompaña.
_TIPOS_MEDIDOS = frozenset({"ley", "decreto", "reglamento"})


def _respaldo_de_gaceta(gaceta: Dict[str, Any]) -> str:
    """La frase de respaldo, preferiendo la que COMPONE EL EMISOR.

    `texto_citable` lo entregó JurisAI después de que publicáramos «Gaceta 10753 del None»:
    el número y la fecha viajan por separado y la fecha falta en dos tercios del corpus, así
    que interpolarla sin comprobar metía un `None` dentro de la evidencia que sostiene el
    veredicto — y el informe cita esa frase tal cual.

    Usarlo en vez de componerla acá no es comodidad: **quien conoce el formato correcto de una
    cita oficial es el emisor**, y el día que cambie —o que sepa distinguir «Gaceta Oficial»
    de un suplemento— nos enteramos sin tocar nada. La composición propia queda como respaldo
    para respuestas viejas y para cualquier otro emisor que no la traiga.
    """
    citable = gaceta.get("texto_citable")
    if isinstance(citable, str) and citable.strip():
        return f" Publicada en {citable.strip()}."
    if not gaceta.get("numero"):
        return ""
    frase = f" Publicada en la Gaceta {gaceta['numero']}"
    return frase + (f" del {gaceta['fecha']}." if gaceta.get("fecha") else ".")


def _sin_duplicados(halladas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Una norma por id canónico, quedándose con la grada que dice MÁS.

    El emisor devolvió un tiempo cinco normas por duplicado —el mismo id, una en grada
    `texto` y otra `registral`— porque el enlace entre gradas se rehace por campañas y esas
    cinco nunca se enlazaron. Ya lo corrigió de raíz.

    Se deduplica igual acá, y no por desconfianza: dos días seguidos aparecieron propiedades
    de esta fuente que eran ciertas por accidente hasta que dejaron de serlo. Un recuento que
    depende de que el emisor nunca duplique es exactamente esa clase de acuerdo tácito.

    Hoy no cambiaría ningún veredicto —se toma la PRIMERA norma en el tiempo y un duplicado
    tiene la misma fecha—, pero sí protege a cualquier lectura futura que cuente normas.
    Se prefiere `texto` sobre `registral` por la misma razón que el emisor: la leída dice
    estrictamente más.
    """
    por_id: Dict[str, Dict[str, Any]] = {}
    for n in halladas:
        clave = str(n.get("id") or id(n))
        previa = por_id.get(clave)
        if previa is None or (n.get("grada") == "texto" and previa.get("grada") != "texto"):
            por_id[clave] = n
    return list(por_id.values())


def _fecha(norma: Dict[str, Any]) -> str:
    return str(norma.get("fecha_promulgacion") or "")


def comprobar_obligacion(consulta: Dict[str, Any], vence: Optional[str],
                         buscar) -> Comprobacion:
    """Computa el veredicto de UNA obligación normativa.

    *consulta* es lo que el expediente declara buscar (`cita_a`, `tipo`, `desde`, `hasta`);
    *vence* es el plazo legal, calculado del articulado y no del API. *buscar* se inyecta
    para que este módulo no sepa de clientes HTTP ni haga red en los tests.
    """
    from shared.data.jurisai_client import JurisAIUnavailable, normas, vacio_es_concluyente

    oid = str(consulta.get("obligacion") or "?")
    try:
        resp = buscar(**{k: v for k, v in consulta.items() if k != "obligacion"})
    except JurisAIUnavailable as e:
        # No se degrada a «no existe». Es la regla entera de este módulo.
        return _comprobacion(oid, "no_verificable",
                            f"No se pudo consultar la base normativa: {e}")

    halladas = _sin_duplicados(normas(resp))
    alcance = resp.get("alcance") or {}
    if not halladas:
        # El emisor mide su corpus POR TIPO: leyes y decretos sí, reglamentos y resoluciones
        # NO. Nos apoyamos en su `vacio_es_concluyente`, que ya lo refleja — pero el segundo
        # cinturón es barato y la consecuencia de que falle es acusar al Estado de un
        # incumplimiento sobre un universo que nadie midió.
        if vacio_es_concluyente(resp) and str(consulta.get("tipo") or "") in _TIPOS_MEDIDOS:
            return _comprobacion(
                oid, "incumplida",
                f"El corpus «{alcance.get('corpus', 'declarado')}» está completo entre "
                f"{alcance.get('completo_desde', '?')} y {alcance.get('completo_hasta', '?')} "
                f"y no contiene ninguna norma que satisfaga la obligación.",
                alcance=alcance)
        huecos = alcance.get("huecos") or []
        return _comprobacion(
            oid, "sin_registro_publico",
            "No se localizó la norma, y el alcance NO es concluyente"
            + (f" (huecos declarados: {huecos})" if huecos else "")
            + ": no se afirma incumplimiento.",
            alcance=alcance)

    # Con varias, manda la PRIMERA en el tiempo: es la que cumple la obligación. Tomar la
    # más reciente haría parecer tardío un cumplimiento que fue en plazo.
    norma = min(halladas, key=_fecha)
    fecha = _fecha(norma)
    cita = f"{norma.get('tipo', '')} {norma.get('numero', '')}".strip() or norma.get("id", "")
    respaldo = _respaldo_de_gaceta(norma.get("gaceta") or {})

    if not vence or not fecha:
        return _comprobacion(oid, "cumplida",
                            f"{cita} del {fecha or 's/f'}.{respaldo}", norma, alcance)
    tarde = fecha > vence

    # ── LA GRIETA QUE EL EMISOR AVISA Y NOSOTROS DEBEMOS RESPETAR ──────────────────────
    # Cuando se le pasa `vence`, el API computa la holgura Y marca
    # `veredicto_sensible_a_publicacion` si el dictado cae a ≤30 días del plazo y NO hay
    # fecha de Gaceta. Ese es el caso al filo: una norma dictada días ANTES del vencimiento
    # pero publicada después, donde «dentro del plazo» y «fuera del plazo» dependen de un
    # dato que falta en dos tercios del corpus.
    #
    # Ignorarlo sería publicar un veredicto firme sobre una diferencia que no medimos —y en
    # la dirección más cara, porque «cumplida» absuelve—. Cuando el emisor lo marca, el
    # veredicto se degrada a `no_verificable`: el estado declarado a mano queda intacto y la
    # evidencia dice exactamente qué dato falta para cerrarlo.
    #
    # Que el 134-14 tenga 625 días de holgura es lo que vuelve sólido ESE caso, no una
    # propiedad del método: con 625 días ninguna fecha de publicación imaginable lo mueve.
    holgura = resp.get("holgura_dias")
    if resp.get("veredicto_sensible_a_publicacion"):
        return _comprobacion(
            oid, "no_verificable",
            f"{cita} del {fecha}, contra un plazo que vencía el {vence}"
            + (f" (holgura de {holgura} días)" if holgura is not None else "")
            + ". El emisor marca el veredicto como SENSIBLE A LA PUBLICACIÓN: el dictado "
              "cae al filo del plazo y no consta la fecha de Gaceta, así que el "
              "cumplimiento depende de un dato que no está medido. No se afirma ni "
              "cumplimiento ni incumplimiento." + respaldo,
            norma, alcance)

    detalle = f" (holgura de {holgura} días)" if holgura is not None else ""
    return _comprobacion(
        oid, "cumplida_tarde" if tarde else "cumplida",
        f"{cita} del {fecha}: {'DESPUÉS' if tarde else 'dentro'} del plazo, que vencía el "
        f"{vence}{detalle}.{respaldo}", norma, alcance)


def comprobar(obligaciones: List[Any], buscar) -> List[Comprobacion]:
    """Comprueba las obligaciones que declaran una consulta normativa.

    Las demás se saltan sin ruido: constituir una comisión o convocar una reunión no deja
    rastro en la Gaceta, y pretender verificarlas por acá produciría un `incumplida` sobre
    un acto que esta fuente no puede ver.
    """
    out: List[Comprobacion] = []
    for o in obligaciones:
        consulta = dict(getattr(o, "verificacion_normativa", None) or {})
        if not consulta:
            continue
        consulta["obligacion"] = o.id
        vence = ((o.plazo or {}).get("vence") if isinstance(o.plazo, dict) else None)
        if isinstance(vence, list):        # plazos múltiples: manda el primero vencido
            vence = min(vence) if vence else None
        out.append(comprobar_obligacion(consulta, vence, buscar))
    return out
