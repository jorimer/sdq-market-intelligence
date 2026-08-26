"""El AÑO del sistema: reglas que evitan un titular falso.

Es el primer documento de la firma cuyo sujeto es el sistema entero y que además NOMBRA
entidades. Cada regla de `reports/anuario` nace de un modo concreto de mentir con datos
correctos, y los tres primeros tests usan el panel REAL de 2025 medido contra producción.
"""
import datetime

import pytest

from modules.banking_score.reports.anuario import UMBRAL_MOVIMIENTO, anuario_del_sistema
from modules.banking_score.reports import anuario as _mod

_CORTES = ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


def _panel(scores_por_corte, bandas=None, tipos=None):
    """`{corte: {entidad: {...}}}` desde `{entidad: [score por corte]}`."""
    bandas, tipos = bandas or {}, tipos or {}
    return {
        datetime.date.fromisoformat(c): {
            n: {"score": v[i],
                "banda": (bandas.get(n) or [None] * len(_CORTES))[i],
                "tipo": tipos.get(n, "banca_multiple")}
            for n, v in scores_por_corte.items() if v[i] is not None}
        for i, c in enumerate(_CORTES)
    }


@pytest.fixture()
def con_panel(monkeypatch):
    def _instalar(panel):
        monkeypatch.setattr(_mod, "_panel", lambda db, cortes: panel)
        return anuario_del_sistema(object(), 2025)
    return _instalar


# ── La trampa de la media ──────────────────────────────────────────────

def test_LA_MEDIA_Y_LA_MEDIANA_pueden_decir_lo_contrario_y_se_DECLARA(con_panel):
    """Caso REAL de 2025 (medido en prod): la media sube y la mediana baja. Las dos son
    correctas. Titular con la media estaría respaldado y sería falso como lectura."""
    # Cuatro entidades que bajan un poco + una que se dispara: mueve la media, no la mediana.
    # Es la forma exacta del panel real, donde una cambiaria mejoró +60,60 puntos.
    r = con_panel(_panel({
        "A": [70, 70, 69, 68, 68], "B": [68, 68, 68, 67, 67],
        "C": [66, 66, 66, 65, 65], "D": [64, 64, 63, 62, 62],
        "E": [62, 62, 62, 61, 61], "F": [10, 20, 35, 50, 55],
    }))
    sis = r["sistema"]
    assert sis["cambio_mediana"] < 0 < sis["cambio_media"], sis
    assert sis["medias_y_medianas_divergen"] is True
    assert "mediana" in sis["lectura"] and "extremos" in sis["lectura"]


def test_el_estadistico_de_referencia_es_la_MEDIANA(con_panel):
    r = con_panel(_panel({"A": [70, 70, 70, 70, 70], "B": [60, 60, 60, 60, 60]}))
    assert r["sistema"]["estadistico_de_referencia"] == "mediana"


def test_si_NO_divergen_no_se_afirma_que_si(con_panel):
    r = con_panel(_panel({"A": [70, 69, 68, 67, 66], "B": [60, 59, 58, 57, 56]}))
    assert r["sistema"]["medias_y_medianas_divergen"] is False
    assert "extremos" not in r["sistema"]["lectura"]


# ── El universo ────────────────────────────────────────────────────────

def test_las_PARCIALES_no_se_ordenan_pero_se_NOMBRAN(con_panel):
    """Un año incompleto no se rankea contra uno completo; ocultarlo sería peor, porque
    desaparecería sin aviso."""
    r = con_panel(_panel({"Completa": [60, 61, 62, 63, 64],
                          "Otra": [70, 70, 70, 70, 70],
                          "Recién llegada": [None, None, None, None, 90]}))
    assert r["universo"]["comparables"] == 2
    parciales = [p["entidad"] for p in r["universo"]["parciales"]]
    assert parciales == ["Recién llegada"]
    assert r["universo"]["parciales"][0]["cortes_presentes"] == 1


def test_los_agregados_EXCLUYEN_a_las_parciales(con_panel):
    """Si la recién llegada entrara al agregado, movería la mediana del sistema sin haber
    estado el año."""
    sin = con_panel(_panel({"A": [60, 60, 60, 60, 60], "B": [70, 70, 70, 70, 70]}))
    con = con_panel(_panel({"A": [60, 60, 60, 60, 60], "B": [70, 70, 70, 70, 70],
                            "X": [None, None, None, None, 99]}))
    assert sin["sistema"]["por_corte"][-1]["mediana"] == con["sistema"]["por_corte"][-1]["mediana"]


# ── Movimiento, tipo y banda ───────────────────────────────────────────

def test_un_movimiento_INMATERIAL_no_se_llama_mejora_ni_deterioro(con_panel):
    r = con_panel(_panel({"A": [60, 60, 60, 60, 60 + UMBRAL_MOVIMIENTO / 2],
                          "B": [70, 70, 70, 70, 70]}))
    assert r["conteo_direccion"]["estable"] == 2


def test_el_cambio_por_tipo_usa_la_MEDIANA_del_tipo(con_panel):
    r = con_panel(_panel(
        {"M1": [60, 60, 60, 60, 55], "M2": [60, 60, 60, 60, 56], "M3": [60, 60, 60, 60, 57],
         "C1": [50, 50, 50, 50, 52], "C2": [50, 50, 50, 50, 53]},
        tipos={"C1": "cambiaria", "C2": "cambiaria"}))
    por = {t["tipo"]: t for t in r["por_tipo"]}
    assert por["banca_multiple"]["cambio_mediana"] == -4.0
    assert por["cambiaria"]["direccion"] == "mejora"
    # Ordenados del peor al mejor: el hallazgo estructural va primero.
    assert r["por_tipo"][0]["tipo"] == "banca_multiple"


