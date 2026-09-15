"""La capacidad de pago del hogar la leen los CUATRO ejes financieros, no solo banca.

**Dónde estaba y por qué estaba mal.** El módulo vivía en `modules/banking_score/reports/`
y no lee nada de banca: son series nacionales del BCRD y del MHE. Con esa ubicación, ningún
otro eje podía usarlo sin importar de banca — que es justo lo que la arquitectura de la casa
prohíbe («los módulos son independientes; lo transversal va en `shared`»).

**Por qué aplica a los cuatro, con lecturas distintas.** El dato es el mismo; lo que cambia
es qué responde:

* **banca** — capacidad de pagar el crédito de consumo, que es el rubro más grande del
  sistema y vive en los quintiles bajos;
* **pensiones** — capacidad de COTIZAR: la informalidad define quién queda fuera del sistema
  y el piso de ingreso define sobre qué se aporta;
* **seguros** — persistencia de la póliza: una voluntaria compite con la canasta;
* **política monetaria** — lectura DISTRIBUTIVA de la postura: a quién le está costando más
  el nivel de precios, que el índice del titular no muestra.

Copiar el bloque con la misma glosa en los cuatro habría sido peor que no tenerlo: diría que
significa lo mismo en todos, y no.
"""

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Los cuatro ejes financieros, con el archivo donde arman su snapshot.
EJES = {
    "banca (trimestral y anual)": "modules/banking_score/products.py",
    "seguros": "modules/insurance_intel/products.py",
    "pensiones": "modules/pension_intel/products.py",
    "política monetaria": "app/products_monetary_policy.py",
}

#: La plantilla que interpreta el bloque en cada eje. Distinta a propósito.
PLANTILLAS = {
    "banking_sector_map": "el crédito de consumo",
    "pension_entity": "cotizar",
    "insurance_entity": "póliza",
    "mp_evaluation": "distributiva",
}


def test_el_modulo_vive_en_shared_y_no_dentro_de_un_eje():
    """Dentro de banca, ningún otro módulo podía leerlo sin romper la independencia."""
    assert (REPO / "shared" / "capacidad_de_pago.py").is_file()
    assert not (REPO / "modules" / "banking_score" / "reports"
                / "capacidad_de_pago.py").exists()


#: Los cuatro ejes que CONSUMEN el bloque. Ninguno puede aparecer en sus importaciones.
_EJES_CONSUMIDORES = ("banking_score", "insurance_intel", "pension_intel",
                      "macro_political_risk")


def test_no_importa_de_ningun_eje_CONSUMIDOR():
    """Si importara de uno de los ejes que lo leen, volvería a atarse a él por la puerta de
    atrás y el próximo eje tendría que importar de ese.

    Sí importa los MODELOS de `macro_monitor` y `social_dev`: son los dueños de las dos
    tablas donde viven las series que lee. Es un acoplamiento distinto —al dueño del dato, no
    al consumidor de la lectura— y preexistente: los modelos de esas tablas viven dentro de
    sus módulos y no hay hoy una capa de acceso compartida. Queda anotado como deuda de
    arquitectura, separada de la que este archivo vino a cerrar."""
    src = (REPO / "shared" / "capacidad_de_pago.py").read_text()
    for eje in _EJES_CONSUMIDORES:
        assert f"modules.{eje}" not in src, (
            f"el bloque compartido importa de «{eje}», que es uno de los ejes que lo leen")


def test_solo_importa_de_los_DUEÑOS_DEL_DATO_y_se_declara_cuáles():
    """Fijar la lista hace que agregar una dependencia nueva sea una decisión y no un
    descuido: hoy son las dos tablas de series, y cualquier otra tiene que justificarse."""
    import re
    src = (REPO / "shared" / "capacidad_de_pago.py").read_text()
    modulos = set(re.findall(r"from modules\.([a-z_]+)", src))
    assert modulos == {"macro_monitor", "social_dev"}, (
        f"el bloque compartido importa de {sorted(modulos)}: solo debería tocar a los dueños "
        f"de las tablas de series")


@pytest.mark.parametrize("eje", sorted(EJES))
def test_cada_eje_financiero_lo_SIRVE(eje):
    src = (REPO / EJES[eje]).read_text()
    assert "capacidad_de_pago" in src, (
        f"«{eje}» no sirve la capacidad de pago del hogar: su informe sale sin la lectura "
        f"que explica si el cliente puede pagar")


@pytest.mark.parametrize("plantilla,palabra", sorted(PLANTILLAS.items()))
def test_cada_eje_tiene_su_PROPIA_lectura(plantilla, palabra):
    """El dato es el mismo y la lectura no. Una glosa copiada diría que significa lo mismo
    en los cuatro, y eso es falso: en pensiones acota el tamaño posible del sistema, en
    seguros la persistencia de cartera, en banca la mora y en política monetaria a quién le
    cuesta más el nivel de precios."""
    from shared.narrative.claude_engine import THIN_TEMPLATES
    thin = THIN_TEMPLATES[plantilla]
    assert "capacidad_de_pago" in thin, f"«{plantilla}» no declara qué hacer con el bloque"
    assert palabra.lower() in thin.lower(), (
        f"«{plantilla}» no dice qué significa el bloque EN SU EJE")


