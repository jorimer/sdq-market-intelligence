"""Un eje cableado tiene DOS mitades: el dato y la plantilla que lo pide.

**La lección que lo motivó, medida en producción el 2026-08-31.** Se cableó
`construction_intel` con el perfil de su sector y funcionó a la primera EN EL DATO: el bloque
viajaba en el contexto. La prosa generada no lo usó ni una vez. El modelo hacía lo correcto —
su plantilla dice «Usa EXCLUSIVAMENTE las cifras del contexto (…)» y enumera, y el
financiamiento no estaba en esa lista.

Es la familia de «el cómputo existe y la superficie no lo pide», que en la misma sesión
apareció con el mapa sectorial servido en 1 de 4 tipos de informe. Acá la superficie es el
PROMPT, que no se contaba como superficie.

Este test recorre los ejes cableados y exige las dos mitades. Un eje nuevo que sume el bloque
al contexto y olvide su plantilla queda con el dato viajando sin usarse, y NADA falla: el
informe sale, más pobre y en silencio.
"""
import ast
import importlib
import inspect

import pytest

from shared.narrative.claude_engine import THIN_TEMPLATES

#: eje → (módulo de contexto, plantilla, slug del marco BCRD-17).
#: Al cablear un eje nuevo se agrega acá; el test de abajo comprueba que la lista no se quede
#: corta contra el código.
EJES_CABLEADOS = {
    "construction": ("modules.construction_intel.ai_context", "construction_outlook",
                     "construccion"),
    "energy": ("modules.energy_intel.ai_context", "energy_outlook", "energia"),
    "free_zones": ("modules.free_zones_intel.ai_context", "free_zones_outlook",
                   "zonas_francas"),
    "telecom": ("modules.telecom_intel.ai_context", "telecom_outlook", "comunicaciones"),
    "tourism": ("modules.tourism_intel.ai_context", "tourism_outlook", "turismo"),
}

#: Capas que un eje declara NO servir aunque su fuente las alcance, y por qué. Es la única
#: puerta: sin una entrada acá, el test de abajo exige que la plantilla nombre toda capa que
#: el crosswalk alcanza para ese slug.
OMISIONES_DECLARADAS = {
    # `construction_intel` ya publica el crecimiento del PIB de construcción del BCRD con su
    # propio nombre. Servirle además `actividad` pondría dos cifras de crecimiento del mismo
    # sector en el mismo contexto —una interanual y una de tres años— y el modelo elige la
    # que le cae más cerca.
    ("construction", "actividad"): "ya publica construction_gdp_growth_*_pct del BCRD",
}


def test_el_barrido_no_esta_vacio():
    """Un `@parametrize` sobre una lista vacía sale SKIPPED, no FAILED."""
    assert len(EJES_CABLEADOS) == 5


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_el_contexto_del_eje_INCLUYE_el_bloque(eje):
    mod_name, _plantilla, _slug = EJES_CABLEADOS[eje]
    mod = importlib.import_module(mod_name)
    arbol = ast.parse(inspect.getsource(mod))
    # Se exige la LLAMADA en el dict de retorno, no que el nombre aparezca en el texto: el
    # comentario que explica el arreglo lo menciona y un test de texto se satisfaría con eso.
    llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "_financiamiento"]
    assert llamadas, f"{eje}: el contexto no arma el bloque de financiamiento"