def test_el_cambio_de_banda_se_lista_con_su_DIRECCION(con_panel):
    r = con_panel(_panel(
        {"Baja": [60, 60, 60, 60, 50], "Queda": [70, 70, 70, 70, 70]},
        bandas={"Baja": ["Sólida"] * 4 + ["Adecuada"], "Queda": ["Sólida"] * 5}))
    assert len(r["cambios_de_banda"]) == 1
    b = r["cambios_de_banda"][0]
    assert b["entidad"] == "Baja" and b["desde"] == "Sólida" and b["hasta"] == "Adecuada"
    assert b["cambio_score"] < 0


def test_los_EXTREMOS_viajan_con_su_advertencia(con_panel):
    r = con_panel(_panel({"Peor": [60, 60, 60, 60, 20], "Mejor": [40, 45, 50, 55, 80],
                          "Medio": [60, 60, 60, 60, 60]}))
    assert r["extremos"]["mayor_deterioro"]["entidad"] == "Peor"
    assert r["extremos"]["mayor_mejora"]["entidad"] == "Mejor"
    assert "COLAS" in r["extremos"]["advertencia"]


# ── Bordes ─────────────────────────────────────────────────────────────

def test_sin_panel_suficiente_no_se_fabrica_un_anuario(con_panel):
    solo_uno = {datetime.date.fromisoformat(c): {} for c in _CORTES}
    solo_uno[datetime.date(2025, 12, 31)] = {
        "A": {"score": 60, "banda": None, "tipo": "banca_multiple"}}
    assert con_panel(solo_uno) is None


def test_el_anio_se_mide_de_CIERRE_a_CIERRE(con_panel):
    """El primer corte es el diciembre ANTERIOR: «el año» de una entidad es dic a dic, no
    marzo a diciembre."""
    r = con_panel(_panel({"A": [50, 90, 90, 90, 60], "B": [70, 70, 70, 70, 70]}))
    assert r["cortes"][0].startswith("2024-12")
    # +10 contra el cierre anterior, aunque contra marzo sería −30.
    assert r["conteo_direccion"]["mejora"] == 1


# ── La ruta ────────────────────────────────────────────────────────────

def test_el_anuario_TIENE_una_ruta_que_lo_genera():
    """Registrar el tipo no alcanza: sin endpoint, el producto es inalcanzable. Cada boletín
    de sistema tiene el suyo (`/wire/generate`, `/datawatch/generate`…) y el anuario nació
    sin uno."""
    from modules.banking_score.api import router_reports as rr

    rutas = {r.path for r in rr.router.routes}
    assert any(p.endswith("/anuario/generate") for p in rutas), sorted(rutas)


def test_todo_boletin_de_sistema_narrado_tiene_su_ruta():
    """Regla estructural: el próximo boletín que alguien registre va a tener ruta o va a
    romper este test."""
    from modules.banking_score.api import router_reports as rr

    rutas = " ".join(r.path for r in rr.router.routes)
    faltan = [t for t in sorted(rr._NARRATED_SYSTEM_TYPES)
              if f"/{t.replace('_', '-')}/generate" not in rutas
              and f"/{t}/generate" not in rutas]
    assert not faltan, f"boletines registrados y sin ruta que los genere: {faltan}"


# ── El año tiene que haber CERRADO ─────────────────────────────────────
#
# El defecto que esto cierra era el CAMINO POR DEFECTO de la aplicación. El período del topbar
# arranca en el corte más reciente; con el panel de producción al 2026-03-31, apretar «Anuario
# del sistema» sin tocar el selector pedía el anuario 2026. El motor exigía dos cortes y
# encontraba exactamente dos —la línea base de dic-2025 y marzo—, así que EMITÍA el documento:
# portada «Anuario», sección «El sistema en 2026», y un «cambio del año» que era diciembre a
# marzo. Ninguna cifra falsa; un TRIMESTRE con el encabezado de un año.

def test_un_anio_EN_CURSO_no_produce_anuario(con_panel):
    """Dos cortes alcanzaban, y ése era el problema: el segundo era el primer trimestre."""
    panel = _panel({"A": [70.0, 71.0, None, None, None],
                    "B": [60.0, 62.0, None, None, None]})
    assert con_panel(panel) is None, (
        "un año sin su corte de diciembre salía titulado como año entero")


def test_con_el_cierre_del_anio_SI_se_emite(con_panel):
    """El contrapeso: sin él, la regla se satisface no emitiendo nunca."""
    panel = _panel({"A": [70.0, 71.0, 72.0, 73.0, 74.0],
                    "B": [60.0, 61.0, 62.0, 63.0, 64.0]})
    out = con_panel(panel)
    assert out is not None and out["anio"] == 2025


def test_el_cierre_puede_faltar_EN_EL_MEDIO_sin_vetar(con_panel):
    """Lo que se exige es el cierre del AÑO, no que estén los cuatro trimestres.

    Un trimestre ausente en el medio deja un año igualmente resumible cierre a cierre; exigir
    los cinco cortes sería más estricto de lo que el producto necesita y vetaría años reales.
    """
    panel = _panel({"A": [70.0, None, 72.0, None, 74.0],
                    "B": [60.0, None, 62.0, None, 64.0]})
    assert con_panel(panel) is not None
