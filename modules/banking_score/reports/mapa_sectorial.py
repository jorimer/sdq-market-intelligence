"""El libro de crédito del SISTEMA abierto por sector, y la posición de cada entidad en él.

Qué contesta y por qué no puede contestarlo un banco solo. La pregunta de un comité de
crédito es «mi cartera de construcción se deterioró: ¿es mi originación o es el sector?».
Para responderla hay que comparar la mora de la entidad en ese sector contra la del RESTO
del sistema en el mismo sector, y eso exige el libro de las otras noventa y una entidades.
Un banco tiene una sola fila del cubo de la SIB: la suya.

Tres lecturas, en este orden:

1. **El sistema por sector** — cuánto se presta a cada sector, con qué mora y con qué mora
   TEMPRANA (31-90 días), que es la señal adelantada.
2. **La posición de la entidad** — su peso en cada sector contra el peso que ese sector
   tiene en el sistema. Estar concentrado no es un defecto: es una decisión que se lee
   contra lo que hace el resto.
3. **La atribución** — la brecha entre la mora de la entidad y la del sector separa lo
   IDIOSINCRÁTICO de lo COMPARTIDO. Es la única de las tres que exige el panel completo, y
   es la que vale.

Doctrina aplicada. Las relaciones se COMPUTAN acá y el modelo las copia; no se le pide que
derive una dirección. Cada cuota nombra su población en la clave (`peso_en_su_cartera_pct`
vs `cuota_del_sector_pct`) porque son dos denominadores distintos y el modelo reatribuye al
sujeto más cercano. Y solo se ordena lo comparable: una entidad que no presta a un sector NO
entra en la mora de ese sector con un cero — no prestar no es prestar bien.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, CarteraSectorial

logger = logging.getLogger(__name__)

# Debajo de este monto la mora de una celda es ruido: un solo crédito la mueve decenas de
# puntos. No se oculta la celda —desaparecer sin aviso es peor— pero no se rankea ni se
# narra como señal.
MATERIALIDAD_DEUDA = 1_000_000.0

# Cuánto tiene que separarse la mora de la entidad de la del sector para llamarla suya. Por
# debajo, la diferencia no sostiene una afirmación de originación.
BRECHA_MATERIAL_PP = 1.0


def _pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Porcentaje, o None. NUNCA cero: un cociente sin denominador es un dato ausente, y
    servirlo como 0,0 lo vuelve una afirmación —«no tiene mora»— que nadie midió."""
    if num is None or not den:
        return None
    return round(100.0 * float(num) / float(den), 2)


def _celdas(db: Session, corte: date) -> List[CarteraSectorial]:
    return (db.query(CarteraSectorial)
            .filter(CarteraSectorial.period_end == corte)
            .all())


def sistema_por_sector(db: Session, corte: date) -> Dict[str, Any]:
    """El sistema entero abierto por sector, agregando sobre provincias y entidades."""
    filas = (db.query(
                CarteraSectorial.sector,
                func.sum(CarteraSectorial.deuda),
                func.sum(CarteraSectorial.vencida),
                func.sum(CarteraSectorial.vencida_31_90),
                func.count(func.distinct(CarteraSectorial.bank_id)))
             .filter(CarteraSectorial.period_end == corte)
             .group_by(CarteraSectorial.sector).all())
    if not filas:
        return {"corte": str(corte), "sectores": [], "sin_dato": True}

    total = sum(float(f[1] or 0) for f in filas)
    sectores = []
    for sector, deuda, vencida, temprana, n_ent in filas:
        d = float(deuda or 0)
        sectores.append({
            "sector": sector,
            "deuda": round(d, 2),
            # El SUJETO en la clave: esta cuota es sobre el crédito TOTAL del sistema, no
            # sobre la cartera de ninguna entidad.
            "peso_en_el_sistema_pct": _pct(d, total),
            "entidades_que_prestan": int(n_ent or 0),
            "mora_pct": _pct(vencida, d),
            # Señal ADELANTADA: se deteriora antes que la vencida.
            "mora_temprana_31_90_pct": _pct(temprana, d),
        })
    sectores.sort(key=lambda s: -float(s["deuda"] or 0))
    return {
        "corte": str(corte),
        "credito_total_del_sistema": round(total, 2),
        "sectores": sectores,
        "que_es": ("el crédito de TODAS las entidades supervisadas abierto por sector "
                   "económico; la mora temprana de 31 a 90 días se deteriora antes que la "
                   "vencida, así que ordena por anticipación y no por daño consumado"),
    }


