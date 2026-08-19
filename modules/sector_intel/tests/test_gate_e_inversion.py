"""El Gate E sectorial contra el desenlace que el IAI SÍ pretende anticipar.

El índice se validaba contra crecimiento del EMPLEO y daba nulo/negativo (IC medio anual
−0,03; spread de quintiles −1,13 pp). El resultado era correcto y la pregunta no: el IAI es
un Índice de Atractivo de **Inversión**, y el empleo no es lo que dice anticipar. Decisión
del dueño: validarlo contra inversión realizada — la IED por actividad del BCRD.

Lo que estos tests fijan es la parte que se rompe en silencio: el mapa de actividades, los
guards del cuadro, y que el titular no se elija por magnitud sino por intervalo.
"""
import pytest

from modules.sector_intel.validation.outcomes import label_panel_ied
from modules.sector_intel.validation.report import _titular
from shared.data.ied_bcrd import IedError, parse_annual_sheet
from shared.data.sector_crosswalk import ied_coverage, ied_members, map_ied_label


# ── El mapa de actividades ────────────────────────────────────────

def test_las_nueve_actividades_mapean_a_slugs_reales():
    cob = ied_coverage()
    assert cob["n_actividades"] == 9
    assert "manufactura_local" in ied_members("comercio_industria")
    assert ied_members("comercio_industria") == ["comercio", "manufactura_local"]


def test_la_cobertura_parcial_se_declara_en_vez_de_imputarse():
    """La IED no llega a agropecuario ni a construcción: quedan FUERA, no en cero.

    Imputarles cero afirmaría que no recibieron inversión, cuando lo que pasa es que el
    BCRD no los desagrega.
    """
    cob = ied_coverage()
    assert "agropecuario" in cob["uncovered"]
    assert "construccion" in cob["uncovered"]
    assert set(cob["covered"]) & set(cob["uncovered"]) == set()


def test_el_total_del_cuadro_no_entra_como_actividad():
    assert map_ied_label("Total Flujos IED") is None
    assert map_ied_label("Otros") is None
    assert map_ied_label("Comercio / Industria") == "comercio_industria"


# ── Los guards del cuadro ─────────────────────────────────────────

_FILAS_OK = [
    ["Actividad Económica", 2020, 2021],
    ["Turismo", 10.0, 20.0],
    ["Minero", 5.0, 5.0],
    ["Total Flujos IED", 15.0, 25.0],
]


def test_una_actividad_nueva_del_bcrd_falla_cerrado():
    filas = [r[:] for r in _FILAS_OK]
    filas.insert(3, ["Agroindustria", 1.0, 2.0])
    filas[-1] = ["Total Flujos IED", 16.0, 27.0]
    with pytest.raises(IedError, match="no reconocida"):
        parse_annual_sheet(filas)


def test_si_la_suma_no_cuadra_con_el_total_del_bcrd_falla_cerrado():
    """Se verifica contra una magnitud REAL de la fuente, no contra una invariante propia."""
    filas = [r[:] for r in _FILAS_OK]
    filas[-1] = ["Total Flujos IED", 99.0, 25.0]
    with pytest.raises(IedError, match="no cuadra"):
        parse_annual_sheet(filas)


def test_el_cuadro_bien_leido_devuelve_las_actividades():
    d = parse_annual_sheet([r[:] for r in _FILAS_OK])
    assert d == {"turismo": {"2020": 10.0, "2021": 20.0},
                 "minero": {"2020": 5.0, "2021": 5.0}}


# ── El desenlace ──────────────────────────────────────────────────

def test_sin_lookahead_la_fila_se_descarta_no_se_fabrica():
    panel = [{"branch": "turismo", "period": "2024", "iai_score": 60.0, "sector_size": 2.0}]
    assert label_panel_ied(panel, {"turismo": {"2024": 100.0}}) == []


def test_la_intensidad_es_el_primario_y_el_nivel_viaja_aparte():
    panel = [{"branch": "turismo", "period": "2020", "iai_score": 60.0, "sector_size": 2.0}]
    fila = label_panel_ied(panel, {"turismo": {"2021": 100.0}})[0]
    assert fila["ied_next"] == 100.0
    assert fila["ied_intensity_next"] == 50.0


def test_sin_tamano_la_intensidad_se_declara_none_en_vez_de_caer_al_nivel():
    panel = [{"branch": "turismo", "period": "2020", "iai_score": 60.0, "sector_size": None}]
    fila = label_panel_ied(panel, {"turismo": {"2021": 100.0}})[0]
    assert fila["ied_intensity_next"] is None
    assert fila["ied_next"] == 100.0


# ── El titular ────────────────────────────────────────────────────

def test_el_titular_se_elige_por_intervalo_no_por_magnitud():
    """Un titular por mayor magnitud convertiría un no concluyente en credencial."""
    empleo = {"conclusive": False, "mean_yearly_ic": 0.40}
    inversion = {"conclusive": True, "mean_yearly_ic": 0.12}
    assert _titular(empleo, inversion) == "inversion"
    assert _titular(empleo, None) is None
    assert _titular({"conclusive": True}, {"conclusive": False}) == "empleo"


# ── El control por tamaño ─────────────────────────────────────────

def test_el_control_por_tamano_es_obligatorio_en_el_bloque_de_inversion():
    """La intensidad se divide por el tamaño, y el tamaño es una variable del IAI.

    Sin medir qué hace el tamaño SOLO contra el mismo desenlace, «el IAI ordena al revés la
    inversión» y «el deflactor produce el signo» son indistinguibles — y son conclusiones
    opuestas. El bloque tiene que traer el control siempre, no como un extra opcional.
    """
    import inspect

    from modules.sector_intel.validation import report as mod

    fuente = inspect.getsource(mod._gate_e_inversion)
    assert "control_solo_tamano" in fuente
    assert "nota_control" in fuente
