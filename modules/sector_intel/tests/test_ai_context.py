"""Tests for the sector IAI AI-context builder (Gate D). Pure, offline."""
import pytest

from modules.sector_intel.ai_context import sector_ai_context

_LATEST = {
    "sector_code": "turismo",
    "period": "2024",
    "iai_score": 61.2,
    "iai_band": "Atractivo",
    "sgps_score": 58.0,
    "iai_breakdown": {
        "sector": {"score": 80.0, "weight": 0.3, "contribution": 24.0},
        "macro": {"score": 55.0, "weight": 0.2, "contribution": 11.0},
        "business": {"score": 50.0, "weight": 0.2, "contribution": 10.0},
        "talent": {"score": 50.0, "weight": 0.15, "contribution": 7.5},
        "regulation": {"score": 40.0, "weight": 0.15, "contribution": 6.0},
    },
}


def test_context_is_compact_and_explains_drivers():
    ctx = sector_ai_context(_LATEST, sector_name="Turismo")
    assert ctx["sector_code"] == "turismo" and ctx["sector_name"] == "Turismo"
    assert ctx["iai_score"] == 61.2 and ctx["iai_band"] == "Atractivo"
    # Dimensions sorted by contribution desc (sector first).
    assert ctx["dimensions"][0]["dimension"].startswith("Sector")
    # Strongest = sector (80), weakest = regulation (40).
    assert ctx["strongest_dimension"]["score"] == 80.0
    assert ctx["weakest_dimension"]["score"] == 40.0


def test_la_procedencia_se_COMPUTA_de_las_variables_y_no_se_transcribe():
    """Acá vivía `_LIVE_DIMS = {"sector", "macro"}` y este test lo bendecía.

    Era cierto cuando se escribió y envejeció: hoy 8 de las 9 variables del índice corren
    con dato real —TSS, SIB, ENCFT, ENAE, capital humano del Banco Mundial y WGI— y la única
    rúbrica efectiva es `ease_of_business`, porque el Doing Business se descontinuó. El
    contexto le decía al modelo que negocios, talento y regulatoria eran rúbrica declarada,
    o sea que el producto se subestimaba a sí mismo en el texto que se vende.

    La procedencia se GENERA del registro —el `source` por variable que estampa el motor—,
    que es la misma regla que la doctrina ya se aplica a sí misma.
    """
    latest = {**_LATEST, "iai_breakdown": {
        "sector": {"score": 80.0, "weight": 0.3, "contribution": 24.0, "variables": {
            "sector_size": {"raw": 8.9, "normalized": 70.0, "source": "live"},
            "sector_growth": {"raw": 3.5, "normalized": 60.0, "source": "live"}}},
        "business": {"score": 50.0, "weight": 0.2, "contribution": 10.0, "variables": {
            "credit_cost": {"raw": 8.39, "normalized": 88.0, "source": "live"},
            "operating_cost": {"raw": 26113.1, "normalized": 100.0, "source": "live"},
            "ease_of_business": {"raw": 50.0, "normalized": 50.0, "source": "rubric"}}},
        "talent": {"score": 50.0, "weight": 0.15, "contribution": 7.5, "variables": {
            "skills_index": {"raw": 50.28, "normalized": 50.0, "source": "rubric"}}},
    }}
    filas = {r["dimension"].split(" ")[0]: r for r in sector_ai_context(latest)["dimensions"]}
    assert filas["Sector"]["provenance"] == "real"
    assert filas["Entorno"]["provenance"] == "real en parte"
    assert filas["Entorno"]["variables_reales_de_la_dimension"] == "2 de 3"
    # Se nombra lo que ES rúbrica, que es la lista corta y la que el modelo necesita para no
    # construir una conclusión fuerte encima.
    assert any("facilidad de hacer negocios" in x
               for x in filas["Entorno"]["sobre_rubrica_declarada"])
    assert filas["Talento"]["provenance"] == "rúbrica declarada"


def test_un_breakdown_VIEJO_sin_procedencia_no_la_inventa():
    """Los breakdown anteriores al estampado no traen `source`. Devolver «real» ahí sería
    afirmar procedencia sobre algo que no la declara — el defecto al revés."""
    latest = {**_LATEST, "iai_breakdown": {
        "sector": {"score": 80.0, "weight": 0.3, "contribution": 24.0}}}
    fila = sector_ai_context(latest)["dimensions"][0]
    assert fila["provenance"] == "no declarada"


