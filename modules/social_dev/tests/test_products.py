"""``social_dev`` como SectorProduct — contrato, series sub-nacionales y procedencia.

El punto de este eje es que su dato varía DENTRO del país. Los tests que importan son
los que verifican justamente eso: que se publican las series con desagregación
geográfica y NO las variables nacionales disfrazadas de regionales, y que la señal por
variable declara el alcance.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import (
    PRODUCT_CATALOG,
    ProductTier,
    SectorProduct,
    get_product,
    is_implemented,
    required_signal_methods,
)
from modules.social_dev.models.models import DevelopmentScore, SocialIndicator
from modules.social_dev.products import SECTOR_KEY, SocialDevProduct  # noqa: F401 — registra


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


def _seed(db):
    """Panel mínimo: pobreza por región, cobertura por región Y provincia, una serie
    provincial del SIUBEN, y una variable NACIONAL aplicada a todas las regiones."""
    rows = [
        ("enriquillo", "poverty_rate", "2024", 31.0, "region", "ONE", "% de la población"),
        ("valdesia", "poverty_rate", "2024", 11.0, "region", "ONE", "% de la población"),
        ("ozama", "secondary_coverage", "2024", 67.7, "region", "ONE", "% (cobertura neta secundaria)"),
        ("distrito_nacional", "secondary_coverage", "2024", 73.1, "provincia", "ONE",
         "% (cobertura neta secundaria)"),
        ("elias_pina", "siuben_illiteracy_head_share", "2024-Q4", 36.3, "provincia", "SIUBEN",
         "% de jefes/as del padrón"),
        ("elias_pina", "siuben_illiteracy_head_share", "2024-Q3", 36.9, "provincia", "SIUBEN",
         "% de jefes/as del padrón"),
        # NACIONAL: entra al IDM aplicado a las 10 regiones, pero NO es una serie
        # geográfica y no debe publicarse como tal.
        ("nacional", "informality_rate", "2024", 55.46, "nacional", "ONE", "%"),
    ]
    for entity, theme, period, value, disagg, source, unit in rows:
        db.add(SocialIndicator(entity_key=entity, theme=theme, period=period, value=value,
                               disaggregation=disagg, source=source, unit=unit))
    db.add(DevelopmentScore(
        entity_key="enriquillo", period="2024", development_score=38.4, band="Bajo",
        breakdown={"health": {"score": 62.0, "weight": 0.25, "provenance": "real"},
                   "education": {"score": 41.2, "weight": 0.25, "provenance": "real"}}))
    db.add(DevelopmentScore(entity_key="valdesia", period="2024", development_score=61.2,
                            band="Medio", breakdown={}))
    db.commit()


def test_social_dev_esta_en_el_catalogo_y_registrado():
    """Era un EJE sin ser un PRODUCTO, y por eso ni la Data API ni /quality podían
    verlo: ambos recorren PRODUCT_CATALOG. Un 404 por ausencia del catálogo se lee
    desde afuera como un problema de permisos, que es la confusión que esto cierra."""
    assert SECTOR_KEY in {e.sector_key for e in PRODUCT_CATALOG}
    assert is_implemented(SECTOR_KEY)


def test_cumple_el_contrato_de_sector_product(db):
    product = get_product(SECTOR_KEY, db)
    assert isinstance(product, SectorProduct)
    for method in required_signal_methods():
        assert callable(getattr(product, method, None)), f"falta {method}"


def test_publica_solo_series_con_desagregacion_geografica(db):
    """Servir una variable nacional 'por región' sería entregar una CONSTANTE con
    etiqueta geográfica: no distingue demarcaciones y no le sirve a quien las ordena."""
    _seed(db)
    codes = {s.code for s in get_product(SECTOR_KEY, db).canonical_series()}
    assert "poverty_rate.enriquillo" in codes
    assert "secondary_coverage.distrito_nacional" in codes          # provincia
    assert "siuben_illiteracy_head_share.elias_pina" in codes
    assert not any(c.endswith(".nacional") for c in codes)
    assert not any(c.startswith("informality_rate") for c in codes)


def test_cada_serie_declara_licencia_y_universo(db):
    """Sin licencia el manifiesto la pone en cuarentena (fail-closed); sin el universo,
    una composición del padrón SIUBEN se lee como la tasa de la provincia."""
    _seed(db)
    series = {s.code: s for s in get_product(SECTOR_KEY, db).canonical_series()}
    assert all(s.license for s in series.values())
    siuben = series["siuben_illiteracy_head_share.elias_pina"]
    assert "padrón" in siuben.note and "NO la población general" in siuben.note
    assert siuben.frequency == "quarterly"          # el SIUBEN publica por trimestre
    assert series["poverty_rate.enriquillo"].frequency == "annual"
    # Todas son porcentajes: su variación se mide en PUNTOS, no en % sobre %.
    assert all(s.nature == "rate" for s in series.values())


def test_observaciones_de_una_serie_llegan_ordenadas(db):
    _seed(db)
    obs = get_product(SECTOR_KEY, db).series_observations(
        "siuben_illiteracy_head_share.elias_pina")
    assert [o.period for o in obs] == ["2024-Q3", "2024-Q4"]
    assert [o.value for o in obs] == [36.9, 36.3]
    assert all(o.source == "SIUBEN" for o in obs)


def test_as_of_no_se_finge(db):
    """El eje no guarda revisiones point-in-time. Devolver la serie de hoy con etiqueta
    de ayer sería una mentira barata; se levanta ValueError y la API lo traduce a 422."""
    _seed(db)
    with pytest.raises(ValueError, match="point-in-time"):
        get_product(SECTOR_KEY, db).series_observations("poverty_rate.enriquillo",
                                                        as_of="2020-01-01")


def test_score_idm_se_publica_con_su_desglose(db):
    _seed(db)
    product = get_product(SECTOR_KEY, db)
    scores = product.canonical_scores()
    assert [s.code for s in scores] == ["idm"]
    assert set(scores[0].subjects) == {"enriquillo", "valdesia"}
    assert scores[0].direction                      # obligatoria en la práctica
    obs = product.score_observations("idm", subject="enriquillo")
    assert obs and obs[0].score == 38.4 and obs[0].band == "Bajo"
    assert obs[0].dimensions                        # el desglose numérico SÍ viaja
    assert product.score_observations("otro_codigo") == []


def test_la_señal_por_variable_declara_el_alcance_nacional(db):
    """La mitad que faltaba: seis de las nueve variables del IDM son nacionales y se
    aplican idénticas a las 10 regiones. Sin declararlo, 'dato real' se leía como
    'diferencia entre demarcaciones', que es falso."""
    _seed(db)
    sig = get_product(SECTOR_KEY, db).variable_signals()
    by_key = {s.key: s for s in sig["signals"]}
    assert sig["period"] == "2024"
    assert by_key["informality_rate"].scope == "national"
    assert by_key["life_expectancy"].scope == "national"
    assert by_key["financial_inclusion"].scope == "national"
    # Las que sí se miden por demarcación quedan en el default.
    assert by_key["poverty_rate"].scope == "per_subject"
    assert by_key["secondary_coverage"].scope == "per_subject"


def test_pulse_es_agregado_sin_nombres_de_demarcacion(db):
    """El sensor de anonimización del ensamblador exige que el Pulse no filtre sujetos."""
    _seed(db)
    snap = get_product(SECTOR_KEY, db).snapshot(ProductTier.pulse, "")
    assert snap.entity_name is None and snap.entity_roster == ()
    assert snap.payload["distribution"]["n"] == 2
    assert "enriquillo" not in str(snap.payload)


def test_nivel_nombrado_exige_scope_y_lo_valida(db):
    _seed(db)
    product = get_product(SECTOR_KEY, db)
    with pytest.raises(ValueError, match="scope"):
        product.snapshot(ProductTier.insight, "")
    with pytest.raises(ValueError, match="no tiene IDM"):
        product.snapshot(ProductTier.insight, "", scope="marte")
    snap = product.snapshot(ProductTier.insight, "", scope="enriquillo")
    assert snap.entity_name == "Enriquillo" and snap.payload["rank"] == 2


def test_sin_dato_el_producto_lo_dice_en_vez_de_inventar(db):
    product = get_product(SECTOR_KEY, db)
    assert product.has_engine() is False
    assert product.data_signals().coverage == 0.0
    assert product.canonical_series() == [] and product.canonical_scores() == []
    assert product.snapshot(ProductTier.pulse, "").payload == {"has_score": False}


def test_scope_options_solo_ofrece_regiones_con_score(db):
    _seed(db)
    values = {o["value"] for o in get_product(SECTOR_KEY, db).scope_options()}
    assert values == {"enriquillo", "valdesia"}
