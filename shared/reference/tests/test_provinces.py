"""Catálogo provincial — integridad del padrón y tolerancia del emparejador.

El emparejador tiene un recurso difuso (prefijo común único) que existe SOLO porque
algunos archivos oficiales llegan con la codificación rota de origen. Estos tests fijan
sus dos mitades: que resuelve lo que debe, y —más importante— que **se niega** cuando la
etiqueta no distingue a un único candidato.
"""
import pytest

from shared.data.one_client import REGIONS
from shared.reference.provinces import (
    PROVINCES,
    province_catalog,
    province_slug,
    region_of,
)


def test_padron_completo_y_sin_duplicados():
    """32 provincias (31 + Distrito Nacional), slugs y nombres únicos."""
    slugs = [s for s, _n, _r in PROVINCES]
    names = [n for _s, n, _r in PROVINCES]
    assert len(PROVINCES) == 32
    assert len(set(slugs)) == 32
    assert len(set(names)) == 32


def test_cada_provincia_pertenece_a_una_region_del_catalogo_de_la_one():
    """La regionalización debe cerrar contra las 10 regiones de desarrollo reales:
    una provincia mapeada a una región inexistente rompería la agregación hacia arriba
    en silencio."""
    region_slugs = {slug for slug, _label in REGIONS}
    for slug, _name, region in PROVINCES:
        assert region in region_slugs, f"{slug} apunta a una región inexistente: {region}"
    # Y las 10 regiones deben estar todas cubiertas: una región sin provincias sería
    # un agujero en el padrón, no una región vacía.
    assert {r for _s, _n, r in PROVINCES} == region_slugs


def test_slugs_provinciales_no_colisionan_con_los_de_region():
    """Ambos niveles conviven en ``sd_indicators.entity_key``: una colisión mezclaría
    una provincia con una región bajo la misma clave."""
    assert not ({s for s, _n, _r in PROVINCES} & {slug for slug, _l in REGIONS})


@pytest.mark.parametrize("label,expected", [
    ("Azua", "azua"),
    ("Distrito Nacional", "distrito_nacional"),
    ("San José de Ocoa", "san_jose_de_ocoa"),
    ("San Jose De Ocoa", "san_jose_de_ocoa"),      # sin acento, casing del proveedor
    ("  santiago  ", "santiago"),                   # espacios de sobra
    ("Elias Pina", "elias_pina"),
    ("Monsenor Nouel", "monsenor_nouel"),
    ("Salcedo", "hermanas_mirabal"),                # nombre anterior a 2007
    ("Baoruco", "bahoruco"),                        # grafía oficial alterna
    ("El Seybo", "el_seibo"),
])
def test_emparejamiento_exacto_y_por_alias(label, expected):
    assert province_slug(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("Dajab›n", "dajabon"),                   # 'ó' perdida por codificación rota
    ("Samanÿ", "samana"),
    ("Santiago Rodr­guez", "santiago_rodriguez"),
])
def test_recurso_difuso_recupera_etiquetas_con_codificacion_rota(label, expected):
    """Casos REALES tomados de los CSV del SIUBEN: el byte del acento no lo recupera
    ninguna decodificación, pero el prefijo sigue siendo único."""
    assert province_slug(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("Santiago, Dominican Republic", "santiago"),
    ("Santiago Rodriguez, Dominican Republic", "santiago_rodriguez"),
    ("Distrito Nacional, Distrito Nacional, Dominican Republic", "distrito_nacional"),
    ("San Juan de la Maguana", "san_juan"),
])
def test_etiqueta_con_cola_no_se_confunde_con_una_provincia_mas_larga(label, expected):
    """Caso REAL de GDELT, y el defecto que casi entra: contra
    ``"Santiago, Dominican Republic"`` el prefijo común favorece a *Santiago Rodríguez*
    (9 caracteres contra 8). El puntaje castiga al candidato que la etiqueta deja a
    medias, y por eso gana *Santiago*."""
    assert province_slug(label) == expected


@pytest.mark.parametrize("label", [
    "",
    None,
    "San",              # prefijo ambiguo: San Cristóbal / San Juan / San Pedro…
    "Santi",            # ambiguo: Santiago / Santiago Rodríguez
    "La",               # ambiguo: La Vega / La Romana / La Altagracia
    "Provincia",
    "Total país",
    "Región Cibao Norte",   # es una REGIÓN, no una provincia
])
def test_se_niega_cuando_la_etiqueta_no_distingue(label):
    """El default es no emparejar. Una fila descartada y contada es recuperable; una
    fila asignada a la provincia equivocada contamina la serie sin dejar rastro."""
    assert province_slug(label) is None


def test_region_of_y_catalogo():
    assert region_of("santo_domingo") == "ozama"
    assert region_of("distrito_nacional") == "ozama"
    assert region_of("provincia_inexistente") is None
    assert len(province_catalog()) == 32
