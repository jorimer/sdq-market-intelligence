"""La SONDA: contrastar un candidato contra la línea base que la propia ley declara.

**Para qué existe.** Atar un indicador costaba un ciclo entero —escribir el conector,
desplegar, sincronizar— y recién al final se descubría si la serie medía lo que el indicador
dice medir. El error se pagaba completo y tarde.

La ley trae su propio oráculo y no se estaba usando: la END declara VALOR y AÑO de línea base
para 67 de los 77 indicadores sin verificar. Una serie candidata que no reproduce ese valor en
ese año no mide lo que el indicador mide. Eso se comprueba contra la fuente viva en segundos,
sin desplegar nada, y descarta candidatos antes de que cuesten un conector.

**EL LÍMITE, y no es un detalle de implementación.** La sonda DESCARTA Y ORDENA; no promueve
jamás. Coincidir en el número no es medir el mismo concepto, y este eje ya tiene el caso que
lo prueba: el indicador 2.34 (saneamiento) da 80,77 contra una base legal de 82,7 —Δ 2,3%,
«coincide»— y está DESCARTADO con razón, porque el emisor cambió su escala en 2015 y la
cercanía de niveles es justamente lo que haría pasar ese cambio de definición por un dato
comparable. La sonda mide coincidencia de NIVEL; ese descarte era de DEFINICIÓN, y ninguna
tolerancia numérica lo habría visto.

Por eso el veredicto más fuerte que emite se llama `revisar_concepto` y no «verificado»: dice
«este candidato sobrevive al filtro barato, ahora andá a mirar qué mide de verdad».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from modules.law_intel.registro import Indicador

Observacion = Tuple[str, float]

#: Δ porcentual contra la línea base por debajo del cual el candidato SOBREVIVE al filtro.
#: No es una tolerancia de "verdad": es dónde se corta el descarte barato. Un 2% no prueba
#: que midan lo mismo, y un 12% sí prueba bastante bien que no.
_TOLERANCIA_SOBREVIVE = 2.0
_TOLERANCIA_SALVEDAD = 10.0

VEREDICTOS: Dict[str, str] = {
    "revisar_concepto": ("reproduce la línea base de la ley; sobrevive al filtro barato y "
                         "AHORA hay que comprobar qué mide"),
    "revisar_concepto_con_salvedad": ("se acerca a la línea base sin reproducirla; si se ata, "
                                      "la diferencia se declara en el informe"),
    "descartar": "no reproduce la línea base: este candidato no mide lo que el indicador mide",
    "sin_dato_en_la_base": ("la serie existe y no llega al año que la ley fija como base: no "
                            "se puede contrastar contra el oráculo"),
    "sin_oraculo": ("el indicador no declara línea base numérica; esta comprobación no "
                    "aplica y hay que evaluarlo a mano"),
}


@dataclass(frozen=True)
class Sondeo:
    indicador: str
    veredicto: str
    base_ley: Optional[float] = None
    anio_base: Optional[str] = None
    valor_fuente: Optional[float] = None
    delta_pct: Optional[float] = None
    motivo: Optional[str] = None
    #: CÓMO se comparó contra la ley. Viaja porque un acierto promediando una
    #: ventana de seis años y uno contra un año exacto no son la misma evidencia,
    #: y quien decide el binding tiene que poder distinguirlos.
    lectura: Optional[str] = None

    @property
    def sobrevive(self) -> bool:
        """Si vale la pena gastar un conector en este candidato. NO es «está verificado»."""
        return self.veredicto.startswith("revisar_concepto")


#: La ley fecha algunas líneas base con una VENTANA en vez de un año: «Promedio 2005- 2010»,
#: «2006- 2008». Se acepta con y sin la palabra, porque el articulado usa las dos formas para
#: lo mismo, y el espacio suelto tras el guion es como quedó en la transcripción del PDF.
_RX_VENTANA = re.compile(r"^\s*(?:promedio\s+)?(\d{4})\s*-\s*(\d{4})\s*$", re.I)


def ventana_de(base_anio_texto: Optional[str]) -> Optional[Tuple[int, int]]:
    """`(desde, hasta)` de una línea base fechada con una ventana, o `None`.

    Devuelve `None` para un rango truncado como «2005-», que en el registro es un defecto de
    transcripción y no una ventana: adivinar el año que falta sería inventar el período sobre
    el que se promedia.
    """
    m = _RX_VENTANA.match(str(base_anio_texto or ""))
    if not m:
        return None
    desde, hasta = int(m.group(1)), int(m.group(2))
    return (desde, hasta) if hasta > desde else None


def _promedio_de_ventana(valores: Dict[str, float],
                         ventana: Tuple[int, int]) -> Tuple[Optional[float], str]:
    """Promedio de la ventana, o `None` con el motivo si no está COMPLETA.

    La completitud no es formalismo. Un promedio de tres años sobre una ventana de seis es
    otro número, y se parecería lo suficiente al de la ley como para pasar por bueno. Es la
    misma regla que hace que los conteos regionales solo se publiquen con las diez regiones
    presentes: promediar lo que hay produce una cifra que nadie pidió.
    """
    desde, hasta = ventana
    esperados = [str(a) for a in range(desde, hasta + 1)]
    faltan = [a for a in esperados if a not in valores]
    if faltan:
        return None, (f"la serie no cubre la ventana {desde}-{hasta} que declara la ley: "
                      f"faltan {faltan}")
    vals = [valores[a] for a in esperados]
    return sum(vals) / len(vals), ""


def sondear(ind: Indicador, obs: Sequence[Observacion],
            transformar=None) -> Sondeo:
    """Contrasta las observaciones de un candidato contra la línea base declarada por la ley.

    ``transformar`` lleva el valor de la fuente a la magnitud del indicador y es EL punto
    donde más se equivoca quien usa esto: el 2.19 salió con 752% de discrepancia porque la
    ley pide analfabetismo y el emisor publica alfabetización. Con el complemento coincide al
    0,4%. Un «no coincide» sin haber revisado la transformación no es un descarte: es una
    pregunta sin responder.
    """
    if not isinstance(ind.base_valor, (int, float)):
        return Sondeo(ind.id, "sin_oraculo",
                      motivo=f"línea base no numérica: {ind.base_valor!r}")
    base = float(ind.base_valor)
    valores = {str(p): float(v) for p, v in obs}

    # ── LA VENTANA ────────────────────────────────────────────────────────────────────
    # Para nueve indicadores la ley no fechó la línea base con un año sino con una ventana.
    # Rendirse ahí dejaba a esos indicadores SIN la comprobación fuerte, para siempre: no es
    # que el oráculo fallara, es que nunca se le preguntaba.
    #
    # Que la lectura correcta sea el promedio no se supuso, se comprobó sobre el 3.22: la
    # razón exportaciones/importaciones va de 0,639 a 0,850 dentro de la ventana y NINGÚN año
    # suelto cae a menos del 2% de la base legal; solo el promedio, a 0,9%. Con una serie
    # plana la coincidencia no diría nada, y por eso `lectura` viaja con el resultado.
    if not ind.base_anio:
        ventana = ventana_de(ind.base_anio_texto)
        if ventana is None:
            return Sondeo(ind.id, "sin_oraculo", base_ley=base,
                          anio_base=ind.base_anio_texto,
                          motivo=(f"la línea base no declara un año ni una ventana legible: "
                                  f"{ind.base_anio_texto!r}"))
        prom, falla = _promedio_de_ventana(valores, ventana)
        if prom is None:
            return Sondeo(ind.id, "sin_dato_en_la_base", base_ley=base,
                          anio_base=f"{ventana[0]}-{ventana[1]}", motivo=falla)
        return _veredicto(ind, base, f"{ventana[0]}-{ventana[1]}", prom, transformar,
                          lectura=f"promedio de la ventana {ventana[0]}-{ventana[1]} "
                                  f"({ventana[1] - ventana[0] + 1} años, completa)")

    anio = str(ind.base_anio)
    v = valores.get(anio)
    if v is None:
        # Tres situaciones distintas, y decirlas iguales manda al lector a la conclusión
        # equivocada. «La serie no devolvió observaciones» sobre una serie de seis años se
        # lee como que el conector está roto, cuando lo que pasa es que el legislador fijó
        # la base en un año que la fuente no cubre — que no es un defecto de nadie y se
        # resuelve distinto.
        cerca = sorted(p for p in valores if abs(int(p) - int(anio)) <= 3) if valores else []
        if cerca:
            motivo = f"la serie no tiene {anio}; sí tiene {cerca}"
        elif valores:
            rango = f"{min(valores)}-{max(valores)}"
            motivo = (f"la serie devuelve {len(valores)} observaciones ({rango}) y ninguna "
                      f"a menos de tres años de {anio}: el oráculo de la ley no la alcanza")
        else:
            motivo = "la serie no devolvió observaciones"
        return Sondeo(ind.id, "sin_dato_en_la_base", base_ley=base, anio_base=anio,
                      motivo=motivo)
    return _veredicto(ind, base, anio, v, transformar, lectura=f"año exacto {anio}")


def _veredicto(ind: Indicador, base: float, anio: str, v: float, transformar,
               lectura: str) -> Sondeo:
    """El contraste contra la línea base. Único lugar donde se decide el veredicto.

    Va aparte para que el camino del año exacto y el de la ventana promediada no puedan
    divergir: el umbral de tolerancia es el mismo y la ventana no lo afloja. Lo único que
    cambia entre los dos es CÓMO se leyó la base, y eso se publica en `lectura`.
    """
    v = float(transformar(v)) if transformar else float(v)
    # Una base de cero no admite delta porcentual y el indicador tampoco se juzga así: se
    # declara en vez de dividir por cero o inventar un 100%.
    if base == 0:
        return Sondeo(ind.id, "sin_oraculo", base_ley=base, anio_base=anio, valor_fuente=v,
                      motivo="la línea base es 0: el contraste porcentual no significa nada",
                      lectura=lectura)
    d = round(abs(v - base) / abs(base) * 100, 1)
    if d <= _TOLERANCIA_SOBREVIVE:
        ver = "revisar_concepto"
    elif d <= _TOLERANCIA_SALVEDAD:
        ver = "revisar_concepto_con_salvedad"
    else:
        ver = "descartar"
    return Sondeo(ind.id, ver, base_ley=base, anio_base=anio, valor_fuente=round(v, 4),
                  delta_pct=d, motivo=VEREDICTOS[ver], lectura=lectura)
