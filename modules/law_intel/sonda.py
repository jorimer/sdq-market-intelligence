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

    @property
    def sobrevive(self) -> bool:
        """Si vale la pena gastar un conector en este candidato. NO es «está verificado»."""
        return self.veredicto.startswith("revisar_concepto")


def sondear(ind: Indicador, obs: Sequence[Observacion],
            transformar=None) -> Sondeo:
    """Contrasta las observaciones de un candidato contra la línea base declarada por la ley.

    ``transformar`` lleva el valor de la fuente a la magnitud del indicador y es EL punto
    donde más se equivoca quien usa esto: el 2.19 salió con 752% de discrepancia porque la
    ley pide analfabetismo y el emisor publica alfabetización. Con el complemento coincide al
    0,4%. Un «no coincide» sin haber revisado la transformación no es un descarte: es una
    pregunta sin responder.
    """
    if not isinstance(ind.base_valor, (int, float)) or not ind.base_anio:
        return Sondeo(ind.id, "sin_oraculo",
                      motivo=f"línea base no numérica o sin año: {ind.base_valor!r}")
    base = float(ind.base_valor)
    anio = str(ind.base_anio)
    valores = {str(p): v for p, v in obs}
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
    v = float(transformar(v)) if transformar else float(v)
    # Una base de cero no admite delta porcentual y el indicador tampoco se juzga así: se
    # declara en vez de dividir por cero o inventar un 100%.
    if base == 0:
        return Sondeo(ind.id, "sin_oraculo", base_ley=base, anio_base=anio, valor_fuente=v,
                      motivo="la línea base es 0: el contraste porcentual no significa nada")
    d = round(abs(v - base) / abs(base) * 100, 1)
    if d <= _TOLERANCIA_SOBREVIVE:
        ver = "revisar_concepto"
    elif d <= _TOLERANCIA_SALVEDAD:
        ver = "revisar_concepto_con_salvedad"
    else:
        ver = "descartar"
    return Sondeo(ind.id, ver, base_ley=base, anio_base=anio, valor_fuente=round(v, 4),
                  delta_pct=d, motivo=VEREDICTOS[ver])
