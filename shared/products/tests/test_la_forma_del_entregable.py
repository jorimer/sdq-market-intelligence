"""Tres defectos de FORMA del PDF que se vende. Los tres se ven en el documento y en ningún test.

**A · La portada rotulaba «Período» sobre un corte de información.** `render_product_pdf`
imprime `**Período:** {period}` con lo que el producto declare. Medido contra los 18 ejes del
catálogo en producción, cuatro pasan una fecha completa — pero `banking` (2026-06-30), `macro`
(2025-12-31) y `monetary_policy` (2026-07-31) son CIERRES de período y bajo ese rótulo se leen
bien. El único mal rotulado es `macro_forecast` (2026-09-06), que no es un cierre sino el
corte de información, y su propia metodología ya lo llama «Corte del informe».

**B · El informe citaba una serie por la ruta de la hoja de cálculo.** La tabla publicaba
`bcrd.xls.pib_2018.serie_original_indice`. El mecanismo existía y la doctrina estaba escrita
en `canonical.CURATED_LABELS`: lo no-curado se declara así «para que un informe no lo cite por
la ruta de la hoja de cálculo». Nada lo vigilaba.

**C · Los subíndices salían como cajas negras.** Medido renderizando cada familia: los
subíndices fallan TODOS y los superíndices salvo ¹²³; el griego, la matemática, las flechas y
la tipografía renderizan bien. O sea que `BV₀` y `λ₁` fallaban por el subíndice, no por la λ.

La cura no es transliterar (pierde la forma) ni cambiar la fuente (cambia el aspecto de TODOS
los informes): ReportLab entiende `<sub>`/`<super>` y con la fuente que ya hay dibuja un
subíndice de verdad.
"""
import pytest

# ── C · los subíndices y superíndices ───────────────────────────────────────────────

@pytest.mark.parametrize("crudo, esperado", [
    ("BV₀ es el valor libro", "BV<sub>0</sub>"),
    ("λ₁ se elige por verosimilitud", "<sub>1</sub>"),
    ("λ₂ = 1 lo impone el prior", "<sub>2</sub>"),
    ("RI_t sobre BV₋₁", "<sub>-1</sub>"),
    ("el m³ de gas", "m<super>3</super>"),
    ("x⁴ y x⁹", "x<super>4</super>"),
])
def test_los_indices_se_convierten_a_marcado_que_la_fuente_SI_dibuja(crudo, esperado):
    """Sin esto la fuente del renderer los dibuja como ■: verificado en el PDF."""
    from shared.products.render import _inline

    assert esperado in _inline(crudo), f"{crudo!r} → {_inline(crudo)!r}"


def test_no_queda_NINGUN_indice_unicode_sin_convertir():
    """El barrido: si mañana alguien escribe ₅ en la prosa, no puede llegar crudo al PDF."""
    from shared.products.render import _inline

    todos = "₀₁₂₃₄₅₆₇₈₉₊₋ ⁰⁴⁵⁶⁷⁸⁹"
    salida = _inline(f"prueba {todos} fin")
    for ch in todos.replace(" ", ""):
        assert ch not in salida, f"{ch!r} llegó crudo al marcado: {salida!r}"


def test_el_marcado_no_queda_ESCAPADO():
    """`_inline` escapa `<` y `>`: insertar el marcado antes lo volvería `&lt;sub&gt;`."""
    from shared.products.render import _inline

    salida = _inline("BV₀ y un < de verdad")
    assert "<sub>0</sub>" in salida, salida
    assert "&lt;" in salida, "el escape de un `<` de verdad tiene que seguir ocurriendo"


def test_en_el_WORD_va_FORMATO_de_run_y_no_marcado():
    """Word no interpreta `<sub>`: lo dibujaría literal. Ahí el subíndice es una propiedad."""
    from shared.products.render_docx import _partir_por_indices

    partes = _partir_por_indices("BV₀ y x⁴")
    assert ("0", "sub") in [(t, k) for t, k in partes if k], partes
    assert ("4", "super") in [(t, k) for t, k in partes if k], partes
    assert "".join(t for t, _k in partes) == "BV0 y x4", partes


