"""Excess Return (residual income). Acá se decide si el modelo es correcto.

    valor = BV₀ + Σ_{t=1..T} RI_t/(1+Ke)^t + TV/(1+Ke)^T
    RI_t  = (ROE_t − Ke) × BV_{t−1}
    TV    = RI_{T+1} / (Ke − g)

Una entidad vale su libro **más el valor presente de lo que gane por encima de lo que su
capital exige**. De ahí sale que el spread `ROE − Ke` sea la lectura y no el valor.

**El terminal es una perpetuidad de RESIDUAL INCOME, no de utilidad.** Es el error que hunde
el modelo entero: con el terminal sobre utilidad, una entidad con `ROE = Ke` —que por
definición no crea ni destruye valor— saldría valiendo MÁS que su libro. El modelo diría que
existe valor donde no lo hay, para todas las entidades a la vez.

**Y se descuenta por `(1+Ke)^T`, no por `(1+Ke)^(T+1)`.** El terminal ya está expresado en
valor al momento T; descontarlo un período de más lo subestima sistemáticamente.

**El ROE se recalcula sobre patrimonio de APERTURA.** La SIB publica ROE sobre patrimonio
PROMEDIO; son bases distintas y mezclarlas mete un error sistemático proporcional al
crecimiento —cuanto más crece la entidad, más grande el error, y siempre en la misma
dirección—. El publicado queda como control de consistencia, nunca como insumo.

**Clean surplus no se cumple.** El balance de la SIB trae revaluaciones y ajustes de
inversiones disponibles para la venta, así que `BV_t ≠ BV_{t−1} + utilidad − dividendos`. La
diferencia se reporta como **partida explícita** y no se absorbe: absorberla la haría
desaparecer dentro del valor, que es donde nadie la puede auditar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


class HorizonteInvalidoError(ValueError):
    """`g >= Ke`: la perpetuidad no converge.

    Con `g = b × ROE` la condición NO está garantizada —una entidad muy rentable que retiene
    mucho la viola sin nada raro—, y si se calcula igual, el terminal sale negativo o
    explota. No se corrige en silencio: se acorta el horizonte explícito y se declara.
    """


@dataclass(frozen=True)
class Periodo:
    """Un año del horizonte explícito, con todo lo que hace falta para auditarlo."""

    t: int
    bv_apertura: float
    roe_pct: float
    #: `(ROE − Ke) × BV_apertura`. Positivo = crea valor ese año.
    residual_income: float
    factor_descuento: float
    vp_residual_income: float
    #: La diferencia entre el patrimonio proyectado por clean surplus y el observado. Viaja
    #: por período y no agregada: una diferencia que se compensa entre años no es lo mismo
    #: que una que se acumula, y agregarla borra esa distinción.
    ajuste_clean_surplus: float = 0.0


@dataclass(frozen=True)
class Valuacion:
    ke_pct: float
    bv_inicial: float
    periodos: Tuple[Periodo, ...]
    #: Valor terminal EN EL MOMENTO T (sin descontar). Se guarda aparte del descontado para
    #: que el descuento sea auditable en vez de estar embebido en un solo número.
    terminal_en_T: float
    terminal_descontado: float
    valor: float
    g_pct: float
    #: Suma de los ajustes de clean surplus. Partida EXPLÍCITA, nunca absorbida en el valor.
    ajuste_clean_surplus_total: float = 0.0
    advertencias: Tuple[str, ...] = ()

    @property
    def exceso_sobre_libro(self) -> float:
        return self.valor - self.bv_inicial

    @property
    def pb_implicito(self) -> float:
        """P/B DERIVADO, no asumido: sale del valor, no lo produce."""
        return self.valor / self.bv_inicial if self.bv_inicial else 0.0

    @property
    def vp_de_los_excesos(self) -> float:
        return sum(p.vp_residual_income for p in self.periodos)


def crecimiento_sostenible(roe_pct: float, retencion: float) -> float:
    """`g = b × ROE`. Es lo que la entidad puede crecer reinvirtiendo, sin capital nuevo."""
    return retencion * roe_pct


def verificar_convergencia(g_pct: float, ke_pct: float) -> None:
    """`g < Ke` ESTRICTO, antes de calcular nada.

    Verificar después es tarde: la perpetuidad ya devolvió un número —negativo o enorme— que
    parece un resultado.
    """
    if g_pct >= ke_pct:
        raise HorizonteInvalidoError(
            f"g = {g_pct:.2f} % no es menor que Ke = {ke_pct:.2f} %: la perpetuidad no "
            "converge. No se calcula un terminal con esta combinación — se acorta el "
            "horizonte explícito hasta que el crecimiento ceda, y se declara.")


def valuar(*, bv_inicial: float, ke_pct: float, roe_por_periodo: Sequence[float],
           retencion: float, roe_terminal_pct: Optional[float] = None,
           g_terminal_pct: Optional[float] = None,
           patrimonio_observado: Optional[Sequence[float]] = None) -> Valuacion:
    """El modelo completo.

    *roe_por_periodo* son los ROE del horizonte explícito, en %. *retencion* es `b`.
    *patrimonio_observado*, si se pasa, es el patrimonio publicado de cada cierre: con él se
    computa el ajuste de clean surplus por período.
    """
    if bv_inicial <= 0:
        raise ValueError("el patrimonio inicial tiene que ser positivo para valuar")
    ke = ke_pct / 100.0
    avisos: List[str] = []

    roe_T = roe_terminal_pct if roe_terminal_pct is not None else (
        roe_por_periodo[-1] if roe_por_periodo else ke_pct)
    g_pct = (g_terminal_pct if g_terminal_pct is not None
             else crecimiento_sostenible(roe_T, retencion))
    verificar_convergencia(g_pct, ke_pct)

    periodos: List[Periodo] = []
    bv = float(bv_inicial)
    ajuste_total = 0.0
    for i, roe_pct in enumerate(roe_por_periodo, start=1):
        # RI sobre el patrimonio de APERTURA, que es el que estuvo disponible para ganar.
        ri = (roe_pct - ke_pct) / 100.0 * bv
        fd = (1.0 + ke) ** i
        ajuste = 0.0
        # Clean surplus: el patrimonio de cierre proyectado contra el observado.
        bv_cierre_proyectado = bv * (1.0 + crecimiento_sostenible(roe_pct, retencion) / 100.0)
        if patrimonio_observado is not None and i - 1 < len(patrimonio_observado):
            ajuste = float(patrimonio_observado[i - 1]) - bv_cierre_proyectado
            ajuste_total += ajuste
        periodos.append(Periodo(
            t=i, bv_apertura=bv, roe_pct=roe_pct, residual_income=ri,
            factor_descuento=fd, vp_residual_income=ri / fd,
            ajuste_clean_surplus=ajuste))
        # El patrimonio del año siguiente: el OBSERVADO cuando existe, porque el modelo no
        # tiene por qué imponerle su proyección a un dato publicado.
        bv = (float(patrimonio_observado[i - 1])
              if patrimonio_observado is not None and i - 1 < len(patrimonio_observado)
              else bv_cierre_proyectado)

    if ajuste_total:
        avisos.append(
            f"Clean surplus no se cumple: {ajuste_total:+,.0f} entre el patrimonio "
            "proyectado y el publicado, acumulado en el horizonte. Va como partida "
            "explícita — el balance de la SIB trae revaluaciones y ajustes de inversiones "
            "disponibles para la venta que no pasan por resultados.")

    # ── El terminal: perpetuidad de RESIDUAL INCOME ──
    # RI_{T+1} sobre el patrimonio de apertura del período T+1, que es `bv`.
    ri_terminal = (roe_T - ke_pct) / 100.0 * bv
    terminal_en_T = ri_terminal / ((ke_pct - g_pct) / 100.0)
    # Descontado por (1+Ke)^T: el terminal YA está expresado en valor al momento T.
    t_final = len(roe_por_periodo)
    terminal_descontado = terminal_en_T / ((1.0 + ke) ** t_final) if t_final else terminal_en_T

    valor = bv_inicial + sum(p.vp_residual_income for p in periodos) + terminal_descontado
    return Valuacion(
        ke_pct=ke_pct, bv_inicial=float(bv_inicial), periodos=tuple(periodos),
        terminal_en_T=terminal_en_T, terminal_descontado=terminal_descontado,
        valor=valor, g_pct=g_pct, ajuste_clean_surplus_total=ajuste_total,
        advertencias=tuple(avisos))


def roe_sobre_apertura(utilidad: float, patrimonio_apertura: float) -> float:
    """ROE en %, sobre patrimonio de APERTURA.

    La SIB publica ROE sobre patrimonio PROMEDIO. Son bases distintas: con crecimiento del
    patrimonio, el promedio es mayor que la apertura, así que el ROE publicado es MENOR que
    éste, y la brecha crece con el crecimiento. Mezclarlos mete un error sistemático — nunca
    aleatorio — proporcional a cuánto crece la entidad.
    """
    if patrimonio_apertura <= 0:
        raise ValueError("el patrimonio de apertura tiene que ser positivo")
    return utilidad / patrimonio_apertura * 100.0


def control_contra_el_publicado(roe_propio_pct: float,
                                roe_publicado_pct: Optional[float]) -> Optional[float]:
    """La diferencia contra el ROE que publica la SIB. Es un CONTROL, no un insumo.

    Se reporta para que quien lea pueda contrastar, y porque una diferencia grande o de signo
    inesperado delata un problema en la utilidad o en el patrimonio antes que en el modelo.
    """
    if roe_publicado_pct is None:
        return None
    return round(roe_propio_pct - roe_publicado_pct, 4)
