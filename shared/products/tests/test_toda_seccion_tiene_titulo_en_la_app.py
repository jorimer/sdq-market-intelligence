"""Toda sección que la app puede mostrar tiene TÍTULO en los tres idiomas — y el de SU eje.

La app titula cada sección del informe con `platform.catalog.section.<clave>`
(`frontend/src/modules/platform/sectionTitle.ts`) y, sin entrada, cae a la CLAVE con espacios:
el cliente leía «insurance pulse», «early warning» o «estado de la ley» mientras el PDF del
mismo informe traía el título del producto. Dos superficies en desacuerdo, y ningún test
fallaba. La regla existía solo para construcción; acá vale para todo el catálogo.

**Qué lee, y por qué con `ast`.** Sin importar los módulos —un import que falla no puede volver
invisible a un producto— y sin regex —un `)` en un comentario ya truncó la lista de un guard—.
De cada archivo que registra un producto:

1. las claves de su `_SECTION_TITLES`, que son las que su render sabe titular;
2. las de todo `sections=`: lo que el manifiesto declara por nivel —que es lo que viaja a la app
   como `commercial.sections`— y lo que un render arma aparte (el año por trimestres de banca,
   que depende del PERÍODO y no del nivel);

y además las secciones ESTÁNDAR (`STANDARD_SECTION_TITLES`), que el ensamblador agrega al final
de todo informe: el glosario salía en la app como «std glossary».

**Qué dejaba afuera el glob.** Los productos no se buscan por nombre de archivo —
`modules/*/products*.py` perdía `structure_product.py` y los dos de `app/`— sino por la llamada
a `register_product`. Y banca no declara `_SECTION_TITLES`: sus títulos viven en
`pdf_generator.NARRATIVE_SECTION_TITLES`, que titula además documentos que no pasan por el
catálogo (boletín, criterios). Por eso de banca se leen sus `sections=` y no ese diccionario.

**Una clave, varios ejes.** Una sola entrada no puede servir a dos ejes que titulan la misma
clave con sentidos distintos: `recommendation` es «Recomendación» en banca y «Lectura para
Decisión» en el resto del catálogo, y la app le decía «Recomendación» a todos. Para esas
claves la app busca primero `platform.catalog.sectionBySector.<eje>.<clave>`, y este guard
exige que cada eje cuyo PDF no coincide con la entrada general tenga la suya.

**Qué no ve.** Una narrativa que un producto agregue fuera de su manifiesto Y fuera de su
`_SECTION_TITLES`. Hoy no hay ninguna (`delta_mensual` está en el segundo), y sin título
tampoco saldría bien en el PDF.
"""
import ast
import functools
import json
import pathlib
import unicodedata
from typing import Dict, List, Optional, Tuple

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
I18N = RAIZ / "frontend" / "src" / "shared" / "i18n"
IDIOMAS = ("es", "en", "fr")
REPORT_SECTIONS = RAIZ / "shared" / "products" / "report_sections.py"
PDF_BANCA = RAIZ / "modules" / "banking_score" / "reports" / "pdf_generator.py"
#: Donde viven los productos. `shared/` no registra ninguno: es el framework.
BASES = ("modules", "app")
#: Los productos SIN `_SECTION_TITLES` propio: los titula el generador de banca. Se nombran
#: para que un producto nuevo que olvide el suyo no herede en silencio un diccionario ajeno.
TITULADOS_POR_EL_GENERADOR_DE_BANCA = {
    "modules/banking_score/products.py",
    "modules/banking_score/products_year_review.py",
}

