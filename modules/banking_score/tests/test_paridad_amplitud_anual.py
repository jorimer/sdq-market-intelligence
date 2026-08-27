"""PARIDAD de amplitud entre el Deep Dive trimestral y la Revisión Anual.

**El error que fija este archivo.** Dejé fuera del anual cuatro bloques —sensibilidades,
soporte soberano, alerta temprana y telón macro— argumentando que «son del corte, no del año».
El dueño lo refutó en una línea: *«la única diferencia entre un trimestre y un año con estos
datos es el período comparado»*.

Tenía razón, y el propio código trimestral me contradecía: los computa **al corte del
informe**, con un comentario que dice por qué —«si no, un Deep Dive de diciembre mostraba las
alertas de marzo»—. Un año TIENE un corte: su cierre. Excluir hechos no distingue dos
productos; empobrece uno.

Lo que estos tests fijan:

  * que el anual sirva los mismos bloques que el trimestral, en el MISMO nivel (deep_dive);
  * que los compute al CIERRE del año y no al último período disponible — un anuario de 2020
    con las alertas de hoy sería peor que no tenerlas;
  * que el telón macro respete la consistencia temporal: fechado después del cierre, se OMITE.

Y una prueba estructural: si mañana el trimestral gana un bloque de amplitud, el anual tiene
que ganarlo o declararlo. La lista se lee del CÓDIGO, no de mi memoria — que es justo lo que
falló.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from modules.banking_score import products, products_year_review

#: Bloques de amplitud que el Deep Dive trimestral sirve. Se declaran acá para poder afirmar
#: paridad, y el test de abajo comprueba contra el código que la lista no envejeció.
BLOQUES_DE_AMPLITUD = ("sensibilidades", "soporte_soberano", "early_warning",
                       "propension_quiebra", "entorno_macro")


def _claves_servidas(fuente: str) -> set:
    """Las claves de string que el módulo asigna en un dict/payload, leídas con `ast`."""
    arbol = ast.parse(fuente)
    claves = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Subscript) and isinstance(nodo.slice, ast.Constant):
            if isinstance(nodo.slice.value, str):
                claves.add(nodo.slice.value)
    return claves


def test_el_barrido_LEE_el_trimestral():
    """Prueba negativa: sin esto, un módulo renombrado daría cero claves y paridad trivial."""
    claves = _claves_servidas(inspect.getsource(products))
    assert len(claves) > 20, "el barrido no leyó el producto trimestral"
    for bloque in BLOQUES_DE_AMPLITUD:
        assert bloque in claves, (
            f"'{bloque}' ya no lo sirve el trimestral: la lista de este test envejeció.")


def _amplitud_ejecutada(monkeypatch):
    """Corre `_amplitud_al_cierre` de verdad, con los cuatro motores stubeados.

    Se EJECUTA en vez de leer el fuente: la primera versión de este test buscaba las claves en
    el texto del módulo y pasaba en verde con el bloque DESCONECTADO del snapshot. Comprobaba
    que la función existe, no que sirva. Es la misma familia que «un test del motor no es un
    test de la ruta», y me la comí de nuevo el mismo día.

    Los motores se stubean porque acá no se prueban ellos: se prueba que el anual los llame y
    ponga su resultado en el payload.
    """
    import modules.banking_score.early_warning as ew
    import modules.banking_score.propension_quiebra as pq
    import modules.banking_score.scoring.sensitivity as sens
    import modules.banking_score.scoring.support as sup
    import shared.contracts as contratos

    monkeypatch.setattr(sens, "sensitivity_table", lambda *a, **k: {"palancas_alza": []})
    monkeypatch.setattr(sup, "support_overlay", lambda *a, **k: {"soporte": "ninguno"})
    monkeypatch.setattr(ew, "bank_alerts", lambda *a, **k: {"flags": []})
    monkeypatch.setattr(pq, "evaluar_entidad", lambda *a, **k: {"probabilidad": 0.1})
    monkeypatch.setattr(contratos, "load_macro_contract",
                        lambda *a, **k: {"period": "2025-12",
                                         "factors": [{"name": "pib", "direction": "up"}]})

    class _RR:
        overall_score = 58.71
        banda_resiliencia = "Adecuada"
        indicator_details = {"solvencia": {"raw": 23.26, "score": 87.2}}

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _RR()

    class _DB:
        def query(self, *a, **k):
            return _Q()

    class _Tipo:
        value = "aap"

    class _Bank:
        id = "b1"
        name = "Entidad"
        bank_type = _Tipo()

    return products_year_review._amplitud_al_cierre(_DB(), _Bank(), 2025)


@pytest.mark.parametrize("bloque", BLOQUES_DE_AMPLITUD)
def test_el_anual_SIRVE_el_mismo_bloque(bloque, monkeypatch):
    servido = _amplitud_ejecutada(monkeypatch)
    assert bloque in servido, (
        f"El Deep Dive trimestral sirve '{bloque}' y la Revisión Anual no lo puso en el "
        "payload. Si es una decisión, declarála en el módulo con su motivo; si es un olvido, "
        "es el defecto que este archivo existe para atrapar.")


def test_sin_CIERRE_calificado_no_se_inventa_amplitud(monkeypatch):
    """Sin el corte de diciembre no hay año — ya lo exige `revision_anual`— y acá tampoco se
    fabrica un bloque vacío que el modelo leería como «no hay señales»."""
    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class _DB:
        def query(self, *a, **k):
            return _Q()

    class _Bank:
        id = "b1"
        name = "Entidad"
        bank_type = None

    assert products_year_review._amplitud_al_cierre(_DB(), _Bank(), 2025) == {}


def test_los_bloques_se_computan_AL_CIERRE_del_anio():
    """Al cierre, no al último período disponible. El trimestral lo declara y aprendió por qué;
    el anual tiene que hacer lo mismo o mostraría las alertas de hoy en el año 2020."""
    fuente = inspect.getsource(products_year_review._amplitud_al_cierre)
    assert "date(anio, 12, 31)" in fuente
    # Cada llamada que acepta un corte lo recibe: se busca el nombre de la variable, no un
    # literal, porque el literal es la fecha y la variable es la INTENCIÓN.
    for llamada in ("support_overlay", "bank_alerts", "evaluar_entidad"):
        i = fuente.index(llamada + "(")
        assert "cierre" in fuente[i:i + 220], f"{llamada} no recibe el cierre del año"


def test_el_telon_macro_POSTERIOR_al_cierre_se_omite():
    """La misma regla del trimestral: el corte manda sobre TODA la información mostrada.
    Sin ella, la Revisión Anual 2020 describiría la macro de 2026."""
    fuente = inspect.getsource(products_year_review._amplitud_al_cierre)
    assert "_posterior_al_corte" in fuente
    assert "entorno_macro" in fuente


def test_la_amplitud_es_del_DEEP_DIVE_y_no_del_Insight():
    """Paridad también en el nivel: el trimestral la gatea a deep_dive y el anual igual.
    Servirla en Insight regalaría el nivel de arriba."""
    fuente = inspect.getsource(products_year_review.BankingYearReviewProduct.snapshot)
    i = fuente.index("_amplitud_al_cierre")
    previo = fuente[:i]
    assert "if tier == ProductTier.deep_dive:" in previo


def test_el_modulo_del_anual_esta_en_la_huella_de_la_CACHE():
    """Cambiar el contexto sin invalidar la caché deja los informes ya generados sirviendo el
    texto viejo indefinidamente — `ProductReportCache` no tiene TTL."""
    assert "products_year_review.py" in products.AI_CONTEXT_FILES
    assert Path(inspect.getfile(products_year_review)).name == "products_year_review.py"
