"""El ENTORNO de una valuación: la macro al corte y la industria del tipo de la entidad.

Es la cuarta sección de la estructura que se pidió para un informe de valuación —análisis
macroeconómico y de industria— y no existía: la plataforma tiene el módulo macro y el balance
de todo el sistema, y el informe no los pedía.

**Tres reglas, y de dónde salen.**

1. **Cada cifra macro lleva su período de fuente.** El corte manda sobre la entidad valuada
   las capas agregadas se publican con SU período. Una serie ausente se OMITE — nunca se
   publica como 0,0 —, y el bloque viaja en el payload para que la prosa no recompute nada.
2. **La industria es el RESTO del tipo de la entidad, sobre el padrón completo al mismo
   corte**, con las claves nombrando la población (`roe_del_resto_del_tipo_pct`, no
   `roe_sector`): el sujeto viaja con el número. El RESTO y no el total: una entidad que es
   el 75 % de su tipo comparada contra un agregado que ella domina siempre sale «en línea» —
   el sesgo dice «acá no pasa nada»—. Y el ROE del resto es de DOCE MESES sobre patrimonio de
   apertura —la misma base con la que se computa el de la entidad en `service.historia_de`—:
   comparar un ROE sobre apertura contra uno sobre promedio es un error sistemático.
3. **Las relaciones se computan.** «Por encima», «por debajo», «en línea» salen de la resta,
   no de la prosa
   y la brecha se publica en puntos porcentuales con su signo.

Por qué NO se cita acá la proyección del PIB: vive en `macro_forecast` con su propio gate y
readiness, y citarla desde valuación la publicaría por una puerta que no tiene ese gate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from modules.valuation.service import _un_anio_antes, utilidad_de_doce_meses
from shared.data.periodos import fin_del_periodo

logger = logging.getLogger("sdq.valuation.entorno")

#: Las series del BCRD que arman la capa macro. Son las MISMAS que consume el bloque del BVAR
#: (`macro_monitor/forecasting/bloque.py`) para que las dos superficies digan lo mismo.
SERIE_PIB = "bcrd.xls.pib_2018.serie_original_indice"
SERIE_IPC = "bcrd.xls.ipc_base_2019_2020.variacion_porcentual_12_meses"
SERIE_TC = "bcrd.xls.tasa_dolar_referencia_mc.promtrimestral.venta"

MEDIDA_INTERANUAL = "interanual"
MEDIDA_NIVEL = "nivel"
MEDIDA_VARIACION_12M = "variacion_12_meses"

#: Umbral de «en línea»: una brecha menor que esto no se lee como dirección.
EN_LINEA_PP = 0.25


@dataclass(frozen=True)
class Cifra:
    """Un número con su período de fuente y su medida. Sin período no hay cifra."""
    valor: float
    periodo: str
    medida: str
    #: Para el tipo de cambio: la variación interanual que acompaña al nivel.
    interanual_pct: Optional[float] = None


@dataclass(frozen=True)
class Industria:
    """El RESTO del tipo de la entidad, sobre el padrón completo al corte. `None` es «no se
    pudo medir». `n_entidades_del_tipo` cuenta a la entidad
    los `n_en_*` no."""
    tipo: str
    periodo: str
    n_entidades_del_tipo: int
    roe_del_resto_del_tipo_pct: Optional[float] = None
    roe_entidad_pct: Optional[float] = None
    crecimiento_cartera_del_resto_del_tipo_pct: Optional[float] = None
    crecimiento_cartera_entidad_pct: Optional[float] = None
    morosidad_del_resto_del_tipo_pct: Optional[float] = None
    morosidad_entidad_pct: Optional[float] = None
    #: Cuántas entidades del RESTO entraron a cada agregado: la población de cada cifra.
    n_en_roe: int = 0
    n_en_cartera: int = 0
    n_en_morosidad: int = 0


@dataclass(frozen=True)
class Entorno:
    pib_interanual: Optional[Cifra] = None
    inflacion_12m: Optional[Cifra] = None
    tipo_de_cambio: Optional[Cifra] = None
    industria: Optional[Industria] = None
    advertencias: Tuple[str, ...] = field(default_factory=tuple)


# ── Lectura ───────────────────────────────────────────────────────────────────────


def leer_entorno(db: Session, *, bank_id: str, tipo: str, periodo: str) -> Entorno:
    """Todo lo que la sección publica, computado al CORTE del informe."""
    corte = date.fromisoformat(periodo[:10])
    avisos: List[str] = []
    return Entorno(
        pib_interanual=_seguro(lambda: _pib_interanual(db, corte), "PIB", avisos),
        inflacion_12m=_seguro(lambda: _inflacion(db, corte), "inflación", avisos),
        tipo_de_cambio=_seguro(lambda: _tipo_de_cambio(db, corte), "tipo de cambio", avisos),
        industria=_seguro(lambda: _industria(db, bank_id=bank_id, tipo=tipo, corte=corte),
                          "industria", avisos),
        advertencias=tuple(avisos))


def _seguro(fn, nombre: str, avisos: List[str]):
    """Una capa que falla no se lleva el informe: se omite y se anota por qué."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        logger.warning("entorno: no se pudo leer %s: %s", nombre, e)
        avisos.append(f"{nombre}: no se pudo leer ({e.__class__.__name__})")
        return None