#: Para cada clave que varios ejes titulan DISTINTO en su PDF: qué título representa la entrada
#: general `platform.catalog.section.<clave>`. Todo eje con otro título lleva su entrada en
#: `sectionBySector`. `None` = la general no representa a ninguno: es solo el último recurso y
#: cada eje que usa la clave lleva la suya. No es una transcripción que pueda envejecer: el
#: guard exige que el título exista en algún PDF y que la entrada general en español lo diga.
TITULO_QUE_REPRESENTA_LA_GENERAL: Dict[str, Optional[str]] = {
    # Todo el catálogo salvo banca. «Lectura para decisión» no es una recomendación, y
    # decírsela a un cliente con otra palabra cambia lo que el informe afirma.
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
    "risk_assessment": "Evaluación de Riesgos",
    # Seguros y pensiones nombran su panel —el mercado, las AFP—, y el panel es la población.
    "peer_positioning": None,
}


def _fuentes() -> List[pathlib.Path]:
    return [f for base in BASES for f in sorted((RAIZ / base).rglob("*.py"))
            if "tests" not in f.parts]


@functools.lru_cache(maxsize=None)
def archivos_de_producto() -> Tuple[pathlib.Path, ...]:
    """Todo archivo con una llamada a `register_product`, esté donde esté la llamada: sector
    registra un producto por clave dentro de un `for`, no en el cuerpo del módulo."""
    return tuple(
        f for f in _fuentes()
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "register_product"
               for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))))


def _constantes(arbol: ast.Module) -> Dict[str, ast.expr]:
    """Asignaciones de MÓDULO: `SECCION_X = "x"`, `_SECCIONES = (...)`, `A = B + (...)`."""
    tabla: Dict[str, ast.expr] = {}
    for nodo in arbol.body:
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name)):
            tabla[nodo.targets[0].id] = nodo.value
        elif (isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name)
              and nodo.value is not None):
            tabla[nodo.target.id] = nodo.value
    return tabla


