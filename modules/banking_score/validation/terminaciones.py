"""Cohorte canónica de terminaciones del sistema financiero dominicano.

Por qué existe. El modelo de alerta temprana se describía como calibrado contra "todos los
quiebres de la historia", pero la única cohorte en código eran SEIS bancos nombrados
(``sib_historical_backtest.FAILED_COHORT``), de los cuales solo tres son evaluables por
ratios. El histórico del ledger tiene **224 salidas** entre 205 códigos de entidad, de las
cuales **99 son quiebras** por el estado en que la entidad dejó de reportar. Ese conjunto no
estaba armado, y los pesos vigentes no salieron de él.

El problema real no es encontrar las salidas —es distinguir la QUIEBRA de la fusión, el
renombre y la salida voluntaria—. Una entidad que deja de reportar puede haber sido
absorbida, haberse fusionado, haber cambiado de código, o haber muerto. Tratarlas igual
contamina la cohorte con casos que no son deterioro.

Cómo se resuelve, y qué NO se pretende. El ledger contable no dice por qué una entidad salió;
no hay campo de causa. Lo que sí dice es en qué ESTADO salió, y eso alcanza para la etiqueta
económica —que es la que importa en un régimen que absorbía y renombraba en vez de quebrar
formalmente—: una entidad con patrimonio negativo no fue una fusión estratégica, cualquiera
haya sido la forma legal del desenlace.

  insolvencia     patrimonio negativo, o mora ≥ 3× el piso de su tipo al salir.
  deterioro       mora sobre el piso de su tipo al salir, sin llegar a insolvencia.
  sana_al_salir   ratios presentes y dentro de lo normal → fusión, venta o salida voluntaria.
                  NO entra a la cohorte de quiebras.
  no_evaluable    sin ratios al corte de salida. Se declara; no se asume ni sana ni quebrada.

LINAJE — la trampa conocida. ``entidad_code`` es un slot que la SB reutiliza: BANCRÉDITO→LEÓN,
MERCANTIL→REPUBLIC BANK. Si un código llevó más de un nombre, la salida que se observa puede
ser la del SUCESOR y no la de la entidad que quebró. Esos casos se marcan con
``revisar_linaje`` para poder auditarlos — 83 de las 224 —, pero NO se excluyen: filtrarlos
"por prudencia" borraba a Bancrédito y a Mercantil, porque justamente las entidades absorbidas
son las que comparten código con su sucesor.

VALIDACIÓN: las cuatro quiebras sistémicas de 2003 caen donde deben. Baninter sale en 2003-05
como insolvencia —el mes exacto de la intervención—, Banco Nacional de Crédito (Bancrédito) en
2003-12, Banco Mercantil en 2005-03, y Banco Global en 2002-07. Ninguna de las tres primeras
era detectable keyeando por código.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.banking_score.validation.ew_calibration import morosidad_floor

logger = logging.getLogger("sdq.banking.terminaciones")

# Meses de rezago de publicación tolerados: más allá, la entidad salió del sistema.
EXIT_LAG_M = 6
# Múltiplo del piso de morosidad de su tipo a partir del cual la salida se lee como
# insolvencia y no como deterioro. Tres veces lo normal PARA SU TIPO —no un umbral plano—:
# una corporación de crédito opera con mora de dos dígitos y un banco múltiple no.
INSOLVENCIA_MULT = 3.0

NATURALEZAS = ("insolvencia", "deterioro", "sana_al_salir", "no_evaluable")


@dataclass(frozen=True)
class Terminacion:
    entidad_code: str
    entidad_nombre: str
    tipo_entidad: Optional[str]
    fecha_salida: date
    naturaleza: str
    evidencia: Tuple[str, ...]     # qué disparó la clasificación, para poder auditarla
    revisar_linaje: bool
    n_meses_serie: int
    morosidad_salida: Optional[float]
    apalancamiento_salida: Optional[float]

    @property
    def es_quiebra(self) -> bool:
        """La cohorte de quiebras: insolvencia + deterioro. `sana_al_salir` queda fuera —es
        una fusión o una venta— y `no_evaluable` también: no se cuenta como quiebra lo que no
        se pudo mirar."""
        return self.naturaleza in ("insolvencia", "deterioro")


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _meses(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def clasificar(fila: Dict, n_nombres: int, n_meses: int,
               fecha_salida: date) -> Terminacion:
    """Clasifica UNA salida por el estado en que la entidad dejó de reportar."""
    mora = _f(fila.get("morosidad_pct"))
    apa = _f(fila.get("apalancamiento_pct"))
    tipo = fila.get("tipo_entidad")
    piso = morosidad_floor(tipo)
    ev: List[str] = []
    if apa is not None and apa < 0:
        ev.append("patrimonio negativo")
    if mora is not None and mora >= INSOLVENCIA_MULT * piso:
        ev.append(f"morosidad {mora:.1f}% ≥ 3× el piso de su tipo ({piso:.0f}%)")
    if ev:
        naturaleza = "insolvencia"
    elif mora is not None and mora > piso:
        naturaleza = "deterioro"
        ev.append(f"morosidad {mora:.1f}% sobre el piso de su tipo ({piso:.0f}%)")
    elif mora is not None:
        naturaleza = "sana_al_salir"
        ev.append(f"morosidad {mora:.1f}% dentro de lo normal para su tipo al salir")
    else:
        # Sin morosidad NO se declara sana. Un patrimonio contable positivo no es evidencia
        # de salud —casi toda entidad lo tiene hasta el trimestre en que no—, y en la era
        # temprana del ledger la mora apenas se reporta: aprobar por ausencia de dato mandaba
        # las quiebras de los años 90 al cajón de "fusiones". Es la doctrina de siempre: un
        # dato ausente se declara, no se rellena con el supuesto favorable.
        naturaleza = "no_evaluable"
        ev.append("sin morosidad al corte de salida; el patrimonio positivo no basta")
    return Terminacion(
        entidad_code=str(fila.get("entidad_code")),
        entidad_nombre=str(fila.get("entidad_nombre") or ""),
        tipo_entidad=tipo, fecha_salida=fecha_salida, naturaleza=naturaleza,
        evidencia=tuple(ev), revisar_linaje=n_nombres > 1, n_meses_serie=n_meses,
        morosidad_salida=mora, apalancamiento_salida=apa,
    )


def detectar(panel: Dict[str, Dict[date, Dict]],
             panel_end: Optional[date] = None) -> List[Terminacion]:
    """Todas las salidas del panel, clasificadas.

    LA UNIDAD ES LA INSTITUCIÓN (el nombre), NO EL CÓDIGO. ``entidad_code`` es un slot que la
    SB reutiliza: ``BANCRÉDITO - LEÓN`` es UN código que corre de 1981 a 2003 con un nombre y
    de 2004 a 2014 con otro; ``MERCANTIL - REPUBLIC BANK`` igual. Keyeando por código,
    Bancrédito y Mercantil —dos de las cuatro quiebras sistémicas de 2003— NUNCA SALEN: su
    serie continúa bajo el sucesor y la quiebra se vuelve invisible. Es el trampa que el
    propio ``sib_historical_backtest`` documenta y que hay que resolver acá también.

    Por eso se recorre cada RUN contiguo de un mismo nombre dentro de un código: el fin de un
    run que no llega al final del panel es una terminación, sea porque la entidad murió o
    porque el slot pasó a otra institución. La entidad que reporta hasta el final del panel
    (con el rezago tolerado) no salió.
    """
    if not panel:
        return []
    if panel_end is None:
        panel_end = max(d for s in panel.values() for d in s)
    out: List[Terminacion] = []
    for code, serie in panel.items():
        fechas = sorted(serie)
        if not fechas:
            continue
        # Runs contiguos por nombre dentro del código.
        runs: List[Tuple[str, List[date]]] = []
        for d in fechas:
            nom = str(serie[d].get("entidad_nombre") or "")
            if runs and runs[-1][0] == nom:
                runs[-1][1].append(d)
            else:
                runs.append((nom, [d]))
        for i, (nom, ds) in enumerate(runs):
            ultima = ds[-1]
            es_ultimo_run = i == len(runs) - 1
            if es_ultimo_run and _meses(ultima, panel_end) <= EXIT_LAG_M:
                continue    # sigue viva al final del panel
            # `revisar_linaje` marca que el CÓDIGO alojó más de una institución: la lectura
            # de esta salida puede confundirse con la del sucesor y pide revisión humana.
            out.append(clasificar(serie[ultima], len(runs), len(ds), ultima))
    return sorted(out, key=lambda t: t.fecha_salida)


def cohorte_canonica(terminaciones: Sequence[Terminacion], *,
                     solo_linaje_limpio: bool = False) -> List[Terminacion]:
    """Las quiebras utilizables para calibrar: insolvencia + deterioro.

    ``revisar_linaje`` NO excluye. Una primera versión filtraba esos casos por prudencia y el
    resultado fue perder a Bancrédito y a Mercantil —dos de las cuatro quiebras sistémicas de
    2003—, porque justamente las entidades absorbidas son las que comparten código con su
    sucesor. Con la detección por RUNS de nombre cada institución ya queda aislada; la marca
    sirve para auditar el caso, no para borrarlo.

    ``solo_linaje_limpio=True`` da el subconjunto conservador, para medir cuánto depende un
    resultado de los casos con código compartido — pero no es el default, porque ese
    subconjunto tiene un sesgo conocido: se come las quiebras que terminaron en absorción.
    """
    return [t for t in terminaciones
            if t.es_quiebra and (not solo_linaje_limpio or not t.revisar_linaje)]


def resumen(terminaciones: Sequence[Terminacion]) -> Dict[str, Any]:
    """Los conteos que hacen falta para saber sobre qué se está calibrando."""
    por_nat: Dict[str, int] = {n: 0 for n in NATURALEZAS}
    por_decada: Dict[int, int] = {}
    for t in terminaciones:
        por_nat[t.naturaleza] = por_nat.get(t.naturaleza, 0) + 1
        dec = t.fecha_salida.year // 10 * 10
        por_decada[dec] = por_decada.get(dec, 0) + 1
    return {
        "n_salidas": len(terminaciones),
        "por_naturaleza": por_nat,
        "por_decada": dict(sorted(por_decada.items())),
        "n_revisar_linaje": sum(1 for t in terminaciones if t.revisar_linaje),
        "n_cohorte_canonica": len(cohorte_canonica(terminaciones)),
        "n_cohorte_linaje_limpio": len(cohorte_canonica(terminaciones,
                                                        solo_linaje_limpio=True)),
    }


def formato(terminaciones: Sequence[Terminacion]) -> str:
    r = resumen(terminaciones)
    lineas = [f"Salidas detectadas: {r['n_salidas']}", ""]
    for nat in NATURALEZAS:
        lineas.append(f"  {nat:16} {r['por_naturaleza'].get(nat, 0):4}")
    lineas += ["",
               f"  requieren revisión de linaje: {r['n_revisar_linaje']}",
               f"  COHORTE CANÓNICA (quiebras utilizables): {r['n_cohorte_canonica']}"
               f"  ({r['n_cohorte_linaje_limpio']} si se excluyen los de código compartido"
               f" — subconjunto sesgado: pierde las quiebras absorbidas)",
               "", "  por década: " + ", ".join(f"{k}s: {v}"
                                                for k, v in r["por_decada"].items())]
    return "\n".join(lineas)
