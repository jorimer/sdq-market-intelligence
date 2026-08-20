"""Qué se puede AFIRMAR de cada eje hoy — computado, con su frescura, y vetable.

Todo material comercial (catálogo, deck, propuesta) repite cifras de validación. Hasta ahora
esas cifras se copiaban a mano de un reporte, y el reporte podía haber envejecido: producción
sirvió durante 19 días un Gini de 0,44 calculado con un score que ya no existía, mientras el
deck decía 0,16. Copiar de un artefacto obsoleto es cómo una contradicción de la casa termina
en un PDF entregado a un cliente.

Este módulo es la ÚNICA fuente de la tabla comercial de validación. Tres propiedades:

1. **Computa, no transcribe.** Lee el reporte persistido de cada motor y arma la afirmación
   con sus cifras. Nadie escribe un Gini a mano.
2. **Veta lo obsoleto.** Una credencial cuyo reporte está `stale` —o cuya frescura es
   indeterminada— sale marcada `publicable: False`. El gate de la Fase 6: si no se puede
   verificar que la cifra corresponde al insumo de hoy, no entra a material comercial.
3. **Distingue seis grupos**, porque «tiene validación» abarca cosas que no se comparan: un
   backtest contra quiebras reales y un índice sin corte transversal no son el mismo
   argumento de venta.

El estado ESTRUCTURAL de cada eje (si tiene motor, qué lo impide) lo declara el producto
(`ESTADO_BACKTEST`); acá se le suma el VEREDICTO vigente, que vive en el reporte y cambia.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# Los seis grupos, de mayor a menor fuerza del argumento. El orden importa: es el que usa
# el material comercial para no presentar como equivalentes cosas que no lo son.
GRUPO_EVENTO_REAL = "A · validado contra evento real"
GRUPO_CONCLUYENTE = "B · discriminación concluyente contra desenlace realizado"
GRUPO_CONVERGENTE = "C · concluyente por validez convergente"
GRUPO_PARCIAL = "D · validación parcial o acotada"
GRUPO_NO_CONCLUYENTE = "E · validación corrida y NO concluyente"
# «Sin backtest» a secas sería inexacto para política monetaria, que SÍ tiene backtest
# —expanding-window out-of-sample sobre 190 decisiones— pero de CLASIFICACIÓN de una serie,
# no de discriminación entre sujetos. El rótulo nombra lo que falta, no lo que no hay.
GRUPO_SIN_MOTOR = "F · sin backtest de discriminación transversal (obstáculo declarado)"

GRUPOS = (GRUPO_EVENTO_REAL, GRUPO_CONCLUYENTE, GRUPO_CONVERGENTE,
          GRUPO_PARCIAL, GRUPO_NO_CONCLUYENTE, GRUPO_SIN_MOTOR)

# Ejes cuya validación es CONVERGENTE (contra una medida independiente del mismo período),
# no un backtest temporal. Se declara acá porque es una propiedad del método, no del dato.
_CONVERGENTES = {"social_dev"}


def _reporte(db: Session, clave: str) -> Optional[Dict[str, Any]]:
    from shared.settings.models import AppSetting

    try:
        row = db.query(AppSetting).filter(AppSetting.key == clave).first()
        return json.loads(str(row.value)) if row and row.value else None
    except Exception:  # noqa: BLE001 — una credencial que no se puede leer no rompe la tabla
        db.rollback()
        return None


def _mejor_senal(reporte: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La señal que el propio reporte declara titular, si la hay.

    Nunca elige «la de mayor Gini»: un titular por magnitud convierte un resultado no
    concluyente en credencial. Si el reporte no nombra titular, no hay titular.
    """
    # Dos motores nombran lo mismo distinto: `signals`/`headline_signal` (banca, seguros,
    # pensiones) y `outcomes`/`headline_outcome` (sector_intel). Leer solo uno hacía que el
    # titular DECLARADO por el otro no se leyera nunca, y la credencial caía al primer bloque
    # del reporte — que en sector_intel es el desenlace que el propio motor descarta.
    titular = reporte.get("headline_signal") or reporte.get("headline_outcome")
    senales = reporte.get("signals") or reporte.get("outcomes") or {}
    if titular and isinstance(senales.get(titular), dict):
        return {"senal": titular, **senales[titular]}
    return None