def _claves(nodo: ast.expr, tabla: Dict[str, ast.expr],
            vistos: frozenset = frozenset()) -> Optional[List[str]]:
    """Las cadenas que produce una expresión, o `None` si este lector no sabe leerla —que no
    es lo mismo que «no produce ninguna»—."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return [nodo.value]
    if isinstance(nodo, ast.Name) and nodo.id in tabla and nodo.id not in vistos:
        return _claves(tabla[nodo.id], tabla, vistos | {nodo.id})
    if isinstance(nodo, (ast.Tuple, ast.List)):
        out: List[str] = []
        for elemento in nodo.elts:
            parte = _claves(elemento, tabla, vistos)
            if parte is None:
                return None
            out += parte
        return out
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        izq, der = _claves(nodo.left, tabla, vistos), _claves(nodo.right, tabla, vistos)
        return None if izq is None or der is None else izq + der
    if (isinstance(nodo, ast.ListComp) and len(nodo.generators) == 1
            and isinstance(nodo.elt, ast.Name)
            and isinstance(nodo.generators[0].target, ast.Name)
            and nodo.elt.id == nodo.generators[0].target.id):
        # `[s for s in ("a", "b") if s in narratives]`: el filtro quita claves, no las inventa.
        return _claves(nodo.generators[0].iter, tabla, vistos)
    return None


def _deriva_del_manifiesto(nodo: ast.expr) -> bool:
    """`list(level.sections)`: la lista es la del manifiesto, que ya se leyó en su literal."""
    if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id in ("list", "tuple") and len(nodo.args) == 1):
        nodo = nodo.args[0]
    return isinstance(nodo, ast.Attribute) and nodo.attr == "sections"


def secciones_de(fuente: str) -> Tuple[Dict[str, str], List[str]]:
    """(clave → de dónde salió, expresiones que el lector no supo leer) de un archivo."""
    arbol = ast.parse(fuente)
    tabla = _constantes(arbol)
    claves: Dict[str, str] = {}
    ilegibles: List[str] = []

    titulos = tabla.get("_SECTION_TITLES")
    if isinstance(titulos, ast.Dict):
        for k in titulos.keys:
            leidas = None if k is None else _claves(k, tabla)
            if leidas is None:
                ilegibles.append("_SECTION_TITLES: " + (ast.unparse(k) if k else "**…"))
            for clave in leidas or ():
                claves.setdefault(clave, "_SECTION_TITLES")
    elif titulos is not None:
        ilegibles.append("_SECTION_TITLES no es un dict literal")

    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        for kw in nodo.keywords:
            if kw.arg != "sections":
                continue
            leidas = _claves(kw.value, tabla)
            if leidas is None and not _deriva_del_manifiesto(kw.value):
                ilegibles.append(f"línea {nodo.lineno}: sections={ast.unparse(kw.value)}")
            for clave in leidas or ():
                claves.setdefault(clave, f"sections= (línea {nodo.lineno})")
    return claves, ilegibles


def _leer(archivo: pathlib.Path) -> Tuple[Dict[str, str], List[str]]:
    return secciones_de(archivo.read_text(encoding="utf-8"))


def _dict_de_titulos(nodo: ast.Dict, tabla: Dict[str, ast.expr]) -> Dict[str, str]:
    """Clave → título de un dict literal. Lo que no se sabe leer queda afuera, y entonces el
    test del PDF lo reporta como sección sin título: la omisión no es silenciosa."""
    out: Dict[str, str] = {}
    for k, v in zip(nodo.keys, nodo.values):
        claves = None if k is None else _claves(k, tabla)
        valor = _claves(v, tabla)
        if claves and valor and len(valor) == 1:
            for clave in claves:
                out[clave] = valor[0]
    return out


def _titulos_estandar() -> Dict[str, str]:
    arbol = ast.parse(REPORT_SECTIONS.read_text(encoding="utf-8"))
    tabla = _constantes(arbol)
    titulos = tabla["STANDARD_SECTION_TITLES"]
    assert isinstance(titulos, ast.Dict)
    return _dict_de_titulos(titulos, tabla)


def secciones_estandar() -> List[str]:
    titulos = _titulos_estandar()
    assert titulos, "STANDARD_SECTION_TITLES cambió de forma: enseñale al lector"
    return list(titulos)


def _titulos_del_generador_de_banca() -> Dict[str, str]:
    """Los pares literales de `NARRATIVE_SECTION_TITLES`. Las fusiones con los criterios y las
    estándar van dentro de un `try` y no se leen acá: las estándar se suman aparte."""
    arbol = ast.parse(PDF_BANCA.read_text(encoding="utf-8"))
    tabla = _constantes(arbol)
    out: Dict[str, str] = {}
    for nodo in arbol.body:
        if (isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == "NARRATIVE_SECTION_TITLES"
                        for t in nodo.targets)):
            out.update(_dict_de_titulos(nodo.value, tabla))
    return out


def titulos_del_pdf(archivo: pathlib.Path) -> Tuple[Dict[str, str], bool]:
    """(clave → título con que el PDF la imprime, ¿lo titula el generador de banca?)."""
    tabla = _constantes(ast.parse(archivo.read_text(encoding="utf-8")))
    propios = tabla.get("_SECTION_TITLES")
    if isinstance(propios, ast.Dict):
        return {**_titulos_estandar(), **_dict_de_titulos(propios, tabla)}, False
    return {**_titulos_estandar(), **_titulos_del_generador_de_banca()}, True


def _claves_de_sector(arbol: ast.Module, tabla: Dict[str, ast.expr]) -> List[str]:
    """El primer argumento de cada `register_product`: una constante, o la variable de un `for`
    que recorre un diccionario de módulo (sector registra un producto por clave)."""
    recorridos = {n.target.id: n.iter for n in ast.walk(arbol)
                  if isinstance(n, ast.For) and isinstance(n.target, ast.Name)}
    out: List[str] = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "register_product" and nodo.args):
            continue
        arg = nodo.args[0]
        leidas = _claves(arg, tabla)
        if leidas is None and isinstance(arg, ast.Name) and arg.id in recorridos:
            iterable = recorridos[arg.id]
            fuente: Optional[ast.expr] = (tabla.get(iterable.id)
                                          if isinstance(iterable, ast.Name) else iterable)
            if isinstance(fuente, ast.Dict):
                leidas = [c for k in fuente.keys if k is not None
                          for c in (_claves(k, tabla) or ())]
        assert leidas, f"no sé leer la clave de `register_product` de la línea {nodo.lineno}"
        out += leidas
    return out


@functools.lru_cache(maxsize=None)
def universo() -> Dict[str, Tuple[str, ...]]:
    """Clave de sección → dónde se declara. Es todo lo que la app puede llegar a titular."""
    donde: Dict[str, List[str]] = {}
    for archivo in archivos_de_producto():
        rel = archivo.relative_to(RAIZ).as_posix()
        for clave, origen in _leer(archivo)[0].items():
            donde.setdefault(clave, []).append(f"{rel} · {origen}")
    for clave in secciones_estandar():
        donde.setdefault(clave, []).append("shared/products/report_sections.py")
    return {k: tuple(v) for k, v in donde.items()}


@functools.lru_cache(maxsize=None)
def titulos_por_eje() -> Dict[str, Dict[str, str]]:
    """Clave de sección → {clave del eje → título de su PDF}, solo lo que ese eje muestra."""
    out: Dict[str, Dict[str, str]] = {}
    for archivo in archivos_de_producto():
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        ejes = _claves_de_sector(arbol, _constantes(arbol))
        titulos, _ = titulos_del_pdf(archivo)
        for seccion in _leer(archivo)[0]:
            for eje in ejes:
                if seccion in titulos:
                    out.setdefault(seccion, {})[eje] = titulos[seccion]
    return out


def _normal(texto: str) -> str:
    """Mismo título salvo mayúsculas, tildes y espacios: «Lectura para Decisión» y «Lectura
    para decisión» dicen lo mismo; «Recomendación» no."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.casefold().split())


