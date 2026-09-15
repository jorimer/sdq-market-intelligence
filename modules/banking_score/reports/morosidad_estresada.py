"""La MOROSIDAD ESTRESADA de la entidad: total, desglose, lo que la mora convencional no ve y
su posición contra el resto del sistema. Todo computado.

**Por qué existe (2026-09-15).** Un alto funcionario de Banco Múltiple Santa Cruz leyó el Deep
Dive 2025 y objetó que el motor comparara entidades con la mora convencional: «el indicador
más comparable es la mora ampliada o estresada, ya que incluye castigos y otros componentes».
Tiene razón por un motivo concreto: un banco que castiga rápido publica una mora baja sin
tener mejor cartera. El dueño decidió usar la estresada OFICIAL de la SIB, desglosada, y que
NO entre al score —la mora y los castigos ya puntúan; sumarla contaría dos veces el mismo
hecho—. Va al texto.

**Tres reglas que este módulo aplica y que no son estilo:**

* La brecha se mide DENTRO del cuadro de la estresada (su total menos su propio vencido). La
  mora convencional publicada sale de otro cuadro de la SIB, con otra cartera: Santa Cruz a
  marzo de 2025 publica 2,37 % y el vencido del cuadro estresado da 2,12 %. Restarlas mezclaría
  denominadores.
* El sistema es el RESTO de las instituciones de crédito (`SISTEMA_TIPOS`), sin la entidad
  evaluada: incluirla la compararía en parte contra sí misma.
* Un componente ausente no se rellena: el bloque declara que no hay estresada y por qué.
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, BankingData
from modules.banking_score.scoring.benchmarks import SISTEMA_LABEL, SISTEMA_TIPOS
from shared.narrative.derived import MATERIALIDAD_PP

#: La definición del regulador, en prosa, para que el modelo la cite sin reconstruirla.
DEFINICION_SIB = (
    "Morosidad estresada según la Superintendencia de Bancos (catálogo de indicadores "
    "financieros, I.027): cartera vencida + cartera en cobranza judicial + tarjetas de crédito "
    "con atraso de 31 a 60 días + créditos reestructurados (según el REA y temporales) + "
    "castigos y adjudicaciones de los últimos 12 meses, sobre la cartera de crédito.")

#: Qué dice cada medida y por qué se leen juntas. Es la explicación que pidió el dueño.
COMO_LEER_LAS_DOS_MORAS = (
    "La mora convencional mide lo vencido que la entidad todavía tiene en su balance, y es la "
    "base de la cobertura de provisiones. La estresada suma lo que la convencional no ve —lo "
    "que ya se castigó, se reestructuró o se adjudicó— y por eso es la que compara entidades "
    "con políticas de castigo distintas. La diferencia entre las dos es el deterioro que salió "
    "del balance o cambió de forma. La estresada no entra al score: la mora y los castigos ya "
    "puntúan.")

#: Por qué la mora convencional publicada no se resta de la estresada.
NOTA_DE_CARTERAS = (
    "La mora convencional publicada y la estresada salen de dos cuadros distintos de la SIB, "
    "con carteras distintas, y no se restan entre sí. Lo que la mora convencional no ve se "
    "mide dentro del cuadro de la estresada: su total menos su propio componente de cartera "
    "vencida.")

MOTIVO_COMPONENTE_AUSENTE = (
    "La SIB no publicó para este corte todos los componentes de la morosidad estresada de la "
    "entidad; sin uno de ellos la cifra la subestimaría, así que no se publica.")

#: Columna de `banking_data` → nombre del componente en el informe. El orden es el del
#: catálogo de la SIB.
COMPONENTES = (
    ("estresada_vencido_pct", "cartera vencida"),
    ("estresada_cobranza_pct", "cartera en cobranza judicial"),
    ("estresada_tc31a60_pct", "tarjetas de crédito con atraso de 31 a 60 días"),
    ("estresada_reestructurado_rea_pct", "créditos reestructurados según el REA"),
    ("estresada_reestructurado_temporal_pct", "reestructuraciones temporales"),
    ("castigos_pct", "castigos de los últimos 12 meses"),
    ("estresada_adjudicado_pct", "adjudicaciones de los últimos 12 meses"),
)


def _f(v: Any) -> Optional[float]:
    return None if v is None else float(v)


def _mediana_del_resto(db: Session, bank: Bank, corte: date) -> tuple:
    filas = (db.query(BankingData.morosidad_estresada_pct, Bank.bank_type)
             .join(Bank, Bank.id == BankingData.bank_id)
             .filter(BankingData.period_end == corte, BankingData.bank_id != bank.id,
                     BankingData.morosidad_estresada_pct.isnot(None))
             .all())
    valores = [float(v) for v, tipo in filas
               if tipo is not None and tipo.value in SISTEMA_TIPOS]
    return (round(statistics.median(valores), 4) if valores else None), len(valores)


def morosidad_estresada_al_corte(db: Session, bank: Bank,
                                 corte: date) -> Optional[Dict[str, Any]]:
    """El bloque de la estresada de *bank* al *corte*, o ``None`` si no hay fila de datos."""
    fila = (db.query(BankingData)
            .filter(BankingData.bank_id == bank.id, BankingData.period_end == corte)
            .one_or_none())
    if fila is None:
        return None
    bloque: Dict[str, Any] = {
        "corte": str(corte),
        "definicion": DEFINICION_SIB,
        "como_leer_las_dos_moras": COMO_LEER_LAS_DOS_MORAS,
        "nota_de_carteras": NOTA_DE_CARTERAS,
        "puntua_en_el_score": False,
        "morosidad_convencional_publicada_de_la_entidad_pct": _f(fila.morosidad_pct),
    }
    total = _f(fila.morosidad_estresada_pct)
    componentes = [(etiqueta, _f(getattr(fila, col))) for col, etiqueta in COMPONENTES]
    if total is None or any(v is None for _, v in componentes):
        return {**bloque, "disponible": False, "motivo": MOTIVO_COMPONENTE_AUSENTE}

    vencida = componentes[0][1] or 0.0
    fuera_de_la_vencida = [(e, v) for e, v in componentes[1:] if v]
    mayor = max(fuera_de_la_vencida, key=lambda c: c[1], default=None)
    bloque.update({
        "disponible": True,
        "morosidad_estresada_de_la_entidad_pct": round(total, 4),
        "componentes_de_la_estresada_de_la_entidad": [
            {"componente": e, "pct_de_la_cartera_de_la_entidad": round(v or 0.0, 4)}
            for e, v in componentes],
        "lo_que_la_mora_convencional_no_ve_pp": round(total - vencida, 4),
        "mayor_componente_fuera_de_la_vencida": mayor[0] if mayor else None,
    })

    mediana, n = _mediana_del_resto(db, bank, corte)
    if mediana is None:
        bloque["sin_referencia_del_sistema"] = (
            "Ninguna otra institución de crédito tiene la morosidad estresada completa en "
            "este corte: no hay contra qué ubicar a la entidad.")
        return bloque
    diferencia = round(total - mediana, 4)
    bloque.update({
        "mediana_estresada_del_resto_del_sistema_pct": mediana,
        "n_entidades_del_resto_del_sistema": n,
        "universo_del_resto_del_sistema": SISTEMA_LABEL,
        "excluye_a_la_entidad_evaluada": True,
        "diferencia_con_la_mediana_del_resto_pp": diferencia,
        "posicion_frente_a_la_mediana_del_resto": (
            "en línea" if abs(diferencia) < MATERIALIDAD_PP
            else "por encima" if diferencia > 0 else "por debajo"),
    })
    return bloque


def morosidad_estresada_del_anio(db: Session, bank: Bank,
                                 cortes: List[str]) -> Optional[Dict[str, Any]]:
    """Apertura (cierre del año anterior) y cierre del año, con el cambio computado."""
    apertura = morosidad_estresada_al_corte(db, bank, date.fromisoformat(cortes[0]))
    cierre = morosidad_estresada_al_corte(db, bank, date.fromisoformat(cortes[-1]))
    if cierre is None:
        return None
    out: Dict[str, Any] = {"apertura": apertura, "cierre": cierre}
    if (apertura and apertura.get("disponible") and cierre.get("disponible")):
        out["cambio_de_la_estresada_de_la_entidad_en_el_anio_pp"] = round(
            cierre["morosidad_estresada_de_la_entidad_pct"]
            - apertura["morosidad_estresada_de_la_entidad_pct"], 4)
    return out
