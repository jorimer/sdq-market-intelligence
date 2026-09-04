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
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import panel as panel_mod
from shared.data.bcrd_excel import canonical
from shared.data.periodos import fin_del_periodo

#: Cómo entra cada variable. `dlog` = variación logarítmica ×100; `nivel` = tal cual.
NIVEL, DLOG = "nivel", "dlog"


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
    Variable("pib_real", ("pib_real",), DLOG, mensual=False),
    Variable(
        "inflacion", (), NIVEL, codigo="bcrd.inflacion.inflacion.interanual",
        porque_este_codigo=(
            "`inflacion_interanual` no declara puente y no puede: la interanual NO es una "
            "columna del archivo del IPC —que publica el índice y su variación mensual— y "
            "la plataforma la computa. La serie que sí existe es la del conector del API, "
            "491 meses desde 1985, y es la que se usa."),
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
    out: Dict[str, float] = {}
    for a, b in zip(ks, ks[1:]):
        if serie[a] > 0 and serie[b] > 0:
            out[b] = (math.log(serie[b]) - math.log(serie[a])) * 100
    return out


@dataclass(frozen=True)
class BloqueArmado:
    trimestres: Tuple[str, ...]
    nombres: Tuple[str, ...]
    #: Matriz T×n, alineada a `trimestres`.
    Y: Tuple[Tuple[float, ...], ...]
    #: Qué variable recorta la muestra, y desde cuándo empieza cada una.
    inicio_por_variable: Dict[str, str]


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
    if not series or any(not s for s in series.values()):
        return BloqueArmado((), tuple(v.nombre for v in BLOQUE), (), inicio)

    comunes = set.intersection(*(set(s) for s in series.values()))
    if hasta:
        comunes = {t for t in comunes if t <= hasta}
    orden = sorted(comunes, key=lambda t: (fin_del_periodo(t) or date.min, t))
    Y = tuple(tuple(series[v.nombre][t] for v in BLOQUE) for t in orden)
    return BloqueArmado(tuple(orden), tuple(v.nombre for v in BLOQUE), Y, inicio)
