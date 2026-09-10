"""La lectura del movimiento: el delta contra su línea base, COMPUTADO.

**Qué produce y para quién.** Un bloque cerrado —cifra, línea base, variación, dirección y
emisor— que el modelo COPIA. No lo deriva: el modelo acierta las cifras y falla las
relaciones, y además el guard numérico exige que toda cifra del texto se trace al contexto.
Si el modelo produce el número, no hay contra qué trazarlo.

**La línea base la elige la NATURALEZA de la serie, no una tabla de decisiones.**

* ``flow`` — contra el MISMO período del año anterior. Es la única comparación que no
  confunde estación con tendencia: las licencias, las llegadas y las reclamaciones tienen
  estación, y medirlas contra el mes anterior publica el calendario como si fuera el ciclo.
  Viaja además su VENTANA MÓVIL de 12 meses, que es lo comparable con el índice anual.
* ``stock`` — contra el último nivel publicado. Un saldo no se acumula: se compara con lo
  que era.
* ``rate`` / ``index`` — contra el mismo período del año anterior, y **en puntos**, no en
  porcentaje. Una tasa que va de 4,23 % a 5,35 % subió 1,12 puntos; decir «+26 %» es
  aritméticamente correcto y económicamente falso.
* ``unknown`` — **no se computa**. Se declara el motivo. Un consumidor honesto no computa lo
  que no sabe interpretar, y adivinar una sola transformación para todas es un error de
  categoría en el 37 % del catálogo (ver ``shared/data/series_nature.py``).

**Lo que falta se declara; no se rellena.** Sin línea base no hay delta: la serie sale con su
valor y un motivo escrito, nunca con un cero ni con un promedio. Y la ventana de 12 meses
exige los DOCE puntos — sin ellos se declara no disponible en vez de sumar los que haya, que
es la misma regla con la que banca cerró el ROA/ROE (``banking_score/scoring/ttm.py``); la
doctrina se reusa, el código no se importa: un módulo no importa de otro.

**Toda magnitud que se resta viaja con su medida.** Cada fila nombra su unidad, su período
base y el TIPO de línea base usada. Una reconciliación que restaba una tasa trimestral de
interanuales publicó la conversión de unidades como si fuera una brecha.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.observations import service
from shared.observations.models import SectorObservation

logger = logging.getLogger("sdq.observations.delta")

# ── Tipos de línea base, nombrados. El nombre viaja al contexto: un delta que no dice
# contra qué se midió obliga al lector a suponerlo, y va a suponer mal. ──────────────
BASE_ANIO_ANTERIOR = "mismo_periodo_del_anio_anterior"
BASE_ULTIMO_NIVEL = "ultimo_nivel_publicado"

#: Naturalezas cuya variación se expresa en PUNTOS y no en porcentaje.
_EN_PUNTOS = ("rate", "index")

#: Cuántos períodos tiene una ventana móvil de doce meses en una serie mensual.
VENTANA_MESES = 12


def _anio_anterior(period: str) -> Optional[str]:
    """``"2025-07"`` → ``"2024-07"``; ``"2025-Q3"`` → ``"2024-Q3"``; ``"2025"`` → ``"2024"``.

    Devuelve ``None`` ante un período que no sabe leer. Inventarle un año anterior a una
    cadena desconocida sería fabricar la comparación entera.
    """
    p = str(period or "").strip()
    if len(p) >= 4 and p[:4].isdigit():
        try:
            return f"{int(p[:4]) - 1}{p[4:]}"
        except ValueError:
            return None
    return None


def _meses_previos(period: str, n: int) -> Optional[List[str]]:
    """Los *n* períodos mensuales que terminan en *period*, incluido. ``None`` si no es mensual."""
    p = str(period or "").strip()
    if len(p) != 7 or p[4] != "-" or not (p[:4].isdigit() and p[5:].isdigit()):
        return None
    anio, mes = int(p[:4]), int(p[5:])
    if not 1 <= mes <= 12:
        return None
    salida: List[str] = []
    for _ in range(n):
        salida.append(f"{anio:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            anio, mes = anio - 1, 12
    return list(reversed(salida))


def _ventana_movil(valores: Dict[str, Optional[float]], period: str) -> Dict[str, Any]:
    """La suma de los últimos doce meses, o el motivo por el que no se puede.

    Exige los DOCE puntos. Sumar los que haya y rotularlo «doce meses» es publicar una cifra
    que no es la que su nombre dice, y el lector no tiene cómo sospecharlo.
    """
    meses = _meses_previos(period, VENTANA_MESES)
    if meses is None:
        return {"disponible": False,
                "motivo": f"el período «{period}» no es mensual: no hay ventana de doce meses"}
    faltan = [m for m in meses if valores.get(m) is None]
    if faltan:
        return {"disponible": False,
                "meses_faltantes": faltan,
                "motivo": (f"faltan {len(faltan)} de los {VENTANA_MESES} meses de la ventana "
                           f"({', '.join(faltan[:3])}{'…' if len(faltan) > 3 else ''})")}
    # Se materializan los doce valores antes de sumar: `faltan` ya garantiza que ninguno es
    # nulo, pero escribirlo así lo hace evidente para quien lee y para el checker, en vez de
    # depender de una invariante que vive tres líneas más arriba.
    puntos: List[float] = [float(v) for v in (valores[m] for m in meses) if v is not None]
    return {"disponible": True, "desde": meses[0], "hasta": meses[-1],
            "valor": round(sum(puntos), 6)}


def _variacion(valor: float, base: float, en_puntos: bool) -> Dict[str, Any]:
    """La variación con su MEDIDA declarada. Nunca un número suelto."""
    abs_ = round(valor - base, 6)
    if en_puntos:
        return {"medida": "puntos", "variacion_en_puntos": abs_, "variacion_pct": None}
    if base == 0:
        # Dividir por cero produciría un infinito o una cifra de siete dígitos que se lee
        # como una explosión del sector. El cambio absoluto sí es cierto.
        return {"medida": "absoluta", "variacion_absoluta": abs_, "variacion_pct": None,
                "motivo_sin_pct": "la línea base es cero: la variación porcentual no existe"}
    return {"medida": "porcentaje", "variacion_absoluta": abs_,
            "variacion_pct": round((valor - base) / abs(base) * 100.0, 2)}


def _direccion(valor: float, base: float) -> str:
    """La dirección se COMPUTA acá y el modelo la copia; no la deduce del par de cifras."""
    if valor > base:
        return "sube"
    if valor < base:
        return "baja"
    return "sin cambio"


def _fila(db: Session, *, sector_key: str, series_code: str, period: str,
          etiquetas: Dict[str, str]) -> Dict[str, Any]:
    filas = service.serie(db, sector_key=sector_key, series_code=series_code, hasta=period)
    if not filas:
        return {"serie": series_code, "etiqueta": etiquetas.get(series_code, series_code),
                "no_disponible": "el eje no tiene observaciones de esta serie"}

    valores: Dict[str, Optional[float]] = {r.period: r.value for r in filas}
    actual: Optional[SectorObservation] = next(
        (r for r in reversed(filas) if r.period == period), None)
    if actual is None or actual.value is None:
        return {"serie": series_code, "etiqueta": etiquetas.get(series_code, series_code),
                "periodo": period,
                "no_disponible": f"no hay observación de «{series_code}» para {period}"}

    naturaleza = (actual.nature or "unknown").strip().lower()
    salida: Dict[str, Any] = {
        "serie": series_code,
        "etiqueta": etiquetas.get(series_code, series_code),
        "periodo": period,
        "valor": actual.value,
        "unidad": actual.unit,
        "naturaleza": naturaleza,
        "emisor": actual.source,
    }

    if naturaleza == "unknown":
        salida["no_disponible"] = (
            "la naturaleza de la serie no está declarada: no se computa una variación cuya "
            "interpretación se estaría adivinando")
        return salida

    if naturaleza == "stock":
        previos = [r for r in filas if r.period < period and r.value is not None]
        base_row = previos[-1] if previos else None
        tipo_base = BASE_ULTIMO_NIVEL
    else:
        anterior = _anio_anterior(period)
        base_row = next((r for r in filas
                         if anterior and r.period == anterior and r.value is not None), None)
        tipo_base = BASE_ANIO_ANTERIOR

    if base_row is None or base_row.value is None:
        salida["linea_base"] = {
            "tipo": tipo_base,
            "no_disponible": ("no hay observación para la línea base que esta naturaleza "
                              f"exige ({tipo_base})"),
        }
    else:
        en_puntos = naturaleza in _EN_PUNTOS
        salida["linea_base"] = {"tipo": tipo_base, "periodo": base_row.period,
                                "valor": base_row.value, "unidad": base_row.unit}
        salida["movimiento"] = {"direccion": _direccion(actual.value, base_row.value),
                                **_variacion(actual.value, base_row.value, en_puntos)}

    # La ventana móvil se computa AUNQUE falte la línea base del punto: son dos medidas
    # distintas con bases distintas —el mes contra su mes, la ventana contra su ventana— y
    # atarlas hacía desaparecer la lectura anual por un hueco que no era suyo. Que aparezca
    # la lectura de doce meses cuando el mes puntual no tiene comparación es información,
    # no un descuido.
    if naturaleza == "flow":
        ventana = _ventana_movil(valores, period)
        if ventana.get("disponible"):
            ventana["comparable_con"] = "el índice anual del eje"
            base_ventana = _ventana_movil(valores, _anio_anterior(period) or "")
            if base_ventana.get("disponible"):
                ventana["linea_base"] = {"tipo": BASE_ANIO_ANTERIOR,
                                         "desde": base_ventana["desde"],
                                         "hasta": base_ventana["hasta"],
                                         "valor": base_ventana["valor"]}
                ventana["movimiento"] = {
                    "direccion": _direccion(ventana["valor"], base_ventana["valor"]),
                    **_variacion(ventana["valor"], base_ventana["valor"], False)}
            else:
                ventana["linea_base"] = {
                    "tipo": BASE_ANIO_ANTERIOR,
                    "no_disponible": base_ventana.get("motivo", "sin ventana anterior")}
        salida["ventana_movil_12m"] = ventana
    return salida


def leer_delta(db: Session, *, sector_key: str, period: str,
               series: Optional[List[str]] = None,
               etiquetas: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """El bloque del delta de *sector_key* en *period*, listo para copiar.

    Devuelve ``{"periodo", "series": [...], "sin_lectura": [...]}``. Las series que no se
    pudieron leer NO desaparecen: van en ``sin_lectura`` con su motivo, porque una lista que
    solo trae lo que salió bien se lee como que todo salió bien.
    """
    codigos = series if series is not None else service.codigos(db, sector_key=sector_key)
    etiquetas = etiquetas or {}
    filas = [_fila(db, sector_key=sector_key, series_code=c, period=period,
                   etiquetas=etiquetas) for c in codigos]
    return {
        "periodo": period,
        "series": [f for f in filas if "no_disponible" not in f],
        "sin_lectura": [{"serie": f["serie"], "etiqueta": f.get("etiqueta"),
                         "motivo": f["no_disponible"]}
                        for f in filas if "no_disponible" in f],
    }
