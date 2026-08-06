"""El CORTE del informe manda sobre TODA la información mostrada.

Decisión del dueño (2026-08-06): no basta con recortar la trayectoria. Un informe fechado
"al 31-dic-2025" no puede describir el entorno macro de 2026, ni citar una afirmación
soberana de agosto-2026, ni declarar cobertura a marzo-2026 en su metodología. Rotular la
capa con su propio año no alcanza: fue justamente rotularla lo que llevó al modelo a
inventar "proyectado"/"preliminar" para explicar una cifra del futuro.
"""
from datetime import date

from modules.banking_score.products import _posterior_al_corte
from modules.banking_score.scoring.support import _sovereign_as_of
from shared.products.report_sections import _methodology_md, _periodo_posterior

CORTE = date(2025, 12, 31)


# ── Capa 1: telón macro ───────────────────────────────────────────────────────

def test_periodo_posterior_reconoce_los_tres_granos():
    assert _posterior_al_corte("2026", CORTE) is True
    assert _posterior_al_corte("2026-03", CORTE) is True
    assert _posterior_al_corte("2026-01-31", CORTE) is True
    assert _posterior_al_corte("2025", CORTE) is False
    assert _posterior_al_corte("2025-12", CORTE) is False
    assert _posterior_al_corte("2025-09-30", CORTE) is False


def test_periodo_ilegible_no_oculta_por_las_dudas():
    """Ante lo no parseable NO se esconde: ocultar dato bueno es su propio defecto."""
    assert _posterior_al_corte(None, CORTE) is False
    assert _posterior_al_corte("", CORTE) is False
    assert _posterior_al_corte("último trimestre", CORTE) is False


# ── Capa 2: ancla soberana ────────────────────────────────────────────────────

def _sov():
    return {
        "rating": "BB", "agency": "S&P", "score": 45.0,
        "as_of": "2022-12-19",            # acción anterior al corte: legítima
        "affirm_date": "2026-08-01",      # verificación POSTERIOR: no había ocurrido
        "agencies": [
            {"agency": "S&P", "rating": "BB", "action_date": "2022-12-19"},
            {"agency": "Fitch", "rating": "BB-", "action_date": "2025-11-07"},
            {"agency": "Moody's", "rating": "Ba3", "action_date": "2026-02-10"},
        ],
    }


def test_la_afirmacion_posterior_al_corte_no_se_muestra():
    out = _sovereign_as_of(_sov(), CORTE)
    assert out["affirm_date"] is None


def test_el_rating_vigente_al_corte_se_conserva():
    """No se altera el rating ni el score: sólo se recorta lo que aún no había pasado."""
    out = _sovereign_as_of(_sov(), CORTE)
    assert out["rating"] == "BB" and out["score"] == 45.0
    assert out["as_of"] == "2022-12-19"


def test_se_excluye_la_agencia_cuya_accion_es_posterior():
    out = _sovereign_as_of(_sov(), CORTE)
    ags = {a["agency"] for a in out["agencies"]}
    assert ags == {"S&P", "Fitch"}, "Moody's actuó en 2026-02, después del corte"


def test_sobre_vacio_es_seguro():
    assert _sovereign_as_of({}, CORTE)["agencies"] == []


# ── Capa 3: metodología ───────────────────────────────────────────────────────

class _Sig:
    sources = ("SIB", "BCRD")
    cadence = "trimestral"
    freshness_days = 128
    coverage = 1.0
    detail = "81 entidades calificadas en 2026-03-31."


def test_la_metodologia_declara_el_corte():
    md = _methodology_md(_Sig(), None, as_of="2025-12-31")
    assert "Corte del informe:** 2025-12-31" in md


def test_se_omite_la_lectura_del_dato_posterior_al_corte():
    md = _methodology_md(_Sig(), None, as_of="2025-12-31")
    assert "2026-03-31" not in md


def test_la_lectura_del_dato_anterior_al_corte_si_se_muestra():
    class _S(_Sig):
        detail = "80 entidades calificadas en 2025-09-30."
    assert "2025-09-30" in _methodology_md(_S(), None, as_of="2025-12-31")


def test_sin_corte_el_comportamiento_no_cambia():
    """Otros consumidores (readiness, auditoría) no se ven afectados."""
    md = _methodology_md(_Sig(), None)
    assert "2026-03-31" in md
    assert "Corte del informe" not in md


def test_deteccion_de_periodo_posterior_es_conservadora():
    assert _periodo_posterior("sin fechas acá", "2025-12-31") is False
    assert _periodo_posterior("dato de 2025-06", "2025-12-31") is False
    assert _periodo_posterior("dato de 2026-01", "2025-12-31") is True
