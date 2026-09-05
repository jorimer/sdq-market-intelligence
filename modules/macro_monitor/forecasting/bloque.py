"""El bloque de variables del BVAR: qué entra, en qué forma y desde cuándo.

Cinco variables, y la composición NO fue una preferencia: el spec la traía marcada
`[Guessing]`, «a confirmar con la data real». La confirmación tuvo dos vueltas.

La primera medición decía que la tasa activa arrancaba en 2017 y que el bloque de cinco
costaba 40 trimestres — porque el registro canónico solo declaraba el archivo vigente. El
BCRD publica la serie en cuatro archivos por período, y con los tres tramos históricos dados
de alta son 343 meses desde 1998. Con eso el cuello de botella vuelve a ser el PIB (2007-Q1),
que es lo que el spec asumía, y ya no hay que elegir entre el canal de crédito y la muestra.

**Cada variable entra en la forma en que es estacionaria**, que no es un detalle técnico: un
VAR sobre niveles no estacionarios estima relaciones espurias y sus intervalos no significan
nada. El PIB entra en variación logarítmica; las tasas y la inflación, que ya son
porcentajes, en NIVEL —diferenciarlas destruiría la información de política que el bloque
existe para capturar—; el tipo de cambio en variación logarítmica.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import panel as panel_mod
from shared.data.bcrd_excel import canonical
from shared.data.periodos import fin_del_periodo

#: Cómo entra cada variable. `dlog` = variación logarítmica ×100 contra el período
#: ANTERIOR; `interanual` = variación contra el mismo período del año anterior, en %;
#: `nivel` = tal cual.
NIVEL, DLOG, INTERANUAL = "nivel", "dlog", "interanual"

#: Qué MIDE la serie que produce cada transformación, una vez transformada. Es lo que
#: viaja con el número hasta la reconciliación sectorial, que no puede restar una tasa
#: anual de una trimestral y hasta ahora lo hacía sin que nada fallara.
MEDIDA_POR_TRANSFORMACION: Dict[str, str] = {
    NIVEL: panel_mod.INTERANUAL,   # las dos series a NIVEL del bloque (inflación y tasa
                                   # activa) ya vienen expresadas como variación
                                   # interanual del emisor; ver sus `porque_este_codigo`.
    DLOG: panel_mod.TRIMESTRAL,
    INTERANUAL: panel_mod.INTERANUAL,
}


@dataclass(frozen=True)
class Variable:
    nombre: str
    #: Claves del registro canónico que, empalmadas en orden, forman la serie.
    tramos: Tuple[str, ...]
    transformacion: str
    #: Mensual → se agrega a trimestre por promedio. Trimestral → se toma tal cual.
    mensual: bool = True
    #: Código de serie EXPLÍCITO, para las dos variables cuya entrada canónica no declara
    #: puente y no puede declararlo. El motivo va acá y no en un comentario suelto: elegir
    #: una serie concreta es una decisión de método y tiene que quedar a la vista.
    codigo: Optional[str] = None
    porque_este_codigo: str = ""


BLOQUE: Tuple[Variable, ...] = (
    Variable(
        "pib_real", ("pib_real",), INTERANUAL, mensual=False,
        porque_este_codigo=(
            "CORREGIDO. Entraba como DLOG entre trimestres CONSECUTIVOS, o sea una tasa "
            "TRIMESTRAL, mientras el panel sectorial mide interanual. `reconciliar` restaba "
            "una de la otra y publicaba la diferencia como «brecha contra el agregado».\n\n"
            "El costo, medido en el informe del 2026-09-05: la tabla sectorial mostró 8 de 18 "
            "actividades contrayéndose cuando el modelo crudo proyectaba las 18 positivas. "
            "Sobre la serie real (77 trimestres) el QoQ promedia +1,13 % y el YoY +4,54 %; la "
            "brecha publicada fue -3,536 pp. No era desacuerdo entre modelos: era la "
            "diferencia entre una tasa anual y una trimestral.\n\n"
            "Y el DLOG traía un segundo defecto encima. El indice del PIB que publica el BCRD "
            "es la serie ORIGINAL, sin desestacionalizar: su QoQ medio va de -1,13 % (Q3) a "
            "+4,67 % (Q4), 5,80 pp de amplitud puramente de calendario, asi que el titular "
            "dependia de en que trimestre caia el horizonte. El interanual no arrastra "
            "estacionalidad y es, ademas, la medida que la entrada canonica de `pib_real` "
            "declara citable: «el crecimiento (YoY del volumen) es invariante a la base».\n\n"
            "Costo medido del cambio: 3 observaciones de arranque (el bloque pasa de 76 a 73 "
            "trimestres, 2008-Q1 en vez de 2007-Q2). El bloque lo sigue anclando `pib_real` "
            "en los dos casos."),
    ),
    Variable(
        "inflacion", (), NIVEL,
        codigo="bcrd.xls.ipc_base_2019_2020.variacion_porcentual_12_meses",
        porque_este_codigo=(
            "CORREGIDO. Antes apuntaba a la serie del conector del API con el motivo escrito "
            "de que «la interanual NO es una columna del archivo del IPC». Eso era falso y no "
            "lo medí: el archivo publica `variacion_porcentual_12_meses`, que ES la "
            "interanual, con 511 meses desde 1984-01 y sin huecos.\n\n"
            "El costo de la suposición fue concreto. La serie del conector tiene un hueco de "
            "SEIS meses (2025-11 → 2026-04) que se lleva el trimestre 2026-Q1 entero; como el "
            "bloque es la intersección, el BVAR quedaba recortado en 2025-Q4 y sus dos "
            "horizontes publicables caían sobre trimestres YA CERRADOS. Medido en producción: "
            "el motor no podía emitir un solo pronóstico.\n\n"
            "Las dos series son la misma medición —diferencia media 0,0025 pp y máxima 0,0053 "
            "sobre los 493 meses en común, que es redondeo: el API sirve dos decimales y el "
            "archivo la precisión completa—, así que el cambio no mueve ningún número: "
            "destapa los seis meses que faltaban y suma un año de historia."),
    ),
    Variable("tpm", ("tpm",), NIVEL),
    Variable(
        "tipo_cambio", (), DLOG, mensual=False,
        codigo="bcrd.xls.tasa_dolar_referencia_mc.promtrimestral.venta",
        porque_este_codigo=(
            "`tipo_cambio` no declara puente porque el archivo publica catorce series —siete "
            "cortes por compra y venta— y cuál es «el» tipo de cambio depende del uso. Para "
            "un bloque TRIMESTRAL la elección es el promedio del trimestre, y de las dos "
            "puntas la de VENTA, que es la que enfrenta quien compra divisas para importar. "
            "166 trimestres desde 1985-Q1."),
    ),
    Variable("tasa_activa",
             ("tasa_activa_1998_2007", "tasa_activa_2008_2012",
              "tasa_activa_2013_2016", "tasa_activa"), NIVEL),
)


def _codigo(entrada_key: str, codigos: Sequence[str]) -> Optional[str]:
    entrada = next((e for e in canonical.registry() if e.key == entrada_key), None)
    if entrada is None:
        return None
    return canonical.codigo_de(entrada, codigos)


def serie_empalmada(db: Session, var: Variable, codigos: Sequence[str]) -> Dict[str, float]:
    """Los tramos de una variable, unidos en una sola serie.

    Los tramos NO solapan —el BCRD publica cada período en su archivo—, así que unirlos es
    concatenar y no promediar. El quiebre, cuando existe, se declara en `SERIES_NOTES`; acá
    no se corrige nada en silencio.
    """
    if var.codigo:
        return dict(panel_mod.observaciones(db, var.codigo))
    out: Dict[str, float] = {}
    for clave in var.tramos:
        code = _codigo(clave, codigos)
        if code is None:
            continue
        out.update(dict(panel_mod.observaciones(db, code)))
    return out


def _a_trimestre(serie: Dict[str, float], mensual: bool) -> Dict[str, float]:
    if not mensual:
        return {p: v for p, v in serie.items() if "-Q" in p}
    por: Dict[str, List[float]] = {}
    for p, v in serie.items():
        if len(p) == 7 and p[5] != "Q":
            por.setdefault(panel_mod.trimestre_de(p), []).append(v)
    return {t: sum(vs) / len(vs) for t, vs in por.items()}


def _transformar(serie: Dict[str, float], como: str) -> Dict[str, float]:
    if como == NIVEL:
        return dict(serie)
    ks = sorted(serie, key=lambda t: (fin_del_periodo(t) or date.min, t))
    if como == INTERANUAL:
        # La MISMA función que usa el panel sectorial, a proposito: cuando cada capa tenia la
        # suya, una media contra `t-1` y la otra contra `t-4`, las dos se llamaban «el
        # crecimiento del PIB», y la reconciliacion restaba una de la otra.
        return panel_mod.variacion_interanual_pct(serie, ks)
    out: Dict[str, float] = {}
    for a, b in zip(ks, ks[1:]):
        if serie[a] > 0 and serie[b] > 0:
            out[b] = (math.log(serie[b]) - math.log(serie[a])) * 100
    return out


def medida_de(nombre: str) -> str:
    """En qué MEDIDA queda la serie de una variable del bloque, ya transformada.

    Es lo que la reconciliacion sectorial necesita saber y no tenia como preguntar.
    """
    var = next((v for v in BLOQUE if v.nombre == nombre), None)
    if var is None:
        raise KeyError(f"{nombre!r} no es una variable del bloque")
    return MEDIDA_POR_TRANSFORMACION[var.transformacion]


@dataclass(frozen=True)
class BloqueArmado:
    trimestres: Tuple[str, ...]
    nombres: Tuple[str, ...]
    #: Matriz T×n, alineada a `trimestres`.
    Y: Tuple[Tuple[float, ...], ...]
    #: Qué variable recorta la muestra, y desde cuándo empieza cada una.
    inicio_por_variable: Dict[str, str]
    #: Hasta dónde llega CADA variable. El inicio se declaraba y el final no, y el final es
    #: el que cuesta horizontes: el bloque termina donde termina la variable más atrasada, y
    #: si esa variable tiene un hueco reciente el modelo pierde trimestres sin que nada avise.
    #: Pasó — un hueco de seis meses en la serie de inflación del conector del API se llevó
    #: 2026-Q1 entero, y con él la capacidad de emitir un solo pronóstico. Nada falló: el
    #: motor simplemente proyectaba trimestres ya cerrados.
    fin_por_variable: Dict[str, str] = field(default_factory=dict)

    @property
    def rezagadas(self) -> Tuple[str, ...]:
        """Las variables cuyo último dato queda por DEBAJO del máximo del bloque.

        Son las que están costando horizontes. Se nombran para que un operador pueda ver de
        quién depende, en vez de mirar un bloque corto sin explicación.
        """
        if not self.fin_por_variable:
            return ()
        tope = max(self.fin_por_variable.values())
        return tuple(sorted(n for n, f in self.fin_por_variable.items() if f < tope))


def armar(db: Session, *, hasta: Optional[str] = None) -> BloqueArmado:
    """El bloque alineado sobre los trimestres donde TODAS las variables tienen dato.

    La intersección es deliberada: un VAR con huecos rellenados estima sobre datos que nadie
    publicó. Lo que recorta la muestra se DECLARA en `inicio_por_variable`, para que quien
    lea el modelo sepa qué variable le está costando historia.
    """
    from sqlalchemy import text

    codigos = [r[0] for r in db.execute(text("select distinct series_code from mm_series"))]
    series: Dict[str, Dict[str, float]] = {}
    inicio: Dict[str, str] = {}
    for var in BLOQUE:
        cruda = serie_empalmada(db, var, codigos)
        trim = _transformar(_a_trimestre(cruda, var.mensual), var.transformacion)
        series[var.nombre] = trim
        if trim:
            inicio[var.nombre] = min(trim)
    fin = {n: max(s) for n, s in series.items() if s}
    if not series or any(not s for s in series.values()):
        return BloqueArmado((), tuple(v.nombre for v in BLOQUE), (), inicio, fin)

    comunes = set.intersection(*(set(s) for s in series.values()))
    if hasta:
        comunes = {t for t in comunes if t <= hasta}
    orden = sorted(comunes, key=lambda t: (fin_del_periodo(t) or date.min, t))
    Y = tuple(tuple(series[v.nombre][t] for v in BLOQUE) for t in orden)
    return BloqueArmado(tuple(orden), tuple(v.nombre for v in BLOQUE), Y, inicio, fin)
