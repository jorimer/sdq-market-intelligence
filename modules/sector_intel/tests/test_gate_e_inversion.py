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


# ── Lo que el producto declara ────────────────────────────────────

class _DBConReporte:
    """Sesión mínima que devuelve un reporte de Gate E persistido."""

    def __init__(self, payload):
        import json
        self._valor = json.dumps(payload)

    def query(self, *_a, **_k):
        return self

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return type("Row", (), {"value": self._valor})()


def test_el_producto_declara_el_resultado_medido_no_lo_llama_diferido():
    """Decía «Gate E sectorial diferido» cuando el Gate E había corrido y dado resultado.

    Un producto que llama «diferido» a una validación con resultado no está siendo prudente:
    está ocultando el resultado, que es lo contrario.
    """
    from modules.sector_intel.products import _nota_validacion_iai

    nota = _nota_validacion_iai(_DBConReporte({
        "has_data": True,
        "headline_outcome": None,
        "outcomes": {
            "empleo": {"mean_yearly_ic": -0.03, "ic_ci": [-0.267, 0.208], "n_observations": 160},
            "inversion": {"mean_yearly_ic": -0.321, "ic_ci": [-0.5, -0.142],
                          "n_observations": 144,
                          "control_solo_tamano": {"intensidad": {"mean_yearly_ic": -0.323}}},
        },
    }))
    assert "diferido" not in nota
    assert "-0.03" in nota and "-0.321" in nota
    assert "-0.323" in nota, "El control por tamaño tiene que viajar con el número del índice."
    assert "DESCRIPTIVO" in nota


def test_sin_reporte_el_producto_lo_dice_en_vez_de_afirmar_algo():
    from modules.sector_intel.products import _nota_validacion_iai

    class _Vacia(_DBConReporte):
        def __init__(self):
            pass

        def first(self):
            return None

    nota = _nota_validacion_iai(_Vacia())
    assert "aún no corrido" in nota


# ── El veredicto del control se COMPUTA, no lo infiere el lector ───

def test_el_control_trae_su_veredicto_computado():
    """Las dos cifras sueltas obligaban al cliente a sacar la conclusión.

    El control existe desde la Fase 3 y publicaba −0,321 del índice contra −0,323 del tamaño
    solo, sin decir qué significan juntas. Un lector de material comercial no tiene por qué
    deducir de esos dos números que el índice no agrega nada sobre el tamaño: esa frase ES la
    conclusión, y las conclusiones se computan.
    """
    from shared.validation.control_tamano import (
        VEREDICTO_EMPATE, VEREDICTO_TAMANO_ALCANZA, veredicto_de_control,
    )

    # El caso real: el control alcanza al índice (misma magnitud, mismo signo).
    juicio = veredicto_de_control(-0.321, [-0.5, -0.142], -0.323)
    assert juicio["el_tamano_alcanza_al_score"] is True
    assert juicio["veredicto"] in (VEREDICTO_TAMANO_ALCANZA, VEREDICTO_EMPATE)

    # Y el contraste por NIVEL, donde el tamaño solo ordena MEJOR que el índice.
    nivel = veredicto_de_control(0.287, [0.163, 0.412], 0.377)
    assert nivel["el_tamano_alcanza_al_score"] is True


def test_sin_una_de_las_dos_cifras_el_veredicto_no_se_inventa():
    from shared.validation.control_tamano import (
        VEREDICTO_CONTROL_NO_EVALUABLE, veredicto_de_control,
    )

    for juicio in (veredicto_de_control(None, [0.1, 0.2], -0.3),
                   veredicto_de_control(-0.3, [-0.5, -0.1], None)):
        assert juicio["veredicto"] == VEREDICTO_CONTROL_NO_EVALUABLE
        assert juicio["el_tamano_alcanza_al_score"] is False
