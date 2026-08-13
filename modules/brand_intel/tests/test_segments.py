"""Las dos dimensiones del corte: la población y el atributo.

Los tres defectos que estas pruebas cierran salieron del mazo REAL de Ola 5 en producción:
«Santo Domingo» guardado de tres formas (166 celdas partidas en tres series), el enunciado de
la pregunta metido en el campo del corte (12 formas), y 144 celdas de índice de atributo
cayendo en una sola coordenada porque el atributo no tenía dónde vivir.
"""
import pytest

from modules.brand_intel.engines import segments as seg
from modules.brand_intel.engines import validation as val


# ── una población, una escritura ───────────────────────────────────────

@pytest.mark.parametrize("impreso", ["SD", "sd", "Sto. Domingo", "STO DOMINGO",
                                     "Santo Domingo", "santo domingo"])
def test_the_same_place_always_resolves_to_one_form(impreso):
    conocidos = ["total", "santo domingo", "santiago"]
    assert seg.resolve_segment(impreso, conocidos) == "santo domingo"


@pytest.mark.parametrize("impreso", ["ST", "Stgo", "SGO", "Santiago", "santiago"])
def test_santiago_too(impreso):
    assert seg.resolve_segment(impreso, ["total", "santo domingo", "santiago"]) == "santiago"


def test_what_the_engagement_already_writes_wins_over_our_alias_table():
    """Si el encargo viene escribiendo el corte de una forma, una entrega nueva cae ahí y no
    abre una segunda. La tabla de alias es una ayuda, no la autoridad."""
    assert seg.resolve_segment("SD", ["Santo Domingo"]) == "Santo Domingo"
    assert seg.resolve_segment("sd", []) == "santo domingo"     # sin nada, el alias


def test_an_unknown_cut_is_kept_not_forced():
    """Un corte que no conocemos se normaliza y se guarda; no se fuerza al más parecido."""
    assert seg.resolve_segment("Puerto Plata", ["santo domingo"]) == "puerto plata"
    assert seg.resolve_segment("  NSE  BC+ ", []) == "bc+"


def test_ambiguity_is_refused():
    """«Santo» prefija a dos cortes conocidos: no se elige ninguno, se guarda tal cual."""
    salida = seg.resolve_segment("Santo", ["santo domingo", "santo cerro"])
    assert salida == "santo"


def test_empty_is_total_not_none():
    for vacio in (None, "", "   "):
        assert seg.resolve_segment(vacio) == "total"


# ── el atributo es una dimensión, no un pedazo del corte ───────────────

def test_the_statement_packed_with_a_bar_is_split_into_its_two_dimensions():
    atributo, corte = seg.normalize_cut("calidad de la comida | sd",
                                        ["total", "santo domingo"])
    assert atributo == "calidad de la comida"
    assert corte == "santo domingo"


def test_a_bar_with_total_on_the_right_still_yields_the_attribute():
    atributo, corte = seg.normalize_cut("tiempo de entrega de su pedido | total")
    assert atributo == "tiempo de entrega de su pedido"
    assert corte == "total"


def test_a_plain_cut_has_no_attribute():
    assert seg.normalize_cut("santiago", ["santiago"]) == (None, "santiago")


# ── la clave de conflicto distingue por atributo ───────────────────────

def _celda(attr, valor, key):
    return val.Cell(key=key, metric_code="attribute_index", value=valor,
                    wave_code="2026-06", brand_slug="mcdonalds", segment="total",
                    attribute=attr)


def test_two_attributes_of_one_grid_are_not_a_contradiction():
    """El defecto exacto de la lámina 32: ocho atributos × dieciocho marcas caían en la
    misma coordenada y el detector los declaraba contradictorios entre sí. Con el atributo
    en la clave, son mediciones distintas y ninguna se marca."""
    celdas = [_celda("hamburguesas deliciosas", 87.0, "a"),
              _celda("café", 181.0, "b"),
              _celda("precio", 104.0, "c")]
    val.check_internal_duplicates(celdas)
    assert [c.validation for c in celdas] == [val.UNCHECKED] * 3


def test_the_same_attribute_read_twice_with_different_numbers_still_conflicts():
    """La corroboración no se pierde: el MISMO atributo con dos cifras sigue siendo un
    conflicto real, que es para lo que el detector existe."""
    celdas = [_celda("café", 181.0, "a"), _celda("café", 174.0, "b")]
    val.check_internal_duplicates(celdas)
    assert all(c.validation == val.CONFLICT for c in celdas)
    assert "valores distintos" in celdas[0].validation_note


def test_the_same_attribute_read_twice_agreeing_is_corroboration():
    celdas = [_celda("café", 181.0, "a"), _celda("café", 181.0, "b")]
    val.check_internal_duplicates(celdas)
    assert all(c.validation == val.PASSED for c in celdas)


# ── la reparación de lo YA extraído, sin releer el mazo ────────────────