def _catalogo_de_la_app(idioma: str) -> dict:
    return json.loads((I18N / f"{idioma}.json").read_text(encoding="utf-8")
                      )["platform"]["catalog"]


def _titulos_de_la_app(idioma: str) -> Dict[str, str]:
    return _catalogo_de_la_app(idioma)["section"]


def _titulos_por_eje_de_la_app(idioma: str) -> Dict[str, Dict[str, str]]:
    return _catalogo_de_la_app(idioma).get("sectionBySector") or {}


# ── El barrido encontró lo que tenía que encontrar ─────────────────────────────────

def test_el_barrido_ENCONTRO_todos_los_productos():
    """Un barrido vacío pasa en verde sin comprobar nada. Se cruza contra una segunda lectura
    —el texto— para que un cambio de forma de la llamada no saque productos en silencio."""
    por_ast = {f.relative_to(RAIZ).as_posix() for f in archivos_de_producto()}
    por_texto = {f.relative_to(RAIZ).as_posix() for f in _fuentes()
                 if "register_product(" in f.read_text(encoding="utf-8")}
    assert por_ast == por_texto
    assert len(por_ast) >= 17, sorted(por_ast)
    # Los que un glob por nombre de archivo dejaba afuera, nombrados uno por uno.
    for fuera_del_glob in ("modules/sector_intel/structure_product.py",
                           "modules/banking_score/products_year_review.py",
                           "app/products_macro.py", "app/products_monetary_policy.py"):
        assert fuera_del_glob in por_ast


def test_de_cada_producto_se_leyo_al_menos_una_seccion():
    vacios = [f.relative_to(RAIZ).as_posix() for f in archivos_de_producto() if not _leer(f)[0]]
    assert not vacios, f"el lector no sacó ninguna sección de: {vacios}"


def test_el_lector_sabe_leer_todo_sections_de_los_productos():
    """Una forma nueva que el lector no entienda no se salta: se enseña o se declara."""
    ilegibles = {f.relative_to(RAIZ).as_posix(): il
                 for f in archivos_de_producto() if (il := _leer(f)[1])}
    assert not ilegibles, f"formas que el guard no sabe leer: {ilegibles}"