def _observaciones(db: Session, code: str) -> List[Tuple[str, float]]:
    from modules.macro_monitor.forecasting.panel import observaciones
    return observaciones(db, code)


def _al_corte(pares: List[Tuple[str, float]], corte: date) -> List[Tuple[str, float]]:
    return [(p, v) for p, v in pares if (fin_del_periodo(p) or date.max) <= corte]


def _pib_interanual(db: Session, corte: date) -> Optional[Cifra]:
    """Variación del índice de volumen contra el mismo trimestre del año anterior, con la
    función que comparten el bloque del BVAR y el panel sectorial: mismo número en las tres
    superficies."""
    from modules.macro_monitor.forecasting.panel import variacion_interanual_pct
    pares = _al_corte(_observaciones(db, SERIE_PIB), corte)
    if not pares:
        return None
    trimestres = [p for p, _v in pares]
    yoy = variacion_interanual_pct(dict(pares), trimestres)
    if not yoy:
        return None
    ultimo = trimestres[-1]
    if ultimo not in yoy:
        return None
    return Cifra(round(yoy[ultimo], 4), ultimo, MEDIDA_INTERANUAL)


def _inflacion(db: Session, corte: date) -> Optional[Cifra]:
    pares = _al_corte(_observaciones(db, SERIE_IPC), corte)
    if not pares:
        return None
    p, v = pares[-1]
    return Cifra(round(v, 4), p, MEDIDA_VARIACION_12M)


def _tipo_de_cambio(db: Session, corte: date) -> Optional[Cifra]:
    pares = _al_corte(_observaciones(db, SERIE_TC), corte)
    if not pares:
        return None
    p, v = pares[-1]
    previo = dict(pares).get(_mismo_trimestre_anterior(p))
    yoy = round((v / previo - 1) * 100, 4) if previo else None
    return Cifra(round(v, 4), p, MEDIDA_NIVEL, interanual_pct=yoy)


def _mismo_trimestre_anterior(periodo: str) -> str:
    return f"{int(periodo[:4]) - 1}{periodo[4:]}"