# ── A · el rótulo de la portada ─────────────────────────────────────────────────────

def test_la_portada_puede_rotular_su_periodo_por_lo_que_ES(tmp_path):
    """«Período: 2026-09-06» describe mal un corte de información."""
    from shared.products.render import render_product_pdf

    p = render_product_pdf(
        sector_key="x", display_name="X", title="X", period="2026-09-06",
        period_label="Corte", narratives={"s": "cuerpo"}, section_titles={"s": "S"},
        output_dir=str(tmp_path))
    texto = _texto_del_pdf(p)
    assert "Corte: 2026-09-06" in texto, texto[:400]
    assert "Período: 2026-09-06" not in texto, texto[:400]


def test_el_rotulo_por_defecto_NO_cambia(tmp_path):
    """Los ejes que pasan un período de verdad tienen que seguir diciendo «Período»."""
    from shared.products.render import render_product_pdf

    p = render_product_pdf(
        sector_key="x", display_name="X", title="X", period="2026-Q2",
        narratives={"s": "cuerpo"}, section_titles={"s": "S"}, output_dir=str(tmp_path))
    assert "Período: 2026-Q2" in _texto_del_pdf(p)


def test_el_eje_de_proyecciones_rotula_su_corte():
    """Y lo llama igual que su propia metodología, que ya decía «Corte del informe»."""
    import app.main  # noqa: F401
    from modules.macro_monitor import products_forecast as pf

    assert pf.ROTULO_DEL_PERIODO == "Corte"


def _texto_del_pdf(path: str) -> str:
    import subprocess

    return subprocess.run(["pdftotext", "-layout", path, "-"],
                          capture_output=True, text=True).stdout


# ── B · nunca la ruta de la hoja de cálculo ─────────────────────────────────────────

def test_la_serie_del_PIB_tiene_etiqueta_curada():
    """`is_curated` la daba False y el informe la citaba igual, por su ruta de Excel."""
    from shared.data.bcrd_excel.canonical import curated_label, is_curated

    code = "bcrd.xls.pib_2018.serie_original_indice"
    assert is_curated(code), f"«{code}» no está curada y el informe la publica"
    assert curated_label(code), "sin etiqueta legible no hay qué publicar en su lugar"


def _prosa_del_producto():
    """Todas las funciones de prosa del eje, barridas — no una lista escrita a mano.

    Mi primer guard miraba DOS funciones y el defecto vivía en una tercera: la sección de
    Desempeño publicaba la serie cruda y el PDF real la mostró. Una lista a mano protege lo
    que uno se acordó de poner.
    """
    import inspect

    from modules.macro_monitor import products_forecast as pf

    p = pf._SAMPLE_PAYLOAD
    salida = {}
    for nombre, fn in vars(pf).items():
        if not (nombre.startswith("_md_") and inspect.isfunction(fn)):
            continue
        try:
            salida[nombre] = str(fn(p))
        except Exception as e:  # noqa: BLE001 — se declara, no se saltea en silencio
            salida[nombre] = f"<<no se pudo renderizar: {e}>>"
    salida["_titular_de"] = str(pf._titular_de(None, p.get("proyecciones") or []) or "")
    return salida


def test_el_barrido_de_prosa_ENCUENTRA_funciones():
    """Un barrido vacío pasa solo. Éste es su testigo."""
    prosa = _prosa_del_producto()
    assert len(prosa) >= 6, sorted(prosa)
    rotas = {k: v for k, v in prosa.items() if v.startswith("<<no se pudo")}
    assert not rotas, f"el barrido no pudo renderizar: {rotas}"


def test_la_prosa_del_informe_no_cita_una_ruta_de_hoja_de_calculo():
    """El guard sobre la superficie, no sobre el mapa: lo que importa es lo que se imprime."""

    for nombre, md in sorted(_prosa_del_producto().items()):
        assert "bcrd.xls." not in md, (
            f"«{nombre}» cita una serie por la ruta de la hoja de cálculo:\n{md[:300]}")