def posicion_de_la_entidad(db: Session, bank: Bank, corte: date) -> Optional[Dict[str, Any]]:
    """Dónde presta esta entidad, y cómo le va ahí contra el resto del sistema."""
    mias = [c for c in _celdas(db, corte) if str(c.bank_id) == str(bank.id)]
    if not mias:
        logger.info("Mapa sectorial: %s no tiene desglose en %s.", bank.name, corte)
        return None

    sistema = {s["sector"]: s for s in sistema_por_sector(db, corte)["sectores"]}
    por_sector: Dict[str, Dict[str, float]] = {}
    for c in mias:
        a = por_sector.setdefault(str(c.sector), {"deuda": 0.0, "vencida": 0.0,
                                                  "temprana": 0.0, "provincias": 0.0})
        a["deuda"] += float(c.deuda or 0)
        a["vencida"] += float(c.vencida or 0)
        a["temprana"] += float(c.vencida_31_90 or 0)
        a["provincias"] += 1

    mi_total = sum(v["deuda"] for v in por_sector.values())
    filas = []
    for sector, v in por_sector.items():
        s = sistema.get(sector) or {}
        mora_mia = _pct(v["vencida"], v["deuda"])
        mora_sis = s.get("mora_pct")
        material = v["deuda"] >= MATERIALIDAD_DEUDA
        brecha = (None if mora_mia is None or mora_sis is None
                  else round(mora_mia - mora_sis, 2))
        filas.append({
            "sector": sector,
            "deuda": round(v["deuda"], 2),
            "provincias_en_que_presta": int(v["provincias"]),
            # DOS cuotas con DOS denominadores. Sin el sujeto en la clave, el modelo las
            # confunde y publica «concentra el 31% del sector» cuando es de su cartera.
            "peso_en_su_cartera_pct": _pct(v["deuda"], mi_total),
            "cuota_del_sector_pct": _pct(v["deuda"], s.get("deuda")),
            "peso_del_sector_en_el_sistema_pct": s.get("peso_en_el_sistema_pct"),
            "mora_pct": mora_mia,
            "mora_del_sector_pct": mora_sis,
            "mora_temprana_31_90_pct": _pct(v["temprana"], v["deuda"]),
            "mora_temprana_del_sector_pct": s.get("mora_temprana_31_90_pct"),
            # LA RELACIÓN SE COMPUTA ACÁ. El modelo la copia; si tuviera que derivarla de
            # dos porcentajes, invertiría la dirección — ya pasó en este repo.
            "brecha_de_mora_pp": brecha,
            "atribucion": _atribuir(brecha, material),
            "material": material,
        })
    filas.sort(key=lambda f: -float(f["deuda"] or 0))
    return {
        "entidad": bank.name,
        "corte": str(corte),
        "credito_clasificado": round(mi_total, 2),
        "sectores": filas,
        "regla_de_atribucion": (
            f"la brecha es la mora de la entidad menos la del MISMO sector en todo el "
            f"sistema; por debajo de {BRECHA_MATERIAL_PP} punto porcentual no se atribuye a "
            f"ninguna de las dos causas, y por debajo de "
            f"RD${MATERIALIDAD_DEUDA:,.0f} de exposición la mora de una celda es ruido"),
    }


def _atribuir(brecha: Optional[float], material: bool) -> str:
    """Idiosincrático, compartido, o no atribuible — nunca una cuarta cosa inventada."""
    if brecha is None:
        return "sin_dato"
    if not material:
        return "exposicion_no_material"
    if abs(brecha) < BRECHA_MATERIAL_PP:
        return "compartido_con_el_sector"
    return "idiosincratico_peor" if brecha > 0 else "idiosincratico_mejor"