def test_el_contexto_dice_QUE_HAY_DENTRO_de_cada_dimension():
    """Sin esto el modelo dice que una dimensión lastra y no puede decir por qué.

    Agropecuario cambió de banda al entrar el costo del capital —paga 13,61 % de tasa con el
    segundo salario más bajo del país— y ésa, que es la única frase accionable del informe,
    no se podía escribir porque el contexto solo llevaba el score de la dimensión.
    """
    latest = {**_LATEST, "iai_breakdown": {
        "business": {"score": 56.9, "weight": 0.25, "contribution": 14.2, "variables": {
            "credit_cost": {"raw": 13.61, "normalized": 25.35, "source": "live"},
            "operating_cost": {"raw": 28537.27, "normalized": 95.46, "source": "live"}}}}}
    dentro = {f["variable"]: f for f in sector_ai_context(latest)["dimensions"][0]["que_hay_dentro"]}
    tasa = next(v for k, v in dentro.items() if "costo del capital" in k)
    assert tasa["valor"] == 13.61 and tasa["procedencia"] == "real"
    assert tasa["posicion_en_la_escala_de_valor_del_panel_0_100"] == 25.35
    salario = next(v for k, v in dentro.items() if "costo laboral" in k)
    assert salario["valor"] == 28537.27


def test_la_rentabilidad_viaja_en_POR_CIENTO_y_no_como_razon():
    """El guard numérico veta una cifra REAL cuando cambia de FORMA: la rentabilidad es una
    razón (0,048) y el modelo la escribe «4,8 %». Servirla cruda es cómo un peso de 0,38 se
    publicó como «38 %» y el ensamblador vetó el informe. Se sirve como se va a citar."""
    latest = {**_LATEST, "iai_breakdown": {
        "business": {"score": 50.0, "weight": 0.25, "contribution": 12.5, "variables": {
            "profitability": {"raw": 0.048, "normalized": 30.0, "source": "live"}}}}}
    fila = sector_ai_context(latest)["dimensions"][0]["que_hay_dentro"][0]
    assert "POR CIENTO" in fila["variable"]
    assert fila["valor"] == 4.8, "la razón llegó cruda: el guard vetaría el «4,8 %» del texto"


def test_TODA_variable_de_la_doctrina_tiene_su_nombre_citable():
    """La prueba negativa del barrido. Una variable nueva del índice que no esté en la tabla
    viaja al modelo con su identificador de código (`credit_cost`) y su valor crudo, sin
    unidad — que es cómo una razón se publica como porcentaje."""
    from modules.sector_intel.ai_context import _VARIABLES
    from shared.doctrine import load_doctrine

    cfg = load_doctrine("sectoral")
    declaradas = {v for vs in cfg.dimension_variables.values() for v in vs}
    assert declaradas, "la doctrina no declaró ninguna variable: el barrido estaría vacío"
    faltan = declaradas - set(_VARIABLES)
    assert not faltan, f"variables del IAI sin nombre citable: {sorted(faltan)}"


def test_handles_missing_breakdown():
    ctx = sector_ai_context({"sector_code": "x", "iai_score": None, "iai_breakdown": None})
    assert ctx["dimensions"] == []
    assert ctx["strongest_dimension"] is None and ctx["weakest_dimension"] is None


# ── La reincidencia: que la procedencia no vuelva a transcribirse ─────────────
def test_la_procedencia_NO_se_resuelve_con_un_condicional_sobre_una_lista_fija():
    """El guard estructural de la regresión.

    El defecto original era una línea: `"provenance": "real" if key in _LIVE_DIMS else …`.
    Es correcta el día que se escribe y miente el día que un conector sube una dimensión a
    dato real, sin que nada falle — el score cambia y el texto sigue diciendo «rúbrica».
    Los tests de valor de arriba pasarían si alguien reescribiera la lista fija con los
    nombres de hoy; esto exige que el valor salga de un CÓMPUTO sobre el breakdown.
    """
    import ast
    import inspect

    from modules.sector_intel import ai_context as mod

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(mod)))
              if isinstance(n, ast.FunctionDef) and n.name == "sector_ai_context")
    for nodo in ast.walk(fn):
        if not isinstance(nodo, ast.Dict):
            continue
        for k, v in zip(nodo.keys, nodo.values):
            if isinstance(k, ast.Constant) and k.value == "provenance":
                assert not isinstance(v, ast.IfExp), (
                    "la procedencia volvió a resolverse con un condicional en línea: es una "
                    "transcripción, y envejece sin que nada falle")


def test_la_PLANTILLA_no_nombra_dimensiones_como_reales_ni_como_rubrica():
    """La otra mitad. El prompt decía «apóyate en las dimensiones real (sector, exposición
    macro); sobre las de rúbrica declarada (negocios, talento, regulatoria) no construyas
    conclusión fuerte»: mandaba a NO apoyarse en el 60 % del peso del score, cuando 8 de las
    9 variables ya corren con dato real. Un contexto computado con un prompt que lo
    contradice deja el defecto en pie."""
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES["sector_outlook"]
    for frase in ("(negocios, talento, regulatoria)", "(sector, exposición macro)"):
        assert frase not in t, f"la plantilla clasifica dimensiones a mano: «{frase}»"
    assert "provenance" in t and "que_hay_dentro" in t, (
        "la plantilla no manda a leer la procedencia computada ni las variables: el bloque "
        "viaja en el contexto y el modelo no lo usa")