def _poblacion(reporte: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Sobre QUIÉN se midió la cifra, si el motor lo declara.

    Viaja pegada a la credencial y no en un documento aparte. El caso: el Gini de banca se
    cita con su N desde siempre, y ese N incluye un 47 % de entidades que no otorgan crédito
    —están en el universo por diseño del producto, pero un lector que ve «Gini 0,23 · n=1.693»
    entiende «discriminación entre bancos», que no es lo que se midió. El sujeto viaja con el
    número o el número se reatribuye solo.
    """
    pob = reporte.get("poblacion_del_panel")
    if not isinstance(pob, dict):
        return None
    sin_credito = pob.get("sin_libro_de_credito") or {}
    return {
        "por_tipo_de_entidad": pob.get("por_tipo_de_entidad"),
        "sin_libro_de_credito": sin_credito or None,
        "nota": pob.get("nota") or pob.get("motivo"),
    }


def _primario(reporte: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """El desenlace que el motor declara TARGETEAR, concluya o no.

    `headline_outcome` responde «¿cuál sostiene una afirmación?» y puede ser None;
    `outcome_primario` responde «¿cuál hay que mirar?», que es un hecho de diseño. Sin la
    segunda, un eje sin titular caía al primer bloque del reporte — y en `sector_intel` ese es
    el desenlace de empleo, que el propio motor declara que «NO es lo que el IAI dice
    anticipar». La tabla comercial publicó eso.
    """
    clave = reporte.get("outcome_primario")
    bloque = (reporte.get("outcomes") or {}).get(clave) if clave else None
    return {"senal": clave, **bloque} if isinstance(bloque, dict) else None


def _metrica_de_bloque(b: Dict[str, Any], senal: Optional[str]) -> Optional[Dict[str, Any]]:
    """Traduce un bloque de desenlace a la forma de la tabla, sea Gini o IC medio anual."""
    if b.get("gini") is not None:
        ic = b.get("gini_ci") or [None, None]
        return {"metrica": "Gini", "valor": b.get("gini"), "ic": ic,
                "n": b.get("n_obs") or b.get("n_observations"), "eventos": b.get("n_events"),
                "senal": senal, "concluyente": bool(b.get("conclusive")),
                "invertida": bool(b.get("invertida") or b.get("invertido")),
                "control_de_tamano": b.get("control_solo_tamano")}
    if b.get("mean_yearly_ic") is not None:
        return {"metrica": "IC medio anual", "valor": b.get("mean_yearly_ic"),
                "ic": b.get("ic_ci") or [None, None],
                "n": b.get("n_observations"), "eventos": None, "senal": senal,
                "concluyente": bool(b.get("conclusive")),
                "invertida": bool(b.get("invertido") or b.get("invertida")),
                "control_de_tamano": b.get("control_solo_tamano")}
    return None


def _cifra_principal(eje: str, reporte: Dict[str, Any]) -> Dict[str, Any]:
    """Métrica, valor, IC y N de la cifra que ese eje publica. Sin inventar formas."""
    senal = _mejor_senal(reporte)
    if senal:
        cifra = _metrica_de_bloque(senal, senal.get("senal"))
        if cifra:
            return cifra
    # Ningún desenlace concluye: se muestra el que el motor declara PRIMARIO, no el primer
    # bloque que aparezca. Una cifra no concluyente se publica igual —el grupo la acota— pero
    # tiene que ser la del desenlace que el índice dice anticipar.
    primario = _primario(reporte)
    if primario:
        cifra = _metrica_de_bloque(primario, primario.get("senal"))
        if cifra:
            return cifra
    # Formas propias de cada motor, leídas tal cual las publica.
    for bloque in ("governance", "export_collapse"):
        b = reporte.get(bloque)
        if isinstance(b, dict) and b.get("gini") is not None:
            ic = b.get("gini_ci") or [None, None]
            return {"metrica": "Gini", "valor": b.get("gini"), "ic": ic,
                    "n": b.get("n_observations"), "eventos": b.get("n_events"),
                    "senal": bloque, "concluyente": bool(ic[0] is not None and ic[0] > 0),
                    "invertida": bool(b.get("invertida") or b.get("invertido")),
                    "control_de_tamano": b.get("control_solo_tamano")}
    if reporte.get("spearman") is not None:
        ic = reporte.get("spearman_ci") or [None, None]
        concluye = bool(ic[0] is not None and ic[1] is not None and (ic[0] > 0 or ic[1] < 0))
        return {"metrica": "Spearman", "valor": reporte.get("spearman"), "ic": ic,
                "n": reporte.get("n_regions") or reporte.get("n_countries"),
                "eventos": None, "senal": None, "concluyente": concluye,
                # NUNCA se deduce del signo: en ESG el desenlace es mortalidad y un Spearman
                # NEGATIVO es la dirección CORRECTA (más resiliencia, menos muertes). Deducirlo
                # acá marcó como «invertido» el resultado concluyente de ese eje, en el
                # documento comercial. La dirección buena la sabe el motor, no el consumidor.
                "invertida": bool(reporte.get("invertida") or reporte.get("invertido")),
                "control_de_tamano": reporte.get("control_solo_tamano")}
    if reporte.get("gini") is not None:
        ic = reporte.get("gini_ci") or [None, None]
        return {"metrica": "Gini", "valor": reporte.get("gini"), "ic": ic,
                "n": reporte.get("n_observations"), "eventos": reporte.get("n_events"),
                "senal": None, "concluyente": bool(ic[0] is not None and ic[0] > 0),
                "invertida": bool(reporte.get("invertida") or reporte.get("invertido")),
                "control_de_tamano": reporte.get("control_solo_tamano")}
    if reporte.get("mean_yearly_ic") is not None:
        ic = reporte.get("ic_ci") or [None, None]
        return {"metrica": "IC medio anual", "valor": reporte.get("mean_yearly_ic"), "ic": ic,
                "n": reporte.get("n_observations"), "eventos": None, "senal": None,
                "concluyente": bool(ic[0] is not None and ic[0] > 0),
                "invertida": bool(reporte.get("invertido") or reporte.get("invertida")),
                "control_de_tamano": None}
    return {"metrica": None, "valor": None, "ic": None, "n": None, "eventos": None,
            "senal": None, "concluyente": False, "invertida": False,
            "control_de_tamano": None}


def _grupo(eje: str, estado, cifra: Dict[str, Any], evento_real: bool) -> str:
    if evento_real:
        return GRUPO_EVENTO_REAL
    if estado is not None and not estado.tiene_motor:
        return GRUPO_SIN_MOTOR
    if eje in _CONVERGENTES:
        return GRUPO_CONVERGENTE if cifra["concluyente"] else GRUPO_NO_CONCLUYENTE
    if cifra["valor"] is None:
        return GRUPO_PARCIAL
    return GRUPO_CONCLUYENTE if cifra["concluyente"] else GRUPO_NO_CONCLUYENTE


def credenciales(db: Session) -> Dict[str, Any]:
    """Tabla de credenciales por eje del catálogo, lista para material comercial.

    ``publicable`` es el gate: solo True cuando la cifra existe Y su reporte se verificó
    vigente contra el insumo. Un `stale` indeterminado NO pasa — la mitad del defecto que
    originó todo esto fue servir como verdad un número del que nadie podía decir de cuándo era.
    """
    import app.main  # noqa: F401 — asegura productos y motores registrados
    from shared.products.registry import PRODUCT_CATALOG, get_product
    from shared.validation.frescura import MOTORES, con_frescura

    filas: List[Dict[str, Any]] = []
    for entrada in PRODUCT_CATALOG:
        producto = get_product(entrada.sector_key, db)
        estado = getattr(type(producto), "ESTADO_BACKTEST", None)
        motor = MOTORES.get(estado.eje_motor) if (estado and estado.eje_motor) else None

        reporte = _reporte(db, motor.clave) if motor else None
        cifra = _cifra_principal(entrada.sector_key, reporte) if reporte else {
            "metrica": None, "valor": None, "ic": None, "n": None, "eventos": None,
            "senal": None, "concluyente": False}
        frescura = (con_frescura(dict(reporte), motor.eje, db)
                    if (reporte and motor) else {"stale": None,
                                                 "stale_reason": "sin reporte persistido"})
        # La cohorte de quiebras reales de banca es una credencial APARTE del backtest: se
        # corre en vivo sobre el ledger de terminaciones y no depende de este reporte.
        evento_real = entrada.sector_key == "banking"
        filas.append({
            "eje": entrada.sector_key,
            "nombre": entrada.display_name,
            "grupo": _grupo(entrada.sector_key, estado, cifra, evento_real),
            **cifra,
            # La POBLACIÓN viaja con la cifra. Sin esto, «Gini 0,23 · n=1.693» se lee como
            # discriminación entre bancos, y el 47 % de ese panel no otorga crédito.
            "poblacion": _poblacion(reporte or {}),
            "generated_at": (reporte or {}).get("generated_at"),
            "stale": frescura.get("stale"),
            "stale_reason": frescura.get("stale_reason"),
            # EL GATE. Sin cifra no hay nada que publicar; con cifra, solo si se verificó
            # vigente. `stale is None` (indeterminado) no pasa, a propósito.
            "publicable": bool(cifra["valor"] is not None and frescura.get("stale") is False),
            "estado_backtest": asdict(estado) if estado is not None else None,
        })

    vetadas = [f["eje"] for f in filas
               if f["valor"] is not None and not f["publicable"]]
    return {
        "ejes": filas,
        "por_grupo": {g: [f["eje"] for f in filas if f["grupo"] == g] for g in GRUPOS},
        "n_publicables": sum(1 for f in filas if f["publicable"]),
        # Cifras que EXISTEN pero no se pueden publicar por frescura. Se listan en vez de
        # desaparecer: un veto silencioso se lee como que el eje no tiene validación.
        "vetadas_por_frescura": vetadas,
    }
