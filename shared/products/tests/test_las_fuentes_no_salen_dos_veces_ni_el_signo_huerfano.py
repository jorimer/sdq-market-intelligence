"""Dos defectos de la ANATOMÍA del informe, los dos compartidos por todos los productos.

**1 · Las fuentes salían dos veces.** `_methodology_md` las lista inline —«Fuentes de dato:
BCRD — IMAE, …»— y `_sources_md` las repite en viñetas cuatro líneas después. Las dos desde
`sig.sources`, o sea el mismo dato dos veces en la misma página. No es de un producto: alcanza
a TODO producto servido en deep dive que declare fuentes, por construcción.

El detalle que impide la cura fácil: `_TIERS_WITH_SOURCES` es solo deep dive, mientras la
metodología se sirve también en insight. Borrar la lista inline dejaría a insight SIN fuentes
en ninguna parte, que es peor que repetirlas. La lista inline tiene que salir **solo cuando la
sección de fuentes no va a renderizarse** — o sea que la metodología necesita saber su nivel,
que hasta ahora no recibía.

**2 · El signo se separaba de su número al saltar de línea.** «una variación de 0.38 \\n%
contra…» — el número en una línea y su unidad en la siguiente. Es el defecto de forma que ya
pagamos con los glifos de subíndice: se ve en el PDF que se vende, no en ningún test.

La cura usa el mecanismo que este repositorio YA tiene funcionando —la entidad `&nbsp;` de
ReportLab, con la que se arman las viñetas y la numeración— y no un carácter nuevo sin probar.
En el Word va el carácter U+00A0, que es lo que Word entiende.
"""
import pytest

from shared.products import ProductTier
from shared.products.contract import DataHealth

FUENTES = ("BCRD — IMAE, PIB por sectores de origen, TPM",
           "SDQ — ledger de pronósticos (mm_forecast_log)")


class _Producto:
    """El mínimo que `standard_sections` necesita: declara fuentes y nada más."""

    sector_key = "prueba"

    def data_signals(self):
        return DataHealth(coverage=0.9, freshness_days=0, cadence="quarterly",
                          sources=FUENTES, detail="dos fuentes")

    def validation_state(self):
        return None


# ── 1 · las fuentes, una sola vez ───────────────────────────────────────────────────

def test_en_DEEP_DIVE_las_fuentes_no_se_listan_DOS_veces():
    """La sección de fuentes las publica en viñetas; la metodología no tiene que repetirlas."""
    from shared.products.report_sections import METHODOLOGY_KEY, SOURCES_KEY, standard_sections

    secs = standard_sections(_Producto(), ProductTier.deep_dive, as_of="2026-09-05")
    metodo, fuentes = secs.get(METHODOLOGY_KEY, ""), secs.get(SOURCES_KEY, "")
    assert fuentes, "deep dive tiene que traer la sección de fuentes"
    for f in FUENTES:
        assert f in fuentes, f"«{f}» no está en la sección de fuentes"
        assert f not in metodo, (
            f"«{f}» sale DOS veces en el mismo informe: inline en Metodología y en viñetas "
            "en Fuentes")


def test_en_INSIGHT_las_fuentes_SIGUEN_saliendo():
    """Insight no lleva sección de fuentes: si se borra la lista inline, desaparecen.

    Es el modo de falla que convierte «arreglé una repetición» en «borré el dato». La regla
    no es «nunca inline» sino «inline solo si la sección no va a salir».
    """
    from shared.products.report_sections import METHODOLOGY_KEY, SOURCES_KEY, standard_sections

    secs = standard_sections(_Producto(), ProductTier.insight, as_of="2026-09-05")
    assert not secs.get(SOURCES_KEY), "insight no debería traer sección de fuentes"
    metodo = secs.get(METHODOLOGY_KEY, "")
    for f in FUENTES:
        assert f in metodo, (
            f"«{f}» no sale en NINGUNA parte del informe de insight: la cura borró el dato "
            "en vez de la repetición")


# ── 2 · el signo no se separa de su número ──────────────────────────────────────────

@pytest.mark.parametrize("crudo, esperado", [
    ("una variación de 0.38 % contra", "0.38&nbsp;%"),
    ("aporta 0.287 pp al agregado", "0.287&nbsp;pp"),
    ("cae -3.536 pp por actividad", "-3.536&nbsp;pp"),
    ("el 100 % del índice", "100&nbsp;%"),
])
def test_el_numero_no_se_separa_de_su_unidad(crudo, esperado):
    """`&nbsp;` es la entidad que ReportLab ya usa en este repo para viñetas y numeración."""
    from shared.products.render import _inline

    assert esperado in _inline(crudo), f"{crudo!r} → {_inline(crudo)!r}"


def test_la_entidad_no_queda_ESCAPADA():
    """El escape de `&` corre en `_inline`: insertar `&nbsp;` antes lo volvería `&amp;nbsp;`.

    Un `&amp;nbsp;` se dibuja LITERAL en el PDF —el cliente lee «0.38&nbsp;%»— que es peor
    que el defecto que vino a arreglar.
    """
    from shared.products.render import _inline

    salida = _inline("una variación de 0.38 % y A & B")
    assert "&amp;nbsp;" not in salida, salida
    assert "&amp;" in salida, "el escape de un `&` de verdad tiene que seguir ocurriendo"


def test_en_el_WORD_va_el_CARACTER_no_la_entidad():
    """Word no interpreta entidades de ReportLab: `&nbsp;` saldría literal en el .docx."""
    from shared.products.render_docx import _texto_sin_cortes

    salida = _texto_sin_cortes("una variación de 0.38 % contra")
    assert " %" in salida, repr(salida)
    assert "&nbsp;" not in salida, salida


def test_la_seccion_SIGUE_cumpliendo_su_titulo():
    """Se llama «Metodología y fuentes»: no puede quedarse sin decir nada de las fuentes.

    Borrar la lista y dejar el título habría sido cambiar una repetición por una promesa
    incumplida. Y renombrar el título tampoco: vive en SIETE superficies —backend, el motor
    de research, los tres i18n y dos pantallas— sin ningún guard de paridad, que es
    exactamente el modo de falla de «un tipo nuevo se registra en todas sus superficies».
    El puntero cuesta una línea y no repite ningún nombre.
    """
    from shared.products.report_sections import (
        METHODOLOGY_KEY, STANDARD_SECTION_TITLES, standard_sections,
    )

    assert "fuentes" in STANDARD_SECTION_TITLES[METHODOLOGY_KEY].lower()
    metodo = standard_sections(_Producto(), ProductTier.deep_dive,
                               as_of="2026-09-05")[METHODOLOGY_KEY]
    assert "**Fuentes de dato:**" in metodo, metodo
    assert "Fuentes y referencias" in metodo, (
        "la sección no dice dónde están las fuentes que su título promete")


def test_el_puntero_CONCUERDA_con_cuantas_fuentes_hay():
    """«Las 1 fuentes» es de las cosas que hacen que un informe se lea como generado."""
    from shared.products.contract import DataHealth
    from shared.products.report_sections import METHODOLOGY_KEY, standard_sections

    class _Una(_Producto):
        def data_signals(self):
            return DataHealth(coverage=0.9, freshness_days=0, cadence="quarterly",
                              sources=("BCRD — IMAE",), detail="una")

    metodo = standard_sections(_Una(), ProductTier.deep_dive,
                               as_of="2026-09-05")[METHODOLOGY_KEY]
    assert "La fuente que respalda" in metodo, metodo
    assert "Las 1" not in metodo
