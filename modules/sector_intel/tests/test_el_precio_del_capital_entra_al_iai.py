"""El COSTO DEL CAPITAL entra al IAI — decisión del dueño del 2026-09-01.

**Qué se decidió y sobre qué medición.** El índice ya medía el precio del trabajo
(`operating_cost`, salario cotizable de la TSS) y no medía el del capital, que para varios
sectores es el insumo que decide una inversión. Entra `credit_cost`: la tasa promedio
ponderada a la que el sistema financiero le presta al sector, del cubo `carteras/creditos`
de la SIB.

**Por qué la tasa y no la mora.** Se midieron las dos sobre el cubo de producción y
correlacionan a **r = +0,65**: el precio del crédito ES, en buena parte, la lectura que el
mercado hace del riesgo del sector, y meter las dos sería el mismo hecho votando dos veces —
que es el defecto que en este repo hizo que tres indicadores de lo mismo pesaran el 60 % de
un score. La cobertura de provisiones se descartó por medición y no por gusto: energía marca
4.031 % contra un rango de 124-483 % del resto, y bajo el min-max CRUDO de este motor
(`normalize_variable`, que no usa `robust_bounds`) ese único valor comprimiría a los otros
once contra el piso.

**Lo que estos tests protegen** es la propiedad que hace honesta a la cobertura parcial: que
dentro de un período la variable esté para todos los slugs que la fuente alcanza, o para
ninguno. Una cobertura parcial POR PERÍODO movería el ranking por PRESENCIA y no por dato.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.doctrine import load_doctrine, load_doctrine_raw
from shared.reference.cartera_sectorial import CarteraSectorial
from shared.reference.sector_variables import SectorVariable  # noqa: F401 — register table
from modules.sector_intel.service import _load_credit_cost, assemble_iai_dataset

CORTE = date(2024, 12, 31)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _celda(db, banco, etiqueta, deuda, tasa, corte=CORTE):
    """Una celda del cubo. La tasa viaja con SU BASE (`deuda_con_tasa`): el promedio
    ponderado se reconstruye a cualquier nivel de agregación, nunca se promedia."""
    db.add(CarteraSectorial(bank_id=banco, period_end=corte, sector=etiqueta,
                            provincia="SIN PROVINCIA", deuda=deuda,
                            tasa_ponderada=tasa, deuda_con_tasa=deuda))


def _sector_var(db, slug, var, value, period="2024"):
    db.add(SectorVariable(sector_code=slug, dimension="sector", variable=var,
                          value=value, period=period, source="BCRD"))


# ── La declaración en la doctrina ─────────────────────────────────────────────
def test_la_variable_esta_declarada_en_NEGOCIOS_y_es_de_riesgo_creciente():
    """Más caro el crédito, menos atractivo. Si quedara fuera de `risk_increasing`, el motor
    premiaría al sector que paga la tasa más alta y nadie lo notaría en el score."""
    cfg = load_doctrine("sectoral")
    assert "credit_cost" in cfg.dimension_variables["business"]
    assert "credit_cost" in cfg.risk_increasing


def test_NO_tiene_rubrica_default_y_esa_es_la_excepcion_honesta():
    """El slug sin cobertura la deja AUSENTE y el motor la omite. Un default de 50 le
    inventaría al único sector sin dato una tasa promedio que no paga."""
    assert "credit_cost" not in (load_doctrine_raw("sectoral").get("rubric_defaults") or {})


def test_es_la_UNICA_variable_del_indice_que_sale_del_cubo_de_la_SIB():
    """Un hecho, un voto. Mora y tasa correlacionan a r=+0,65 sobre el cubo real: sumar la
    mora sería el mismo hecho votando dos veces, que es el defecto que ya hizo que tres
    indicadores de lo mismo pesaran el 60 % de un score en este repo. Si alguien agrega otra
    variable del cubo, esto lo frena hasta que se decida explícitamente."""
    cfg = load_doctrine("sectoral")
    del_cubo = {v for vs in cfg.dimension_variables.values() for v in vs
                if v in {"credit_cost", "credit_npl", "credit_coverage", "credit_depth",
                         "credit_collateral", "credit_dollarization"}}
    assert del_cubo == {"credit_cost"}, f"hay más de una variable del cubo en el índice: {del_cubo}"


# ── La tasa se RE-DERIVA, no se promedia ──────────────────────────────────────
def test_la_tasa_se_pondera_por_DEUDA_y_no_se_promedia(db):
    """Dos entidades en la misma letra con carteras de tamaños muy distintos. El promedio
    simple daría 15,0 y no es la tasa de nadie; la ponderada da 10,5, que es lo que el
    sector paga en conjunto."""
    _celda(db, "b1", "F - CONSTRUCCIÓN", deuda=900.0, tasa=10.0)
    _celda(db, "b2", "F - CONSTRUCCIÓN", deuda=100.0, tasa=15.0)
    db.commit()
    assert _load_credit_cost(db, "2024")["construccion"] == pytest.approx(10.5)


# ── La propiedad que hace honesta a la cobertura parcial ──────────────────────
def test_el_slug_que_la_SIB_no_cubre_queda_AUSENTE_no_en_cincuenta(db):
    """`comunicaciones` es el único de los 17 sin ninguna letra CIIU. Ausente, el motor
    omite la variable; con un 50 inventado entraría al min-max y movería a todos."""
    _celda(db, "b1", "F - CONSTRUCCIÓN", deuda=1000.0, tasa=11.8)
    _sector_var(db, "construccion", "sector_size", 13.4)
    db.commit()
    asm = assemble_iai_dataset(db, "2024")
    assert asm["dataset"]["construccion"]["credit_cost"] == pytest.approx(11.8)
    assert asm["sources"]["construccion"]["credit_cost"] == "live"
    assert "credit_cost" not in asm["dataset"]["comunicaciones"]
    assert "credit_cost" not in asm["sources"]["comunicaciones"]


def test_un_periodo_SIN_cubo_deja_a_TODOS_sin_la_variable(db):
    """La propiedad central. El cubo arranca en 2021 y el IAI se puntúa desde 2007: si un
    período histórico diera la variable a ALGUNOS, el motor —que normaliza contra los pares
    DE ESE PERÍODO— movería el ranking por presencia y no por dato. O todos, o ninguno."""
    _celda(db, "b1", "F - CONSTRUCCIÓN", deuda=1000.0, tasa=11.8, corte=date(2024, 12, 31))
    _sector_var(db, "construccion", "sector_size", 13.4, period="2015")
    db.commit()
    assert _load_credit_cost(db, "2015") == {}
    asm = assemble_iai_dataset(db, "2015")
    con = [s for s, v in asm["dataset"].items() if "credit_cost" in v]
    assert con == [], f"un período sin cubo repartió la variable a {con}"


def test_el_corte_es_el_DEL_ANIO_que_se_puntua_y_no_una_foto_reciente(db):
    """No es purismo: se midió sobre los 21 cortes del cubo (2021-Q1 → 2026-Q1) y el orden
    transversal de las tasas se mueve —rho de Spearman de +0,69 entre el primero y el
    último—, así que una foto de 2026 aplicada a 2021 no describiría ese año: lo reescribiría.
    """
    _celda(db, "b1", "F - CONSTRUCCIÓN", deuda=1000.0, tasa=7.9, corte=date(2021, 12, 31))
    _celda(db, "b1", "F - CONSTRUCCIÓN", deuda=1000.0, tasa=11.8, corte=date(2024, 12, 31))
    db.commit()
    assert _load_credit_cost(db, "2021")["construccion"] == pytest.approx(7.9)
    assert _load_credit_cost(db, "2024")["construccion"] == pytest.approx(11.8)


def test_una_tasa_mas_ALTA_baja_el_score_de_negocios(db):
    """La dirección, medida de punta a punta contra el motor real y no contra la doctrina:
    declarar `risk_increasing` y que el motor no lo aplicara daría el mismo YAML y el score
    invertido."""
    _celda(db, "b1", "F - CONSTRUCCIÓN", deuda=1000.0, tasa=18.0)   # crédito CARO
    _celda(db, "b1", "H - ALOJAMIENTO Y SERVICIOS DE COMIDA", deuda=1000.0, tasa=6.0)   # BARATO
    for slug in ("construccion", "turismo"):
        _sector_var(db, slug, "sector_size", 10.0)
    db.commit()
    from modules.sector_intel.scoring.iai import compute_iai
    asm = assemble_iai_dataset(db, "2024")
    caro = compute_iai("construccion", asm["dataset"])["dimensions"]["business"]
    barato = compute_iai("turismo", asm["dataset"])["dimensions"]["business"]
    assert caro["variables"]["credit_cost"]["inverted"] is True
    assert caro["variables"]["credit_cost"]["normalized"] == 0.0
    assert barato["variables"]["credit_cost"]["normalized"] == 100.0
    assert barato["score"] > caro["score"]
