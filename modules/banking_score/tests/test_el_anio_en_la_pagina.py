"""El año de la entidad, IMPRESO: qué movió el score y si cambió de banda.

La descomposición ya viajaba al modelo. Si no se imprime, la afirmación «el deterioro lo
impulsó X» le queda al lector como un acto de fe — la misma lección que ya documentaba la
tabla de trayectoria: si la narrativa razona sobre una cifra, esa cifra tiene que estar en la
página.

Acá la verificación es especialmente barata: **cada columna suma el cambio total**. Con esta
tabla al lado, el informe donde la §1 adjudicó a la eficiencia un semestre en el que la
eficiencia había MEJORADO se habría desmentido solo: el lector ve el +0.12.
"""
import pytest

from modules.banking_score.reports.pdf_generator import (_build_aportes_table,
                                                         _build_banda_del_periodo, _get_styles)

_PER = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31",
        "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
#: Trayectoria REAL de Asociación Bonao, verificada contra producción.
_S = {
    "solidez":         [79.02, 79.84, 81.56, 81.61, 82.32, 80.53, 79.78, 74.64],
    "calidad":         [78.71, 77.81, 76.97, 77.54, 75.21, 76.10, 76.43, 72.15],
    "eficiencia":      [28.99, 27.20, 24.71, 19.24, 16.84, 10.47,  8.03, 11.43],
    "liquidez":        [61.29, 60.03, 62.05, 61.49, 61.53, 59.19, 61.58, 57.21],
    "diversificacion": [22.77, 20.82, 20.77, 21.91, 28.78, 23.24, 21.73, 22.75],
}


def _tray(banda_ini="Sólida", banda_fin="Adecuada", n=8):
    return {
        "sub": {k: [{"period_end": p, "score": v}
                    for p, v in zip(_PER[-n:], vals[-n:])] for k, vals in _S.items()},
        "overall": [{"period_end": _PER[-n], "score": 67.83, "banda_resiliencia": banda_ini},
                    {"period_end": _PER[-1], "score": 61.24, "banda_resiliencia": banda_fin}],
    }


def _celdas(entity_type="aap", tray=None):
    els = _build_aportes_table(tray or _tray(), entity_type, _get_styles())
    tabla = next(e for e in els if hasattr(e, "_cellvalues"))
    return [[c.getPlainText() if hasattr(c, "getPlainText") else str(c) for c in fila]
            for fila in tabla._cellvalues]


def _texto(els):
    return " ".join(e.getPlainText() if hasattr(e, "getPlainText") else str(e) for e in els)


# ── La identidad que la vuelve verificable ─────────────────────────────

def test_cada_columna_SUMA_el_cambio_total():
    """Es lo que permite al lector auditar la atribución sin creerle a la prosa."""
    filas = _celdas()
    total = [float(x) for x in filas[-1][1:]]
    for col in range(len(total)):
        suma = sum(float(f[col + 1]) for f in filas[1:-1] if f[col + 1] != "—")
        assert suma == pytest.approx(total[col], abs=0.02), f"columna {col}"


def test_EL_CASO_la_tabla_desmiente_la_atribucion_publicada():
    """§1 dijo que el 2º semestre lo impulsó «el colapso de eficiencia». En la página se ve
    que eficiencia aportó a FAVOR en esa ventana."""
    filas = _celdas()
    cols = filas[0]
    i_sem = cols.index("Semestre")
    ef = next(f for f in filas if f[0].startswith("Eficiencia"))
    assert float(ef[i_sem]) > 0, ef


def test_los_pesos_son_los_del_TIPO_de_entidad():
    aap = _celdas("aap")[-1][1:]
    bm = _celdas("banca_multiple")[-1][1:]
    assert aap != bm, "la tabla ignora el tipo de entidad"


# ── Bordes ─────────────────────────────────────────────────────────────

def test_solo_se_imprimen_las_ventanas_que_la_serie_SOPORTA():
    """Con dos cortes no se habla del último año. Una ventana inventada es peor que ausente."""
    assert _celdas(tray=_tray(n=2))[0] == ["Sub-componente", "Trimestre"]


def test_sin_trayectoria_no_se_imprime_nada():
    assert _build_aportes_table({}, "aap", _get_styles()) == []
    assert _build_aportes_table({"sub": {}}, "aap", _get_styles()) == []


# ── El cambio de banda ─────────────────────────────────────────────────

def test_el_cambio_de_banda_se_DICE():
    """El hecho que un comité recuerda del año. En 2025 lo vivieron 18 de 86 entidades."""
    t = _texto(_build_banda_del_periodo(_tray("Sólida", "Adecuada"), _get_styles()))
    assert "Sólida" in t and "Adecuada" in t and "cambió de banda" in t


def test_si_NO_cambio_de_banda_no_se_afirma_que_si():
    t = _texto(_build_banda_del_periodo(_tray("Sólida", "Sólida"), _get_styles()))
    assert "cambió de banda" not in t and "Sólida" in t


def test_sin_banda_en_la_serie_no_se_inventa():
    tray = _tray()
    for p in tray["overall"]:
        p["banda_resiliencia"] = None
    assert _build_banda_del_periodo(tray, _get_styles()) == []
