"""La base del valor se DECLARA, los supuestos son una sección propia, y la muestra es
producible por el motor.

**Los tres defectos, medidos sobre un Deep Dive real generado de `d9578841`.**

1. El modelo valúa el 100 % del patrimonio, como participación de control y en marcha, sin
   prima de control ni descuento por iliquidez — y no lo decía en ninguna parte: cero líneas
   sobre «prima de control», «minoría» o «iliquidez». Un lector profesional lo busca, y su
   ausencia silenciosa se lee como omisión, no como decisión. El punto que además hace
   CONSISTENTE al informe: el panel de transacciones son compras de control, así que el
   contraste P/B modelo vs. P/B pagado ya está en la misma base — y tampoco se decía.
2. §6 «Metodología de valuación» y §10 «Supuestos y sensibilidad» servían el MISMO texto
   (`SECCION_SUPUESTOS: metodologia` en `_secciones_computadas`). Un informe de 13 secciones
   con dos idénticas. La sección de supuestos tiene que traer los PARÁMETROS que produjeron
   esta cifra —Rf, β, ERP, Ke, ROE, persistencia, retención, g— con su procedencia, y la
   sensibilidad; la de metodología, el método.
3. La muestra curada publicaba un rango de Ke de 2,5 pp de ancho que el motor NO puede
   producir: solo el término de rúbrica (β × ERP) abre 3,375 pp. Una vidriera que enseña un
   número que el método no da.

**Por qué entran por HTTP.** Un guard que construye la `Lectura` a mano declara cumplida la
precondición que prueba. Acá el informe se pide como lo pide el cliente y se lee lo que sale.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
from datetime import date
from typing import Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
import shared.products.models  # noqa: F401
from modules.banking_score.models.models import Bank, BankType, DataSource
from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine import por_tipo as pt
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.panel import transacciones as tx
from modules.valuation.products import (
    _SAMPLE_PAYLOAD,
    SECCION_CONTRASTE,
    SECCION_LIMITACIONES,
    SECCION_METODOLOGIA,
    SECCION_SUPUESTOS,
    ValuationProduct,
)
from modules.valuation.tests._siembra import sembrar_trimestres
from shared.database.base import Base
from shared.products.tiers import ProductTier

RAIZ = pathlib.Path(__file__).resolve().parents[3]
NARRATIVA = RAIZ / "modules/valuation/narrativa.py"

CURVA = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
         ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    # Una asociación (mutual, sin acciones) y un banco múltiple: la frase de las AAP tiene
    # que salir para la primera y NO para el segundo.
    for ident, nombre, tipo, patr in (
            ("aap1", "Asociación Grande", BankType.aap, 30_000_000_000.0),
            ("aap2", "Asociación Chica", BankType.aap, 10_000_000_000.0),
            ("bm1", "Banco Múltiple Uno", BankType.banca_multiple, 50_000_000_000.0),
            ("bm2", "Banco Múltiple Dos", BankType.banca_multiple, 20_000_000_000.0)):
        s.add(Bank(id=ident, name=nombre, bank_type=tipo))
        # Cuatro cortes por año con utilidad ACUMULADA, como publica la SIB: con solo
        # diciembre el ROE de doce meses y el acumulado coinciden y el defecto no se ve.
        sembrar_trimestres(s, ident, patrimonio_diciembre=[patr * (1.05 ** j) for j in range(4)],
                           anios=(2022, 2023, 2024, 2025), roe_anual_pct=10.0)
    for p, v in CURVA:
        s.add(MacroSeries(series_code=SERIE_RF, period=p, value=v))
    for i in range(29):
        s.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                          period=f"{2019 + i // 4}-Q{i % 4 + 1}", value=9.03))
    s.commit()
    yield s
    s.close()


def _por_http(db, scope: str, tier: str = "deep_dive") -> Dict[str, str]:
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
    return r.json()["narratives"]


def _veces(texto: str, frase: str) -> int:
    return len(re.findall(re.escape(frase), texto, flags=re.IGNORECASE))


# ── 1 · La base del valor se declara, UNA vez, donde corresponde ─────────────────


def test_la_METODOLOGIA_declara_la_base_del_valor_y_que_no_hay_ajustes(db) -> None:
    narr = _por_http(db, "aap1")
    met = narr[SECCION_METODOLOGIA]
    for frase in ("100 %", "participación de control", "prima de control",
                  "descuento por iliquidez"):
        assert frase in met, f"la metodología no declara: «{frase}»"
    todo = "\n".join(narr.values())
    # UNA vez: la afirmación de método no se repite sección por sección.
    assert _veces(todo, "prima de control") == 1, "la prima de control se declara más de una vez"
    assert _veces(todo, "descuento por iliquidez") == 1


def test_las_LIMITACIONES_dicen_que_una_minoritaria_NO_vale_la_fraccion(db) -> None:
    narr = _por_http(db, "aap1")
    lim = narr[SECCION_LIMITACIONES]
    assert "fracción proporcional" in lim, (
        "las limitaciones no dicen que una participación minoritaria no vale la fracción")
    assert _veces("\n".join(narr.values()), "fracción proporcional") == 1


def test_la_frase_de_las_MUTUALES_sale_para_la_AAP_y_NO_para_el_banco(db) -> None:
    from modules.valuation.narrativa import FRASE_AAP_SIN_ACCIONES
    aap = _por_http(db, "aap1")
    banco = _por_http(db, "bm1")
    assert _veces(aap[SECCION_LIMITACIONES], FRASE_AAP_SIN_ACCIONES[:40]) == 1, (
        "una asociación de ahorros y préstamos no tiene acciones, y el informe no lo dice")
    assert _veces("\n".join(banco.values()), FRASE_AAP_SIN_ACCIONES[:40]) == 0, (
        "la frase de las mutuales salió para un banco múltiple")


def test_el_CONTRASTE_dice_que_el_panel_esta_en_la_MISMA_base_de_control(db) -> None:
    """Computado del panel, no afirmado: cuántos comparables compran el 100 % y cuál es la
    fracción mínima. Si mañana entra un comparable minoritario, la frase cambia sola."""
    comparables = [t for t in tx.PANEL if t.comparable]
    n_todo = sum(1 for t in comparables if t.porcentaje >= 1.0)
    minimo = min(t.porcentaje for t in comparables)
    con = _por_http(db, "aap1")[SECCION_CONTRASTE]
    assert f"{n_todo} de las {len(comparables)}" in con, (
        "el contraste no dice cuántos comparables son compras del 100 %")
    assert f"{minimo * 100:.0f} %" in con, "no nombra la fracción mínima comprada"
    assert "misma base" in con


# ── 2 · Supuestos es una sección PROPIA, con los parámetros de ESTA cifra ────────


def test_SUPUESTOS_no_es_una_copia_de_METODOLOGIA(db) -> None:
    narr = _por_http(db, "aap1")
    assert narr[SECCION_SUPUESTOS] != narr[SECCION_METODOLOGIA], (
        "§Supuestos y §Metodología sirven el MISMO texto: el informe se repite a sí mismo")
    assert len(narr[SECCION_SUPUESTOS]) > 600


def test_SUPUESTOS_trae_los_PARAMETROS_que_produjeron_la_cifra(db) -> None:
    """Cada número de la sección es del snapshot; ninguno se transcribe de una constante
    ajena a esta valuación. La beta es la de las AAP, no la genérica."""
    prod = ValuationProduct(db)
    snap = prod.snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    sp, pr = snap.payload["spread"], snap.payload["procedencia"]
    sup = _por_http(db, "aap1")[SECCION_SUPUESTOS]
    beta = pt.beta_de("aap")
    esperados = {
        "Ke bajo": f"{sp['ke_rango_pct'][0]:.2f} %",
        "Ke alto": f"{sp['ke_rango_pct'][1]:.2f} %",
        "ROE": f"{sp['roe_proyectado_pct']:.2f} %",
        "beta baja": f"{beta[0]:.2f}", "beta alta": f"{beta[1]:.2f}",
        "Rf baja": f"{pr['rf_pct'][0]:.2f} %", "Rf alta": f"{pr['rf_pct'][1]:.2f} %",
        "persistencia": f"{pr['persistencia']:.3f}",
        "retención": f"{pr['retencion_supuesta']:.2f}",
        "g terminal": f"{pr['g_terminal_pct']:.2f} %",
        "rúbrica": f"{pr['fraccion_de_rubrica']:.0%}".replace("%", " %"),
    }
    faltan = [k for k, v in esperados.items() if v not in sup]
    assert faltan == [], f"parámetros que produjeron la cifra y no están en §Supuestos: {faltan}"
    # Y la Rf del payload es la de la curva de la fixture, no un número suelto.
    vivos = [v for _p, v in CURVA][-8:]
    assert pr["rf_pct"] == [min(vivos), max(vivos)]
    assert pr["n_observaciones_rf"] == 8


def test_SUPUESTOS_trae_la_SENSIBILIDAD_computada(db) -> None:
    from modules.valuation.narrativa import _cuanto_falta_para_cambiar_de_signo
    from modules.valuation.products import _lectura_desde_payload
    prod = ValuationProduct(db)
    snap = prod.snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    lec = _lectura_desde_payload(snap)
    sup = _por_http(db, "aap1")[SECCION_SUPUESTOS]
    assert f"{lec.pb_alto:.2f}×" in sup and f"{lec.pb_bajo:.2f}×" in sup
    if not lec.cambia_de_signo:
        assert f"{abs(_cuanto_falta_para_cambiar_de_signo(lec)):.2f} pp" in sup
    else:
        assert "cruza" in sup.lower()


# ── 3 · La muestra es producible por el motor ────────────────────────────────────


def test_la_MUESTRA_tiene_un_Ke_que_el_motor_puede_producir() -> None:
    """`Ke = Rf + β × ERP` en los dos extremos, con la beta del tipo de la muestra."""
    from modules.valuation.engine import cost_of_capital as cc
    sp, pr = _SAMPLE_PAYLOAD["spread"], _SAMPLE_PAYLOAD["procedencia"]
    beta = pt.beta_de(_SAMPLE_PAYLOAD["tipo_de_entidad"])
    assert list(pr["beta"]) == list(beta) and list(pr["erp"]) == list(cc.ERP)
    rf = pr["rf_pct"]
    assert sp["ke_rango_pct"][0] == pytest.approx(rf[0] + beta[0] * cc.ERP[0], abs=0.01)
    assert sp["ke_rango_pct"][1] == pytest.approx(rf[1] + beta[1] * cc.ERP[1], abs=0.01)
    assert sp["spread_pp"][0] == pytest.approx(sp["roe_proyectado_pct"] - sp["ke_rango_pct"][0], abs=0.01)
    assert sp["spread_pp"][1] == pytest.approx(sp["roe_proyectado_pct"] - sp["ke_rango_pct"][1], abs=0.01)


def test_la_MUESTRA_trae_las_mismas_secciones_declaradas() -> None:
    prod = ValuationProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive,
                                       prod.sample_snapshot(ProductTier.deep_dive)))
    assert narr[SECCION_SUPUESTOS] != narr[SECCION_METODOLOGIA]
    assert "prima de control" in narr[SECCION_METODOLOGIA]
    assert "fracción proporcional" in narr[SECCION_LIMITACIONES]
    assert f"{_SAMPLE_PAYLOAD['procedencia']['rf_pct'][0]:.2f} %" in narr[SECCION_SUPUESTOS]


# ── La prosa que otros tests buscan vive en CONSTANTES ───────────────────────────


def test_las_frases_de_la_base_del_valor_son_CONSTANTES_de_modulo() -> None:
    """Un literal partido por ancho de línea deja de existir en el fuente aunque el valor
    sea correcto; la frase que un test busca tiene que ser una constante entera."""
    arbol = ast.parse(NARRATIVA.read_text("utf-8"))
    nombres = {t.id for n in arbol.body if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
    for c in ("BASE_DEL_VALOR", "FRASE_PARTICIPACION_MINORITARIA", "FRASE_AAP_SIN_ACCIONES"):
        assert c in nombres, f"falta la constante {c} en narrativa.py"
