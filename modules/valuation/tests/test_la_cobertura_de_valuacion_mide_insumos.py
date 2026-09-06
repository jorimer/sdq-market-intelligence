"""La frase de cobertura de valuación dice lo que el eje mide: INSUMOS presentes, no peso
anclado a dato real.

**El defecto, en un informe real.** El Deep Dive de Banco Popular (2026-09-06) decía en §8 y
§12 que el **37 % del Ke es rúbrica** y, nueve páginas después, en la metodología estándar del
framework: «**100 % del índice se construye sobre dato real medido en la fuente**». El
documento se contradecía. `data_signals()` mide la fracción de insumos presentes (3 de 3) con
la semántica por defecto —la de índice—, y esa frase le hace decir algo falso a un eje cuyo
insumo central es un supuesto declarado. Misma familia que el eje de proyecciones (#1117).
"""
from __future__ import annotations

import pytest

from modules.valuation.tests.test_el_entorno_llega_al_informe import _db, _por_http


@pytest.fixture()
def db():
    s = _db()
    yield s
    s.close()


def _texto_de_cobertura(cuerpo) -> str:
    textos = [v for v in cuerpo["narratives"].values() if "Cobertura" in v]
    assert textos, "ninguna sección trae la frase de cobertura"
    return "\n".join(textos)


def test_la_metodologia_estandar_NO_dice_dato_real_del_indice_para_valuacion(db) -> None:
    texto = _texto_de_cobertura(_por_http(db))
    assert "del índice se construye sobre dato real" not in texto, (
        "la metodología estándar afirma «100 % dato real» en un eje cuyo Ke es 37 % rúbrica")
    assert "insumos" in texto and "rúbrica" in texto.lower(), texto[:300]


def test_el_eje_declara_su_semantica_de_cobertura() -> None:
    from modules.valuation.products import ValuationProduct
    from shared.registry.signals import COVERAGE_INPUTS, COVERAGE_KINDS
    assert COVERAGE_INPUTS in COVERAGE_KINDS
    assert ValuationProduct().data_signals().coverage_kind == COVERAGE_INPUTS


def test_la_fraccion_de_rubrica_se_escribe_con_espacio_en_TODO_el_informe(db) -> None:
    """«37%» pegado en §8 y §13 contra «37 %» en §11/§12: la misma cifra con dos formas."""
    import re
    # Las secciones del PRODUCTO: las estándar del framework (glosario: «de 5% a 7%») son
    # otra superficie con su propia forma.
    narr = _por_http(db)["narratives"]
    todo = "\n".join(v for k, v in narr.items() if not k.startswith("std_"))
    pegados = re.findall(r"\d%", todo)
    assert not pegados, f"porcentajes pegados: {pegados[:5]}"