def _capas_que_la_fuente_ALCANZA(slug):
    """Las capas del perfil que existen para *slug*, DERIVADAS del crosswalk.

    Se derivan y no se listan a mano: una segunda tabla del mismo mapa es como las dos se
    desincronizan, y acá el costo de desincronizarse es que la plantilla deje de pedir una
    capa que sí viaja — el bloque llega al contexto y la prosa nunca lo usa, en silencio.
    """
    from shared.perfil_del_sector import (_ACTIVIDAD_IED_POR_SLUG, _RAMA_POR_SLUG,
                                          letras_del_slug)
    capas = {}
    if letras_del_slug(slug):
        capas["credito"] = f"credito_del_sistema_al_sector_{slug}"
    capas["costo_laboral"] = f"costo_laboral_del_sector_{slug}"      # la TSS cubre los 17
    capas["actividad"] = f"actividad_del_sector_{slug}_en_las_cuentas_nacionales"
    if slug in _RAMA_POR_SLUG:                                        # la ENCFT parte los 17
        capas["ocupacion"] = f"ocupacion_de_la_rama_del_sector_{slug}"
    if slug in _ACTIVIDAD_IED_POR_SLUG:                               # la IED cubre 10 de 17
        capas["inversion_extranjera"] = f"inversion_extranjera_en_el_sector_{slug}"
    return capas


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_la_plantilla_del_eje_PIDE_todas_las_capas_que_su_fuente_ALCANZA(eje):
    """La mitad que se olvida, ahora sobre las CINCO capas.

    La primera versión enumeraba dos claves a mano. Al sumar tres capas más eso habría
    quedado corto sin fallar: la plantilla seguiría verde pidiendo dos de cinco, y las otras
    tres viajarían al contexto sin que la prosa las usara — que es exactamente el defecto que
    este archivo existe para prevenir, repetido a mayor escala.
    """
    _mod, plantilla, slug = EJES_CABLEADOS[eje]
    texto = THIN_TEMPLATES[plantilla]
    for capa, clave in _capas_que_la_fuente_ALCANZA(slug).items():
        if (eje, capa) in OMISIONES_DECLARADAS:
            assert clave not in texto, (
                f"{eje}: declara omitir «{capa}» y la plantilla igual la nombra")
            continue
        assert clave in texto, (
            f"{eje}: la plantilla no nombra «{clave}». El bloque viaja en el contexto y el "
            "modelo no lo usa, porque la enumeración de cifras permitidas lo deja afuera")


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_el_eje_que_OMITE_una_capa_lo_hace_en_el_CODIGO_y_no_solo_en_el_test(eje):
    """Una omisión declarada en el test y no en el código deja la clave viajando igual.

    El contrato es al revés de lo que parece: `OMISIONES_DECLARADAS` no apaga nada, solo
    dice qué se espera. Quien apaga es el `omitir=(...)` del contexto del eje, y si falta,
    la plantilla no la pide pero el dato sí llega — y llega para ser ignorado.
    """
    omitidas = {capa for (e, capa) in OMISIONES_DECLARADAS if e == eje}
    if not omitidas:
        return
    mod_name, _plantilla, _slug = EJES_CABLEADOS[eje]
    fuente = inspect.getsource(importlib.import_module(mod_name))
    literales = {n.value for n in ast.walk(ast.parse(fuente))
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    faltan = omitidas - literales
    assert not faltan, (
        f"{eje}: declara omitir {sorted(faltan)} y su contexto no lo pasa en `omitir=`")


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_la_plantilla_manda_a_CITAR_la_fecha_de_la_capa(eje):
    """Son capas de otro período que el índice del eje, y de períodos distintos entre sí: el
    cubo es trimestral, las cuentas nacionales y la IED anuales, la ENCFT por rama. Sin la
    fecha, el modelo las fecha en el encabezado del informe."""
    _mod, plantilla, slug = EJES_CABLEADOS[eje]
    texto = THIN_TEMPLATES[plantilla]
    # `comunicaciones` es el único slug que la SIB no cubre: sin crédito no hay corte
    # trimestral que citar, y exigir esa palabra ahí sería exigir algo que no viaja.
    from shared.perfil_del_sector import letras_del_slug
    if letras_del_slug(slug):
        assert "corte_de_esta_capa" in texto
    assert "anio_de_esta_capa" in texto


@pytest.mark.parametrize("eje", sorted(EJES_CABLEADOS))
def test_la_plantilla_NO_manda_a_declarar_la_ausencia(eje):
    """Decisión del dueño del 2026-08-31: lo que no se puede afirmar no se menciona.

    Las dos formas valen —«no la menciones» y «no las menciones»—: lo que se protege es la
    instrucción, no su número gramatical. Atar el test a una sola forma haría fallar a un eje
    que dice lo mismo bien escrito, que es cómo un test correcto se vuelve un estorbo.
    """
    _mod, plantilla, _slug = EJES_CABLEADOS[eje]
    texto = THIN_TEMPLATES[plantilla]
    assert ("no la menciones ni digas que" in texto
            or "no las menciones ni digas que" in texto)


def test_la_LISTA_no_se_queda_corta_contra_el_codigo():
    """La prueba negativa del barrido: si alguien cablea un quinto eje y no lo agrega acá,
    los tests de arriba siguen en verde sobre los cuatro que sí conocen — y el nuevo queda
    sin vigilancia, que es exactamente el modo de falla que este archivo previene."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[2]
    cableados = set()
    for ctx in sorted(raiz.glob("modules/*/ai_context.py")):
        if "contexto_del_perfil_del_sector" in ctx.read_text(encoding="utf-8"):
            cableados.add(ctx.parent.name)
    declarados = {m.split(".")[1] for m, _p, _s in EJES_CABLEADOS.values()}
    faltan = cableados - declarados
    assert not faltan, (
        f"estos ejes arman el bloque y no están en EJES_CABLEADOS: {sorted(faltan)}. "
        "Su plantilla podría no pedirlo y nadie se enteraría")


# ─── La capacidad de pago del hogar (fase 6) ──────────────────────────────────
#
# Se reparte SOLO donde la lectura significa algo, y la lectura cambia por eje: demanda de
# vivienda en construcción, costo laboral en zonas francas, demanda interna en turismo,
# asequibilidad del servicio en telecom. Deliberadamente NO va en `law`, `esg`, `trade` ni
# `macro`: ahí sería relleno.
EJES_CON_CAPACIDAD_DE_PAGO = {
    "construction": ("modules.construction_intel.products", "construction_outlook"),
    "free_zones": ("modules.free_zones_intel.products", "free_zones_outlook"),
    "tourism": ("modules.tourism_intel.products", "tourism_outlook"),
    "telecom": ("modules.telecom_intel.products", "telecom_outlook"),
}


@pytest.mark.parametrize("eje", sorted(EJES_CON_CAPACIDAD_DE_PAGO))
def test_la_capacidad_de_pago_LLEGA_al_contexto(eje):
    """La mitad que se olvida.

    En la fase 4 el financiamiento llegó al payload y la prosa no lo usó nunca, porque el
    contexto del modelo no lo tenía. Un eje que la sume al payload y no al `base_ctx` queda
    con el dato viajando sin que el modelo pueda verlo, y nada falla.
    """
    import importlib
    mod = importlib.import_module(EJES_CON_CAPACIDAD_DE_PAGO[eje][0])
    arbol = ast.parse(inspect.getsource(mod))
    # Se exige la ASIGNACIÓN al contexto, no la mención: el comentario que explica esto
    # nombra la clave y un test de texto se satisfaría con eso.
    asignada = any(
        isinstance(n, ast.Dict)
        and any(isinstance(k, ast.Constant) and k.value == "capacidad_de_pago"
                for k in n.keys if k is not None)
        for n in ast.walk(arbol))
    assert asignada, (
        f"{eje}: la capacidad de pago no entra al contexto del modelo. Viaja en el payload y "
        "la prosa no la puede usar")


@pytest.mark.parametrize("eje", sorted(EJES_CON_CAPACIDAD_DE_PAGO))
def test_la_plantilla_PIDE_la_capacidad_de_pago_con_SU_lectura(eje):
    """Lo que cambia entre ejes es la LECTURA, no el dato. Si la plantilla solo la nombrara,
    el modelo escribiría el mismo párrafo de inflación en los cuatro."""
    _mod, plantilla = EJES_CON_CAPACIDAD_DE_PAGO[eje]
    texto = THIN_TEMPLATES[plantilla]
    assert "capacidad_de_pago" in texto, f"{eje}: la plantilla no la pide"
    assert "ESTA lectura" in texto, (
        f"{eje}: la plantilla la nombra pero no dice CÓMO leerla en este eje")
    assert "a qué año" in texto, (
        f"{eje}: no exige citar el año de la capa, que no es el del informe")
    assert "no la menciones" in texto, (
        f"{eje}: manda a declarar la ausencia, contra la decisión del 2026-08-31")


def test_cada_eje_lee_las_capas_NUEVAS_de_una_forma_DISTINTA():
    """La misma disciplina que la capacidad de pago, sobre actividad/ocupación/IED.

    Cinco plantillas con el mismo párrafo sobre inversión extranjera serían relleno
    repartido: la capa llegaría a los cinco informes diciendo lo mismo, que es indistinguible
    de no haberla traído. Se recorta la lectura ENTERA, no un prefijo — un prefijo deja pasar
    una copia parcial, y en este repo ya pasó.
    """
    lecturas = {}
    for eje, (_m, plantilla, _slug) in EJES_CABLEADOS.items():
        t = THIN_TEMPLATES[plantilla]
        i = t.index("Y si el contexto trae ")
        fin = t.index("Cada una de estas capas trae SU propia fecha", i)
        lecturas[eje] = " ".join(t[i:fin].split())
    assert len(set(lecturas.values())) == len(lecturas), (
        f"hay ejes con la MISMA lectura de las capas nuevas: {sorted(lecturas)}")


def test_cada_eje_tiene_una_lectura_DISTINTA():
    """La prueba negativa: cuatro plantillas con el mismo párrafo serían relleno repartido.

    Se recorta la lectura ENTERA —de «ESTA lectura:» hasta el aviso común sobre el año— y no
    un prefijo de N caracteres. La primera versión comparaba los primeros 160 y una copia
    PARCIAL se le escapaba: dos ejes podían compartir la mitad del párrafo y el test daba
    verde. Comprobado por mutación.
    """
    lecturas = {}
    for eje, (_m, plantilla) in EJES_CON_CAPACIDAD_DE_PAGO.items():
        t = THIN_TEMPLATES[plantilla]
        i = t.index("ESTA lectura:")
        fin = t.index("No es una capa del índice", i)
        lecturas[eje] = " ".join(t[i:fin].split())
    assert len(set(lecturas.values())) == len(lecturas), (
        f"hay ejes con la MISMA lectura: {lecturas}")


def test_los_ejes_donde_seria_RELLENO_no_la_reciben():
    """`law`, `esg`, `trade` y `macro` quedaron fuera a propósito. Si alguien la agrega sin
    una lectura propia, esto lo frena: repartir un bloque por completitud es lo contrario de
    enriquecer."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[2]
    for mod in ("law_intel", "esg_climate", "trade_intel"):
        fuente = raiz / "modules" / mod / "products.py"
        if not fuente.exists():
            continue
        assert "capacidad_de_pago" not in fuente.read_text(encoding="utf-8"), (
            f"{mod} recibió la capacidad de pago: se decidió que ahí no significa nada. "
            "Si cambió el criterio, agregá su lectura a la plantilla y quitalo de este test")
