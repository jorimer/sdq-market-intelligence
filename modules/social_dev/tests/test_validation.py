"""Gate E — IDM convergent validity (regional ranking vs PNUD IDHr). Offline."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.validation.metrics import spearman, spearman_bootstrap_ci
from modules.social_dev.models.models import DevelopmentScore  # noqa: F401 — register table
from modules.social_dev.validation.report import build_convergent_validity


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def test_spearman_perfect_and_inverse():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 2], [2, 1]) is None  # n<3


def test_spearman_bootstrap_ci_seeded_reproducible():
    xs = [1, 2, 3, 4, 5, 6]
    ys = [1, 2, 3, 4, 5, 6]
    rho, lo, hi = spearman_bootstrap_ci(xs, ys, n_boot=200)
    assert rho == pytest.approx(1.0) and lo is not None and lo <= hi


# Real prod IDM regional scores (latest period) — convergent validity must hold.
_PROD_IDM = {
    "cibao_sur": 57.77, "cibao_nordeste": 57.67, "cibao_norte": 57.56, "valdesia": 57.42,
    "yuma": 57.13, "ozama": 55.00, "higuamo": 52.89, "cibao_noroeste": 49.28,
    "el_valle": 41.88, "enriquillo": 41.21,
}


def test_convergent_validity_matches_pnud_idhr(db):
    for slug, score in _PROD_IDM.items():
        db.add(DevelopmentScore(entity_key=slug, period="2024", development_score=score))
    db.commit()

    rep = build_convergent_validity(db)
    assert rep["has_data"] and rep["n_regions"] == 10
    assert rep["spearman"] == 0.733                       # the real, strong convergent ρ
    assert rep["spearman_ci"][0] is not None and rep["spearman_ci"][1] is not None
    assert len(rep["pairs"]) == 10
    # Ozama is the explainable divergence (IDHr #1 by income; IDM ranks it mid).
    assert rep["top_divergence"]["region"] == "ozama"
    assert rep["source"].startswith("PNUD")


def test_convergent_validity_needs_min_regions(db):
    db.add(DevelopmentScore(entity_key="ozama", period="2024", development_score=55.0))
    db.commit()
    rep = build_convergent_validity(db)
    assert rep["has_data"] is False


# ── El CONTROL POR TAMAÑO ──────────────────────────────────────────────────────
#
# `social_dev` era el último motor del catálogo sin control, y no por diseño: la población
# por región no estaba conectada. Estos tests cubren la propiedad que hace que el control
# sirva —que compare el MISMO panel en el MISMO momento— y las dos formas de fallar en
# silencio: desaparecer cuando falta el insumo, y computarse sobre un universo parcial.

def _sembrar_poblacion(db, por_region, periodo="2024"):
    from modules.social_dev.models.models import SocialIndicator
    from shared.data.sisdom_poblacion import THEME, UNIT

    for slug, hab in por_region.items():
        db.add(SocialIndicator(theme=THEME, entity_key=slug, period=periodo,
                               value=float(hab), source="MEPyD", disaggregation="region",
                               unit=UNIT))
    db.commit()


def _sembrar_idm(db, scores, periodo="2024"):
    from modules.social_dev.models.models import DevelopmentScore

    for slug, score in scores.items():
        db.add(DevelopmentScore(entity_key=slug, period=periodo, development_score=score,
                                band="Medio"))
    db.commit()


#: Población real de las 10 regiones (SISDOM 02 3 009b, año 2024). Se usa la de verdad y no
#: una inventada: el veredicto del control depende de cuánto se PARECEN dos ordenamientos, y
#: unos números redondos fabricarían un acuerdo o un desacuerdo que no existe.
_POBLACION_2024 = {
    "cibao_norte": 1658496, "cibao_sur": 746040, "cibao_nordeste": 650506,
    "cibao_noroeste": 426490, "valdesia": 922102, "enriquillo": 388555,
    "el_valle": 501028, "yuma": 770675, "higuamo": 588659, "ozama": 4225716,
}


def test_el_control_viaja_dentro_del_reporte(db):
    """Pegado a la cifra que acota. Un número que hay que ir a buscar a otra clave no se lee
    junto al que corrige, y entonces no corrige nada."""
    _sembrar_idm(db, _PROD_IDM)
    _sembrar_poblacion(db, _POBLACION_2024)
    rep = build_convergent_validity(db)
    ctrl = rep["control_solo_tamano"]
    assert ctrl["variable"] == "poblacion_de_la_region"
    assert ctrl["n"] == 10 and ctrl["control_medido"] is True
    assert ctrl["spearman"] is not None and ctrl["veredicto"]


def test_sin_poblacion_el_control_NO_desaparece(db):
    """La falla silenciosa que este contrato existe para impedir: sin insumo, la clave se
    devuelve igual y dice «no evaluable». Si desapareciera, la cifra del score quedaría
    publicada sin la vara que la acota y el silencio se leería como que el control se hizo."""
    _sembrar_idm(db, _PROD_IDM)
    ctrl = build_convergent_validity(db)["control_solo_tamano"]
    assert ctrl["control_medido"] is False
    assert ctrl["empata_con_el_score"] is False
    assert "no evaluable" in ctrl["veredicto"]
    assert ctrl["spearman"] is None


def test_un_panel_parcial_no_se_compara(db):
    """Nueve regiones contra un score de diez son universos distintos. Se niega, no promedia."""
    _sembrar_idm(db, _PROD_IDM)
    _sembrar_poblacion(db, {k: v for k, v in list(_POBLACION_2024.items())[:9]})
    ctrl = build_convergent_validity(db)["control_solo_tamano"]
    assert ctrl["comparable"] is False and ctrl["control_medido"] is False


def test_usa_la_poblacion_DEL_PERIODO_del_score_y_no_la_ultima(db):
    """La propiedad decisiva. Comparar un score de 2024 contra la población de 2025 mediría
    dos momentos distintos; y rellenar hacia adelante mete información que en ese período no
    existía. Se arrastra la última ANTERIOR, nunca la posterior."""
    _sembrar_idm(db, _PROD_IDM, periodo="2024")
    _sembrar_poblacion(db, _POBLACION_2024, periodo="2020")
    # Una población POSTERIOR, deliberadamente invertida: si el control la usara, el
    # ordenamiento por tamaño sería el opuesto y el ρ cambiaría de signo.
    invertida = {k: 5_000_000 - v for k, v in _POBLACION_2024.items()}
    _sembrar_poblacion(db, invertida, periodo="2025")
    ctrl = build_convergent_validity(db)["control_solo_tamano"]
    assert ctrl["periodo_de_la_poblacion"] == "2024"
    assert ctrl["n"] == 10

    solo_vieja = build_convergent_validity(db)["control_solo_tamano"]["spearman"]
    # Y el valor coincide con computar el control SOLO con la de 2020 (la vigente al 2024).
    from modules.social_dev.validation.report import control_solo_tamano
    esperado = control_solo_tamano(db, sorted(_PROD_IDM), rho=0.9, ic=[0.5, 1.0],
                                   periodo="2024")["spearman"]
    assert solo_vieja == esperado


def test_la_regla_del_empate_no_se_reimplementa_aca(db):
    """Vive en `shared.validation.control_tamano`. Duplicarla es cómo dos motores llaman
    «empate» a cosas distintas en el mismo documento."""
    import inspect

    from modules.social_dev.validation import report as mod

    fuente = inspect.getsource(mod.control_solo_tamano)
    assert "veredicto_de_control(" in fuente
    assert "VEREDICTO_EMPATE" not in fuente
