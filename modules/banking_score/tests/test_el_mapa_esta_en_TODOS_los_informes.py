"""El mapa sectorial llega a TODOS los informes de banca, no a uno.

**Lo que pasó.** El cubo de créditos —21 trimestres × 41 entidades × 19 sectores × 33
provincias × 21 medidas— se construyó para que los informes dijeran algo que un banco con la
API de la SIB no puede decir. Se cableó al trimestral y ahí se dio por terminado. Los dos
productos ANUALES —la Revisión Anual y el año por trimestres— y los boletines de SISTEMA
salieron sin él, y nadie lo notó hasta que el dueño comparó tres PDFs y ninguno traía la
sección. El activo estaba en la base; lo que faltaba era la distribución.

Es la regla del repo —«un tipo NUEVO se registra en TODAS sus superficies»— aplicada al
revés: no era un tipo nuevo el que faltaba registrar, era una SECCIÓN nueva que había que
llevar a todos los tipos existentes. La lección escrita no cubría ese sentido; este test sí.

**Las DOS lecturas del mismo cubo.** `mapa_sectorial` compara a una ENTIDAD contra el resto
del sistema sector por sector; `mapa_sectorial_sistema` abre el libro del PAÍS. El sujeto
decide cuál corresponde: pedirle a un boletín de sistema la lectura de entidad produce una
sección sobre alguien que el documento no nombra.
"""

import pytest

from modules.banking_score.reports.narrative import (
    _CEREBRO_TEMPLATES, _SECTION_TO_TEMPLATE, REPORT_SECTIONS,
)
from modules.banking_score.reports.pdf_generator import NARRATIVE_SECTION_TITLES
from shared.narrative.claude_engine import THIN_TEMPLATES

#: Informes cuyo sujeto es una ENTIDAD y que analizan su cartera: les toca la lectura de
#: entidad. `scorecard` queda fuera a propósito —es el resumen de dos secciones— y los
#: boletines de sistema tienen su propia lectura.
CON_LECTURA_DE_ENTIDAD = ("full_rating", "revision_anual")

#: Informes cuyo sujeto es el SISTEMA.
CON_LECTURA_DE_SISTEMA = ("anuario", "sector_outlook")


@pytest.mark.parametrize("tipo", CON_LECTURA_DE_ENTIDAD)
def test_los_informes_de_ENTIDAD_traen_su_mapa(tipo):
    assert "mapa_sectorial" in REPORT_SECTIONS[tipo], (
        f"«{tipo}» sale sin la única sección que exige el libro de las otras noventa y una "
        f"entidades — que es la razón por la que existe el cubo")


@pytest.mark.parametrize("tipo", CON_LECTURA_DE_SISTEMA)
def test_los_informes_de_SISTEMA_traen_el_libro_del_pais(tipo):
    assert "mapa_sectorial_sistema" in REPORT_SECTIONS[tipo]


@pytest.mark.parametrize("tipo", CON_LECTURA_DE_SISTEMA)
def test_un_informe_de_sistema_NO_lleva_la_lectura_de_entidad(tipo):
    """Su contexto no tiene entidad: la plantilla de entidad escribiría sobre alguien que el
    documento no nombra."""
    assert "mapa_sectorial" not in REPORT_SECTIONS[tipo]


@pytest.mark.parametrize("clave,titulo", [
    ("mapa_sectorial", "Mapa Sectorial del Crédito"),
    ("mapa_sectorial_sistema", "El Crédito del Sistema por Sector"),
])
def test_cada_lectura_tiene_plantilla_PROPIA_titulo_y_ruta_cerebro(clave, titulo):
    plantilla = _SECTION_TO_TEMPLATE[clave]
    assert plantilla in THIN_TEMPLATES, "la plantilla no existe: caería al relleno estático"
    assert plantilla in _CEREBRO_TEMPLATES, "iría por la ruta legacy y saldría hueca"
    assert NARRATIVE_SECTION_TITLES[clave] == titulo


def test_las_dos_lecturas_NO_comparten_plantilla():
    """Compartirla ahorraría un archivo y produciría un anuario que habla de «la entidad»."""
    assert _SECTION_TO_TEMPLATE["mapa_sectorial"] != _SECTION_TO_TEMPLATE[
        "mapa_sectorial_sistema"]


def test_la_plantilla_del_sistema_le_PROHIBE_nombrar_una_entidad():
    thin = THIN_TEMPLATES[_SECTION_TO_TEMPLATE["mapa_sectorial_sistema"]]
    assert "EL SUJETO ES EL SISTEMA" in thin
    assert "no nombres a ninguno" in thin


class TestLosProductosDelCatalogo:
    """El catálogo emite por su propio camino —snapshot + narratives + render—, no por la
    ruta de informes. Un cableado que solo toque `REPORT_SECTIONS` deja los productos
    afuera, que es exactamente lo que había pasado."""

    def test_el_deep_dive_TRIMESTRAL_lo_declara(self):
        from modules.banking_score.products import _DEEP_DIVE_SECTIONS
        assert "mapa_sectorial" in _DEEP_DIVE_SECTIONS

    def test_el_deep_dive_ANUAL_lo_declara(self):
        from shared.products.tiers import ProductTier
        from modules.banking_score.products_year_review import year_review_manifest
        secs = year_review_manifest().levels[ProductTier.deep_dive].sections
        assert "mapa_sectorial" in secs

    def test_el_anual_declara_la_plantilla_JUNTO_a_la_seccion(self):
        """`narrative_templates` y `sections` viajan en paralelo en este manifiesto: agregar
        una sección sin su plantilla las desalinea y el gate de cobertura no lo mira."""
        from shared.products.tiers import ProductTier
        from modules.banking_score.products_year_review import year_review_manifest
        lv = year_review_manifest().levels[ProductTier.deep_dive]
        assert len(lv.sections) == len(lv.narrative_templates)
        assert "banking_sector_map" in lv.narrative_templates

    def test_el_ANIO_POR_TRIMESTRES_computa_su_mapa(self):
        """El otro producto anual: lee el año por dentro y la composición del libro por
        sector es parte de ese adentro."""
        import inspect
        from modules.banking_score import products
        src = inspect.getsource(products.BankingProduct.snapshot)
        assert "posicion_de_la_entidad" in src and "anio_por_trimestres" in src

    def test_la_muestra_del_ANUAL_trae_el_mapa_y_su_prosa(self):
        from shared.products.tiers import ProductTier
        from modules.banking_score.products_year_review import (
            BankingYearReviewProduct, _sample_payload,
        )
        assert _sample_payload(ProductTier.deep_dive).get("mapa_sectorial")
        narr = BankingYearReviewProduct(None).sample_narratives(ProductTier.deep_dive)
        assert narr.get("mapa_sectorial"), (
            "la muestra del anual saldría con la sección vacía: es la pieza de conversión")


def test_el_barrido_encontro_los_tipos():
    """Una aserción de presencia sobre una lista vacía pasa sola."""
    assert set(CON_LECTURA_DE_ENTIDAD) | set(CON_LECTURA_DE_SISTEMA) <= set(REPORT_SECTIONS)
