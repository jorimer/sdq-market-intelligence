"""Tests del sanitizador de meta-comentario (shared.narrative.sanitize).

Cubre: (1) el artefacto real del bug BPD, (2) variantes de auto-corrección/duda en
español e inglés, (3) tags de razonamiento, (4) — crítico — que NO muerda prosa
financiera legítima donde "espera", "corrección" o "un momento" son palabras reales.
"""
from shared.narrative.sanitize import strip_meta_commentary


# ── El bug real ───────────────────────────────────────────────────────────────
def test_real_bpd_artifact_removed():
    txt = ("El indicador de rentabilidad se ubica en 1.4 %, lo que sitúa a la entidad "
           "por debajo del promedio sectorial… espera —el ROA sectorial es 2.1 %, por "
           "lo que la brecha es de 0.7 puntos.")
    clean, removed = strip_meta_commentary(txt)
    assert "espera —" not in clean
    assert "espera" not in clean.lower().split("promedio sectorial")[-1][:20]
    assert removed, "debió reportar el fragmento removido"
    # las cifras se preservan intactas
    assert "1.4 %" in clean and "2.1 %" in clean and "0.7 puntos" in clean


def test_removed_fragment_is_logged_for_telemetry():
    _, removed = strip_meta_commentary("Texto. wait — no, el dato correcto es 5.")
    assert any("wait" in r.lower() for r in removed)


# ── Variantes de auto-corrección ──────────────────────────────────────────────
def test_variants_spanish_dash():
    for marker in ["espera", "un momento", "corrijo", "me equivoqué",
                   "pensándolo bien", "déjame reconsiderar", "mejor dicho"]:
        txt = f"La solvencia es adecuada {marker} —el ICAP es 16.4 %."
        clean, removed = strip_meta_commentary(txt)
        assert removed, f"no removió: {marker}"
        assert "16.4 %" in clean
        assert "—" not in clean or clean.count("—") < txt.count("—")


def test_variants_english_leak():
    for marker in ["wait", "hold on", "actually", "let me reconsider",
                   "scratch that", "on second thought", "i mean", "oops"]:
        txt = f"The ratio is strong {marker} — the figure is 12.2 %."
        clean, removed = strip_meta_commentary(txt)
        assert removed, f"no removió fuga en inglés: {marker}"
        assert marker.lower() not in clean.lower()
        assert "12.2 %" in clean


def test_comma_form_at_sentence_start():
    txt = "La cartera es sólida. Espera, el dato de mora es 1.67 %."
    clean, removed = strip_meta_commentary(txt)
    assert removed
    assert "1.67 %" in clean
    assert "Espera," not in clean


# ── Tags de razonamiento (defensivo) ──────────────────────────────────────────
def test_reasoning_tag_block():
    txt = "Resumen. <thinking>debo revisar el ROA otra vez</thinking> La entidad es sólida."
    clean, removed = strip_meta_commentary(txt)
    assert "thinking" not in clean.lower()
    assert "revisar el ROA" not in clean
    assert "La entidad es sólida" in clean
    assert removed


def test_bracket_tag_block():
    txt = "Intro. [reasoning] internal note [/reasoning] Conclusión."
    clean, removed = strip_meta_commentary(txt)
    assert "reasoning" not in clean.lower()
    assert "internal note" not in clean
    assert "Conclusión" in clean


def test_stray_tag():
    txt = "Análisis sólido </thinking> con datos del SIB."
    clean, removed = strip_meta_commentary(txt)
    assert "thinking" not in clean.lower()
    assert "datos del SIB" in clean


# ── Auto-referencias del asistente ────────────────────────────────────────────
def test_self_reference_removed():
    txt = ("La entidad muestra solidez. Como modelo de lenguaje, no puedo emitir "
           "juicios definitivos. El ROE es 10.2 %.")
    clean, removed = strip_meta_commentary(txt)
    assert "modelo de lenguaje" not in clean.lower()
    assert "ROE es 10.2 %" in clean
    assert removed


# ── NO falsos positivos: prosa financiera legítima ────────────────────────────
def test_no_false_positive_espera_verb():
    # "espera" como verbo real, sin raya de interrupción → NO se toca
    txt = "El mercado espera una reducción de la tasa de política monetaria en el trimestre."
    clean, removed = strip_meta_commentary(txt)
    assert clean == txt
    assert not removed


def test_no_false_positive_correccion_noun():
    txt = "La corrección del tipo de cambio observada en marzo fue de 2.1 %."
    clean, removed = strip_meta_commentary(txt)
    assert clean == txt
    assert not removed


def test_no_false_positive_a_ver_absent():
    txt = "El comité debe ver la evolución de la cartera vencida antes de decidir."
    clean, removed = strip_meta_commentary(txt)
    assert clean == txt
    assert not removed


def test_no_false_positive_actually_word_absent_in_spanish():
    # prosa española normal no dispara nada
    txt = ("La solvencia (ICAP 16.44 %) supera el mínimo regulatorio; la morosidad de "
           "1.67 % se mantiene por debajo de la mediana del sistema.")
    clean, removed = strip_meta_commentary(txt)
    assert clean == txt
    assert not removed


def test_empty_and_clean_passthrough():
    assert strip_meta_commentary("") == ("", [])
    t = "Texto perfectamente limpio con cifras 12.3 % y 4.5 puntos."
    assert strip_meta_commentary(t) == (t, [])


def test_figures_never_altered():
    txt = "El ROA es 1.4 % espera —2.1 % es el sectorial, y la mora 1.67 %."
    clean, _ = strip_meta_commentary(txt)
    for fig in ["1.4 %", "2.1 %", "1.67 %"]:
        assert fig in clean
