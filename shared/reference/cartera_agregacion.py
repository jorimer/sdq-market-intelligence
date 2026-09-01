"""Agregación del cubo de crédito: las primitivas, en UN solo cuerpo.

**Por qué viven acá.** Estaban en `modules/banking_score/reports/mapa_sectorial.py`, que era
su único consumidor. Desde la fase 3 del plan de enriquecimiento sectorial las usa también
`shared/perfil_del_sector.py`, y copiarlas habría sido repetir exactamente el defecto que el
2026-08-31 borró la tasa de 38 entidades: dos cuerpos que hacen «lo mismo» y uno se queda
atrás. Viven junto a la tabla que agregan (`shared/reference/cartera_sectorial.py`).

Son PURAS: reciben celdas y devuelven acumulados. No consultan la base ni saben de entidades.
"""
from typing import Any, Dict, List, Optional

from shared.reference.cartera_sectorial import CarteraSectorial


def _pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Porcentaje, o None. NUNCA cero: un cociente sin denominador es un dato ausente, y
    servirlo como 0,0 lo vuelve una afirmación —«no tiene mora»— que nadie midió."""
    if num is None or not den:
        return None
    return round(100.0 * float(num) / float(den), 2)



#: Las medidas del cubo que se SUMAN. La tasa NO está acá a propósito: es un cociente y
#: sumarla no significa nada. Va aparte, re-ponderada por `deuda_con_tasa`.
_SUMABLES = ("deuda", "vencida", "vencida_31_90", "garantia", "provision",
             "creditos", "desembolso", "deuda_moneda_extranjera", "deuda_persona_fisica",
             "deuda_con_tasa")


def _vacio() -> Dict[str, Any]:
    a: Dict[str, Any] = {k: 0.0 for k in _SUMABLES}
    # Numerador de la tasa re-ponderada: Σ(tasa × saldo). Solo acumula celdas con tasa
    # creíble, y `deuda_con_tasa_valida` acumula EL MISMO subconjunto para que el cociente
    # tenga el mismo universo arriba y abajo.
    a["tasa_por_deuda"] = 0.0
    a["deuda_con_tasa_valida"] = 0.0
    a["bancos"] = set()
    a["celdas"] = 0
    return a


def _sumar(acc: Dict[str, Any], c: CarteraSectorial) -> None:
    for k in _SUMABLES:
        acc[k] += float(getattr(c, k, None) or 0)
    tasa = c.tasa_ponderada
    base = float(c.deuda_con_tasa or 0)
    if tasa is not None and base > 0:
        acc["tasa_por_deuda"] += float(tasa) * base
        acc["deuda_con_tasa_valida"] += base
    acc["bancos"].add(str(c.bank_id))
    acc["celdas"] += 1


def _restar(total: Dict[str, Any], propio: Dict[str, Any]) -> Dict[str, Any]:
    """El RESTO del sistema: el agregado del sector menos lo que aporta la entidad.

    Sin esto una entidad grande se compara contra un promedio que ella misma domina, y su
    brecha sale sistemáticamente encogida — el sesgo es máximo justo donde más importa."""
    r: Dict[str, Any] = {k: total[k] - propio[k] for k in _SUMABLES}
    r["tasa_por_deuda"] = total["tasa_por_deuda"] - propio["tasa_por_deuda"]
    r["deuda_con_tasa_valida"] = total["deuda_con_tasa_valida"] - propio["deuda_con_tasa_valida"]
    r["bancos"] = total["bancos"] - propio["bancos"]
    r["celdas"] = total["celdas"] - propio["celdas"]
    return r


def _agregar(celdas: List[CarteraSectorial]) -> Dict[str, Dict[str, Any]]:
    """Acumula por sector UNA sola vez. Las dos lecturas —sistema y entidad— salen de acá,
    porque dos acumuladores separados discrepan en silencio."""
    out: Dict[str, Dict[str, Any]] = {}
    for c in celdas:
        _sumar(out.setdefault(str(c.sector), _vacio()), c)
    return out


def _tasa(acc: Dict[str, Any]) -> Optional[float]:
    """Tasa promedio RE-PONDERADA por saldo. Nunca el promedio simple de los cocientes."""
    base = acc.get("deuda_con_tasa_valida") or 0.0
    if base <= 0:
        return None
    return round(acc["tasa_por_deuda"] / base, 2)


def _medidas(acc: Dict[str, Any]) -> Dict[str, Any]:
    """Las medidas que se derivan de un acumulado, con el SUJETO en cada clave."""
    d = acc["deuda"]
    return {
        "mora_pct": _pct(acc["vencida"], d),
        # Señal ADELANTADA: se deteriora antes que la vencida.
        "mora_temprana_31_90_pct": _pct(acc["vencida_31_90"], d),
        "tasa_promedio_ponderada_pct": _tasa(acc),
        # Cobertura sobre la cartera VENCIDA, no sobre la total: mide si lo ya deteriorado
        # está provisionado. Si no hay mora, no hay qué cubrir y el dato es None, no 0.
        "cobertura_de_provision_sobre_vencida_pct": _pct(acc["provision"], acc["vencida"]),
        "garantia_sobre_deuda_pct": _pct(acc["garantia"], d),
        "dolarizacion_de_la_deuda_pct": _pct(acc["deuda_moneda_extranjera"], d),
        "deuda_de_persona_fisica_pct": _pct(acc["deuda_persona_fisica"], d),
        "creditos": int(acc["creditos"]) or None,
        "credito_promedio": (round(d / acc["creditos"], 2) if acc["creditos"] else None),
        "desembolso_del_trimestre": round(acc["desembolso"], 2) or None,
    }
