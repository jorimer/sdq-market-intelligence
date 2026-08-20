"""Banca como productor de alertas — el adaptador, no un motor nuevo.

**Este módulo no calibra ni un umbral.** `early_warning.py` ya evalúa los precursores de la
crisis RD 2003 y, sobre todo, ya produce ``signal_panel``: dónde está CADA entidad respecto de
CADA umbral, se haya encendido o no, distinguiendo la entidad sana de la NO EVALUABLE. Esas
tres situaciones son exactamente las que el canal de alertas necesita:

- ``activa``       → hay algo que avisar (``umbral``)
- ``sin_activar``  → se evaluó y no disparó ⇒ la condición está resuelta y su marcador de
                     dedup se limpia, para que pueda volver a avisar si recae
- ``sin_dato``     → la regla no se pudo evaluar. **No es lo mismo que estar bien**, y por eso
                     no entra a ``evaluadas``: dar por resuelta una condición que nadie pudo
                     mirar es cómo un guard sin su input deja de fallar y DESAPARECE

Reescribir los umbrales acá habría creado la sexta instancia del mismo guard en dos motores
distintos, que es el defecto que este repo ya pagó cinco veces en un solo módulo.

**La polaridad de la banda está invertida y hay que tenerlo presente.** ``ensemble_score``
devuelve 100 = ningún precursor activo, así que la banda «alta» es la MEJOR y «baja» la peor.
El propio motor documenta que el original se leía al revés. El orden que se le pasa a
``rule_banda`` va de mejor a peor y por eso es ``("alta", "media", "baja")`` — no al revés.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.alerts.motor import Produccion, register_producer
from shared.alerts.reglas import AlertEvent, rule_banda, rule_brecha, rule_umbral

logger = logging.getLogger("sdq.banking_score.alerts")

SECTOR = "banking"

# De mejor a peor. Ver el docstring del módulo: la polaridad de `ensemble_score` es inversa.
ORDEN_BANDAS = ("alta", "media", "baja")

# Una entidad sin ningún precursor activo no aparece en `banks`, pero su banda no es
# "desconocida": es la mejor. Sin esto, una entidad que se recupera se leería como que perdió
# su banda en vez de como que mejoró.
BANDA_SIN_ALERTAS = "alta"

BASIS_BANDA = ("Presión del conjunto de precursores (índice calibrado sobre la crisis RD "
               "2003). Señal de monitoreo, no un pronóstico.")
BASIS_BRECHA = ("El panel de precursores distingue la entidad sana de la NO EVALUABLE: una "
                "regla sin su dato no falla, desaparece.")

# Cadencia del dato bancario (trimestral) + margen, en días. Un período más viejo que esto
# significa que el trimestre siguiente debió haber entrado y no entró.
FRESCURA_MAX_DIAS = 135


def _frescura(periodo_iso: Optional[str]) -> Optional[bool]:
    """¿El período del panel está vigente? ``None`` si no se puede establecer — y ``None``
    NO publica: «no sé de cuándo es» y «está al día» son cosas distintas."""
    if not periodo_iso:
        return None
    try:
        fin = _dt.date.fromisoformat(str(periodo_iso))
    except (TypeError, ValueError):
        return None
    return (_dt.date.today() - fin).days <= FRESCURA_MAX_DIAS


def _periodo_anterior(db: Session, actual: str) -> Optional[_dt.date]:
    """El corte inmediatamente anterior al del panel, o ``None`` si es el primero.

    Sin período anterior no hay transición, y sin transición no hay ni cambio de banda ni
    brecha que declarar — solo una foto, que no es noticia.
    """
    from modules.banking_score.models.models import BankingData

    try:
        objetivo = _dt.date.fromisoformat(actual)
    except (TypeError, ValueError):
        return None
    row = (db.query(BankingData.period_end)
           .filter(BankingData.period_end < objetivo)
           .order_by(BankingData.period_end.desc())
           .first())
    return row[0] if row else None


def _direccion(valor: float, umbral: float) -> Optional[str]:
    """Se COMPUTA de los números, no se transcribe de la regla que la encendió.

    La igualdad exacta no se publica: no se puede afirmar de qué lado del umbral está algo
    que está justo encima, y una alerta que se equivoca de dirección es peor que ninguna.
    """
    if valor > umbral:
        return "por_encima"
    if valor < umbral:
        return "por_debajo"
    return None


def _severidades(bloque: Dict) -> Dict[Tuple[str, str], str]:
    """(bank_id, code) → severidad, tomada de las banderas que el motor ya evaluó."""
    out: Dict[Tuple[str, str], str] = {}
    for b in bloque.get("banks") or []:
        for a in b.get("alerts") or []:
            out[(str(b["bank_id"]), str(a["code"]))] = str(a.get("severity") or "media")
    return out


def _bandas(bloque: Dict) -> Dict[str, str]:
    """bank_id → banda del conjunto. Las entidades sin banderas no vienen en `banks` y su
    banda es la mejor, no una ausencia."""
    out = {str(bid): BANDA_SIN_ALERTAS for bid in (bloque.get("panels") or {})}
    for b in bloque.get("banks") or []:
        if b.get("band"):
            out[str(b["bank_id"])] = str(b["band"])
    return out


def _nombres(bloque: Dict) -> Dict[str, str]:
    return {str(b["bank_id"]): str(b.get("name") or b["bank_id"])
            for b in (bloque.get("banks") or [])}


def producir(db: Session) -> Produccion:
    """Convierte el panel de precursores de banca en eventos de alerta."""
    from modules.banking_score.early_warning import compute_alerts
    from modules.banking_score.models.models import Bank

    actual = compute_alerts(db)
    periodo = str(actual.get("period") or "")
    paneles: Dict = actual.get("panels") or {}
    if not periodo or not paneles:
        return Produccion()

    frescura = _frescura(periodo)
    severidades = _severidades(actual)
    nombres = dict(_nombres(actual))
    # `banks` solo trae las entidades con banderas; el resto necesita su nombre igual.
    faltantes = [bid for bid in paneles if str(bid) not in nombres]
    if faltantes:
        for b in db.query(Bank).filter(Bank.id.in_(faltantes)).all():
            nombres[str(b.id)] = str(b.name)

    anterior_fecha = _periodo_anterior(db, periodo)
    anterior = compute_alerts(db, period=anterior_fecha) if anterior_fecha else {}
    paneles_prev: Dict = (anterior.get("panels") or {}) if anterior else {}
    bandas_prev = _bandas(anterior) if anterior else {}
    bandas_hoy = _bandas(actual)

    eventos: List[AlertEvent] = []
    evaluadas: set[str] = set()

    for bid, filas in paneles.items():
        sid = str(bid)
        label = nombres.get(sid, sid)
        prev_por_code = {str(f.get("code")): f for f in (paneles_prev.get(bid) or [])}

        for fila in filas or []:
            code = str(fila.get("code") or "")
            estado = str(fila.get("estado") or "")
            clave = f"{SECTOR}:{sid}:umbral:{code}"

            if estado == "sin_dato":
                # NO entra a `evaluadas`: nadie pudo mirar esta condición, así que darla por
                # resuelta sería inventar. Lo que sí se declara es la TRANSICIÓN: que antes
                # hubiera dato y ahora no es noticia para quien vigila la entidad.
                prev = prev_por_code.get(code)
                ev = rule_brecha(
                    sector_key=SECTOR, subject=sid, sujeto_label=label, periodo=periodo,
                    dimension=code, dimension_label=str(fila.get("label") or code),
                    tenia_dato=(None if prev is None
                                else str(prev.get("estado")) != "sin_dato"),
                    tiene_dato=False, basis=BASIS_BRECHA, frescura=frescura)
                if ev is not None:
                    eventos.append(ev)
                continue

            evaluadas.add(clave)
            if estado != "activa":
                continue

            valor, umbral = fila.get("value"), fila.get("threshold")
            direccion = (None if valor is None or umbral is None
                         else _direccion(float(valor), float(umbral)))
            if direccion is None:
                continue
            ev = rule_umbral(
                sector_key=SECTOR, subject=sid, sujeto_label=label, periodo=periodo,
                metrica=code, metrica_label=str(fila.get("label") or code),
                valor=float(valor), umbral=float(umbral), direccion=direccion,
                severidad=severidades.get((sid, code), "media"),
                basis=str(fila.get("umbral_significa") or "").strip()
                or "Precursor calibrado sobre la crisis bancaria RD 2003.",
                procedencia={code: "live"}, frescura=frescura,
                clave_valor=_clave_valor(code))
            if ev is not None:
                eventos.append(ev)

        # Cambio de banda del conjunto — una sola por entidad, no una por precursor.
        ev_banda = rule_banda(
            sector_key=SECTOR, subject=sid, sujeto_label=label, periodo=periodo,
            banda_actual=bandas_hoy.get(sid), banda_previa=bandas_prev.get(sid),
            orden_bandas=ORDEN_BANDAS, basis=BASIS_BANDA, frescura=frescura)
        if ev_banda is not None:
            eventos.append(ev_banda)
        if bandas_prev.get(sid):
            evaluadas.add(f"{SECTOR}:{sid}:banda:banda")

    logger.info("alerts/banking: %d evento(s) sobre %d entidad(es) al %s",
                len(eventos), len(paneles), periodo)
    return Produccion(eventos=eventos, evaluadas=evaluadas)


# El panel de banca nombra sus métricas por concepto, y una sola es una PORCIÓN: la
# concentración se computa sobre DEUDORES. El gate exige que la clave lo diga —es la regla
# que salió de publicar «cuatro compañías concentran el 87,1%» cuando eran cuatro ramos— y
# el nombre correcto lo sabe este adaptador, no la regla genérica.
_CLAVES_CON_SUJETO = {
    "concentracion_credito": "concentracion_top10_deudores_pct",
}


def _clave_valor(code: str) -> str:
    return _CLAVES_CON_SUJETO.get(code, code)


def register() -> None:
    """Engancha banca al barrido de alertas (idempotente)."""
    register_producer(SECTOR, producir)


register()
