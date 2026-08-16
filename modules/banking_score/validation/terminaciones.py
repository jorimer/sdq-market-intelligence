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

# Causas del registro CURADO (`data/terminaciones_curadas.yaml`). Mandan sobre la inferida.
CAUSAS_QUIEBRA = ("quiebra",)
CAUSAS_NO_QUIEBRA = ("fusion", "salida_voluntaria", "renombre")
RUTA_CURADAS = "data/terminaciones_curadas.yaml"


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
    # Etiqueta CURADA, cuando existe. Manda sobre `naturaleza`, que se infiere de los ratios.
    causa_curada: Optional[str] = None
    fuente_curada: Optional[str] = None

    @property
    def origen_etiqueta(self) -> str:
        """`curada` = viene de afuera de los ratios; `inferida` = del estado al salir.

        La distinción no es cosmética: un modelo calibrado sobre etiquetas inferidas tiene el
        predictor adentro de la etiqueta y su AUC está inflado. Es el mismo estándar con que
        `deal_scoring` separa sus labels ex-ante de los retrospectivos.
        """
        return "curada" if self.causa_curada else "inferida"

    @property
    def es_quiebra(self) -> bool:
        """La cohorte de quiebras. La causa curada MANDA: si el registro dice que fue una
        fusión, no importa en qué estado contable haya salido.

        Sin curaduría cae a la inferencia: insolvencia + deterioro. `sana_al_salir` queda
        fuera —es fusión o venta— y `no_evaluable` también: no se cuenta como quiebra lo que
        no se pudo mirar.
        """
        if self.causa_curada:
            return self.causa_curada in CAUSAS_QUIEBRA
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


def cargar_curadas(ruta: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """El registro curado, indexado por nombre normalizado de institución.

    Devuelve ``{}`` si el archivo no está o no se puede leer: la ausencia del registro degrada
    a etiquetas inferidas —que es peor pero honesto— y nunca tumba la calibración.
    """
    import pathlib as _pl

    import yaml  # type: ignore[import-untyped]

    destino = _pl.Path(ruta) if ruta else _pl.Path(__file__).resolve().parents[1] / RUTA_CURADAS
    try:
        doc = yaml.safe_load(destino.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:  # noqa: BLE001
        logger.warning("Registro curado ilegible (%s): se usan etiquetas inferidas.", e)
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for fila in doc.get("terminaciones") or []:
        nombre, causa = fila.get("nombre"), fila.get("causa")
        if not nombre or not causa or causa == "desconocida":
            continue
        # Una etiqueta sin procedencia es exactamente el problema que el registro vino a
        # resolver: se ignora en vez de aceptarse.
        if not fila.get("fuente"):
            logger.warning("Terminación curada sin fuente, ignorada: %s", nombre)
            continue
        out[_norm_nombre(str(nombre))] = {"causa": str(causa), "fuente": str(fila["fuente"])}
    return out


def _norm_nombre(s: str) -> str:
    """Nombre normalizado para emparejar el registro con el panel.

    Quita acentos y puntuación —el ledger escribe "Banco Domínico-Hispano" y la fuente
    "Banco Dominico Hispano"— pero NO hace match por substring: aflojar eso es como se
    produce el clásico APAP→Popular. La tolerancia al sufijo entre paréntesis se maneja
    aparte, en :func:`_claves_de`, generando claves alternativas explícitas.
    """
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9áéíóúñü ]+", " ", s)
    return " ".join(s.split())


def _claves_de(nombre: str) -> Tuple[str, ...]:
    """Claves con que una entidad puede aparecer: el nombre completo y, si trae un sufijo
    entre paréntesis, también el nombre sin él. El ledger escribe "Financiera Nacional de
    Créditos (Conacre)" y la fuente oficial "Financiera Nacional de Créditos"."""
    import re
    base = _norm_nombre(nombre)
    sin_parentesis = _norm_nombre(re.sub(r"\([^)]*\)", " ", nombre))
    return (base,) if sin_parentesis == base else (base, sin_parentesis)


def aplicar_curaduria(terminaciones: Sequence[Terminacion],
                      curadas: Optional[Dict[str, Dict[str, str]]] = None
                      ) -> List[Terminacion]:
    """Pega la etiqueta curada sobre la inferida donde exista."""
    from dataclasses import replace

    reg = cargar_curadas() if curadas is None else curadas
    out: List[Terminacion] = []
    usadas: set = set()
    for t in terminaciones:
        c = None
        for clave in _claves_de(t.entidad_nombre):
            if clave in reg:
                c = reg[clave]
                usadas.add(clave)
                break
        out.append(replace(t, causa_curada=c["causa"], fuente_curada=c["fuente"]) if c else t)
    # Una entrada curada que no empareja con ninguna salida NO HACE NADA, y en silencio. Es
    # la misma familia que el guard sin su input: no falla, desaparece. Se avisa siempre.
    for huerfana in sorted(set(reg) - usadas):
        logger.warning("Terminación curada que no empareja con ninguna salida del panel: %r "
                       "— revisá el nombre contra el ledger.", huerfana)
    return out


def huerfanas(terminaciones: Sequence[Terminacion],
              curadas: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
    """Entradas del registro que no emparejan con ninguna salida. Debe ser vacío."""
    reg = cargar_curadas() if curadas is None else curadas
    usadas = set()
    for t in terminaciones:
        for clave in _claves_de(t.entidad_nombre):
            if clave in reg:
                usadas.add(clave)
                break
    return sorted(set(reg) - usadas)


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


def validar_contra_curadas(terminaciones: Sequence[Terminacion]) -> Dict[str, Any]:
    """¿La clasificación automática acierta las salidas cuya causa SÍ conocemos?

    Es la prueba de aceptación que importa y que un AUC no da: un conjunto nombrado y
    verificable —¿marca como quiebra a Baninter, a Bancrédito, a Mercantil?, ¿deja afuera a
    las que se fusionaron estando sanas?—. Un modelo que ordena bien pero se come Baninter
    no sirve para lo que se vende.

    Mide la inferencia CONTRA la curaduría, así que solo corre sobre las filas curadas. Los
    desacuerdos son la lista de trabajo: o la regla automática está mal, o el registro lo está.
    """
    aciertos: List[str] = []
    fallos: List[Dict[str, str]] = []
    for t in terminaciones:
        if not t.causa_curada:
            continue
        esperado = t.causa_curada in CAUSAS_QUIEBRA
        # `es_quiebra` ya usa la curada; acá se pregunta qué habría dicho la INFERENCIA sola.
        inferido = t.naturaleza in ("insolvencia", "deterioro")
        if inferido == esperado:
            aciertos.append(t.entidad_nombre)
        else:
            fallos.append({"entidad": t.entidad_nombre,
                           "fecha": t.fecha_salida.isoformat(),
                           "curada": t.causa_curada, "inferida": t.naturaleza})
    n = len(aciertos) + len(fallos)
    return {"n_curadas": n, "n_aciertos": len(aciertos), "n_fallos": len(fallos),
            "tasa": round(len(aciertos) / n, 3) if n else None,
            "aciertos": aciertos, "fallos": fallos}


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