@pytest.mark.parametrize("clave, forma", [
    ("delta_mensual", "clave de `_SECTION_TITLES` fuera del manifiesto"),
    ("anio_del_sistema", "literal en `sections=`"),
    ("executive_summary", "tupla de módulo en `sections=`"),
    ("soporte_soberano", "tupla concatenada con `+`"),
    ("nowcast", "constante `SECCION_*`"),
    ("anio_por_trimestres", "comprensión en el render, fuera del manifiesto"),
    ("std_glossary", "sección estándar del ensamblador"),
])
def test_el_lector_alcanza_cada_FORMA_de_declarar_una_seccion(clave, forma):
    assert clave in universo(), f"el lector no ve «{clave}» ({forma})"


def test_el_lector_no_inventa_claves():
    """Lo que no sabe leer lo reporta; lo que filtra una comprensión no lo agrega."""
    claves, ilegibles = secciones_de(
        'A = "a"\n_T = (A, "b")\n'
        '_SECTION_TITLES = {A: "x", **OTRO}\n'
        'f(sections=_T + ("c",))\n'
        'g(sections=[s for s in ("d",) if s in n])\n'
        'h(sections=list(level.sections))\n'
        'k(sections=otra_cosa())\n')
    assert set(claves) == {"a", "b", "c", "d"}
    assert len(ilegibles) == 2, ilegibles     # el `**OTRO` y el `otra_cosa()`


def test_las_claves_de_eje_se_leen_de_cada_registro():
    """La entrada por eje se indexa con la clave con que el producto se REGISTRA, que es la
    que la app recibe como `report.sector_key`."""
    ejes = {eje for por_eje in titulos_por_eje().values() for eje in por_eje}
    for esperado in ("banking", "banking_year_review", "macro", "monetary_policy",
                     "valuation", "insurance", "pension"):
        assert esperado in ejes
    # sector registra sus productos con un `for` sobre `SECTOR_PRODUCTS`: sin leer ese
    # recorrido, agribusiness no tendría clave de eje y ninguna entrada suya se exigiría.
    assert "agribusiness" in ejes, sorted(ejes)
    assert len(ejes) >= len(archivos_de_producto()), sorted(ejes)
    # El punto es el separador de claves de i18next: un eje con punto partiría la ruta.
    assert not [e for e in ejes if "." in e]


# ── La regla ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("idioma", IDIOMAS)
def test_toda_seccion_que_la_app_puede_mostrar_tiene_TITULO(idioma):
    titulos = _titulos_de_la_app(idioma)
    faltan = {k: v for k, v in sorted(universo().items())
              if not str(titulos.get(k) or "").strip()}
    assert not faltan, (
        f"{idioma}.json: {len(faltan)} secciones sin `platform.catalog.section` — la app "
        f"mostraría la clave con espacios: {faltan}")


