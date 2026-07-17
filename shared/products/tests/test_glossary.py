"""Tests del glosario automático (detección de términos en texto redactado).

La parte más frágil es la lógica de ``\\b`` con símbolos en el borde ("IC 90%") y la
case-sensitivity condicionada a siglas — cada caso de abajo blinda una de esas aristas.
"""
from shared.products.glossary import GLOSSARY, glossary_markdown


def test_detects_only_terms_present_in_order():
    # (a) texto con ISF y HHI → exactamente esas 2 entradas, en el orden del catálogo.
    text = "El ISF del sistema sube; el HHI confirma un mercado concentrado."
    md = glossary_markdown(text)
    lines = md.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("- **ISF**")
    assert lines[1].startswith("- **HHI**")
    # Orden = orden de definición en GLOSSARY (ISF va antes que HHI en el catálogo).
    keys = list(GLOSSARY)
    assert keys.index("ISF") < keys.index("HHI")


def test_no_known_terms_returns_empty_string():
    # (b) el llamador nunca debe imprimir un glosario vacío.
    assert glossary_markdown("Texto sin ninguna sigla del catálogo.") == ""
    assert glossary_markdown("") == ""


def test_lowercase_terms_match_case_insensitive():
    # (c) "Backtest" capitalizado al inicio de oración matchea `backtest`.
    md = glossary_markdown("Backtest honesto contra la historia disponible.")
    assert "- **backtest**" in md


def test_term_with_trailing_symbol_matches():
    # (d) "IC 90%" seguido de coma o cierre de paréntesis — el caso `\b` + símbolo:
    # entre '%' y ',' no hay frontera de palabra, el patrón no debe exigirla ahí.
    assert "- **IC 90%**" in glossary_markdown("la banda (IC 90%), estable")
    assert "- **IC 90%**" in glossary_markdown("proyección con IC 90%.")


def test_word_boundary_no_false_positive_inside_words():
    # (e) "app" NO dispara la entrada de "pp" (borde de palabra en ambos extremos).
    assert glossary_markdown("la app móvil del banco") == ""


def test_uppercase_sigla_is_case_sensitive():
    # "one" en minúscula (palabra inglesa cualquiera) NO dispara la entrada de la ONE.
    assert glossary_markdown("this is one example") == ""
    assert "- **ONE**" in glossary_markdown("según la ONE, la informalidad bajó")


def test_definitions_do_not_use_the_term_itself():
    # Doctrina del catálogo: la definición no usa el término dentro de sí misma.
    for term, definition in GLOSSARY.items():
        assert term.casefold() not in definition.casefold(), (
            f"La definición de '{term}' usa el propio término")


def test_short_units_are_case_sensitive():
    # Fix del reviewer: "PP"/"PB" en mayúsculas (siglas ajenas al catálogo) NO
    # disparan las unidades pp/pb; las unidades en minúscula sí calzan.
    assert glossary_markdown("El PP ganó las elecciones") == ""
    assert "- **pp**" in glossary_markdown("la tasa sube 2 pp interanual")
