"""Cada trimestre del año, contra SU historia y contra el SISTEMA en el mismo corte.

**Por qué existe (2026-09-15).** El Deep Dive 2025 de Banco Múltiple Santa Cruz destacó que
«el segundo trimestre concentró el 51 % del movimiento del año». Un alto funcionario del banco
respondió lo que el informe no podía contestar: si siempre es así, ¿por qué es relevante? Los
informes recurrentes a la junta ya cubren la variación de un trimestre contra otro; el motor
agrega valor cuando la entidad se desempeña **distinto a su historia o distinto al resto del
mercado en ese trimestre**. Y el texto llegó a especular con «un componente estacional» sin
ningún dato que lo sostuviera.

**Qué computa, por trimestre del año:**

* la historia del MISMO trimestre de la entidad en años anteriores (cambio del score en ese
  tramo, año por año), con su mínimo y su máximo;
* el cambio del RESTO de las instituciones de crédito en ese mismo tramo, excluida la entidad:
  mediana y rango intercuartil;
* un ROTULO resuelto en código. Que un movimiento sea atípico es una relación, y las relaciones
  se computan: el modelo la copia.

**Cuándo no se juzga.** Con menos de `MIN_ANIOS_DE_HISTORIA` años del mismo trimestre no hay
patrón propio que afirmar, y con menos de `MIN_ENTIDADES_DEL_RESTO` pares no hay mercado: se
declara, no se rellena.
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult
from modules.banking_score.scoring.benchmarks import SISTEMA_LABEL, SISTEMA_TIPOS

#: Mismo umbral que el eje usa para llamar «movimiento» a un tramo: por debajo es ruido, y un
#: cambio que se sale del rango por menos que esto no es atípico, es un empate.
UMBRAL_TRAMO = 0.5
MIN_ANIOS_DE_HISTORIA = 3
MIN_ENTIDADES_DEL_RESTO = 5
#: Cuántos años atrás se busca el mismo trimestre.
ANIOS_ATRAS = 6

ORDINARIO = "ordinario"
ATIPICO = "atípico"
HISTORIA_INSUFICIENTE = "historia insuficiente"
SIN_REFERENCIA_DEL_SISTEMA = "sin referencia suficiente del sistema"

_FIN_DE_TRIMESTRE = {3: (3, 31), 6: (6, 30), 9: (9, 30), 12: (12, 31)}

COMO_LEER_EL_ROTULO = (
    "Cada trimestre se compara con el mismo trimestre de años anteriores de la entidad y con "
    "el cambio del resto de las instituciones de crédito en ese mismo corte. Un trimestre "
    "'ordinario' se movió dentro de lo que ya hacía la entidad y dentro del rango del sistema: "
    "no es un hallazgo. Solo un trimestre 'atípico' se destaca, con la referencia contra la "
    "que lo es. Si la entidad repite el patrón todos los años, eso es lo que se dice; si no hay "
    "historia suficiente, se declara y no se habla de estacionalidad.")


def _corte(anio: int, mes: int) -> date:
    m, d = _FIN_DE_TRIMESTRE[mes]
    return date(anio, m, d)


def _corte_anterior(c: date) -> date:
    return date(c.year - 1, 12, 31) if c.month == 3 else _corte(c.year, c.month - 3)


def _scores(db: Session, **filtro) -> Dict[date, float]:
    q = db.query(RatingResult.period_end, RatingResult.overall_score).filter(
        RatingResult.model_type == ModelType.deterministic)
    for k, v in filtro.items():
        q = q.filter(getattr(RatingResult, k) == v)
    return {pe: float(s) for pe, s in q.all() if s is not None}


def _historia_del_trimestre(serie: Dict[date, float], anio: int, mes: int) -> List[Dict[str, Any]]:
    out = []
    for a in range(anio - ANIOS_ATRAS, anio):
        hasta = _corte(a, mes)
        desde = _corte_anterior(hasta)
        if hasta in serie and desde in serie:
            out.append({"anio": a, "cambio": round(serie[hasta] - serie[desde], 2)})
    return out


def _sistema_en_el_tramo(db: Session, bank: Bank, desde: date, hasta: date) -> List[float]:
    filas = (db.query(RatingResult.bank_id, RatingResult.period_end, RatingResult.overall_score)
             .join(Bank, Bank.id == RatingResult.bank_id)
             .filter(RatingResult.model_type == ModelType.deterministic,
                     RatingResult.period_end.in_([desde, hasta]),
                     RatingResult.bank_id != bank.id,
                     Bank.bank_type.in_(list(SISTEMA_TIPOS)))
             .all())
    por_banco: Dict[Any, Dict[date, float]] = {}
    for bid, pe, s in filas:
        if s is not None:
            por_banco.setdefault(bid, {})[pe] = float(s)
    return [round(v[hasta] - v[desde], 2) for v in por_banco.values()
            if desde in v and hasta in v]


def _frente_a_su_historia(cambio: float, historia: List[Dict[str, Any]]) -> str:
    if len(historia) < MIN_ANIOS_DE_HISTORIA:
        return HISTORIA_INSUFICIENTE
    cambios = [h["cambio"] for h in historia]
    fuera = cambio < min(cambios) - UMBRAL_TRAMO or cambio > max(cambios) + UMBRAL_TRAMO
    return ATIPICO if fuera else ORDINARIO


def _frente_al_sistema(cambio: float, del_resto: List[float]) -> tuple:
    if len(del_resto) < MIN_ENTIDADES_DEL_RESTO:
        return SIN_REFERENCIA_DEL_SISTEMA, None
    p25, mediana, p75 = statistics.quantiles(del_resto, n=4, method="inclusive")
    # El rango intercuartil se sirve con el nombre de lo que ES: la MITAD central. Servido como
    # `p25_…`/`p75_…`, el Deep Dive de Santa Cruz regenerado (2026-09-15) escribió «el 75 % de
    # las instituciones entre −2,17 y −0,22». La cifra 50 viaja para que no la deduzca.
    ref = {"mediana_del_cambio_del_resto": round(mediana, 2),
           "la_mitad_central_del_resto_va_desde": round(p25, 2),
           "la_mitad_central_del_resto_va_hasta": round(p75, 2),
           "pct_del_resto_dentro_de_la_mitad_central": 50,
           "n_entidades_del_resto": len(del_resto), "universo_del_resto": SISTEMA_LABEL}
    fuera = (cambio < p25 or cambio > p75) and abs(cambio - mediana) >= UMBRAL_TRAMO
    return (ATIPICO if fuera else ORDINARIO), ref


def _rotulo(historia: str, sistema: str) -> str:
    if historia == ATIPICO and sistema == ATIPICO:
        return "atípico frente a su historia y frente al sistema"
    if historia == ATIPICO:
        return "atípico frente a su historia"
    if sistema == ATIPICO:
        return "atípico frente al sistema"
    if ORDINARIO in (historia, sistema):
        return ORDINARIO
    return "sin referencia para juzgarlo"


def contexto_de_los_tramos(db: Session, bank: Bank, anio: int,
                           tramos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Por cada tramo del año (los de `anio_por_trimestres._tramos`), su contexto resuelto."""
    serie = _scores(db, bank_id=bank.id)
    out: List[Dict[str, Any]] = []
    for t in tramos:
        hasta = date.fromisoformat(str(t["hasta"]))
        desde = date.fromisoformat(str(t["desde"]))
        cambio = float(t["cambio"])
        historia = _historia_del_trimestre(serie, anio, hasta.month)
        del_resto = _sistema_en_el_tramo(db, bank, desde, hasta)
        vs_historia = _frente_a_su_historia(cambio, historia)
        vs_sistema, ref = _frente_al_sistema(cambio, del_resto)
        rotulo = _rotulo(vs_historia, vs_sistema)
        fila: Dict[str, Any] = {
            "tramo": t["tramo"],
            "cambio_de_la_entidad": round(cambio, 2),
            "historia_del_mismo_trimestre_de_la_entidad": historia,
            "frente_a_su_historia": vs_historia,
            "frente_al_sistema": vs_sistema,
            "rotulo": rotulo,
            "se_destaca": rotulo.startswith(ATIPICO),
        }
        if historia:
            cambios = [h["cambio"] for h in historia]
            fila["rango_historico_del_mismo_trimestre"] = {
                "minimo": min(cambios), "maximo": max(cambios), "n_anios": len(cambios)}
        if ref:
            fila["sistema_en_el_mismo_trimestre"] = ref
        out.append(fila)
    return out
