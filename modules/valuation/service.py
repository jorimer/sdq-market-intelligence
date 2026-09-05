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
    utilidad: Tuple[float, ...]
    #: ROE sobre patrimonio de APERTURA, uno por período con apertura disponible.
    roe_pct: Tuple[float, ...]


def historia_de(db: Session, bank_id: str) -> Historia:
    """Patrimonio y utilidad por período, del más viejo al más nuevo."""
    filas = db.execute(text(
        "SELECT period_end, patrimonio_tecnico, utilidad_neta FROM banking_data "
        "WHERE bank_id = :b AND patrimonio_tecnico IS NOT NULL "
        "ORDER BY period_end"), {"b": bank_id}).fetchall()
    periodos = tuple(str(f[0]) for f in filas)
    patrimonio = tuple(float(f[1]) for f in filas)
    utilidad = tuple(float(f[2]) if f[2] is not None else 0.0 for f in filas)
    roes: List[float] = []
    for i in range(1, len(patrimonio)):
        # Apertura = el cierre del período anterior. El primero no tiene apertura y por eso
        # no tiene ROE: se declara con un período menos en vez de inventarle una base.
        if patrimonio[i - 1] > 0:
            roes.append(er.roe_sobre_apertura(utilidad[i], patrimonio[i - 1]))
    return Historia(periodos, patrimonio, utilidad, tuple(roes))


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
    ke = cc.calcular(db, beta=pt.beta_de(tipo))
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
                          retencion=retencion, g_terminal_pct=g)
            valores.append(v.valor)
        except er.HorizonteInvalidoError as e:
            # `g >= Ke` en este extremo: se acorta el horizonte y se DECLARA, que es lo que
            # el plan pide en vez de forzar el cálculo.
            avisos.append(f"Ke = {k:.2f} %: {e}")
            valores.append(bv0)
    valor_alto, valor_bajo = max(valores), min(valores)

    spread_alto = roe - ke.bajo      # el extremo favorable
    spread_bajo = roe - ke.alto
    serie = tuple((p, r) for p, r in zip(historia.periodos[1:], historia.roe_pct))

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
        retencion=retencion,
        g_terminal_pct=g,
        evidencia_del_tipo=pt.evidencia_de(tipo),
    )


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
        "procedencia": {
            "fraccion_de_rubrica": lec.fraccion_de_rubrica,
            "retencion_supuesta": RETENCION,
            "retencion_evidencia": RETENCION_EVIDENCIA,
            "horizonte_anios": HORIZONTE,
        },
        "serie_spread": [{"periodo": p, "roe_pct": r} for p, r in lec.serie_spread],
        "advertencias": list(lec.advertencias),
    }
