"""Solvencia Basilea RECONSTRUIDA del ledger contable — serie de CONTEXTO, no de umbral.

Por qué existe. El histórico contable de la SB no trae solvencia Basilea: es regulatoria y
en RD arranca ~2004. El backtest y el motor la declaraban "no reconstruible". Eso confundía
dos cosas: que la SB no la *publicara* en 1995 no impide *computarla*, porque Basilea es una
transformación de cantidades que el balance sí tiene — patrimonio desagregado y activos por
clase de riesgo. El catálogo del ledger las tiene en las tres eras (1947-1996, 1997-2006,
2007-2026): caja, Banco Central, bancos del país/exterior, interbancarios, inversiones por
tipo, cartera, participaciones, intangibles; y capital pagado, adicional, reservas,
resultados acumulados, del ejercicio, revaluación, más subordinadas en pasivos.

QUÉ TAN BIEN FUNCIONA — medido, no supuesto. Se reconstruyó la ventana 2021-2026, donde el
ratio real SÍ se publica, y se comparó contra la solvencia de producción (539 observaciones,
26 entidades, endpoint ``/{bank_id}/indicator/solvencia``):

    banca múltiple                  n=182   |error| mediano 1.52 pp   p90 4.59 pp
    bancos de ahorro y crédito      n=105   |error| mediano 1.82 pp   p90 9.47 pp
    corporaciones de crédito        n= 63   |error| mediano 1.87 pp   p90 8.86 pp
    asociaciones de ahorros y prést n=189   |error| mediano 4.72 pp   p90 8.71 pp
    correlación reconstruido↔real: 0.851

POR ESO NO ALIMENTA NINGUNA REGLA DE UMBRAL. ``early_warning.rule_solvency`` dispara en 12%
(``SOLV_WARN``) y 10.5% (``SOLV_HIGH``). Con un p90 de 4.6 pp en el mejor tipo de entidad,
una reconstrucción de 14% puede ser una real de 10%: la bandera fallaría exactamente en la
frontera donde tiene que servir. Es el mismo error de método que la revisión actuarial de
seguros: un umbral más fino que el error de la medición. Lo que la serie SÍ sostiene es
lectura RELATIVA —quién está más delgado de capital que quién— porque ordena bien aunque no
acierte el nivel.

Se intentó bajar el error con parámetros por tipo de entidad; no bajó (banca múltiple quedó
en p90 3.89 pp) y los parámetros se fueron contra sus límites, que es ajustar la curva, no
medir riesgo. Los ponderadores de abajo son Basilea I ESTRUCTURAL declarada, sin ajuste.

La única desviación es ``d_res``: el resultado del ejercicio queda FUERA del capital primario.
No es una elección de conveniencia — un ajuste por mínimos cuadrados sobre el solape lo llevó
a cero en las cuatro variantes probadas, y la norma prudencial lo justifica de forma
independiente (las utilidades no auditadas no computan). El dato y la regla coinciden.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

# ── Ponderadores Basilea I, declarados (no ajustados) ──────────────────────────
W_CAJA_BC = 0.00          # caja y Banco Central
W_INTERBANCARIO = 0.20    # bancos del país/exterior, interbancarios, cobro inmediato
W_INV_DEUDA = 0.20        # papel de deuda: en RD domina el soberano/BCRD
W_INV_ACCIONES = 1.00
W_CARTERA = 1.00          # sin desglose por garantía en el catálogo moderno → sin tramo 50%
W_OTROS = 1.00
W_PARTICIPACIONES = 1.00
CCF_CONTINGENTES = 0.50   # factor de conversión mixto (el catálogo no desglosa el tipo)

# Error MEDIDO contra la solvencia real del solape 2021-2026. Viaja con la serie: publicar
# el nivel sin su error es lo que volvería esto una cifra con cara de Basilea.
ERROR_P90_PP: Dict[str, float] = {
    "banca_multiple": 4.59,
    "banco_ahorro_credito": 9.47,
    "corporacion_credito": 8.86,
    "aap": 8.71,
}
ERROR_P90_DEFAULT = 9.47
# Ningún umbral más fino que esto es legible sobre la serie reconstruida.
UMBRAL_MINIMO_LEGIBLE_PP = ERROR_P90_PP["banca_multiple"]

_BUCKET_0 = {"caja", "banco central"}
_BUCKET_20 = {"bancos del pais", "bancos del exterior", "efectos de cobro inmediato",
              "equivalentes de efectivo", "otras disponibilidades",
              "efectivo y equivalentes de efectivo", "efectivo en transito"}
_INV_DEUDA = {"disponibles para la venta", "mantenidas hasta su vencimiento", "a negociar",
              "negociables", "a costo amortizado", "otras inversiones en instrumentos de deuda",
              "a valor razonable con cambios en el patrimonio",
              "a valor razonable con cambios en resultados", "inversiones",
              "provisiones para inversiones"}
_TIER1 = {"capital pagado", "capital adicional pagado", "reservas patrimoniales",
          "resultados acumulados de ejercicios anteriores", "ajustes al patrimonio",
          "ajustes por conversion de moneda", "ajustes por participacion en otras empresas",
          "capital, reservas y superavit"}
_TIER2 = {"superavit por revaluacion",
          "ganancias (perdidas) no realizadas en inversiones disponibles para la venta",
          "ganancias (perdidas) no realizadas en inversiones de valor razonable con cambios "
          "en el patrimonio"}
_SUBORDINADAS = {"obligaciones subordinadas", "deudas subordinadas",
                 "obligaciones convertibles en capital", "obligaciones asimilables de capital"}


@dataclass(frozen=True)
class SolvenciaReconstruida:
    """Resultado etiquetado. ``apta_para_umbral`` es False SIEMPRE y a propósito: es la
    barrera que impide que alguien la cablee a una regla de 10%/12% sin leer el error."""
    patrimonio_tecnico: float
    apr: float
    solvencia_pct: float
    error_p90_pp: float
    apta_para_umbral: bool
    procedencia: str

    @property
    def rango(self) -> tuple:
        """El intervalo que la medición realmente sostiene."""
        return (self.solvencia_pct - self.error_p90_pp, self.solvencia_pct + self.error_p90_pp)


def _norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def reconstruir(rows: Iterable, bank_type: Optional[str] = None) -> Optional[SolvenciaReconstruida]:
    """Solvencia Basilea reconstruida de UNA entidad en UN corte, desde las filas del ledger.

    ``rows`` son las líneas de ``SibHistoricalLedger`` de ese (entidad, fecha) — los mismos
    objetos que consume ``sib_historical_crosswalk.derive_group``. Devuelve ``None`` si no
    hay activos ponderables: sin APR no hay ratio, y un cero acá sería una brecha disfrazada.
    """
    a0 = a20 = inv_d = inv_a = cartera = otros = partic = cont = 0.0
    t1_base = t2 = sub = intang = 0.0
    visto = False
    for r in rows:
        visto = True
        n1, n2, n3 = getattr(r, "nivel_1", ""), getattr(r, "nivel_2", ""), getattr(r, "nivel_3", "")
        m = _f(getattr(r, "monto", None))
        k2, k3 = _norm(n2), _norm(n3)
        if getattr(r, "estado", "") != "situacion":
            continue
        if n1 == "Activos":
            if n2 == "Total":
                continue
            if k3 == "intangibles":
                intang += m
            elif k3 in _BUCKET_0:
                a0 += m
            elif k3 in _BUCKET_20 or k2 == "fondos interbancarios":
                a20 += m
            elif k2 == "inversiones":
                inv_d, inv_a = (inv_d + m, inv_a) if k3 in _INV_DEUDA else (inv_d, inv_a + m)
            elif k2 == "cartera de creditos":
                cartera += m
            elif k2 == "participaciones en otras sociedades":
                partic += m
            else:
                otros += m
        elif n1 == "Patrimonio" and n2 != "Total":
            # El resultado del ejercicio NO entra: utilidad no auditada (ver docstring).
            if k3 in _TIER1:
                t1_base += m
            elif k3 in _TIER2:
                t2 += m
        elif n1 == "Pasivos" and k3 in _SUBORDINADAS:
            sub += m
        elif n1.startswith("Cuentas cont") and n2 != "Total":
            cont += m

    if not visto:
        return None
    apr = (W_CAJA_BC * a0 + W_INTERBANCARIO * a20 + W_INV_DEUDA * inv_d
           + W_INV_ACCIONES * inv_a + W_CARTERA * cartera + W_OTROS * otros
           + W_PARTICIPACIONES * partic + CCF_CONTINGENTES * cont)
    if apr <= 0:
        return None
    tier1 = t1_base - intang
    tier2 = min(t2 + sub, max(tier1, 0.0))     # tope regulatorio: secundario ≤ primario
    pt = tier1 + tier2
    err = ERROR_P90_PP.get(bank_type or "", ERROR_P90_DEFAULT)
    return SolvenciaReconstruida(
        patrimonio_tecnico=pt, apr=apr, solvencia_pct=pt / apr * 100.0,
        error_p90_pp=err, apta_para_umbral=False,
        procedencia="reconstruida:basilea_i_estructural",
    )


def etiqueta(res: SolvenciaReconstruida) -> str:
    """Cómo se nombra la cifra cuando se publica. Nunca 'solvencia' a secas: el lector la
    leería como el ratio regulatorio, que es otra cosa y con otro error."""
    lo, hi = res.rango
    return (f"solvencia reconstruida {res.solvencia_pct:.1f}% "
            f"(Basilea I sobre balance contable; ±{res.error_p90_pp:.1f} pp p90 → {lo:.1f}–{hi:.1f}%; "
            f"lectura relativa, no comparable contra el mínimo regulatorio)")