def test_renormalize_repairs_what_it_can_and_declares_what_it_cannot(db, engagement):
    """La prueba que importa del tercer arreglo: recanoniza sin pagar otra lectura, y NO
    finge haber resuelto el atributo que el lector nunca emitió."""
    from modules.brand_intel.ingest.pdf_pipeline import renormalize_staged
    from modules.brand_intel.models.models import (
        BrandExtraction, BrandExtractionCell)

    ext = BrandExtraction(engagement_id=engagement.id, document_name="mazo.pdf",
                          status="validated", n_pages=3, pages_done=3)
    db.add(ext)
    db.flush()

    def celda(segmento, metric="reach_1m", valor=50.0, attr=None):
        db.add(BrandExtractionCell(
            extraction_id=ext.id, engagement_id=engagement.id, page_number=1,
            wave_code="w1", brand_slug="focal", metric_code=metric,
            segment=segmento, attribute=attr, value=valor, unit="pct"))

    celda("sd")                                   # inicial → canónica
    celda("Sto. Domingo", valor=51.0)             # abreviatura → la misma
    celda("santo domingo", valor=52.0)            # ya canónica
    celda("calidad de la comida | st", metric="attribute_index", valor=90.0)
    celda("total", metric="attribute_index", valor=87.0)   # sin atributo: NO reparable
    celda("total", metric="attribute_index", valor=104.0)  # idem
    db.flush()

    out = renormalize_staged(db, ext, known_segments=["total", "santo domingo", "santiago"])

    assert out["celdas"] == 6
    assert out["cortes_recanonizados"] == 3        # sd, Sto. Domingo y el «| st»
    assert out["atributos_recuperados"] == 1       # el empaquetado con barra
    # Lo que NO se puede reparar se DECLARA, en vez de dejar creer que quedó listo.
    assert out["sin_atributo_recuperable"] == 2

    filas = db.query(BrandExtractionCell).filter(
        BrandExtractionCell.extraction_id == ext.id).all()
    cortes = sorted({str(f.segment) for f in filas})
    assert cortes == ["santiago", "santo domingo", "total"]
    assert "sd" not in cortes and "sto domingo" not in cortes
    # Las tres de Santo Domingo tenían valores distintos: eso SÍ es un conflicto real y
    # ahora se ve, porque antes estaban repartidas en tres cortes y ninguna se comparaba.
    assert out["validacion"]["conflict"] >= 3


# ── el atributo en SU PROPIO campo, que es el camino del esquema nuevo ──
#
# La prueba que faltaba y costó una relectura completa del mazo en producción: 247 celdas
# volvieron sin atributo porque `normalize_cut` recibía el texto suelto del campo dedicado y
# lo devolvía como CORTE. Los tests cubrían la forma empaquetada y el corte a secas —las dos
# que yo tenía en la cabeza— y nunca el camino que el esquema nuevo estrenaba.


def test_an_attribute_in_its_own_field_survives():
    a, s = seg.normalize_dimensions("hamburguesas deliciosas", "total", ["total"])
    assert a == "hamburguesas deliciosas"
    assert s == "total"


def test_the_attribute_field_wins_and_the_cut_is_still_canonised():
    a, s = seg.normalize_dimensions("café", "SD", ["total", "Santo Domingo"])
    assert a == "café"
    assert s == "Santo Domingo"          # el corte se canoniza aparte, no se pisa


def test_an_empty_attribute_field_falls_back_to_unpacking_the_cut():
    """Compatibilidad hacia atrás: lo que llegaba empaquetado sigue funcionando."""
    for vacio in (None, "", "   "):
        a, s = seg.normalize_dimensions(vacio, "calidad de la comida | st",
                                        ["total", "santiago"])
        assert (a, s) == ("calidad de la comida", "santiago")


def test_no_attribute_anywhere_is_none_not_empty_string():
    a, s = seg.normalize_dimensions(None, "santiago", ["santiago"])
    assert a is None and s == "santiago"


def test_normalize_cut_alone_would_have_lost_it():
    """Fija el porqué de la función nueva: la vieja, con el texto suelto, lo pierde. Si
    alguien vuelve a llamar a `normalize_cut` con el campo dedicado, este test explica el
    defecto que reintrodujo."""
    a, s = seg.normalize_cut("hamburguesas deliciosas", [])
    assert a is None                                    # el atributo desaparece…
    assert s == "hamburguesas deliciosas"               # …y contamina el corte


def test_every_ingest_route_keeps_an_attribute_that_arrives_in_its_field():
    """La REGLA sobre las tres rutas, no sobre una: mazo, plantilla y recanonización usan
    la misma entrada, así que ninguna puede volver a perderlo por su cuenta."""
    import inspect

    from modules.brand_intel.ingest import excel_ingest, pdf_pipeline

    fuentes = {
        "mazo/recanonización": inspect.getsource(pdf_pipeline),
        "plantilla": inspect.getsource(excel_ingest),
    }
    for nombre, fuente in fuentes.items():
        assert "normalize_dimensions" in fuente, nombre
        # `normalize_cut` con el campo dedicado es justo el defecto: ninguna ruta lo llama.
        assert "normalize_cut(" not in fuente, (
            f"{nombre} volvió a usar normalize_cut: pierde el atributo del campo dedicado")
