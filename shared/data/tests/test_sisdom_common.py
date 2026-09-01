"""El descubrimiento del SISDOM, después de que el emisor se mudara de host.

Estos tests existen por una rotura REAL del 2026-09-01: ``mepyd.gob.do`` dejó de existir y
el conector no degradó —murió entero—. Al repararlo aparecieron DOS fallas más, y las tres
son de descubrimiento, no de parseo:

1. el listado del host viejo ya no existe;
2. el fragmento del libro de Educación copiaba una **errata del emisor anterior**
   («Indicadore de Educación») y el emisor nuevo escribe bien el título;
3. nueve libros de la misma edición se llaman casi igual, así que un fragmento flojo puede
   calzar más de uno — y elegir en silencio entrega otra área temática.

El fixture ``sisdom_edicion_anclas.html`` son las nueve anclas REALES de la página de la
edición 2025, capturadas el 2026-09-01. No se escribe a mano: un fixture inventado
comprueba que el parser entiende el fixture, no que entiende al emisor.
"""
from pathlib import Path

import pytest

from shared.data.sisdom_common import (
    SisdomUnavailable, discover_book_url, discover_publication,
)

_ANCLAS = (Path(__file__).parent / "fixtures" / "sisdom_edicion_anclas.html").read_text()


# ── Paso 1: qué edición ────────────────────────────────────────────

def test_elige_la_edicion_mas_nueva():
    """Las ediciones conviven en el buscador del emisor y los slugs rotan; clavar uno sería
    atarse a la de hoy, que es exactamente cómo murió el conector de la ONE."""
    payload = [
        {"title": "Sistema de Indicadores Sociales (SISDOM) 2024", "url": "https://x/2024"},
        {"title": "Sistema de Indicadores Sociales (SISDOM) 2025", "url": "https://x/2025"},
    ]
    assert discover_publication(payload) == (2025, "https://x/2025")


def test_ignora_lo_que_no_es_del_sisdom():
    """El buscador devuelve cualquier publicación que mencione el término."""
    payload = [{"title": "Informe de recaudación 2026", "url": "https://x/otro"}]
    assert discover_publication(payload) is None


def test_sin_ediciones_no_inventa_una():
    assert discover_publication([]) is None


# ── Paso 2: qué libro dentro de la edición ─────────────────────────

#: (fragmento declarado por el conector, archivo que debe resolver). Son los fragmentos
#: REALES de los cinco libros que consumimos: si uno deja de calzar —o pasa a calzar dos—,
#: este test lo dice en CI y no en la corrida mensual de producción.
FRAGMENTOS_REALES = [
    ("pobreza y distribucion de ingresos", "Pobreza-y-Distribucion-de-Ingresos"),
    ("indicadores de educacion", "Indicadores-de-Educacion"),
    ("indicadores de salud", "Indicadores-de-Salud"),
    ("indicadores demograficos", "Indicadores-Demograficos"),
    ("area especial end", "Area-Especial-END"),
]


@pytest.mark.parametrize("fragmento,archivo", FRAGMENTOS_REALES)
def test_cada_fragmento_declarado_resuelve_a_un_solo_libro(fragmento, archivo):
    assert archivo in discover_book_url(_ANCLAS, fragmento)


def test_el_barrido_de_fragmentos_no_esta_vacio():
    """Un `parametrize` vacío sale SKIPPED, no FAILED: el barrido lleva al lado la prueba
    de que encontró algo."""
    assert len(FRAGMENTOS_REALES) == 5


def test_los_fragmentos_declarados_son_los_que_usan_los_conectores():
    """Que el test y el conector no se desincronicen: si alguien cambia `BOOK_FRAGMENT` en
    un módulo, la lista de arriba tiene que moverse con él o esto falla."""
    from shared.data import sisdom_child_mortality, sisdom_end, sisdom_income, sisdom_schooling

    declarados = {sisdom_income.BOOK_FRAGMENT, sisdom_schooling.BOOK_FRAGMENT,
                  sisdom_child_mortality.BOOK_FRAGMENT, sisdom_end.BOOK_FRAGMENT}
    assert declarados <= {f for f, _a in FRAGMENTOS_REALES}


def test_un_fragmento_que_calza_dos_libros_se_niega_a_elegir():
    """La falla que un desempate silencioso produciría: entregar «Indicadores de Salud»
    cuando se pidió educación, y que el error aparezca recién en el layout de la hoja."""
    with pytest.raises(SisdomUnavailable, match="calza 5 libros"):
        discover_book_url(_ANCLAS, "indicadores de")


def test_un_fragmento_sin_libro_lo_dice_con_su_nombre():
    with pytest.raises(SisdomUnavailable, match="no se encontró el libro"):
        discover_book_url(_ANCLAS, "indicadore de educacion")   # la errata del emisor viejo
