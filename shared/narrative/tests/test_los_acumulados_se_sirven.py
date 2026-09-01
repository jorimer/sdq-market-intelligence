"""Una SUMA de cifras servidas también es una relación, y las relaciones se computan.

**El caso (2026-09-01).** El mapa del sistema servía 33 provincias con su peso individual y
ningún acumulado. La narrativa del anuario escribió «ambas jurisdicciones metropolitanas
concentran el **68,32 %** del crédito del sistema» — que es 54,64 + 13,68 al corte
2025-12-31, hecho a mano. El guard la marcó, con razón: el número no estaba servido.

**Acertó, y eso es suerte, no método.** En comercio, con la misma cuenta, el modelo sacó
**42,2 cuando el dato era 42,3** — ni la suma real ni la de los porcentajes ya redondeados,
sino un tercer número.

**Y prohibirlo no alcanzó.** La plantilla de la entidad ya decía «NO SUMES NI PROMEDIES
PORCENTAJES» y hasta documentaba un caso anterior («el 48,39 %»), y la marca volvió a
aparecer. Es la lección de este repo: la reconciliación va en el DATO, no en una oración más.
"""
import pytest

from shared.narrative.derived import concentracion_top_n

#: Las provincias REALES del corte 2025-12-31 que produjeron la marca, con su deuda cruda.
_PROVINCIAS = [
    {"provincia": "DISTRITO NACIONAL", "deuda": 1_366_000.0},
    {"provincia": "SANTO DOMINGO", "deuda": 342_000.0},
    {"provincia": "SANTIAGO", "deuda": 253_000.0},
    {"provincia": "LA ALTAGRACIA", "deuda": 138_000.0},
    {"provincia": "LA VEGA", "deuda": 46_000.0},
    {"provincia": "SAN CRISTOBAL", "deuda": 43_000.0},
]


def _conc(items=None, **kw):
    base = dict(clave_peso="deuda", clave_nombre="provincia", poblacion="provincias")
    base.update(kw)
    return concentracion_top_n(items if items is not None else _PROVINCIAS, **base)


def test_el_acumulado_de_los_dos_mayores_se_SIRVE():
    r = _conc()
    assert r["top2"]["pct"] == pytest.approx(78.1, abs=0.2)
    assert r["top2"]["miembros"] == ["DISTRITO NACIONAL", "SANTO DOMINGO"]


def test_se_acumula_sobre_el_CRUDO_y_no_sobre_los_pesos_ya_redondeados():
    """El corazón del asunto, y el defecto exacto del «42,2 cuando el dato era 42,3».

    Tres partes de 5 sobre un total de 18: cada una pesa 27,78 % redondeada, y sumarlas a
    mano da **83,34**. El acumulado real sobre el crudo es **83,33**. Un centésimo, y es
    justo la clase de diferencia por la que un guard veta un informe entero.
    """
    items = [{"provincia": f"p{i}", "deuda": 5.0} for i in range(3)]
    items += [{"provincia": "resto", "deuda": 3.0}]
    pesos_redondeados = [round(100 * 5.0 / 18.0, 2)] * 3
    assert round(sum(pesos_redondeados), 2) == 83.34, "la fixture perdió su premisa"
    r = _conc(items)
    assert r["top3"]["pct"] == 83.33, (
        "se acumuló sobre los pesos ya redondeados: el redondeo de cada parte se arrastra "
        "al total, que es exactamente el «42,2 cuando el dato era 42,3»")


def test_el_SUJETO_viaja_con_el_acumulado():
    """En el mismo contexto viajan 33 provincias y 19 sectores. Una clave sin población es
    literalmente cómo se publicó «cuatro compañías concentran el 87,1 %» cuando eran cuatro
    ramos."""
    r = _conc()
    assert r["poblacion"] == "provincias"
    assert r["de_cuantos"] == 6
    assert r["top2"]["miembros"], "sin los miembros, el acumulado no se puede atribuir"


def test_un_acumulado_que_abarca_a_TODOS_no_se_sirve():
    """Sería 100 % y no informa nada; peor, invita a decir «los cinco mayores concentran el
    100 %» como si fuera un hallazgo."""
    r = _conc(_PROVINCIAS[:3], enes=(2, 3, 5))
    assert "top2" in r and "top3" not in r and "top5" not in r


def test_con_menos_de_dos_elementos_no_hay_concentracion():
    """Un «top-N» de uno no es una concentración: es el elemento."""
    assert _conc(_PROVINCIAS[:1]) == {}
    assert _conc([]) == {}


def test_sin_peso_total_no_se_divide_por_cero():
    assert _conc([{"provincia": "a", "deuda": 0.0}, {"provincia": "b", "deuda": 0.0}]) == {}


def test_las_filas_sin_peso_se_descartan_en_vez_de_contarse_como_cero():
    """Un `None` contado como cero hundiría el denominador y subiría el acumulado: la
    concentración se leería más alta de lo que es."""
    r = _conc([{"provincia": "a", "deuda": 10.0}, {"provincia": "b", "deuda": None},
               {"provincia": "c", "deuda": 10.0}, {"provincia": "d", "deuda": 20.0}])
    assert r["de_cuantos"] == 3
    assert r["top2"]["pct"] == pytest.approx(75.0)


# ── Las DOS mitades: servirlo y pedirlo ───────────────────────────

@pytest.mark.parametrize("plantilla,claves", [
    ("anio_del_sistema", ("concentracion_por_provincia", "concentracion_por_sector")),
    ("banking_sector_map_system", ("concentracion_por_provincia", "concentracion_por_sector")),
    ("banking_sector_map", ("concentracion_por_sector",)),
])
def test_la_plantilla_NOMBRA_el_acumulado_servido(plantilla, claves):
    """Servir el dato no alcanza: la plantilla enumera las cifras que el modelo puede citar,
    y lo que no está en esa lista no se usa. Acá además la prohibición SOLA ya se probó y
    falló — hacía falta el número al que apuntar."""
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES[plantilla]
    for c in claves:
        assert c in t, f"{plantilla} no nombra «{c}»: el bloque viaja y el modelo suma igual"


@pytest.mark.parametrize("fn", ["sistema_por_sector", "posicion_de_la_entidad"])
def test_el_mapa_SIRVE_el_acumulado(fn):
    """La otra mitad. Un guard estructural: los tests de valor de arriba prueban el cuerpo
    compartido, no que el mapa lo llame."""
    import ast
    import inspect

    from modules.banking_score.reports import mapa_sectorial as mod

    arbol = ast.parse(inspect.getsource(mod))
    f = next(n for n in ast.walk(arbol)
             if isinstance(n, ast.FunctionDef) and n.name == fn)
    llama = any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "concentracion_top_n"
                for n in ast.walk(f))
    assert llama, f"{fn} dejó de servir el acumulado: el modelo vuelve a sumarlo a mano"
