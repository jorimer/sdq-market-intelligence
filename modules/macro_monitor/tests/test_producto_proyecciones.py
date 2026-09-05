"""El eje de proyecciones: por qué es un eje propio, y qué tiene que seguir siendo cierto.

**Por qué existe como eje y no como sección del eje macro.** Decisión del dueño: se vende
aparte. La familia `special:` no servía y eso se MIDIÓ, no se supuso: `is_subscription_sku`
no la incluye —así que solo admite intervalo `once`, incompatible con el cobro anual que se
decidió— y `sku_grants` devuelve `[]`, así que no concede acceso. Un eje del catálogo, en
cambio, gana `insight:<key>` con intervalos mensual/anual y grants reales **sin tocar
`shared/billing`**, que es código de cobro en vivo. Los dos primeros tests congelan eso: si
alguien vuelve a mover la familia de SKU, se entera acá y no en producción.

**Un eje NUEVO no invade a los productos en producción.** A `law` le pasó: se activaba en 6
de 9 preguntas. Las keywords de este eje son deliberadamente estrechas —ninguna describe el
estado actual de nada—, y hay un test que corre las preguntas típicas de los otros ejes y
exige que este no aparezca.

**Una proyección que no pasa el gate es un GAP con su motivo, no una proyección degradada.**
Publicar un pronóstico sin backtest al lado de uno con backtest, ambos como `PROJECTED`,
borra justamente la distinción que el ledger existe para sostener.
"""
import pytest

from shared.billing.skus import (
    INTERVAL_ANNUAL,
    allowed_intervals,
    insight_sku,
    sku_grants,
)
from shared.products import ProductTier
from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented
from shared.data.medida_de_pronostico import DLOG_PCT

#: El `series_code` OBSERVABLE del PIB. Antes decía `"pib_real"`, que es el nombre de la
#: variable en el bloque del BVAR y no existe como serie.
_SERIE = "bcrd.xls.pib_2018.serie_original_indice"

SECTOR = "macro_forecast"


# ── lo que la decisión comercial exige, congelado ───────────────────────────────────


def test_el_sku_del_eje_admite_cobro_anual():
    """La decisión fue publicación trimestral con cobro ANUAL. Un `special:` no podía."""
    assert INTERVAL_ANNUAL in allowed_intervals(insight_sku(SECTOR))


def test_el_sku_del_eje_concede_acceso():
    """Un `special:` concede `[]`: se compra y no se entrega nada."""
    assert sku_grants(insight_sku(SECTOR)) == [(SECTOR, ProductTier.insight.value)]


def test_el_eje_esta_en_el_catalogo_y_tiene_producto():
    import app.main  # noqa: F401 — registra los productos

    assert any(e.sector_key == SECTOR for e in PRODUCT_CATALOG)
    assert is_implemented(SECTOR)


def test_el_precio_no_esta_en_el_codigo():
    """Regla del dueño: el precio vive en el tarifario, no en una constante."""
    import pathlib
    import re

    fuente = pathlib.Path("modules/macro_monitor/products_forecast.py").read_text()
    # Un precio sería un número con separador de miles o decimales junto a USD/precio.
    assert not re.search(r"(precio|price|usd|tarifa)\s*[:=]\s*\d", fuente, re.I), (
        "hay algo que parece un precio hardcodeado en el producto")


# ── el contrato del framework ───────────────────────────────────────────────────────


def test_ofrece_los_tres_niveles():
    """El framework recomputa readiness sobre sectores × 3; un eje con dos niveles rompe
    la cuenta y el eje aparece incompleto sin que nada lo diga."""
    import app.main  # noqa: F401

    niveles = get_product(SECTOR).product_manifest().levels
    assert set(niveles) == {ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive}


def test_el_desempeno_va_en_el_cuerpo_de_los_niveles_pagos():
    """§5: el track record es el argumento de venta, no la letra chica."""
    import app.main  # noqa: F401
    from modules.macro_monitor.products_forecast import SECCION_DESEMPENO

    m = get_product(SECTOR).product_manifest()
    for tier in (ProductTier.insight, ProductTier.deep_dive):
        assert SECCION_DESEMPENO in m.require_level(tier).sections


def test_los_escenarios_solo_viven_en_el_nivel_profundo():
    """Separarlos por nivel espeja separarlos por tipo: un `Escenario` no tiene
    `backtest_id`, así que no puede anclar nada aunque alguien lo intente."""
    import app.main  # noqa: F401
    from modules.macro_monitor.products_forecast import SECCION_ESCENARIOS

    m = get_product(SECTOR).product_manifest()
    assert SECCION_ESCENARIOS in m.require_level(ProductTier.deep_dive).sections
    assert SECCION_ESCENARIOS not in m.require_level(ProductTier.insight).sections


# ── que no invada ───────────────────────────────────────────────────────────────────


PREGUNTAS_DE_OTROS_EJES = [
    "¿Cuál es el score de solidez de Banreservas?",
    "¿Cómo cerró la inflación el mes pasado?",
    "¿Qué decidió el BCRD con la TPM?",
    "¿Cómo está el sector turismo?",
    "¿Cuánto cuesta la energía?",
    "¿Cuántos afiliados tiene el sistema de pensiones?",
]


