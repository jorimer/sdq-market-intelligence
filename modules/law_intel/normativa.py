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
        return Comprobacion(oid, "no_verificable",
                            f"No se pudo consultar la base normativa: {e}")

    halladas = normas(resp)
    alcance = resp.get("alcance") or {}
    if not halladas:
        if vacio_es_concluyente(resp):
            return Comprobacion(
                oid, "incumplida",
                f"El corpus «{alcance.get('corpus', 'declarado')}» está completo entre "
                f"{alcance.get('completo_desde', '?')} y {alcance.get('completo_hasta', '?')} "
                f"y no contiene ninguna norma que satisfaga la obligación.",
                alcance=alcance)
        huecos = alcance.get("huecos") or []
        return Comprobacion(
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
    gaceta = norma.get("gaceta") or {}
    respaldo = (f" Publicada en la Gaceta {gaceta.get('numero')} del {gaceta.get('fecha')}."
                if gaceta.get("numero") else "")

    if not vence or not fecha:
        return Comprobacion(oid, "cumplida",
                            f"{cita} del {fecha or 's/f'}.{respaldo}", norma, alcance)
    tarde = fecha > vence
    return Comprobacion(
        oid, "cumplida_tarde" if tarde else "cumplida",
        f"{cita} del {fecha}: {'DESPUÉS' if tarde else 'dentro'} del plazo, que vencía el "
        f"{vence}.{respaldo}", norma, alcance)


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