def _industria(db: Session, *, bank_id: str, tipo: str, corte: date) -> Optional[Industria]:
    """Agregados del RESTO del tipo al corte, con la misma ventana que el ROE de la entidad.
    La entidad queda FUERA del agregado: contra un total que ella domina, siempre sale en línea."""
    if not tipo:
        return None
    apertura = _un_anio_antes(corte)
    if apertura is None:
        return None
    filas = db.execute(text(
        "SELECT d.bank_id, d.period_end, d.patrimonio_tecnico, d.utilidad_neta, "
        "d.cartera_bruta, d.cartera_vencida_90d FROM banking_data d "
        "JOIN banks b ON b.id = d.bank_id WHERE b.bank_type = :t "
        "AND d.period_end IN (:c, :a, :dic, :mismo)"),
        # Fechas como ISO, igual que el resto del eje: es lo que la columna guarda en SQLite y
        # lo que Postgres castea; y evita el adaptador de `date` de sqlite3, deprecado.
        {"t": tipo, "c": corte.isoformat(), "a": apertura.isoformat(),
         "dic": date(corte.year - 1, 12, 31).isoformat(),
         "mismo": apertura.isoformat()}).fetchall()
    por_entidad: Dict[str, Dict[date, Tuple[Optional[float], ...]]] = {}
    for f in filas:
        d = f[1] if isinstance(f[1], date) else date.fromisoformat(str(f[1])[:10])
        por_entidad.setdefault(str(f[0]), {})[d] = tuple(
            float(x) if x is not None else None for x in f[2:6])
    presentes = {b for b, cortes in por_entidad.items() if corte in cortes
                 and cortes[corte][0] is not None}
    if len(presentes) < 2:
        return None  # sin padrón no hay tipo contra el cual comparar
    roe_num = roe_den = 0.0
    n_roe = 0
    car_num = car_den = 0.0
    n_car = 0
    mora_num = mora_den = 0.0
    n_mora = 0
    propio: Dict[str, Optional[float]] = {"roe": None, "cartera": None, "mora": None}
    for b in presentes:
        cortes = por_entidad[b]
        patr_c, util_c, cart_c, venc_c = cortes[corte]
        patr_a, _u, cart_a, _v = cortes.get(apertura, (None, None, None, None))
        ytd = {d: v[1] for d, v in cortes.items()}
        doce = utilidad_de_doce_meses(ytd, corte)
        roe = (doce / patr_a * 100) if (doce is not None and patr_a) else None
        crec = ((cart_c / cart_a - 1) * 100) if (cart_c is not None and cart_a) else None
        mora = (venc_c / cart_c * 100) if (venc_c is not None and cart_c) else None
        if b == bank_id:
            propio = {"roe": roe, "cartera": crec, "mora": mora}
            continue  # la entidad no entra a su propio comparador
        if roe is not None and doce is not None and patr_a:
            roe_num += doce
            roe_den += patr_a
            n_roe += 1
        if crec is not None and cart_c is not None and cart_a:
            car_num += cart_c
            car_den += cart_a
            n_car += 1
        if mora is not None and venc_c is not None and cart_c:
            mora_num += venc_c
            mora_den += cart_c
            n_mora += 1

    def _r(v: Optional[float]) -> Optional[float]:
        return None if v is None else round(v, 4)

    return Industria(
        tipo=tipo, periodo=corte.isoformat(), n_entidades_del_tipo=len(presentes),
        roe_del_resto_del_tipo_pct=_r(roe_num / roe_den * 100) if roe_den else None,
        roe_entidad_pct=_r(propio["roe"]),
        crecimiento_cartera_del_resto_del_tipo_pct=(
            _r((car_num / car_den - 1) * 100) if car_den else None),
        crecimiento_cartera_entidad_pct=_r(propio["cartera"]),
        morosidad_del_resto_del_tipo_pct=_r(mora_num / mora_den * 100) if mora_den else None,
        morosidad_entidad_pct=_r(propio["mora"]),
        n_en_roe=n_roe, n_en_cartera=n_car, n_en_morosidad=n_mora)


# ── Relaciones computadas ─────────────────────────────────────────────────────────


def relacion(entidad: Optional[float], tipo: Optional[float]) -> Optional[Tuple[float, str]]:
    """`(brecha_pp, «por encima» | «por debajo» | «en línea»)`, o `None` si falta un lado."""
    if entidad is None or tipo is None:
        return None
    brecha = entidad - tipo
    if abs(brecha) < EN_LINEA_PP:
        return round(brecha, 4), "en línea"
    return round(brecha, 4), ("por encima" if brecha > 0 else "por debajo")