# ── El puesto: la relación que el lector quiere, y que NO es un percentil ─────
def test_el_puesto_se_computa_contra_los_sectores_que_TIENEN_la_variable():
    """El modelo publicó «percentil 25,35» sobre lo que es una posición min-max de VALOR.

    No es lo mismo y la diferencia no es cosmética: sobre el panel
    [10,11,11,12,12,13,13,14,14,15,60] el valor 15 da posición min-max 10,0 y percentil real
    81,8 — 72 puntos de distancia. En un documento que se vende eso es una afirmación
    estadística falsa, así que el puesto se computa y viaja aparte.

    Y el denominador nombra su población: `credit_cost` la tienen 16 sectores, no 17.
    """
    latest = {**_LATEST, "iai_breakdown": {
        "business": {"score": 56.9, "weight": 0.25, "contribution": 14.2, "variables": {
            "credit_cost": {"raw": 13.61, "normalized": 25.35, "source": "live"}}}}}
    ctx = sector_ai_context(latest, puestos={"credit_cost": {"puesto": 14, "de": 16}})
    fila = ctx["dimensions"][0]["que_hay_dentro"][0]
    assert fila["puesto_entre_los_sectores_que_tienen_esta_variable"] == (
        "14 de 16 (1 = el más favorable)")
    assert "percentil" not in str(fila).lower()


def test_sin_puestos_la_clave_no_aparece_en_vez_de_inventarse():
    latest = {**_LATEST, "iai_breakdown": {
        "business": {"score": 56.9, "weight": 0.25, "contribution": 14.2, "variables": {
            "credit_cost": {"raw": 13.61, "normalized": 25.35, "source": "live"}}}}}
    fila = sector_ai_context(latest)["dimensions"][0]["que_hay_dentro"][0]
    assert "puesto_entre_los_sectores_que_tienen_esta_variable" not in fila


def test_en_una_variable_de_RIESGO_el_puesto_1_es_el_valor_mas_BAJO(db_ranking):
    """Ordenar al revés daría un puesto que contradice al score: el sector con el crédito más
    caro saldría «puesto 1» mientras su score de negocios es el peor del panel."""
    from modules.sector_intel.products import _puesto_por_variable

    barato = _puesto_por_variable(db_ranking, "2025", "turismo")
    caro = _puesto_por_variable(db_ranking, "2025", "otros_servicios")
    assert barato["credit_cost"] == {"puesto": 1, "de": 3}
    assert caro["credit_cost"] == {"puesto": 3, "de": 3}
    # Y en una variable donde MAYOR es mejor, el orden se invierte.
    assert _puesto_por_variable(db_ranking, "2025", "otros_servicios")["sector_size"] == {
        "puesto": 1, "de": 3}


def test_el_denominador_es_de_los_que_TIENEN_la_variable_no_del_panel(db_ranking):
    """`credit_cost` la tienen 16 de 17 sectores y `profitability` unos 8: decir «puesto 15
    de 17» cuando el panel son 16 es reatribuir el sujeto, que es el defecto que publicó
    «cuatro compañías concentran el 87,1 %» cuando eran cuatro ramos."""
    from modules.sector_intel.products import _puesto_por_variable

    p = _puesto_por_variable(db_ranking, "2025", "turismo")
    assert p["credit_cost"]["de"] == 3
    assert p["profitability"]["de"] == 2, "el denominador contó sectores sin la variable"


@pytest.fixture()
def db_ranking():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from shared.database.base import Base
    from modules.sector_intel.models.models import SectorScore

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    panel = {   # (credit_cost, sector_size, profitability|None)
        "turismo": (8.39, 8.94, 0.023),
        "construccion": (11.40, 13.45, None),
        "otros_servicios": (15.42, 30.0, 0.10),
    }
    for slug, (tasa, tam, rent) in panel.items():
        vs = {"credit_cost": {"raw": tasa, "source": "live"}}
        if rent is not None:
            vs["profitability"] = {"raw": rent, "source": "live"}
        db.add(SectorScore(sector_code=slug, period="2025", iai_score=50.0, iai_breakdown={
            "business": {"variables": vs},
            "sector": {"variables": {"sector_size": {"raw": tam, "source": "live"}}}}))
    db.commit()
    return db


def test_la_PLANTILLA_prohibe_llamar_percentil_a_la_escala_de_valor():
    """La otra mitad. El contexto puede traer el nombre correcto y el modelo seguir diciendo
    «percentil» si nadie se lo prohíbe — que es lo que pasó."""
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES["sector_outlook"]
    assert "NO es un percentil" in t
    assert "puesto_entre_los_sectores_que_tienen_esta_variable" in t
    assert "sin cambiarlo por 17" in t, (
        "no prohíbe redondear el denominador a 17: el crédito lo tienen 16 sectores y la "
        "rentabilidad 8, y cambiar el denominador es reatribuir el sujeto")
