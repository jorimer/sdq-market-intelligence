"""El FIN que la ley declaró, no el inventario de indicadores.

Un expediente de ley trae dos capas: los **fines** que el legislador se propuso —en la END
son cuatro ejes estratégicos, y la propia ley los nombra— y los **indicadores** con los que
decidió probarlos. El semáforo juzga indicador por indicador; este módulo agrega ese juicio
al nivel del fin, que es la pregunta que le importa a quien no viene a enmendar la ley:
*¿está consiguiendo lo que se propuso?*

**Por qué no basta con el resumen global.** «11 de 44 metas alcanzadas» no dice si el país
avanza en desarrollo social y retrocede en institucionalidad, o al revés. Y ese reparto es lo
único que convierte el marcador en una lectura: los cuatro fines de la END no van juntos.

**No todos los fines se pueden caracterizar, y los que no se DECLARAN.** El Eje 1 de la END
tiene 8 indicadores y el 4 tiene 4. Poner «institucionalidad no alcanza sus metas» sobre dos
observaciones es exactamente el error que este repositorio ya pagó: ordenar lo que no es
comparable. Un fin se caracteriza solo si supera `MINIMO_EVALUADOS` **y**
`FRACCION_MINIMA_DE_LA_LEY`; el que no llega sale igual, con el estado `no_caracterizable` y
el motivo escrito. Un veto silencioso se leería como que el fin no tiene problemas.

**Los dos umbrales se eligieron por ESTRUCTURA y se declaran acá antes que ningún resultado.**
Tres evaluados es el mínimo con el que una mayoría no la decide una sola observación; un
tercio del fin es el mínimo con el que la muestra no es una anécdota del fin. Ninguno se
movió para que un eje concreto cambiara de veredicto — y si alguna vez hay que moverlos, se
mueven acá, a la vista, y no dentro de la frase de un informe.

**`estancada` NO es `retrocede`, y acá tampoco se suman.** El módulo las cuenta por separado
porque el contexto del modelo ya lleva escrito que una serie plana no «se aleja»: fundirlas
en un solo contador volvería a meter por la puerta de atrás la palabra que la doctrina
prohíbe. Las dos incumplen; solo una se mueve en contra.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from modules.law_intel.registro import Indicador
from modules.law_intel.scoring.semaforo import Veredicto

#: Veredictos que cuentan como meta alcanzada al corte.
ALCANZAN = ("alcanzada", "en_trayectoria")

#: Veredictos que cuentan como meta NO alcanzada. `retrocede` y `estancada` están acá porque
#: incumplen, y además se cuentan aparte porque no dicen lo mismo.
NO_ALCANZAN = ("no_alcanzada", "no_alcanzara", "retrocede", "estancada")

#: Veredictos que NO entran al juicio del fin: o no hay medición, o la meta no se resta, o
#: hay serie sin certificar que el nivel sea comparable. Ninguno es incumplimiento.
SIN_VEREDICTO = ("sin_dato", "sin_medicion", "no_evaluable", "medido_sin_certificar")

#: Cuántos indicadores del fin hay que estar juzgando para poder decir algo del fin. Con dos,
#: una sola observación decide la mayoría y el enunciado se vuelve una anécdota con forma de
#: veredicto.
MINIMO_EVALUADOS = 3

#: Y qué fracción del fin tiene que cubrir esa muestra. Un tercio: por debajo, lo que se está
#: describiendo es la parte del fin que se dejó medir, no el fin.
FRACCION_MINIMA_DE_LA_LEY = 1.0 / 3.0

#: Los estados posibles de un fin. Salen de comparaciones, no de umbrales: cuál grupo es más
#: numeroso. Un umbral de porcentaje habría que defenderlo; una mayoría se comprueba mirando.
ESTADOS = {
    "alcanza_en_su_mayoria": "más metas alcanzadas que incumplidas, entre las evaluadas",
    "no_alcanza_en_su_mayoria": "más metas incumplidas que alcanzadas, entre las evaluadas",
    "dividido": "tantas alcanzadas como incumplidas",
    "no_caracterizable": ("este informe no juzga suficientes metas del fin como para decir "
                          "algo del fin"),
}


def _concuerda(n: int, singular: str, plural: str) -> str:
    """Concordancia de número en la frase publicada.

    No es cosmética: `frase()` es prosa que sale impresa en un informe que se vende, y «1 no
    se mueven» le dice al lector que el texto lo armó una máquina sin que nadie lo leyera.
    """
    return singular if n == 1 else plural


@dataclass(frozen=True)
class Fin:
    """Un fin de la ley, con TODOS sus denominadores al lado.

    Cada conteo nombra su población en el propio campo: `indicadores_que_la_ley_le_fija` y
    `evaluados_en_este_informe` no son el mismo denominador, y un porcentaje sobre el que no
    corresponde es la forma más barata de mentir en este producto.
    """

    eje: int
    nombre: str
    indicadores_que_la_ley_le_fija: int
    evaluados_en_este_informe: int
    alcanzadas: int
    no_alcanzadas: int
    retroceden: int
    estancadas: int
    sin_veredicto: int
    estado: str
    motivo_sin_caracterizar: Optional[str] = None

    @property
    def pct_alcanzadas_sobre_evaluados(self) -> Optional[float]:
        if not self.evaluados_en_este_informe:
            return None
        return round(100.0 * self.alcanzadas / self.evaluados_en_este_informe, 1)

    @property
    def pct_no_alcanzadas_sobre_evaluados(self) -> Optional[float]:
        """El complemento, servido. Toda razón viaja con el suyo: el redactor necesita las
        dos y la que falte la calcula él — y una división derivada es una cifra que el guard
        de respaldo no encuentra en el contexto."""
        if not self.evaluados_en_este_informe:
            return None
        return round(100.0 * self.no_alcanzadas / self.evaluados_en_este_informe, 1)

    @property
    def caracterizable(self) -> bool:
        return self.estado != "no_caracterizable"

    def frase(self) -> str:
        """La lectura del fin, ya redactada, para que el modelo la COPIE.

        Se computa acá y no se le pide al modelo que la derive de los conteos: derivar «la
        mayoría» de siete contra veintiuno es justo el tipo de relación que el modelo acierta
        de a ratos, y el informe oficial de la END ya demostró qué pasa cuando el redactor
        elige el adjetivo.
        """
        cabeza = (f"{self.nombre}: de los {self.indicadores_que_la_ley_le_fija} compromisos "
                  f"que la ley le fija, este informe juzga {self.evaluados_en_este_informe}")
        if not self.caracterizable:
            return (f"{cabeza}. No alcanzan para caracterizar el fin: "
                    f"{self.motivo_sin_caracterizar}.")
        cuerpo = (f"; {self.alcanzadas} "
                  f"{_concuerda(self.alcanzadas, 'alcanza', 'alcanzan')} su meta y "
                  f"{self.no_alcanzadas} no")
        partes = []
        if self.retroceden:
            partes.append(f"{self.retroceden} "
                          f"{_concuerda(self.retroceden, 'se aleja', 'se alejan')} de su meta")
        if self.estancadas:
            partes.append(f"{self.estancadas} "
                          f"{_concuerda(self.estancadas, 'no se mueve', 'no se mueven')} "
                          f"mientras la meta avanza")
        cola = f" De los que no alcanzan, {' y '.join(partes)}." if partes else ""
        return f"{cabeza}{cuerpo}.{cola}"


def clase_de(veredicto: str) -> str:
    """`alcanza` | `no_alcanza` | `sin_veredicto`, o levanta.

    Levanta a propósito ante un veredicto que no conoce: cuando el semáforo gane una
    categoría nueva —ya le pasó con `medido_sin_certificar`— tiene que romper acá y no caer
    en silencio del lado de «sin veredicto», que es donde un incumplimiento se vuelve
    invisible sin que nadie se entere.
    """
    if veredicto in ALCANZAN:
        return "alcanza"
    if veredicto in NO_ALCANZAN:
        return "no_alcanza"
    if veredicto in SIN_VEREDICTO:
        return "sin_veredicto"
    raise ValueError(
        f"veredicto '{veredicto}' sin clase declarada en fines.py: clasificalo antes de "
        f"agregarlo al semáforo, o el fin lo contará como si no existiera")


def _motivo(evaluados: int, de_la_ley: int) -> Optional[str]:
    if evaluados < MINIMO_EVALUADOS:
        return (f"solo {evaluados} de sus {de_la_ley} metas tienen veredicto, y hacen falta "
                f"{MINIMO_EVALUADOS}")
    if de_la_ley and evaluados / de_la_ley < FRACCION_MINIMA_DE_LA_LEY:
        return (f"los {evaluados} con veredicto son menos de un tercio de los {de_la_ley} "
                f"que la ley le fija")
    return None


def por_fin(indicadores: Sequence[Indicador], veredictos: Sequence[Veredicto],
            nombres: Optional[Dict[int, str]] = None) -> List[Fin]:
    """El juicio agregado por fin, en el orden en que la ley los numera.

    `nombres` sale del propio expediente (`meta['ejes']`). Si la ley no los nombra, el fin se
    rotula «Eje N» — que es cierto — en vez de inventarle un título.
    """
    nombres = nombres or {}
    de_indicador = {v.indicador: v for v in veredictos}
    ejes = sorted({i.eje for i in indicadores})
    out: List[Fin] = []
    for eje in ejes:
        del_eje = [i for i in indicadores if i.eje == eje]
        conteo = {"alcanza": 0, "no_alcanza": 0, "sin_veredicto": 0}
        retroceden = estancadas = 0
        for ind in del_eje:
            v = de_indicador.get(ind.id)
            if v is None:
                conteo["sin_veredicto"] += 1
                continue
            conteo[clase_de(v.veredicto)] += 1
            retroceden += v.veredicto == "retrocede"
            estancadas += v.veredicto == "estancada"
        evaluados = conteo["alcanza"] + conteo["no_alcanza"]
        motivo = _motivo(evaluados, len(del_eje))
        if motivo is not None:
            estado = "no_caracterizable"
        elif conteo["alcanza"] > conteo["no_alcanza"]:
            estado = "alcanza_en_su_mayoria"
        elif conteo["no_alcanza"] > conteo["alcanza"]:
            estado = "no_alcanza_en_su_mayoria"
        else:
            estado = "dividido"
        out.append(Fin(
            eje=eje, nombre=nombres.get(eje, f"Eje {eje}"),
            indicadores_que_la_ley_le_fija=len(del_eje),
            evaluados_en_este_informe=evaluados,
            alcanzadas=conteo["alcanza"], no_alcanzadas=conteo["no_alcanza"],
            retroceden=retroceden, estancadas=estancadas,
            sin_veredicto=conteo["sin_veredicto"],
            estado=estado, motivo_sin_caracterizar=motivo))
    return out


def publicable(fines: Sequence[Fin]) -> Dict[str, object]:
    """Lo que viaja al contexto del modelo: los fines resueltos, con su frase ya escrita.

    Los no caracterizables van en la misma lista y NO aparte: sacarlos los haría desaparecer
    del informe, y que un fin de la ley no se pueda juzgar es de las cosas más informativas
    que este producto tiene para decir.
    """
    return {
        "fines_de_la_ley_computados": [
            {"eje": f.eje, "nombre": f.nombre,
             "indicadores_que_la_ley_le_fija": f.indicadores_que_la_ley_le_fija,
             "evaluados_en_este_informe": f.evaluados_en_este_informe,
             "alcanzadas": f.alcanzadas, "no_alcanzadas": f.no_alcanzadas,
             "retroceden": f.retroceden, "estancadas": f.estancadas,
             "sin_veredicto": f.sin_veredicto,
             "pct_alcanzadas_sobre_evaluados": f.pct_alcanzadas_sobre_evaluados,
             "pct_no_alcanzadas_sobre_evaluados": f.pct_no_alcanzadas_sobre_evaluados,
             "estado": f.estado, "motivo_sin_caracterizar": f.motivo_sin_caracterizar,
             "lectura_ya_redactada": f.frase()}
            for f in fines],
        "caracterizables": sum(1 for f in fines if f.caracterizable),
        "total_de_fines": len(fines),
        "regla_del_fin": (
            "El fin es la unidad de lectura de este informe: el lector quiere saber si la ley "
            "está consiguiendo lo que se propuso, no cuántos indicadores tiene. Copiá "
            "`lectura_ya_redactada` y no derives la mayoría de los conteos. Un fin con estado "
            "`no_caracterizable` NO se omite y NO se presenta como si cumpliera: se dice que "
            "el informe no juzga suficientes de sus metas, y esa es una afirmación sobre la "
            "evidencia disponible, nunca sobre el desempeño del fin."),
        "regla_de_la_comparacion_entre_fines": (
            "No ordenes los fines entre sí por porcentaje de cumplimiento: están medidos "
            "sobre denominadores distintos y con coberturas distintas. Un fin con 2 de 8 "
            "juzgados no se compara con uno de 28 de 48."),
    }
