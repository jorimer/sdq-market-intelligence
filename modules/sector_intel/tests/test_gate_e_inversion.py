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


# ── El encabezado PLANO lleva el desenlace primario ───────────────
#
# Hasta el 2026-09-01 el encabezado llevaba el desenlace de EMPLEO «por continuidad con lo ya
# publicado», mientras `outcome_primario` decía `inversion`. Un consumidor que no bajaba a
# `outcomes` leía el desenlace que este mismo reporte declara que el índice NO dice anticipar,
# sin control y sin veredicto. El comentario del código ya anticipaba el fallo —«le pasó a la
# tabla comercial»— y volvió a pasar: se reportó como «significativamente negativa» una cifra
# que la plataforma computa como EMPATE con el tamaño.

_PRIMARIO = {
    "n_observations": 144, "n_branches": 9, "years": ["2009", "2024"],
    "mean_yearly_ic": -0.274, "n_years": 16, "ic_t_stat": -3.1,
    "ic_ci": [-0.46, -0.088], "spearman_pooled": -0.3,
    "spearman_pooled_ci": [-0.45, -0.15], "spearman_partial_growth": -0.3,
    "spearman_partial_n": 144, "by_year": [], "quintile_spread": None,
    "conclusive": False, "invertido": True,
    "que_mide": "intensidad de IED realizada en T+1 — el desenlace que el IAI targetea",
    "resolucion": "9 actividades de IED del BCRD",
    "fuente": "BCRD", "contraste_nivel": {"mean_yearly_ic": 0.326},
    "nota_contraste": "el nivel lo domina el tamaño",
    "control_solo_tamano": {
        "intensidad": {"mean_yearly_ic": -0.323, "ic_ci": [-0.521, -0.124],
                       "veredicto": "empate: el tamaño solo alcanza…",
                       "el_tamano_alcanza_al_score": True, "empata_con_el_score": True},
        "nivel": {"mean_yearly_ic": 0.377, "veredicto": "empate: …"},
    },
}


def test_el_encabezado_plano_lleva_las_cifras_del_PRIMARIO():
    from modules.sector_intel.validation.report import _bloque_plano

    plano = _bloque_plano(_PRIMARIO)
    assert plano["mean_yearly_ic"] == -0.274
    assert plano["ic_ci"] == [-0.46, -0.088]
    assert plano["outcome"] == _PRIMARIO["que_mide"]
    assert plano["resolution"] == _PRIMARIO["resolucion"]


def test_el_encabezado_NO_descarta_invertido_ni_conclusive():
    """Los descartaba a propósito (`if k not in ("conclusive", "invertido")`), así que la UI
    no podía saber si la cifra que renderizaba estaba invertida — y `ciExcludesZero` da True
    también para un intervalo entero por DEBAJO de cero. Un −0,274 concluyente hacia abajo se
    pintaba «Significativo»."""
    from modules.sector_intel.validation.report import _bloque_plano

    plano = _bloque_plano(_PRIMARIO)
    assert plano["invertido"] is True
    assert plano["conclusive"] is False


def test_el_VEREDICTO_contra_el_tamano_viaja_en_el_encabezado():
    """Vivía dos niveles más abajo (`outcomes.inversion.control_solo_tamano.intensidad`). Una
    cifra cuyo calificador está en otra rama del payload se publica sin el calificador: es la
    misma regla que el sujeto viajando con el número."""
    from modules.sector_intel.validation.report import _bloque_plano

    plano = _bloque_plano(_PRIMARIO)
    assert plano["veredicto_contra_el_tamano"].startswith("empate")
    assert plano["control_solo_tamano"]["mean_yearly_ic"] == -0.323


def test_sin_control_el_veredicto_dice_NO_SE_SABE_y_no_calla():
    """Un `None` mudo se leería como que la cifra no necesita calificador — el defecto del
    `stale=null`, donde «no sé de cuándo es» y «está al día» se volvían indistinguibles."""
    from shared.validation.control_tamano import VEREDICTO_CONTROL_NO_EVALUABLE
    from modules.sector_intel.validation.report import _bloque_plano

    plano = _bloque_plano({k: v for k, v in _PRIMARIO.items() if k != "control_solo_tamano"})
    assert plano["veredicto_contra_el_tamano"] == VEREDICTO_CONTROL_NO_EVALUABLE


def test_las_DOS_PUNTAS_no_se_desincronizan():
    """El encabezado se DERIVA del primario; copiarlo a mano es cómo se desincroniza sin que
    nada falle. Toda clave de métrica del primario tiene que estar arriba con su mismo valor.
    """
    from modules.sector_intel.validation.report import (_NO_SE_COPIAN_TAL_CUAL,
                                                        _bloque_plano)

    plano = _bloque_plano(_PRIMARIO)
    faltan = {k: v for k, v in _PRIMARIO.items()
              if k not in _NO_SE_COPIAN_TAL_CUAL and plano.get(k) != v}
    assert not faltan, f"el encabezado no copió, o copió distinto: {sorted(faltan)}"
    # Y las que se republican con otra forma NO pueden simplemente desaparecer: cada una
    # tiene que estar arriba bajo su nombre nuevo, o el encabezado pierde información.
    for nativa, arriba in (("que_mide", "outcome"), ("resolucion", "resolution"),
                           ("control_solo_tamano", "control_solo_tamano")):
        assert plano.get(arriba) is not None, (
            f"«{nativa}» se excluyó de la copia verbatim y no se republicó como «{arriba}»")


def test_el_encabezado_se_ARMA_llamando_al_derivador_y_no_a_mano():
    """El guard de reincidencia. Los tests de valor de arriba pasarían igual si alguien
    volviera a escribir las claves a mano con los nombres correctos de hoy — y el encabezado
    volvería a envejecer en silencio el día que el primario gane una clave."""
    import ast
    import inspect

    from modules.sector_intel.validation import report as mod

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(mod)))
              if isinstance(n, ast.FunctionDef) and n.name == "gate_e_report")
    llama = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_bloque_plano" for n in ast.walk(fn))
    assert llama, "`gate_e_report` dejó de derivar su encabezado del desenlace primario"
    literales = {n.value for n in ast.walk(fn)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "crecimiento del empleo formal (Δ% T+1, ENCFT)" not in literales, (
        "el encabezado volvió a nombrar el desenlace de empleo a mano")


def test_el_veredicto_viaja_tambien_como_BOOLEANO_y_no_solo_como_prosa():
    """La UI tiene que decidir si pinta «Significativo». Buscar la palabra «empate» dentro de
    un texto no es un contrato: esa prosa se traduce y se reescribe."""
    from modules.sector_intel.validation.report import _bloque_plano

    plano = _bloque_plano(_PRIMARIO)
    assert plano["empata_con_el_score"] is True
    assert plano["el_tamano_alcanza_al_score"] is True
    sin = _bloque_plano({k: v for k, v in _PRIMARIO.items() if k != "control_solo_tamano"})
    assert sin["empata_con_el_score"] is False, (
        "sin control no se puede afirmar que empata — pero tampoco que NO empata; lo que "
        "dice «no lo sé» es `veredicto_contra_el_tamano`, y por eso los dos viajan juntos")