# ── Serialización: el bloque viaja en el payload ──────────────────────────────────


def a_dict(e: Entorno) -> Dict[str, Any]:
    def cifra(c: Optional[Cifra]) -> Optional[Dict[str, Any]]:
        if c is None:
            return None
        d: Dict[str, Any] = {"valor": c.valor, "periodo": c.periodo, "medida": c.medida}
        if c.interanual_pct is not None:
            d["interanual_pct"] = c.interanual_pct
        return d
    ind = e.industria
    return {
        "macro": {"pib_interanual": cifra(e.pib_interanual),
                  "inflacion_12m": cifra(e.inflacion_12m),
                  "tipo_de_cambio": cifra(e.tipo_de_cambio)},
        "industria": None if ind is None else {
            "tipo": ind.tipo, "periodo": ind.periodo,
            "n_entidades_del_tipo": ind.n_entidades_del_tipo,
            "roe_del_resto_del_tipo_pct": ind.roe_del_resto_del_tipo_pct,
            "roe_entidad_pct": ind.roe_entidad_pct,
            "crecimiento_cartera_del_resto_del_tipo_pct":
                ind.crecimiento_cartera_del_resto_del_tipo_pct,
            "crecimiento_cartera_entidad_pct": ind.crecimiento_cartera_entidad_pct,
            "morosidad_del_resto_del_tipo_pct": ind.morosidad_del_resto_del_tipo_pct,
            "morosidad_entidad_pct": ind.morosidad_entidad_pct,
            "n_en_roe": ind.n_en_roe, "n_en_cartera": ind.n_en_cartera,
            "n_en_morosidad": ind.n_en_morosidad},
        "advertencias": list(e.advertencias),
    }


def desde_dict(d: Optional[Dict[str, Any]]) -> Optional[Entorno]:
    if not d:
        return None
    mac = d.get("macro") or {}

    def cifra(x: Optional[Dict[str, Any]]) -> Optional[Cifra]:
        if not x or x.get("valor") is None or not x.get("periodo"):
            return None
        return Cifra(float(x["valor"]), str(x["periodo"]), str(x.get("medida") or ""),
                     interanual_pct=(None if x.get("interanual_pct") is None
                                     else float(x["interanual_pct"])))
    ind = d.get("industria")
    industria = None
    if ind:
        def f(k: str) -> Optional[float]:
            return None if ind.get(k) is None else float(ind[k])
        industria = Industria(
            tipo=str(ind.get("tipo") or ""), periodo=str(ind.get("periodo") or ""),
            n_entidades_del_tipo=int(ind.get("n_entidades_del_tipo") or 0),
            roe_del_resto_del_tipo_pct=f("roe_del_resto_del_tipo_pct"),
            roe_entidad_pct=f("roe_entidad_pct"),
            crecimiento_cartera_del_resto_del_tipo_pct=f("crecimiento_cartera_del_resto_del_tipo_pct"),
            crecimiento_cartera_entidad_pct=f("crecimiento_cartera_entidad_pct"),
            morosidad_del_resto_del_tipo_pct=f("morosidad_del_resto_del_tipo_pct"),
            morosidad_entidad_pct=f("morosidad_entidad_pct"),
            n_en_roe=int(ind.get("n_en_roe") or 0), n_en_cartera=int(ind.get("n_en_cartera") or 0),
            n_en_morosidad=int(ind.get("n_en_morosidad") or 0))
    return Entorno(pib_interanual=cifra(mac.get("pib_interanual")),
                   inflacion_12m=cifra(mac.get("inflacion_12m")),
                   tipo_de_cambio=cifra(mac.get("tipo_de_cambio")),
                   industria=industria, advertencias=tuple(d.get("advertencias") or ()))