@pytest.mark.parametrize("pregunta", PREGUNTAS_DE_OTROS_EJES)
def test_no_invade_las_preguntas_del_presente(pregunta):
    import app.main  # noqa: F401
    from shared.research.resolve import detect_axes

    assert SECTOR not in detect_axes(pregunta), (
        f"el eje prospectivo se activó en «{pregunta}», que pregunta por el PRESENTE")


def test_pero_si_atiende_las_prospectivas():
    """El contraejemplo obligatorio: unas keywords vacías pasarían todos los tests de
    arriba y el eje no se activaría jamás."""
    import app.main  # noqa: F401
    from shared.research.resolve import detect_axes

    for pregunta in ("¿Cuál es la proyección del PIB para 2027?",
                     "¿Cuánto va a crecer la economía el año que viene?",
                     "¿Qué track record tienen sus pronósticos?"):
        assert SECTOR in detect_axes(pregunta), f"no atendió «{pregunta}»"


# ── la procedencia del eje ──────────────────────────────────────────────────────────


def test_una_proyeccion_sin_backtest_sale_como_gap_con_su_motivo(monkeypatch):
    """No como `PROJECTED` degradada: publicar las dos con el mismo estado borra la
    distinción que el ledger existe para sostener."""
    import app.main  # noqa: F401
    from modules.macro_monitor import products_forecast as pf
    from shared.registry.signals import GAP, ProjectionMeta

    flaca = ProjectionMeta(
        model_id="m.v1", target_series=_SERIE, horizon="2027-Q1", as_of="2026-09-01",
        revision=0, point=3.0, measure=DLOG_PCT, intervals=((0.80, 2.0, 4.0),),
        backtest_id="b", oos_error=0.5, error_metric="rmse", n_oos=2,
        n_oos_overlapping=False)
    monkeypatch.setattr(pf, "_seguro", lambda db, fn, defecto: {_SERIE: flaca})

    prod = pf.MacroForecastProduct(db=object())
    señales = prod.variable_signals()["signals"]
    assert len(señales) == 1
    assert señales[0].state == GAP
    assert señales[0].projection is None, "una señal en brecha no lleva meta de proyección"
    assert "fuera de muestra" in señales[0].note


def test_la_cobertura_proyectada_de_este_eje_si_dice_algo(monkeypatch):
    """A diferencia del eje macro —donde una proyectada va con peso 0 para no diluir la
    cobertura real—, acá el índice ES la proyección, así que lleva peso."""
    import app.main  # noqa: F401
    from modules.macro_monitor import products_forecast as pf
    from shared.registry.signals import AxisRegistry, ProjectionMeta

    buena = ProjectionMeta(
        model_id="m.v1", target_series=_SERIE, horizon="2027-Q1", as_of="2026-09-01",
        revision=0, point=3.0, measure=DLOG_PCT, intervals=((0.80, 2.0, 4.0),),
        backtest_id="b", oos_error=0.5, error_metric="rmse", n_oos=14,
        n_oos_overlapping=False, interval_coverage=((0.80, 0.79, 14),))
    monkeypatch.setattr(pf, "_seguro", lambda db, fn, defecto: {_SERIE: buena})

    señales = pf.MacroForecastProduct(db=object()).variable_signals()["signals"]
    eje = AxisRegistry(sector_key=SECTOR, display_name="x", source="y", implemented=True,
                       signals=tuple(señales))
    assert eje.coverage_projected == pytest.approx(1.0)
    assert eje.coverage_real == 0.0, "una proyección no es dato real, ni en este eje"


# ── la vidriera ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tier", [ProductTier.pulse, ProductTier.insight,
                                  ProductTier.deep_dive])
def test_la_muestra_curada_se_renderiza(tier, tmp_path):
    """Un producto listado que no se puede mostrar es una vidriera rota."""
    import asyncio
    import os

    import app.main  # noqa: F401
    from shared.products.assembler import assemble_sample_report

    r = asyncio.run(assemble_sample_report(get_product(SECTOR), tier,
                                           output_dir=str(tmp_path)))
    path = r if isinstance(r, str) else getattr(r, "path", None) or r.get("path")
    assert os.path.getsize(path) > 5_000


def test_la_muestra_ensena_un_resultado_incomodo():
    """Una muestra que solo enseña aciertos vende un producto que no existe."""
    from modules.macro_monitor.products_forecast import _SAMPLE_PAYLOAD

    assert any(not d["ancla"] for d in _SAMPLE_PAYLOAD["proyecciones"]), (
        "la muestra no enseña ninguna proyección que NO alcance a anclar")
    coberturas = [c for f in _SAMPLE_PAYLOAD["desempeno"]
                  for _n, c, _k in f["interval_coverage"]]
    assert any(c >= 1.0 for c in coberturas), (
        "la muestra no enseña ningún intervalo mal calibrado (sobre-cobertura)")
