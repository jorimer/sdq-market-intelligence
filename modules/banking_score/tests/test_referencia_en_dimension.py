"""REGLA: una sección de DIMENSIÓN de un producto nombrado llega al modelo con una
referencia RESUELTA, no con los indicadores de la entidad a secas.

El defecto real (prod, Deep Dive de banca múltiple, Q1-2026): la ruta de PRODUCTOS servía las
secciones `subcomponent_focus` —donde el informe analiza eficiencia, liquidez, calidad…— con
los cuatro indicadores de la entidad y NADA contra qué compararlos. `_build_section_context`
busca `sector_averages`/`peer_groups` en los benchmarks, y el `peer_block` del snapshot solo
traía concentración de mercado (CR5/CR10/HHI) y pares nombrados.

El hueco no dejaba la sección vacía: la dejaba INVENTADA. El modelo afirmó una eficiencia del
"69%" que ningún dato sostenía, el guard determinista la marcó, la cifra sobrevivió a la
regeneración y el informe se vetó entero — 157 s y ~US$1 de modelo para un error genérico en
pantalla. Es la doctrina literal: si no tenés la cifra que el modelo va a necesitar, pasásela
igual con su nombre real; dejar el hueco es lo que lo llena mal.

Lo que hace este test difícil de re-romper: NO arma el `peer_block` a mano. Corre
`BankingProduct.snapshot()` de punta a punta contra una DB y le pregunta al contexto REAL si
trae referencia. Un `peer_block` armado en el test habría pasado en verde con el bug puesto.

La ruta del PDF (`router_reports`) ya servía esto vía `panel_benchmarks`; la de productos era
la ciega. Mismo patrón que "un guard existe en un motor y falta en el otro", pero invertido:
lo que faltaba de un lado era el INSUMO.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra 'users' (FK de RatingResult)
from shared.database.base import Base
from shared.settings.models import AppSetting  # el snapshot lee el contrato macro
from shared.narrative.numeric_guard import guard_coverage
from shared.products import ProductTier
from modules.banking_score.models.models import (
    Bank, BankingData, BankType, ModelType, RatingResult)
from modules.banking_score.products import BankingProduct
from modules.banking_score.reports.narrative import (
    _SUB_COMPONENT_MAP, _SUB_INDICATORS, _build_section_context)

_PERIODO = date(2026, 3, 31)
_SUJETO = "Banco Múltiple Sujeto"

#: Indicadores del sujeto: los REALES de la entidad cuyo Deep Dive se vetó en prod.
_IND_SUJETO = {
    "solvencia": 12.62, "tier1_ratio": 10.2196, "leverage": 9.5616,
    "cobertura_provisiones": 103.05, "patrimonio_activos": 7.4058,
    "morosidad": 4.2, "pct_cartera_a": 95.66, "concentracion_top10": 38.0276,
    "hhi_sectorial": 2091.6781, "castigos_pct": 3.0173, "exposicion_re": 11.2935,
    "migracion": 4.816,
    "roa": 0.3926, "roe": 5.3013, "margen_financiero": 7.33, "cost_to_income": 49.3813,
    "liquidez_inmediata": 29.4334, "ltd": 84.3129, "liquidez_ajustada": 46.2769,
    "hhi_ingresos": 4520.9253,
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, Bank.__table__, RatingResult.__table__,
                        BankingData.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _detalles(vals: dict) -> dict:
    return {k: {"raw": v, "score": 50.0, "available": True} for k, v in vals.items()}


@pytest.fixture()
def panel(db):
    """Panel con el sujeto + pares suficientes para que el benchmark se MIDA.

    `panel_benchmarks` exige MIN_N=5 observaciones por indicador: por debajo omite el
    promedio, y con un panel corto el test no probaría lo que dice probar."""
    for i in range(7):
        nombre = _SUJETO if i == 0 else f"Banco Múltiple Par {i}"
        # Los pares se desvían del sujeto para que la mediana no coincida con su valor:
        # una comparación "0.00 pp de brecha" pasaría el test sin demostrar dirección.
        factor = 1.0 if i == 0 else (0.8 + 0.1 * i)
        b = Bank(name=nombre, bank_type=BankType.banca_multiple)
        db.add(b)
        db.flush()
        db.add(RatingResult(
            bank_id=b.id, period_end=_PERIODO, overall_score=60.0 - i,
            rating_tier="SDQ-A", model_type=ModelType.deterministic, model_version="1.0",
            solidez_score=55.0, calidad_score=52.65, eficiencia_score=34.48,
            liquidez_score=85.0, diversificacion_score=74.65,
            indicator_details=_detalles({k: v * factor for k, v in _IND_SUJETO.items()})))
    db.commit()
    return db


def _contexto(panel, seccion, tier=ProductTier.deep_dive):
    snap = BankingProduct(panel).snapshot(tier, str(_PERIODO), scope=_SUJETO)
    return _build_section_context(
        seccion, _SUJETO, snap.payload["scoring_result"], snap.period,
        benchmarks=snap.payload["peer_block"])


# ── Prueba NEGATIVA: el barrido tiene sobre qué correr ─────────────────
#
# Sin esto, un rename de `_SUB_COMPONENT_MAP` dejaría el parametrize vacío y la suite
# reportaría SKIPPED —no FAILED—, o sea verde sin haber mirado ninguna dimensión.

def test_hay_secciones_de_dimension_que_revisar():
    assert len(_SUB_COMPONENT_MAP) >= 5, (
        f"Se esperaban las 5 dimensiones del score; hay {sorted(_SUB_COMPONENT_MAP)}")


def test_el_panel_produce_benchmarks_medidos(panel):
    """Si el benchmark saliera DECLARADO (constantes), el test mediría el fallback y no la
    corrección — y las constantes son ANUALES contra un corte trimestral."""
    snap = BankingProduct(panel).snapshot(ProductTier.deep_dive, str(_PERIODO), scope=_SUJETO)
    proc = snap.payload["peer_block"]["procedencia"]
    assert proc["medido"] is True, f"benchmark no medido: {proc.get('nota')}"
    assert proc["period"] == str(_PERIODO), "el benchmark no se midió en el corte del informe"


# ── La regla ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("seccion", sorted(_SUB_COMPONENT_MAP))
def test_la_dimension_recibe_referencia_resuelta(panel, seccion):
    ctx = _contexto(panel, seccion)
    comps = ctx.get("comparaciones") or []
    assert comps, (
        f"'{seccion}' llega al modelo sin NINGUNA referencia: solo los indicadores de la "
        "entidad. Ese es el hueco que el modelo rellena con una cifra inventada.")
    # La dirección viene COMPUTADA, no derivable por el modelo (regla de doctrina).
    for c in comps:
        assert c["direccion"] in ("por encima", "por debajo", "en línea"), c
        assert c["valor_referencia"] is not None, c
    assert guard_coverage(ctx)["comparaciones"] is True


def test_la_comparacion_se_acota_al_grupo_de_pares_propio(panel):
    """`entity_type` tiene que viajar en el `scoring_result`: sin él la comparación cae al
    compat "todos los grupos" y mide una banca múltiple contra agentes de cambio."""
    snap = BankingProduct(panel).snapshot(ProductTier.deep_dive, str(_PERIODO), scope=_SUJETO)
    assert snap.payload["scoring_result"]["entity_type"] == BankType.banca_multiple.value


def test_la_referencia_tambien_llega_al_insight(panel):
    """El Insight es un producto PAGO y usa las mismas secciones de dimensión. Arreglar solo
    el Deep Dive dejaría el mismo hueco un nivel más abajo."""
    ctx = _contexto(panel, "eficiencia_rentabilidad", tier=ProductTier.insight)
    assert ctx.get("comparaciones"), "el Insight sigue sin referencia en la dimensión"


# ── Cobertura por indicador, no solo por dimensión ─────────────────────
#
# Que una dimensión tenga UNA referencia le quita la ceguera total, pero cada indicador sin
# referencia sigue siendo una cifra suelta que el modelo puede leer contra algo que se
# imagina. Calidad de Activos tenía 1 de 8. La regla es: o tiene referencia, o la excepción
# está DECLARADA acá con su motivo.

#: Indicadores que a propósito NO se comparan contra una referencia de panel.
_SIN_REFERENCIA_A_PROPOSITO = {
    # No es una métrica observable: es un compuesto que ya vive en la escala 0-100 del score.
    # Compararlo contra "el promedio del sistema" lo haría sonar como un indicador de balance,
    # y su posición relativa ya la dan el percentil y la trayectoria del sub-componente.
    "composite_calidad",
}


def test_todo_indicador_puntuado_tiene_referencia_o_excepcion_declarada():
    from shared.data.sib_client import INDICATOR_TO_BENCHMARK

    huerfanos = {}
    for sub, keys in _SUB_INDICATORS.items():
        faltan = [k for k in keys
                  if k not in INDICATOR_TO_BENCHMARK and k not in _SIN_REFERENCIA_A_PROPOSITO]
        if faltan:
            huerfanos[sub] = faltan
    assert not huerfanos, (
        "Estos indicadores llegan al modelo sin nada contra qué compararse. Mapealos en "
        f"INDICATOR_TO_BENCHMARK o declará acá por qué no corresponde: {huerfanos}")


def test_la_excepcion_declarada_no_crece_sin_que_nadie_mire():
    """Una lista de excepciones que se llena sola vuelve inútil al test de arriba."""
    assert _SIN_REFERENCIA_A_PROPOSITO == {"composite_calidad"}


def test_toda_referencia_se_enuncia_en_una_unidad_CONOCIDA():
    """Un indicador nuevo con unidad rara ("veces", "días") caería al fallback de porcentaje y
    su brecha saldría narrada en "puntos porcentuales" — cifra correcta, unidad imposible. En
    runtime el fallback se conserva (el informe no se cae por esto); acá se veta."""
    from shared.data.sib_client import INDICATOR_TO_BENCHMARK
    from shared.narrative.derived import UNIDAD_DE_BRECHA
    from modules.banking_score.scoring.indicator_detail import INDICATOR_META

    raras = {k: (INDICATOR_META.get(k) or {}).get("unit")
             for k in INDICATOR_TO_BENCHMARK
             if k in INDICATOR_META
             and (INDICATOR_META.get(k) or {}).get("unit") not in UNIDAD_DE_BRECHA}
    assert not raras, (
        f"Unidades sin frase de brecha declarada en UNIDAD_DE_BRECHA: {raras}")


def test_el_hhi_no_se_narra_en_puntos_porcentuales(panel):
    """El HHI es un índice de 0 a 10.000. Su brecha no es una diferencia de porcentajes."""
    ctx = _contexto(panel, "diversificacion")
    hhi = [c for c in ctx["comparaciones"] if c["indicador"] == "hhi_ingresos"]
    assert hhi, "el HHI de ingresos perdió su referencia"
    for c in hhi:
        assert c["unidad_brecha"] == "puntos del índice", c
        assert "puntos porcentuales" not in c["lectura"], c["lectura"]


def test_calidad_de_activos_deja_de_tener_un_solo_indicador_con_referencia(panel):
    """El caso que motivó esta tanda: 1 de 8. La sección analiza morosidad, castigos,
    concentración y migración — con una sola referencia, las otras siete se leen contra lo
    que el modelo se imagine."""
    ctx = _contexto(panel, "calidad_activos")
    con_ref = {c["indicador"] for c in ctx["comparaciones"]}
    assert len(con_ref) >= 6, f"solo {sorted(con_ref)} tienen referencia"


def test_el_caso_de_prod_cost_to_income_queda_respaldado(panel):
    """El caso literal: la sección donde el modelo escribió el '69%' inventado ahora recibe
    el cost-to-income de la entidad CONTRA su referencia."""
    ctx = _contexto(panel, "eficiencia_rentabilidad")
    inds = {c["indicador"] for c in ctx["comparaciones"]}
    assert "cost_to_income" in inds, f"solo hay referencia para {sorted(inds)}"
