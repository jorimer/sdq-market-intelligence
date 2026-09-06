"""El Deep Dive trae el ANEXO DE PLANILLAS: lo que un tercero necesita para reproducir la cifra.

**La brecha.** De las diez secciones pedidas para un informe de valuación, la décima —los
anexos— estaba a medias: el deep dive trae el anexo del panel de transacciones, pero no las
planillas del modelo. El informe afirma que «cada cifra se puede reproducir con la información
pública que la sección de fuentes nombra», y es cierto — pero el lector tiene que ir a buscar
el dato. El anexo se lo da: la historia de patrimonio y utilidad con la que se computó cada
ROE de doce meses, las observaciones de la curva que armaron la Rf, el flujo del Excess Return
año a año en los dos extremos de Ke, y el estado de la regresión P/B sobre bancos cotizados.

**Todo viaja en el payload** (la prosa no recomputa) y **las identidades cierran**: libro +
Σ VP del residual income + terminal descontado (+ ajuste de clean surplus) = valor, en cada
extremo, con las mismas cifras que publica la conclusión de valor. Un anexo que no cierra
contra la cifra que dice reproducir es peor que ninguno.
"""
from __future__ import annotations

import pytest

from modules.valuation.tests.test_el_entorno_llega_al_informe import _db, _por_http
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    s = _db()
    yield s
    s.close()


def _snapshot(db):
    from modules.valuation.products import ValuationProduct
    return ValuationProduct(db).snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")


def test_el_anexo_va_en_el_DEEP_DIVE_y_no_en_el_insight(db) -> None:
    from modules.valuation.products import SECCION_ANEXO_PANEL, SECCION_ANEXO_PLANILLAS
    dd = _por_http(db, "deep_dive")
    assert SECCION_ANEXO_PLANILLAS in dd["narratives"], "el deep dive no trae las planillas"
    orden = [s for s in dd["commercial"]["sections"] if not s.startswith("std_")]
    assert orden.index(SECCION_ANEXO_PANEL) < orden.index(SECCION_ANEXO_PLANILLAS) == len(orden) - 1
    assert SECCION_ANEXO_PLANILLAS not in _por_http(db, "insight")["narratives"]


def test_las_planillas_VIAJAN_en_el_payload_con_sus_cuatro_bloques(db) -> None:
    pl = _snapshot(db).payload["planillas"]
    for k in ("historia", "curva_rf", "flujos", "regresion_pb"):
        assert k in pl, f"falta el bloque {k}"
    assert len(pl["flujos"]) == 2, "un flujo por extremo de Ke"


def test_el_flujo_del_Excess_Return_CIERRA_contra_el_valor_publicado(db) -> None:
    p = _snapshot(db).payload
    pl, va, sp = p["planillas"], p["valor"], p["spread"]
    kes = sorted(f["ke_pct"] for f in pl["flujos"])
    assert kes == sorted(sp["ke_rango_pct"]), "los flujos no son los de los extremos de Ke"
    valores = []
    for f in pl["flujos"]:
        suma_vp = sum(r["vp_residual_income"] for r in f["periodos"])
        reconstruido = f["bv_inicial"] + suma_vp + f["terminal_descontado"] + f["ajuste_clean_surplus_total"]
        assert reconstruido == pytest.approx(f["valor"], rel=1e-6), (
            f"Ke {f['ke_pct']}: libro + ΣVP + terminal ≠ valor")
        valores.append(f["valor"])
    assert sorted(valores) == pytest.approx(sorted(va["rango"]), rel=1e-9), (
        "los valores de las planillas no son los de la conclusión de valor")
    # El ROE del flujo es el que recibió el motor; el de la lectura viaja redondeado a 4 dp.
    assert all(r["roe_pct"] == pytest.approx(sp["roe_proyectado_pct"], abs=1e-3)
               for f in pl["flujos"] for r in f["periodos"])


def test_la_historia_y_la_curva_son_las_que_produjeron_la_cifra(db) -> None:
    p = _snapshot(db).payload
    pl, pr = p["planillas"], p["procedencia"]
    con_roe = [h for h in pl["historia"] if h["roe_12m_pct"] is not None]
    assert [(h["corte"], h["roe_12m_pct"]) for h in con_roe] == [
        (s["periodo"], s["roe_pct"]) for s in p["serie_spread"]]
    # Cortes sin ventana de doce meses: fila presente, ROE None — no cero.
    assert any(h["roe_12m_pct"] is None for h in pl["historia"])
    assert all(h["patrimonio"] > 0 for h in pl["historia"])
    tasas = [o["tasa_pct"] for o in pl["curva_rf"]]
    assert len(tasas) == pr["n_observaciones_rf"]
    assert [min(tasas), max(tasas)] == pr["rf_pct"]
    assert [pl["curva_rf"][0]["periodo"], pl["curva_rf"][-1]["periodo"]] == pr["rf_ventana"]


def test_la_regresion_PB_declara_su_estado_computado(db) -> None:
    from modules.valuation.panel import latam_comparables as lc
    pl = _snapshot(db).payload["planillas"]["regresion_pb"]
    est = lc.estado()
    assert pl["n"] == est.n and pl["minimo"] == est.minimo and pl["suficiente"] == est.suficiente


def test_el_anexo_PUBLICA_las_tablas_con_las_cifras_del_payload(db) -> None:
    from modules.valuation.products import SECCION_ANEXO_PLANILLAS
    p = _snapshot(db).payload
    pl = p["planillas"]
    md = _por_http(db, "deep_dive")["narratives"][SECCION_ANEXO_PLANILLAS]
    for f in pl["flujos"]:
        assert f"{f['ke_pct']:.2f} %" in md
        assert f"RD$ {f['terminal_descontado']:,.0f}" in md
        assert f"RD$ {f['valor']:,.0f}" in md
    for o in pl["curva_rf"]:
        assert f"| {o['periodo']} | {o['tasa_pct']:.2f} % |" in md
    ultimo = [h for h in pl["historia"] if h["roe_12m_pct"] is not None][-1]
    assert f"{ultimo['roe_12m_pct']:.2f} %" in md
    if not pl["regresion_pb"]["suficiente"]:
        assert f"{pl['regresion_pb']['n']} " in md and f"{pl['regresion_pb']['minimo']}" in md
    assert "no se publica" in md.lower() or "coeficiente" in md.lower()


def test_la_MUESTRA_trae_el_anexo_y_cierra() -> None:
    import asyncio
    from modules.valuation.products import _SAMPLE_PAYLOAD, SECCION_ANEXO_PLANILLAS, ValuationProduct
    pl = _SAMPLE_PAYLOAD["planillas"]
    for f in pl["flujos"]:
        rec = f["bv_inicial"] + sum(r["vp_residual_income"] for r in f["periodos"]) \
            + f["terminal_descontado"] + f["ajuste_clean_surplus_total"]
        assert rec == pytest.approx(f["valor"], rel=1e-6)
    assert sorted(f["valor"] for f in pl["flujos"]) == pytest.approx(
        sorted(_SAMPLE_PAYLOAD["valor"]["rango"]), rel=1e-6)
    prod = ValuationProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, prod.sample_snapshot(ProductTier.deep_dive)))
    assert SECCION_ANEXO_PLANILLAS in narr and len(narr[SECCION_ANEXO_PLANILLAS]) > 800
