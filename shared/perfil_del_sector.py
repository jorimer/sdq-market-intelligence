"""El perfil de un sector económico, uniendo fuentes que nadie cruza.

**Qué contesta.** Para un sector del marco BCRD-17 —`construccion`, `turismo`, `energia`…—:
cuánto crédito le da el sistema financiero, a qué tasa, con qué mora y con qué cobertura de
provisiones, y cuánto paga de salario. Son dos registros nacionales distintos, y la única
razón por la que se pueden unir es que `shared/data/sector_crosswalk.py` los lleva a la misma
llave.

**Por qué vive en `shared/`.** Es la lectura que los once ejes sectoriales van a consumir
(fase 3 del plan, `docs/PLAN_ENRIQUECIMIENTO_SECTORIAL.md`). No tiene nada de banca adentro:
el crédito es un dato nacional que la SIB publica sobre todas las supervisadas, y se sirve
AGREGADO — acá no hay ninguna entidad nombrada.

**Lo que NO trae todavía, y por qué.** La ocupación (ENCFT) y el tamaño/crecimiento del
sector (cuentas nacionales del BCRD) viven en `SectorVariable`, que es tabla de
`sector_intel`. Traerlas exigiría que `shared/` importe el modelo de un módulo — el patrón
que la fase 1 evitó mudando la tabla del cubo en vez de leerla desde afuera. Es una decisión
de arquitectura pendiente, no un olvido, y `cobertura` lo dice en cada respuesta. Además el
sync del empleo lleva desde junio de 2026 fallando con 403 contra one.gob.do.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data.bcrd_sectors import sector_catalog
from shared.data.sector_crosswalk import SIB_SECTORS, sib_members
from shared.reference.cartera_agregacion import _medidas, _sumar, _vacio
from shared.reference.cartera_sectorial import CarteraSectorial

logger = logging.getLogger("sdq.perfil_del_sector")

#: Clave del `AppSetting` donde `tss_salario_sync` deja el salario por slug. Se lee de ahí y
#: no se recalcula: el conector de la TSS raspa un Power BI y no puede correr por consulta.
_CLAVE_SALARIO = "sector_operating_cost"

#: slug BCRD-17 → letras CIIU de la SIB que lo alimentan. Se DERIVA del crosswalk en vez de
#: escribirse: una segunda tabla del mismo mapa es como los dos se desincronizan.
_LETRAS_POR_SLUG: Dict[str, List[str]] = {}
for _s in SIB_SECTORS:
    for _m in _s.members:
        _LETRAS_POR_SLUG.setdefault(_m, []).append(_s.key)


def letras_del_slug(slug: str) -> List[str]:
    """Las letras CIIU que alimentan a *slug* (``[]`` si la SIB no lo cubre)."""
    return list(_LETRAS_POR_SLUG.get(slug, ()))


def _slugs_de_las_letras(letras: List[str]) -> List[str]:
    """Todos los slugs que esas letras alimentan — que puede ser MÁS que el pedido."""
    out: set = set()
    for letra in letras:
        out.update(sib_members(letra))
    return sorted(out)


def credito_al_sector(db: Session, slug: str, corte: date) -> Optional[Dict[str, Any]]:
    """Lo que el sistema financiero le presta a *slug* en un corte, agregado.

    **El sujeto viaja con el número y es más sutil de lo que parece.** Varias letras de la
    SIB alimentan a más de un slug: la `D` no separa manufactura local de zonas francas, y la
    `K` agrupa el inmobiliario con los servicios profesionales. Para esos slugs la cifra NO
    es del sector pedido sino del AGREGADO que la fuente publica, y repartirla sería
    fabricar. Por eso la respuesta trae `es_agregado` y `el_agregado_incluye`: quien la use
    tiene que nombrar esa población, no la del slug que pidió.

    ``None`` si la SIB no cubre el slug (`comunicaciones`) o si el corte no tiene desglose.
    """
    letras = letras_del_slug(slug)
    if not letras:
        return None

    etiquetas = [s.label for s in SIB_SECTORS if s.key in letras]
    celdas = (db.query(CarteraSectorial)
              .filter(CarteraSectorial.period_end == corte,
                      CarteraSectorial.sector.in_(etiquetas))
              .all())
    if not celdas:
        return None

    acc = _vacio()
    for c in celdas:
        _sumar(acc, c)
    if not acc["deuda"]:
        return None

    # El TOTAL del corte, para poder decir cuánto pesa este sector en el libro del país. Se
    # computa acá y el modelo lo copia: pedirle que divida dos cifras es cómo se invierte una
    # relación, y en este repo ya pasó.
    total_pais = (db.query(CarteraSectorial)
                  .filter(CarteraSectorial.period_end == corte).all())
    acc_pais = _vacio()
    for c in total_pais:
        _sumar(acc_pais, c)

    cubiertos = _slugs_de_las_letras(letras)
    es_agregado = len(cubiertos) > 1
    out: Dict[str, Any] = {
        "sector": slug,
        "corte": corte.isoformat(),
        "letras_ciiu_de_la_fuente": sorted(letras),
        "deuda_del_sistema_al_sector": round(acc["deuda"], 2),
        "peso_del_sector_en_el_credito_del_pais_pct": (
            round(100.0 * acc["deuda"] / acc_pais["deuda"], 2) if acc_pais["deuda"] else None),
        "entidades_que_le_prestan": len(acc["bancos"]),
        # El SUJETO en cada clave lo pone `_medidas`, que es el mismo cuerpo que usa el mapa
        # sectorial de banca. Un segundo cuerpo acá discreparía en silencio.
        **_medidas(acc),
        "es_agregado": es_agregado,
        "el_agregado_incluye": cubiertos if es_agregado else None,
    }
    if es_agregado:
        out["por_que_es_agregado"] = next(
            (s.note for s in SIB_SECTORS if s.key in letras and s.note), None)
    return out


def salario_del_sector(db: Session, slug: str) -> Optional[Dict[str, Any]]:
    """Salario promedio cotizable del sector (TSS), con su año.

    Es una lectura TRANSVERSAL: discrimina entre sectores y se aplica pareja en el tiempo,
    porque el conector toma el año más reciente publicado. Por eso viaja con `anio` — leerla
    como si fuera del corte del informe sería atribuirle una fecha que no tiene.
    """
    from shared.settings.models import AppSetting
    fila = db.query(AppSetting).filter(AppSetting.key == _CLAVE_SALARIO).first()
    if not fila or not fila.value:
        return None
    try:
        payload = json.loads(str(fila.value))
    except (TypeError, ValueError):
        logger.warning("El salario por sector de la TSS no es JSON legible.")
        return None
    valor = (payload.get("series") or {}).get(slug)
    if valor is None:
        return None
    return {
        "salario_promedio_cotizable_del_sector_dop_mes": round(float(valor), 2),
        "anio": payload.get("year"),
        "unidad": payload.get("unit"),
        "fuente": payload.get("source") or "TSS",
    }


def perfil_del_sector(db: Session, slug: str, corte: date) -> Optional[Dict[str, Any]]:
    """Las lecturas disponibles de un sector, juntas. ``None`` si no hay ninguna.

    Cada lectura falla por su cuenta: media respuesta es mejor que ninguna, y cuál falta lo
    dice la ausencia de su clave. `cobertura` viaja para que el consumidor sepa sobre qué
    está afirmando — es dato interno del contexto, no texto para el informe.
    """
    if slug not in {s for s, _n in sector_catalog()}:
        return None

    bloque: Dict[str, Any] = {}
    for clave, fn in (("credito_del_sistema", lambda: credito_al_sector(db, slug, corte)),
                      ("costo_laboral", lambda: salario_del_sector(db, slug))):
        try:
            valor = fn()
        except Exception:  # noqa: BLE001 — ninguna lectura tumba al informe
            logger.exception("Perfil del sector %s: falló %s al %s", slug, clave, corte)
            valor = None
        if valor:
            bloque[clave] = valor
    if not bloque:
        return None

    bloque["sector"] = slug
    bloque["cobertura"] = {
        "lecturas_servidas": [k for k in bloque if k not in ("sector", "cobertura")],
        # No es un olvido: son tablas de `sector_intel` y traerlas exige que `shared/` importe
        # el modelo de un módulo — la decisión de arquitectura que la fase 1 evitó.
        "lecturas_pendientes": ["ocupacion_encft", "tamano_y_crecimiento_bcrd"],
    }
    return bloque