def test_una_clave_que_los_ejes_titulan_distinto_no_se_resuelve_con_la_general():
    """La app le decía «Recomendación» a todo producto cuyo PDF dice «Lectura para
    Decisión». Cuando los PDFs de dos ejes titulan una clave distinto, la entrada general
    representa a lo sumo a uno, y el resto lleva su `sectionBySector`."""
    general_es = _titulos_de_la_app("es")
    por_eje_app = {idioma: _titulos_por_eje_de_la_app(idioma) for idioma in IDIOMAS}
    problemas = []
    divergentes = set()
    for seccion, por_eje in sorted(titulos_por_eje().items()):
        distintos = {_normal(t) for t in por_eje.values()}
        if len(distintos) < 2:
            continue
        divergentes.add(seccion)
        if seccion not in TITULO_QUE_REPRESENTA_LA_GENERAL:
            problemas.append(
                f"«{seccion}»: los ejes la titulan distinto {por_eje} — declarar en "
                "TITULO_QUE_REPRESENTA_LA_GENERAL a cuál representa la entrada general")
            continue
        representa = TITULO_QUE_REPRESENTA_LA_GENERAL[seccion]
        if representa is not None:
            if _normal(representa) not in distintos:
                problemas.append(f"«{seccion}»: «{representa}» no es el título de ningún PDF")
            if _normal(str(general_es.get(seccion) or "")) != _normal(representa):
                problemas.append(f"«{seccion}»: la entrada general dice "
                                 f"«{general_es.get(seccion)}» y debería decir «{representa}»")
        for eje, titulo in sorted(por_eje.items()):
            if representa is not None and _normal(titulo) == _normal(representa):
                continue
            for idioma in IDIOMAS:
                if not str(por_eje_app[idioma].get(eje, {}).get(seccion) or "").strip():
                    problemas.append(f"{idioma}.json: «{eje}» titula «{seccion}» como "
                                     f"«{titulo}» y no tiene `sectionBySector.{eje}.{seccion}`")
    sobrantes = sorted(set(TITULO_QUE_REPRESENTA_LA_GENERAL) - divergentes)
    assert not sobrantes, f"estas claves ya no divergen, borrá su declaración: {sobrantes}"
    assert not problemas, "\n".join(problemas)


def test_cada_entrada_por_eje_existe_en_los_tres_idiomas_y_copia_su_PDF():
    """Tres maneras de que una entrada por eje mienta sin fallar: que falte en un idioma —con
    `fallbackLng: "es"` no cae a la general, cae al ESPAÑOL en una pantalla en inglés—, que
    apunte a un eje o una sección que no existen —nunca se aplica—, o que en español diga otra
    cosa que el PDF, que es justo el desacuerdo que vino a cerrar."""
    reales = titulos_por_eje()
    por_eje_app = {idioma: _titulos_por_eje_de_la_app(idioma) for idioma in IDIOMAS}
    pares = {idioma: {(eje, sec) for eje, d in por_eje_app[idioma].items() for sec in d}
             for idioma in IDIOMAS}
    assert pares["es"] == pares["en"] == pares["fr"], {
        idioma: sorted(pares[idioma] ^ pares["es"]) for idioma in IDIOMAS}
    huerfanas = sorted(p for p in pares["es"] if p[0] not in reales.get(p[1], {}))
    assert not huerfanas, f"entradas para un eje o una sección que no existen: {huerfanas}"
    distintas = {f"{eje}.{sec}": (por_eje_app["es"][eje][sec], reales[sec][eje])
                 for eje, sec in sorted(pares["es"])
                 if _normal(por_eje_app["es"][eje][sec]) != _normal(reales[sec][eje])}
    assert not distintas, f"la entrada en español no dice lo que dice el PDF: {distintas}"


# ── La otra mitad del desacuerdo: el PDF ───────────────────────────────────────────

def test_toda_seccion_del_catalogo_tiene_TITULO_en_el_PDF():
    """Sin título, los dos renders caen a la clave: `clave.replace("_", " ").title()`. El
    año del sistema salía impreso «Anio Del Sistema» —sin eñe y con mayúsculas de
    identificador— en la portada del anuario, el mismo defecto que ya había tenido el año
    por trimestres. Lo encontró el barrido de la app, y la app no era la única superficie."""
    assert "anio_por_trimestres" in _titulos_del_generador_de_banca(), (
        "el lector no vio el diccionario de banca")
    sin_titulo = {}
    sin_diccionario = set()
    for archivo in archivos_de_producto():
        rel = archivo.relative_to(RAIZ).as_posix()
        titulos, de_banca = titulos_del_pdf(archivo)
        if de_banca:
            sin_diccionario.add(rel)
        faltan = sorted(set(_leer(archivo)[0]) - set(titulos))
        if faltan:
            sin_titulo[rel] = faltan
    assert sin_diccionario == TITULADOS_POR_EL_GENERADOR_DE_BANCA
    assert not sin_titulo, f"secciones sin título en el PDF: {sin_titulo}"
