"""Arma la valuación de una entidad: del balance publicado al spread, y de ahí al valor.

**El orden importa y es el del informe.** Primero `ROE − Ke`, después el valor. Un consejo que
ve el spread entiende la palanca; uno que ve solo el valor discute el supuesto.

**Todo en RD$.** El patrimonio y la utilidad vienen de los estados de la SIB en pesos, y `Ke`
se construye sobre la curva en pesos. El cruce de monedas lo veta `cost_of_capital.spread`.

**El ROE se recalcula acá, sobre patrimonio de APERTURA**, y no se toma el que publica la SIB
—que va sobre patrimonio promedio—. La diferencia se reporta como control.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from modules.valuation.engine import cost_of_capital as cc
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine import excess_return as er
from modules.valuation.engine import por_tipo as pt

#: Horizonte explícito, en años. Cinco es lo que la historia disponible sostiene: el balance
#: publicado por entidad arranca en 2020, así que proyectar diez sería extrapolar el doble de
#: lo que se observó.
HORIZONTE = 5
#: Retención de utilidades. RÚBRICA declarada: los dividendos por entidad no son públicos en
#: RD, así que `b` se supone y su peso se muestra — entra en `g = b × ROE`, que gobierna el
#: terminal.
RETENCION = 0.60
RETENCION_EVIDENCIA = (
    "La política de dividendos por entidad no se publica en República Dominicana, así que la "
    "retención es un SUPUESTO. Entra en `g = b × ROE`, que gobierna el terminal: por eso se "
    "declara como rúbrica en vez de esconderse dentro del crecimiento."
)


@dataclass(frozen=True)
class Historia:
    """Lo observado, del estado publicado. Nada de esto es supuesto."""

    periodos: Tuple[str, ...]
    patrimonio: Tuple[float, ...]
    #: La utilidad ACUMULADA del ejercicio tal cual la publica la SIB; `None` donde no vino.
    utilidad: Tuple[Optional[float], ...]
    #: ROE de DOCE MESES sobre el patrimonio de doce meses antes, uno por corte con ventana.
    roe_pct: Tuple[float, ...]
    #: Los cortes que tienen ROE, alineados con `roe_pct`. No son todos: el primer año no
    #: tiene apertura y un corte sin utilidad publicada no tiene ventana.
    periodos_con_roe: Tuple[str, ...] = ()


def _un_anio_antes(corte: date) -> Optional[date]:
    try:
        return date(corte.year - 1, corte.month, corte.day)
    except ValueError:  # 29-feb
        return None


def utilidad_de_doce_meses(ytd: Dict[date, Optional[float]], corte: date) -> Optional[float]:
    """La utilidad de los últimos doce meses cerrados en *corte*, o `None`.

    La SIB publica el estado de resultados ACUMULADO del ejercicio (Q1 = 3 meses, Q2 = 6…).
    Dividir ese acumulado por el patrimonio del trimestre anterior daba un «ROE» de 3, 6 o 9
    meses en cada corte intermedio, y la mediana de los últimos cuatro publicaba ~60 % del
    ROE real — con Ke de 14–20 %, «destruye valor» para entidades que no lo hacen. Es la
    misma ventana que banking ya mide en `banking_score/scoring/ttm.py`:

        TTM(Y, m) = acumulado(Y, m) + ejercicio_completo(Y−1) − acumulado(Y−1, m)

    En diciembre el acumulado YA cubre doce meses. Sin los tres insumos no hay ventana, y se
    devuelve `None`: un corte sin utilidad publicada no vale cero.
    """
    actual = ytd.get(corte)
    if actual is None:
        return None
    if corte.month == 12:
        return actual
    mismo_corte_previo = _un_anio_antes(corte)
    if mismo_corte_previo is None:
        return None
    ejercicio_previo = ytd.get(date(corte.year - 1, 12, 31))
    acumulado_previo = ytd.get(mismo_corte_previo)
    if ejercicio_previo is None or acumulado_previo is None:
        return None
    return actual + ejercicio_previo - acumulado_previo


def historia_de(db: Session, bank_id: str) -> Historia:
    """Patrimonio y utilidad por corte, del más viejo al más nuevo, y el ROE de doce meses.

    Sobre patrimonio de APERTURA, y apertura es el patrimonio de DOCE MESES ANTES —no el del
    corte anterior—: con cortes trimestrales, el corte anterior está a tres meses y una
    utilidad anual sobre un patrimonio de tres meses atrás tampoco es un ROE.
    """
    filas = db.execute(text(
        "SELECT period_end, patrimonio_tecnico, utilidad_neta FROM banking_data "
        "WHERE bank_id = :b AND patrimonio_tecnico IS NOT NULL "
        "ORDER BY period_end"), {"b": bank_id}).fetchall()
    cortes = [_como_fecha(f[0]) for f in filas]
    periodos = tuple(c.isoformat() for c in cortes)
    patrimonio = tuple(float(f[1]) for f in filas)
    utilidad: Tuple[Optional[float], ...] = tuple(
        float(f[2]) if f[2] is not None else None for f in filas)
    por_corte = dict(zip(cortes, patrimonio))
    ytd: Dict[date, Optional[float]] = dict(zip(cortes, utilidad))
    roes: List[float] = []
    con_roe: List[str] = []
    for corte in cortes:
        apertura = _un_anio_antes(corte)
        base = por_corte.get(apertura) if apertura else None
        doce_meses = utilidad_de_doce_meses(ytd, corte)
        if base is None or base <= 0 or doce_meses is None:
            continue  # sin ventana de doce meses no hay ROE: se declara con un corte menos
        roes.append(er.roe_sobre_apertura(doce_meses, base))
        con_roe.append(corte.isoformat())
    return Historia(periodos, patrimonio, utilidad, tuple(roes), tuple(con_roe))


def _como_fecha(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _roe_proyectado(historia: Historia, n: int = 4) -> Optional[float]:
    """La mediana de los últimos ROE observados.

    Mediana y no promedio: un trimestre atípico —una venta de activos, una provisión
    extraordinaria— arrastra el promedio hacia un ROE que la entidad no sostiene, y el
    terminal lo perpetúa.
    """
    if not historia.roe_pct:
        return None
    ultimos = sorted(historia.roe_pct[-n:])
    m = len(ultimos) // 2
    return ultimos[m] if len(ultimos) % 2 else (ultimos[m - 1] + ultimos[m]) / 2.0


@dataclass(frozen=True)
class Lectura:
    """La valuación completa de una entidad. El spread va PRIMERO, como en el informe."""

    entidad: str
    periodo: str
    moneda: str
    # ── la lectura ──
    roe_proyectado_pct: float
    ke_bajo_pct: float
    ke_alto_pct: float
    spread_bajo_pp: float
    spread_alto_pp: float
    cambia_de_signo: bool
    # ── el valor, que es consecuencia ──
    patrimonio_libro: float
    valor_bajo: float
    valor_alto: float
    pb_bajo: float
    pb_alto: float
    # ── procedencia y límites ──
    fraccion_de_rubrica: float
    advertencias: Tuple[str, ...]
    serie_spread: Tuple[Tuple[str, float], ...] = ()
    #: El tipo que la SIB le asigna. Decide beta y retención, así que viaja con el número:
    #: dos valuaciones con distinto tipo no son comparables sin saberlo.
    tipo_de_entidad: str = ""
    #: La retención usada, MEDIDA por tipo. Antes era un 0,60 de rúbrica igual para todos.
    retencion: float = RETENCION
    #: El crecimiento terminal efectivo, ya con el techo aplicado si mordió.
    g_terminal_pct: float = 0.0
    #: Qué sostiene los parámetros de este tipo. Va al informe.
    evidencia_del_tipo: str = ""
    #: La persistencia del exceso, MEDIDA por tipo. Gobierna el terminal: con ω < 1 el
    #: exceso se erosiona y el terminal queda acotado por los dos lados.
    persistencia: float = 0.0
    #: Los TÉRMINOS del Ke que produjeron esta cifra, para que la sección de supuestos los
    #: publique tal cual fueron y no como constantes leídas al renderizar: un informe en
    #: caché tiene que decir la beta con la que se valuó, no la que rige hoy.
    rf_pct: Tuple[float, float] = (0.0, 0.0)
    beta: Tuple[float, float] = (0.0, 0.0)
    erp: Tuple[float, float] = (0.0, 0.0)
    n_observaciones_rf: int = 0
    #: Primer y último período de la ventana de la Rf. Sin fechas, un rango no se juzga.
    rf_ventana: Tuple[str, str] = ("", "")

    @property
    def destruye_valor(self) -> bool:
        """Solo cuando el spread es negativo en TODO el rango. Si cambia de signo, la
        respuesta honesta no es «destruye» sino «depende», y eso se dice aparte."""
        return self.spread_alto_pp < 0


def _tipo_de(db: Session, bank_id: str) -> Optional[str]:
    """El tipo que la Superintendencia le asigna a la entidad. Decide beta y retención."""
    from sqlalchemy import text as _sql
    try:
        fila = db.execute(_sql("SELECT bank_type FROM banks WHERE id = :b"),
                          {"b": bank_id}).first()
    except Exception:  # noqa: BLE001
        return None
    return str(fila[0]) if fila and fila[0] else None


def valuar_entidad(db: Session, *, bank_id: str, nombre: str) -> Optional[Lectura]:
    """La valuación de una entidad, o ``None`` si no hay con qué.

    ``None`` y no un esqueleto con ceros: un motor sin su entrada no falla, DESAPARECE, y
    devolver ceros produciría una valuación de una entidad que nadie midió.

    **Los parámetros dependen del TIPO de entidad.** La Superintendencia supervisa cuatro
    clases y el modelo las trataba a las cuatro igual; la beta y la retención salen ahora de
    `engine/por_tipo.py`, con lo que sostiene a cada una.
    """
    historia = historia_de(db, bank_id)
    roe = _roe_proyectado(historia)
    if roe is None or not historia.patrimonio:
        return None
    tipo = _tipo_de(db, bank_id)
    beta = pt.beta_de(tipo)
    # La Rf se arma AL CORTE de la lectura: un informe a una fecha no usa tasas posteriores.
    ke = cc.calcular(db, beta=beta, hasta=_como_fecha(historia.periodos[-1]))
    if ke.alto <= 0:
        return None
    retencion = pt.retencion_de(tipo)

    bv0 = historia.patrimonio[-1]
    # El techo del crecimiento terminal. Sin él, una entidad muy rentable hace explotar la
    # perpetuidad: con el BHD daba un P/B de 12,23x contra un panel observado de 0,77x-2,73x.
    techo = cr.techo_nominal(db)
    g, aviso_g = cr.g_terminal(roe, retencion, techo)

    # Dos valuaciones, una por extremo de Ke. El extremo BAJO de Ke da el valor ALTO.
    valores: List[float] = []
    avisos: List[str] = list(ke.advertencias)
    if aviso_g:
        avisos.append(aviso_g)
    if not techo.es_medido:
        avisos.append(techo.evidencia)
    for k in (ke.bajo, ke.alto):
        try:
            v = er.valuar(bv_inicial=bv0, ke_pct=k, roe_por_periodo=[roe] * HORIZONTE,
                          retencion=retencion, g_terminal_pct=g,
                          persistencia=pt.persistencia_de(tipo), g_max_pct=techo.valor_pct)
            valores.append(v.valor)
        except er.HorizonteInvalidoError as e:
            # `g >= Ke` en este extremo: se acorta el horizonte y se DECLARA, que es lo que
            # el plan pide en vez de forzar el cálculo.
            avisos.append(f"Ke = {k:.2f} %: {e}")
            valores.append(bv0)
    valor_alto, valor_bajo = max(valores), min(valores)

    spread_alto = roe - ke.bajo      # el extremo favorable
    spread_bajo = roe - ke.alto
    serie = tuple(zip(historia.periodos_con_roe, historia.roe_pct))

    return Lectura(
        entidad=nombre, periodo=historia.periodos[-1], moneda=cc.MONEDA,
        roe_proyectado_pct=round(roe, 4),
        ke_bajo_pct=ke.bajo, ke_alto_pct=ke.alto,
        spread_bajo_pp=round(spread_bajo, 4), spread_alto_pp=round(spread_alto, 4),
        cambia_de_signo=cc.cambia_de_signo(ke, roe, moneda_roe=cc.MONEDA),
        patrimonio_libro=bv0, valor_bajo=valor_bajo, valor_alto=valor_alto,
        pb_bajo=round(valor_bajo / bv0, 4) if bv0 else 0.0,
        pb_alto=round(valor_alto / bv0, 4) if bv0 else 0.0,
        fraccion_de_rubrica=ke.fraccion_de_rubrica,
        advertencias=tuple(avisos),
        serie_spread=serie,
        tipo_de_entidad=tipo or "",
        rf_pct=_rf_de(ke), beta=beta, erp=cc.ERP, n_observaciones_rf=ke.n_observaciones_rf,
        rf_ventana=ke.ventana_rf,
        retencion=retencion,
        g_terminal_pct=g,
        evidencia_del_tipo=pt.evidencia_de(tipo),
        persistencia=pt.persistencia_de(tipo),
    )


def _rf_de(ke: cc.CostoDeCapital) -> Tuple[float, float]:
    """El único término REAL del Ke, con su rango. Se lee de la descomposición y no se
    recomputa: dos cálculos del mismo hecho se desincronizan."""
    for t in ke.terminos:
        if not t.es_rubrica:
            return (t.bajo, t.alto)
    return (0.0, 0.0)


def a_payload(lec: Lectura) -> Dict[str, Any]:
    """La forma que consume el producto. El spread va primero, y el valor después."""
    return {
        "entidad": lec.entidad, "periodo": lec.periodo, "moneda": lec.moneda,
        "spread": {
            "roe_proyectado_pct": lec.roe_proyectado_pct,
            "ke_rango_pct": [lec.ke_bajo_pct, lec.ke_alto_pct],
            "spread_pp": [lec.spread_alto_pp, lec.spread_bajo_pp],
            "cambia_de_signo": lec.cambia_de_signo,
            "destruye_valor": lec.destruye_valor,
        },
        "valor": {
            "patrimonio_libro": lec.patrimonio_libro,
            "rango": [lec.valor_bajo, lec.valor_alto],
            "pb_implicito": [lec.pb_bajo, lec.pb_alto],
        },
        # Los parámetros del TIPO viajan en el payload. Sin esto se pierden al reconstruir
        # la lectura, y el informe salía diciendo «entidad de intermediación» genérica, con
        # una persistencia de 0,0 en la sección de metodología. Es el mismo desync que ya
        # había entre las claves planas y las anidadas: dos lecturas del mismo hecho.
        "tipo_de_entidad": lec.tipo_de_entidad,
        "procedencia": {
            "fraccion_de_rubrica": lec.fraccion_de_rubrica,
            "retencion_supuesta": lec.retencion,
            "retencion_evidencia": RETENCION_EVIDENCIA,
            "persistencia": lec.persistencia,
            "g_terminal_pct": lec.g_terminal_pct,
            "evidencia_del_tipo": lec.evidencia_del_tipo,
            "horizonte_anios": HORIZONTE,
            "rf_pct": [lec.rf_pct[0], lec.rf_pct[1]],
            "beta": [lec.beta[0], lec.beta[1]],
            "erp": [lec.erp[0], lec.erp[1]],
            "n_observaciones_rf": lec.n_observaciones_rf,
            "rf_ventana": [lec.rf_ventana[0], lec.rf_ventana[1]],
        },
        "serie_spread": [{"periodo": p, "roe_pct": r} for p, r in lec.serie_spread],
        "advertencias": list(lec.advertencias),
    }
