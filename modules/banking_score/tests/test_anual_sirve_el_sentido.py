"""El producto anual sirve el SENTIDO, no solo los números.

**El defecto que cierra.** El cómputo del año estaba bien; lo que fallaba era lo que se le
ENTREGABA al modelo. El contexto anual servía números pelados y le dejaba deducir lo que ya
sabemos — que es exactamente donde este repo aprendió que el modelo falla:

  * `_balance` daba `subio: true/false` sin la dirección del indicador. Morosidad de 1,33 a
    1,96 y solvencia de 26,8 a 23,3 son las DOS deterioros, y sin el sentido una se narra como
    mejora.
  * `contexto_de_mercado` daba tres números sueltos y dejaba la comparación al modelo, cuando
    esa comparación ES la sección entera.
  * El Pulse ABIERTO servía `tipo: 'aap'` —la clave del enum— en material de mercado.
"""
import pytest

from modules.banking_score.products_year_review import (UMBRAL_CONTRASTE,
                                                        _contraste_con_el_mercado)
from modules.banking_score.reports.revision_anual import _balance

_CORTES = ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


def _serie(clave, v0, v1):
    return {clave: [{"period_end": _CORTES[0], "raw": v0},
                    {"period_end": _CORTES[-1], "raw": v1}]}


# ── El balance dice si el movimiento fue bueno o malo ──────────────────

@pytest.mark.parametrize("clave,v0,v1,esperado", [
    ("morosidad", 1.33, 1.96, "desfavorable"),   # sube y es `lower` → deterioro
    ("morosidad", 1.96, 1.33, "favorable"),
    ("solvencia", 26.84, 23.26, "desfavorable"),  # baja y es `higher` → deterioro
    ("solvencia", 23.26, 26.84, "favorable"),
])
def test_cada_fila_trae_su_VEREDICTO(clave, v0, v1, esperado):
    fila = _balance(_serie(clave, v0, v1), _CORTES)[0]
    assert fila["veredicto"] == esperado
    assert fila["veredicto_por_que"], "un veredicto sin motivo no se puede auditar"


def test_un_indicador_de_OPTIMO_INTERMEDIO_no_recibe_veredicto():
    """`ltd` es `target`: ni subir ni bajar es bueno por sí solo, y un booleano insinúa que sí."""
    fila = _balance(_serie("ltd", 91.7, 98.4), _CORTES)[0]
    assert fila["veredicto"] == "no_aplica"
    assert "óptimo intermedio" in fila["veredicto_por_que"]


def test_un_movimiento_INMATERIAL_es_estable_y_no_deterioro():
    fila = _balance(_serie("solvencia", 26.84, 26.85), _CORTES)[0]
    assert fila["veredicto"] == "estable"


def test_la_fila_trae_UNIDAD_y_glosa():
    """Sin unidad, un cambio de 0,63 se narra como «puntos» cuando son porcentuales."""
    fila = _balance(_serie("morosidad", 1.33, 1.96), _CORTES)[0]
    assert fila["unidad"] == "%"
    assert fila["que_mide"]
    assert fila["sentido_de_la_escala"] == "lower"


# ── El contraste con el mercado viene resuelto ─────────────────────────

def _sistema(cambio=-0.41):
    return {"sistema": {"cambio_mediana": cambio}, "conteo_direccion": {"mejora": 30}}


def test_la_comparacion_contra_su_TIPO_viene_computada():
    r = _contraste_con_el_mercado(-0.60, {"tipo": "aap", "cambio_mediana": -2.91},
                                  _sistema(), "aap")
    assert r["vs_su_tipo"]["sentido"] == "mejor"
    assert r["vs_su_tipo"]["brecha_pp"] == 2.31
    assert "Asociaciones de ahorros y préstamos" in r["vs_su_tipo"]["lectura"]


def test_caer_mientras_el_estrato_sube_es_IDIOSINCRATICO():
    """Es el veredicto de la sección: sin él, «bajó 4 puntos» no distingue lo propio de lo
    que hizo todo el mercado."""
    r = _contraste_con_el_mercado(-4.0, {"tipo": "aap", "cambio_mediana": 1.0},
                                  _sistema(), "aap")
    assert r["es_idiosincratico"] is True
    assert r["es_idiosincratico_por_que"]


def test_acompañar_al_estrato_NO_es_idiosincratico():
    """El contrapeso: sin él, la regla marcaría todo como propio de la entidad."""
    r = _contraste_con_el_mercado(-2.5, {"tipo": "aap", "cambio_mediana": -2.91},
                                  _sistema(), "aap")
    assert r["es_idiosincratico"] is False


def test_un_movimiento_igual_al_del_estrato_se_dice_EN_LINEA():
    r = _contraste_con_el_mercado(-2.9, {"tipo": "aap", "cambio_mediana": -2.91},
                                  _sistema(), "aap")
    assert r["vs_su_tipo"]["sentido"] == "en línea"
    assert abs(r["vs_su_tipo"]["brecha_pp"]) < UMBRAL_CONTRASTE


def test_sin_dato_del_estrato_NO_se_fabrica_un_cero():
    """Un cero inventado se lee como «no se movió», que es una afirmación."""
    r = _contraste_con_el_mercado(-4.0, None, _sistema(), "aap")
    assert r["vs_su_tipo"] is None
    assert r["es_idiosincratico"] is None


# ── El nivel abierto no sirve claves de enum ───────────────────────────

def test_el_tipo_de_entidad_viaja_con_su_ETIQUETA():
    from modules.banking_score.reports.anuario import _anios_con_cierre  # noqa: F401
    from modules.banking_score.etiquetas import etiqueta_de_tipo

    assert etiqueta_de_tipo("aap") == "Asociaciones de ahorros y préstamos"
    assert etiqueta_de_tipo("cambiaria") == "Agentes de cambio"
    # Un tipo NUEVO se nota en vez de salir en blanco.
    assert etiqueta_de_tipo("tipo_inventado") == "tipo_inventado"


def test_las_DOS_superficies_usan_la_misma_etiqueta():
    """Había dos copias que no coincidían: «intermediación cambiaria» contra «Agentes de
    cambio» para la misma clave, según qué pantalla mirabas."""
    from modules.banking_score.api.router_scoring import _TIPO_LABEL as a
    from modules.banking_score.reports.pdf_generator import _TIPO_LABEL as b
    from modules.banking_score.etiquetas import TIPO_LABEL

    assert a is TIPO_LABEL and b is TIPO_LABEL


# ── El prompt tiene que PEDIR que se copie lo computado ────────────────
#
# Servir el veredicto sin decirle al modelo que lo copie deja el arreglo por la mitad: el
# contexto tendría la respuesta y el texto seguiría deduciéndola. Es la misma lección que la
# corrección de dirección invertida — entregar la lectura correcta Y pedir que se copie.

def test_el_prompt_del_año_pide_COPIAR_el_veredicto_del_balance():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES["revision_anual"]
    assert "COPIALO" in t, "el prompt no pide copiar el veredicto"
    assert "NO deduzcas" in t
    assert "no_aplica" in t, "tiene que decir qué hacer con el óptimo intermedio"


def test_el_prompt_del_contraste_pide_COPIAR_y_no_recalcular():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES["revision_anual_mercado"]
    assert "no lo recalcules" in t
    assert "es_idiosincratico" in t


def test_los_prompts_prohiben_nombrar_el_estrato_por_su_CLAVE():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    for nombre in ("anio_del_sistema", "revision_anual_mercado"):
        t = THIN_TEMPLATES[nombre]
        assert "clave técnica" in t, f"{nombre} no prohíbe la clave cruda"
