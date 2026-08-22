"""El tercer camino a `verificado`: el emisor revisó su propia serie y lo DECLARA.

**Por qué hacía falta.** Los dos caminos anteriores cubren dos situaciones y dejan una
afuera. El oráculo cubre «la serie reproduce la cifra que el legislador escribió». La
identidad de concepto cubre «la línea base cae fuera del alcance de la serie, así que el
oráculo no puede correr y el término del emisor tiene que cargar la prueba». Falta el caso
en que el oráculo **corre, falla, y el emisor publica la causa del fallo**.

Es el caso del 3.23. La ley fija 1.625,3 millones de IED para 2010; el mismo emisor publica
hoy 2.023,7 para ese año, publicó 1.896,3 en su añada de 2014, y el republicador
internacional da 1.820,2. Tres cifras del mismo fenómeno y un cuarto valor en la ley. La
causa no hay que suponerla: el BCRD la imprime al pie de su cuadro —«Estadísticas Conforme
al Sexto Manual de Balanza de Pagos del FMI»— y su cuadro anterior advierte «cifras
revisadas parcialmente».

Sin este camino, un indicador cuyo emisor mejoró su metodología queda inverificable para
siempre, y el informe diría «no lo medimos» sobre una serie que el Estado publica con el
nombre exacto que el legislador le puso. Eso castiga al emisor por revisar bien.

**Lo que NO es.** No es aflojar el oráculo. Un oráculo que falla sin causa declarada sigue
siendo un descarte. Los candados están en `bindings._validar` y son cuatro:

1. La identidad del término, computada contra el nombre del indicador — el mismo contraste
   que exige la identidad de concepto, ni un ápice menos.
2. La declaración del emisor, con su texto, dónde aparece y **la fecha en que se comprobó**.
   Es la regla del campo: lo que afirma algo sobre el mundo lleva evidencia con fecha.
3. Al menos dos añadas del mismo emisor o de su republicador, y **ninguna dentro de la
   tolerancia del oráculo**. Si alguna reprodujera la base, el camino correcto sería el
   oráculo y éste sobraría; que sobre y se use igual es cómo un camino de excepción se
   vuelve la puerta de todos.
4. Que el margen se coma la corrección: aplicando a la serie el factor de añada más adverso,
   el veredicto contra cada meta **no puede darse vuelta**. Esto se COMPUTA acá, con
   :func:`absorbe`, y no se transcribe: una conclusión copiada a mano es una conclusión que
   se desincroniza del dato.

El cuarto es el que decide, y por eso vive en este módulo y no en una nota. Es el mismo
criterio con el que la pobreza rural extrema (2.3) se promovió con su quiebre de metodología
declarado y la moderada (2.6) no: ahí el margen era 2,2% contra una brecha de concepto de
7,3% y no alcanzaba.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

#: Misma tolerancia que usa la sonda para decir «la serie reproduce la base». Se importa el
#: número por valor y no el módulo entero para no atar este módulo al de sondeo, pero es
#: deliberadamente EL MISMO: si acá fuera más laxo, una añada que el oráculo rechaza entraría
#: por la puerta de al lado.
TOLERANCIA_ORACULO_PCT = 2.0


class AnadaInvalida(ValueError):
    """Una añada declarada que no se puede usar para computar nada."""


@dataclass(frozen=True)
class Anada:
    """Un valor publicado para el AÑO BASE de la ley por una añada concreta del emisor."""

    valor: float
    fuente: str

    @staticmethod
    def desde(d: Dict[str, object]) -> "Anada":
        try:
            valor = float(d["valor"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError) as e:
            raise AnadaInvalida(f"añada sin `valor` numérico: {d!r}") from e
        fuente = str(d.get("fuente") or "").strip()
        if not fuente:
            raise AnadaInvalida(f"añada sin `fuente` declarada: {d!r}")
        return Anada(valor, fuente)


def divergencia_pct(base_legal: float, valor: float) -> float:
    """Cuánto se aparta una añada de la cifra que el legislador escribió, en porcentaje."""
    if base_legal == 0:
        raise AnadaInvalida("la línea base legal es cero: no hay divergencia relativa que computar")
    return abs(valor - base_legal) / abs(base_legal) * 100.0


def alguna_reproduce_la_base(base_legal: float, anadas: Sequence[Anada]) -> Optional[Anada]:
    """La añada que reproduce la base dentro de la tolerancia del oráculo, si existe.

    Que exista invalida este camino entero: el binding tiene que ir por el oráculo, contra esa
    añada. Devolverla en vez de un booleano deja que el mensaje de error diga CUÁL.
    """
    for a in anadas:
        if divergencia_pct(base_legal, a.valor) <= TOLERANCIA_ORACULO_PCT:
            return a
    return None


def factor_mas_adverso(base_legal: float, anadas: Sequence[Anada], mejor: str) -> float:
    """El factor que más empuja la serie EN CONTRA del veredicto.

    Si más es mejor, lo adverso es que la añada vigente esté inflada respecto de la que usó el
    legislador: el factor que más achica. Si menos es mejor, es al revés. Elegir el factor por
    la dirección del indicador y no por «el más grande» es lo que impide que la corrección se
    aplique en la dirección que conviene.
    """
    if not anadas:
        raise AnadaInvalida("no hay añadas declaradas: no hay factor que computar")
    if mejor not in ("mayor", "menor"):
        raise AnadaInvalida(f"dirección desconocida '{mejor}'")
    factores = [base_legal / a.valor for a in anadas if a.valor]
    if not factores:
        raise AnadaInvalida("todas las añadas declaradas valen cero")
    return min(factores) if mejor == "mayor" else max(factores)


def _cumple(valor: float, meta: float, mejor: str) -> bool:
    return valor >= meta if mejor == "mayor" else valor <= meta


@dataclass(frozen=True)
class Absorcion:
    """El resultado de preguntar si el margen se come la corrección de añada."""

    absorbe: bool
    factor: float
    #: Por meta: `(anio, observado, corregido, meta, cumple_sin_corregir, cumple_corregido)`.
    detalle: Tuple[Tuple[str, float, float, float, bool, bool], ...]
    motivo: str


def absorbe(base_legal: float, anadas: Sequence[Anada], mejor: str,
            observados: Dict[str, float], metas: Dict[str, float]) -> Absorcion:
    """¿Sobrevive el veredicto a la corrección de añada más adversa?

    Se computa meta por meta y no en agregado: un indicador puede cumplir cómodo en 2025 y
    darse vuelta en 2015, y publicar «se cumplió» sobre el promedio de las dos sería publicar
    una conclusión que ninguna de las dos sostiene.

    `observados` y `metas` van por año. Un año con meta y sin observación no se cuenta ni a
    favor ni en contra: no tener el dato es otra cosa que tenerlo y que se dé vuelta.
    """
    factor = factor_mas_adverso(base_legal, anadas, mejor)
    detalle: List[Tuple[str, float, float, float, bool, bool]] = []
    for anio in sorted(metas):
        obs = observados.get(anio)
        if obs is None:
            continue
        corregido = obs * factor
        detalle.append((anio, obs, corregido, metas[anio],
                        _cumple(obs, metas[anio], mejor),
                        _cumple(corregido, metas[anio], mejor)))
    if not detalle:
        return Absorcion(False, factor, (),
                         "ninguna meta tiene observación con la que contrastar")
    dan_vuelta = [d[0] for d in detalle if d[4] != d[5]]
    if dan_vuelta:
        return Absorcion(
            False, factor, tuple(detalle),
            f"la corrección de añada da vuelta el veredicto en {', '.join(dan_vuelta)}")
    return Absorcion(
        True, factor, tuple(detalle),
        f"el veredicto se sostiene en las {len(detalle)} metas con observación, aplicando el "
        f"factor de añada más adverso ({factor:.3f})")