@pytest.mark.parametrize("plantilla", sorted(PLANTILLAS))
def test_ninguna_lectura_lo_convierte_en_un_juicio_sobre_la_ENTIDAD(plantilla):
    """Es contexto de mercado: atribuirle a una AFP o a una aseguradora un problema del
    mercado laboral sería exactamente la clase de relación mal dirigida que este repo veta."""
    from shared.narrative.claude_engine import THIN_TEMPLATES
    thin = THIN_TEMPLATES[plantilla].lower()
    assert any(p in thin for p in ("no como", "nunca como", "no un juicio",
                                   "no lo conviertas", "no la presentes",
                                   "no las presentes")), (
        f"«{plantilla}» no acota el bloque a CONTEXTO: sin eso el modelo lo usa como "
        f"veredicto sobre la entidad")


@pytest.mark.parametrize("modulo,eje", [
    ("modules.banking_score.ai_context_files", "banking_score"),
    ("modules.insurance_intel.products", "insurance_intel"),
    ("modules.pension_intel.products", "pension_intel"),
])
def test_cada_eje_lo_declara_en_su_HUELLA_de_cache(modulo, eje):
    """`ProductReportCache` no tiene TTL. Un archivo de contexto fuera de la huella
    significa que arreglarlo no invalida nada y el informe sigue sirviendo el texto viejo
    indefinidamente — el defecto que la huella vino a cerrar."""
    import importlib
    declarados = getattr(importlib.import_module(modulo), "AI_CONTEXT_FILES", ())
    assert "shared/capacidad_de_pago.py" in declarados, (
        f"«{eje}» lee el bloque compartido y no lo declara: un arreglo de lo que el modelo "
        f"lee no invalidaría su caché")


def test_la_huella_resuelve_una_ruta_COMPARTIDA():
    """La regla vive en el ensamblador y los guards la piden: dos resoluciones distintas se
    desincronizan, y ya pasó — admitir `shared/` en el ensamblador dejó a los dos tests
    buscando `modules/<mod>/shared/...`."""
    from shared.products.assembler import ruta_de_contexto
    assert ruta_de_contexto("shared/capacidad_de_pago.py", "banking_score").is_file()
    assert ruta_de_contexto("products.py", "banking_score").is_file()



#: Pedirla en la plantilla no alcanza si el contexto no la lleva. Producción, 2026-09-15: el
#: bloque estaba completo en el payload de seguros y de pensiones y la prosa lo mencionó cero
#: veces, porque `insurance_entity_context` y `pension_entity_context` no lo copiaban.
_CAPA = {"inflacion_del_deudor": {"hasta": "2025-12"}, "salario_minimo": {"meses_sin_ajuste": 8}}


@pytest.mark.parametrize("modulo,funcion", [
    ("modules.insurance_intel.products", "contexto_de_la_aseguradora"),
    ("modules.pension_intel.products", "contexto_de_la_afp"),
])
def test_el_contexto_de_la_entidad_LLEVA_el_bloque_que_la_plantilla_pide(modulo, funcion):
    import importlib
    mod = importlib.import_module(modulo)
    rating = {"slug": "x", "name": "X", "overall_score": 60.0, "band": "B", "coverage": 1.0,
              "period": "2025", "dimensions": []}
    ctx = getattr(mod, funcion)({"capacidad_de_pago": _CAPA}, rating, [rating])
    assert ctx.get("capacidad_de_pago") == _CAPA
    sin = getattr(mod, funcion)({}, rating, [rating])
    assert "capacidad_de_pago" not in sin, "sin el bloque en el snapshot no se inventa uno vacío"


@pytest.mark.parametrize("archivo,funcion", [
    ("modules/insurance_intel/products.py", "contexto_de_la_aseguradora"),
    ("modules/pension_intel/products.py", "contexto_de_la_afp"),
])
def test_la_narrativa_USA_el_contexto_que_lleva_el_bloque(archivo, funcion):
    """Sin esto, la función existe, pasa su test, y `narratives()` sigue llamando al contexto
    viejo — un guard en la función equivocada."""
    import ast
    arbol = ast.parse((REPO / archivo).read_text())
    narr = next(n for n in ast.walk(arbol)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "narratives")
    llamadas = {c.func.id for c in ast.walk(narr)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert funcion in llamadas
    assert not ({"insurance_entity_context", "pension_entity_context"} & llamadas), (
        "la narrativa arma el contexto de la entidad sin la capacidad de pago")
