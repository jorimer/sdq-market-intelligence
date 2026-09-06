"""El informe trae el ENTORNO: macro al corte y la industria del tipo de la entidad.

**El defecto.** Contra la estructura de diez secciones que se pidió para un informe de
valuación, la cuarta —análisis macroeconómico y de industria— no existía: tres líneas macro
incidentales y el PIB solo en Fuentes. La plataforma tiene el módulo macro y el balance de
todo el sistema, y el informe no los pedía. Familia «servir el dato no alcanza: hay que
pedirlo».

**Doctrina que gobierna la sección.** Cada cifra macro lleva su período de fuente (el corte
manda sobre la entidad
las capas agregadas van con SU período). Una serie ausente se omite —
nunca «0,00 %»—. La industria es el TIPO de la entidad sobre el padrón completo al mismo
corte, con las claves nombrando la población (`_del_tipo`), y las relaciones «por encima /
por debajo / en línea» se COMPUTAN. El ROE del tipo es de doce meses sobre apertura, la
misma base que el de la entidad: comparar bases distintas es un error sistemático.

Los tests entran por HTTP: el informe se pide como lo pide el cliente.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Dict

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
import shared.products.models  # noqa: F401
from modules.banking_score.models.models import Bank, BankType
from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.tests._siembra import sembrar_trimestres
from shared.database.base import Base
from shared.products.tiers import ProductTier

CURVA = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
         ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]
ROE_GRANDE, ROE_CHICA = 12.0, 8.0
MORA_GRANDE, MORA_CHICA = 0.02, 0.04
CARTERA_SOBRE_PATRIMONIO = 8.0


def _db(*, con_ipc: bool = True):
    from modules.valuation.entorno import SERIE_IPC, SERIE_PIB, SERIE_TC
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    for ident, nombre, patr, roe, mora in (
            ("aap1", "Asociación Grande", 30_000_000_000.0, ROE_GRANDE, MORA_GRANDE),
            ("aap2", "Asociación Chica", 10_000_000_000.0, ROE_CHICA, MORA_CHICA)):
        s.add(Bank(id=ident, name=nombre, bank_type=BankType.aap))
        sembrar_trimestres(s, ident, patrimonio_diciembre=[patr * (1.05 ** j) for j in range(4)],
                           anios=(2022, 2023, 2024, 2025), roe_anual_pct=roe)
        s.flush()
        s.execute(text("UPDATE banking_data SET cartera_bruta = patrimonio_tecnico * :k, "
                       "cartera_vencida_90d = patrimonio_tecnico * :k * :m WHERE bank_id = :b"),
                  {"k": CARTERA_SOBRE_PATRIMONIO, "m": mora, "b": ident})
    for p, v in CURVA:
        s.add(MacroSeries(series_code=SERIE_RF, period=p, value=v))
    for i in range(29):
        s.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                          period=f"{2019 + i // 4}-Q{i % 4 + 1}", value=9.03))
    # PIB real: índice trimestral que crece 4 % interanual; IPC mensual; tipo de cambio
    # trimestral que sube 4,2 % interanual.
    for i in range(12):
        s.add(MacroSeries(series_code=SERIE_PIB, period=f"{2023 + i // 4}-Q{i % 4 + 1}",
                          value=100.0 * (1.04 ** (i / 4))))
        s.add(MacroSeries(series_code=SERIE_TC, period=f"{2023 + i // 4}-Q{i % 4 + 1}",
                          value=55.0 * (1.042 ** (i / 4))))
    if con_ipc:
        for m in range(1, 13):
            s.add(MacroSeries(series_code=SERIE_IPC, period=f"2025-{m:02d}", value=3.0 + m * 0.05))
    s.commit()
    return s


@pytest.fixture()
def db():
    s = _db()
    yield s
    s.close()


def _por_http(db, tier: str = "deep_dive", scope: str = "aap1") -> Dict:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.database.session import get_db
    from shared.products.access import (
        AccessDecision, AccessOutcome, AccessTier, require_product_access)
    from shared.products.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/products")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_product_access] = lambda: AccessDecision(
        outcome=AccessOutcome.allowed, sector_key="valuation", tier=ProductTier(tier),
        required_tier=AccessTier.enterprise, user_tier=AccessTier.enterprise)
    r = TestClient(app).get(f"/api/v1/products/valuation/{tier}/report",
                            params={"period": "2025-12-31", "scope": scope})
    assert r.status_code == 200, r.text[:300]
    return r.json()


# ── La sección existe, en los dos niveles nombrados, entre la entidad y lo financiero ──


@pytest.mark.parametrize("tier", ["insight", "deep_dive"])
def test_la_seccion_de_ENTORNO_llega_por_HTTP_y_va_entre_la_entidad_y_lo_financiero(db, tier):
    from modules.valuation.products import (
        SECCION_ANTECEDENTES, SECCION_ENTORNO, SECCION_FINANCIERO)
    cuerpo = _por_http(db, tier)
    assert SECCION_ENTORNO in cuerpo["narratives"], f"{tier}: no hay sección de entorno"
    orden = cuerpo["commercial"]["sections"]
    assert orden.index(SECCION_ANTECEDENTES) < orden.index(SECCION_ENTORNO) < orden.index(
        SECCION_FINANCIERO), orden
    assert len(cuerpo["narratives"][SECCION_ENTORNO]) > 600


# ── Macro: cada cifra con su período, computada de la serie ──────────────────────


def test_la_capa_MACRO_trae_PIB_inflacion_y_tipo_de_cambio_con_su_periodo(db) -> None:
    from modules.valuation.products import SECCION_ENTORNO
    ent = _por_http(db)["narratives"][SECCION_ENTORNO]
    # PIB interanual: el índice crece 4 % contra el mismo trimestre del año anterior.
    assert "4.00 %" in ent and "2025-Q4" in ent, "el PIB interanual al corte no está"
    # Inflación: la última observación al corte es la de diciembre (3,60 %).
    assert "3.60 %" in ent and "2025-12" in ent
    # Tipo de cambio: nivel al corte e interanual.
    tc = 55.0 * (1.042 ** (11 / 4))
    tc_prev = 55.0 * (1.042 ** (7 / 4))
    assert f"{tc:.2f}" in ent and f"{(tc / tc_prev - 1) * 100:.2f} %" in ent
    # Y la Rf con la que se valuó —mínimo y máximo de la ventana de ocho—, que ya es un
    # insumo del informe.
    ventana = [v for _p, v in CURVA][-8:]
    assert f"{min(ventana):.2f} %" in ent and f"{max(ventana):.2f} %" in ent


def test_una_serie_AUSENTE_se_omite_y_no_se_publica_como_cero() -> None:
    from modules.valuation.products import SECCION_ENTORNO
    s = _db(con_ipc=False)
    try:
        ent = _por_http(s)["narratives"][SECCION_ENTORNO]
    finally:
        s.close()
    assert "inflación" not in ent.lower(), "sin serie de IPC la sección habla de inflación"
    assert "0.00 %" not in ent
    assert "4.00 %" in ent, "el PIB sí estaba y desapareció con la inflación"


# ── Industria: el TIPO sobre el padrón completo, misma base, relación computada ──


def test_la_capa_de_INDUSTRIA_compara_contra_el_TIPO_con_la_MISMA_base_y_computa_la_relacion(db):
    from modules.valuation.products import SECCION_ENTORNO
    ent = _por_http(db)["narratives"][SECCION_ENTORNO]
    # El comparador es el RESTO del tipo: la Grande es el 75 % del total y contra el total
    # saldría casi en línea (11,0 %); contra el resto (la Chica, 8 %) la brecha es +4 pp.
    total = (30e9 * ROE_GRANDE + 10e9 * ROE_CHICA) / 40e9
    assert f"{total:.2f} %" not in ent, "el ROE del comparador incluye a la propia entidad"
    assert f"{ROE_CHICA:.2f} % (1)" in ent, "el ROE del resto no es el de las otras entidades"
    assert f"{ROE_GRANDE:.2f} %" in ent
    assert f"+{ROE_GRANDE - ROE_CHICA:.2f} pp" in ent and "por encima" in ent, (
        "la relación entidad vs resto no se computó")
    # Morosidad: 2 % la entidad, 4 % el resto → por debajo.
    assert f"{MORA_CHICA * 100:.2f} % (1)" in ent and "por debajo" in ent
    # Crecimiento de cartera: 5 % las dos → en línea.
    assert "5.00 %" in ent and "en línea con" in ent
    assert "2 entidades" in ent, "la población del tipo no se nombra"


def test_las_CLAVES_del_entorno_nombran_su_poblacion_y_viajan_en_el_payload(db) -> None:
    """El sujeto viaja con el número: `roe_del_resto_del_tipo_pct`, no `roe_sector`. Y el bloque va en
    el payload —la prosa no recomputa nada— con la medida y el período de cada cifra."""
    from modules.valuation.products import ValuationProduct
    snap = ValuationProduct(db).snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    e = snap.payload["entorno"]
    ind, mac = e["industria"], e["macro"]
    for k in ("roe_del_resto_del_tipo_pct", "morosidad_del_resto_del_tipo_pct",
              "crecimiento_cartera_del_resto_del_tipo_pct", "n_entidades_del_tipo", "tipo"):
        assert k in ind, f"falta {k}"
    assert ind["tipo"] == "aap" and ind["n_entidades_del_tipo"] == 2
    for k in ("pib_interanual", "inflacion_12m", "tipo_de_cambio"):
        assert k in mac and "periodo" in mac[k] and "medida" in mac[k], k
    assert mac["pib_interanual"]["medida"] == "interanual"


def test_la_MUESTRA_trae_el_entorno_ilustrativo() -> None:
    from modules.valuation.products import SECCION_ENTORNO, ValuationProduct
    prod = ValuationProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive,
                                       prod.sample_snapshot(ProductTier.deep_dive)))
    assert SECCION_ENTORNO in narr and len(narr[SECCION_ENTORNO]) > 400
