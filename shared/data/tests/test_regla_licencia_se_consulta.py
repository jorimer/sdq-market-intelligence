"""Una licencia declarada se CONSULTA antes de ingerir, o no sirve de nada.

**El defecto que lo obligó.** Los cuatro conectores de la Superintendencia de Bancos
declaraban `license`/`license_ok` y ninguno los miraba: no heredaban del contrato de
`shared.data.base_client`, así que `check_license()` jamás corría. El gate hermano
—`test_regla_licencia_declarada`— estaba verde todo ese tiempo, y con razón: comprueba que
la cadena esté REGISTRADA, no que alguien la consulte. Son dos preguntas distintas y hacían
falta las dos.

**Por qué un test y no una lección escrita.** Al arreglar los cuatro se descubrió que el
mismo patrón está vivo en otros doce conectores de `shared/data/`: declaran `license_ok` y
no lo consultan nunca, porque no heredan de nada. Un defecto con trece instancias no se
cura con una convención — se cura con un barrido que impide la catorce. Los doce quedan
LISTADOS abajo con nombre propio: la deuda no desaparece de la vista, solo deja de crecer.

**Qué NO marca, y por qué.** Una clase que hereda de `FixtureBackedClient` sin sobreescribir
`fetch` está cubierta por el `fetch` del padre, que llama al gate como primera sentencia
(`DGAClient`, `SIPENClient`). Marcarla sería un falso positivo — y un detector que no puede
explicar por qué un caso bueno queda limpio todavía no es un detector.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
PAQUETES = ("shared", "modules", "app")

#: Quien define el gate, no quien lo consume.
_EXCLUIDOS = {pathlib.Path("shared/data/base_client.py")}

_BASES_DEL_CONTRATO = {"SourceClient", "FixtureBackedClient"}
_LLAMADAS_AL_GATE = {"check_license", "check_license_for"}

#: Lo que hace de algo un cliente de datos: DECLARAR la licencia de una fuente. Y es
#: `license` —no `license_ok`— lo que define al sujeto, porque el defecto original fue
#: exactamente declarar la cadena sin el booleano: la primera versión de este guard pedía
#: `license_ok` y por eso pasó en VERDE contra los cuatro conectores rotos que lo
#: motivaron. Medía la propiedad cómoda en vez de la que define el caso.
_MARCAS_DE_CLIENTE = {"license", "license_ok", "LICENSE", "LICENSE_OK"}

#: Y lo que lo distingue de un PORTADOR: traer el dato de afuera. Un modelo de SQLAlchemy
#: con una columna `license`, o un dataclass como `Lineage`, declaran la licencia y no
#: ingieren nada — no hay nada que frenar en ellos. La segunda versión de este guard los
#: marcaba a los 33 y la lista se volvía ruido. El caso que importa es el que SALE A LA RED
#: con una licencia que nunca miró.
#: `Client`/`Session` están acá porque son la forma MÁS común en este repo —diez conectores
#: hacen `with httpx.Client(...) as http: http.get(...)`— y una primera versión que solo
#: miraba `httpx.get(...)` los daba por limpios a los diez.
_EGRESS = {"get", "post", "put", "stream", "request", "urlopen", "urlretrieve", "read_html",
           "read_csv", "read_excel", "Client", "AsyncClient", "Session"}
_LIBRERIAS_DE_RED = {"httpx", "requests", "urllib", "aiohttp", "pd", "pandas"}

#: Conectores que traen dato de afuera declarando una licencia que NUNCA consultan. Son
#: dos formas del mismo defecto: clases sueltas de `shared/data/` que no heredan del
#: contrato —el atributo queda decorativo— y módulos de funciones sin clase donde colgarlo.
#: Medido al 2026-09-04 cerrando T-BR-2, con el detector de abajo.
#:
#: Esta lista solo puede ACHICARSE. Un conector nuevo no entra acá — se arregla.
DEUDA_AL_2026_09_04 = {
    "shared/data/bcrd_labor.py:<módulo>",
    "shared/data/bcrd_prestamos_destino.py:<módulo>",
    "shared/data/cepalstat_client.py:<módulo>",
    "shared/data/cnzfe_client.py:CNZFEClient",
    "shared/data/comtrade_client.py:<módulo>",
    "shared/data/digepres_funcional.py:<módulo>",
    "shared/data/ember_client.py:EmberClient",
    "shared/data/generation_client.py:GenerationMixClient",
    "shared/data/gobdo_tramites.py:<módulo>",
    "shared/data/hacienda_cofog.py:<módulo>",
    "shared/data/hurdat2_client.py:HURDAT2Client",
    "shared/data/indotel_client.py:INDOTELClient",
    "shared/data/ipu_parline_client.py:<módulo>",
    "shared/data/itu_client.py:ITUClient",
    "shared/data/latinobarometro.py:<módulo>",
    "shared/data/minerd_coverage.py:<módulo>",
    "shared/data/mivhed_client.py:MIVHEDClient",
    "shared/data/one_areas_protegidas.py:<módulo>",
    "shared/data/one_construction.py:ONEConstructionClient",
    "shared/data/owid_disasters_client.py:OWIDDisastersClient",
    "shared/data/salario_minimo.py:<módulo>",
    "shared/data/sie_client.py:SIEClient",
    "shared/data/sisdom_common.py:<módulo>",
    "shared/data/sisdom_end.py:<módulo>",
    "shared/data/siuben_client.py:<módulo>",
    "shared/data/tourism_arrivals_client.py:TourismArrivalsClient",
}


def _declara(cuerpo, nombres):
    """¿Hay una asignación a alguno de *nombres* en este cuerpo?"""
    return any(
        isinstance(s, (ast.Assign, ast.AnnAssign))
        and any(isinstance(t, ast.Name) and t.id in nombres
                for t in (s.targets if isinstance(s, ast.Assign) else [s.target]))
        for s in cuerpo
    )


def _hace_egress(arbol):
    """¿Este archivo trae dato de afuera? Es lo que lo vuelve un cliente y no un portador."""
    for n in ast.walk(arbol):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr not in _EGRESS:
            continue
        raiz = n.func.value
        while isinstance(raiz, ast.Attribute):        # urllib.request.urlopen(...)
            raiz = raiz.value
        if isinstance(raiz, ast.Name) and raiz.id in _LIBRERIAS_DE_RED:
            return True
    return False


def _consulta_el_gate(nodo):
    return any(
        isinstance(n, ast.Call)
        and ((isinstance(n.func, ast.Attribute) and n.func.attr in _LLAMADAS_AL_GATE)
             or (isinstance(n.func, ast.Name) and n.func.id in _LLAMADAS_AL_GATE))
        for n in ast.walk(nodo)
    )


def _sujetos():
    """`(id, consulta_el_gate)` de cada cliente de datos del repo.

    Un cliente es: una clase que declara `license_ok` o hereda del contrato, o un módulo
    que declara `LICENSE_OK` (los conectores sin clase, que no tienen dónde heredar).
    """
    for paquete in PAQUETES:
        for path in sorted((RAIZ / paquete).rglob("*.py")):
            rel = path.relative_to(RAIZ)
            if "tests" in rel.parts or rel.name.startswith("test_") or rel in _EXCLUIDOS:
                continue
            try:
                arbol = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):        # pragma: no cover - defensivo
                continue

            egress = _hace_egress(arbol)

            # Para un conector sin clase, el sujeto es el ARCHIVO: no tiene dónde heredar.
            if egress and _declara(arbol.body, _MARCAS_DE_CLIENTE):
                yield f"{rel.as_posix()}:<módulo>", _consulta_el_gate(arbol)

            for n in arbol.body:
                if not isinstance(n, ast.ClassDef):
                    continue
                bases = {b.id for b in n.bases if isinstance(b, ast.Name)}
                hereda = bool(bases & _BASES_DEL_CONTRATO)
                declara = _declara(n.body, _MARCAS_DE_CLIENTE)
                if not (hereda or (declara and egress)):
                    continue
                # Hereda `fetch` del padre sin sobreescribirlo → el gate ya corre ahí.
                propio = any(isinstance(s, ast.FunctionDef) and s.name == "fetch"
                             for s in n.body)
                cubierto = _consulta_el_gate(n) or (hereda and not propio)
                yield f"{rel.as_posix()}:{n.name}", cubierto


_SUJETOS = sorted(_sujetos())


@pytest.mark.parametrize("sujeto,consulta", _SUJETOS, ids=[s for s, _ in _SUJETOS])
def test_todo_cliente_que_declara_licencia_la_consulta(sujeto, consulta):
    assert consulta or sujeto in DEUDA_AL_2026_09_04, (
        f"{sujeto} declara una licencia y nunca la consulta: no llama `check_license()` "
        f"ni `check_license_for()`, y no hereda el `fetch` del contrato que lo haría por "
        f"él. El atributo queda decorativo — el dato entra igual, con la licencia negada "
        f"o sin ella. Llamá al gate en el punto de egress (el más temprano que toque la "
        f"red), o heredá de `shared.data.base_client.FixtureBackedClient`."
    )


def test_la_deuda_no_crece():
    """Ratchet: los doce conocidos pueden bajar, nunca subir."""
    sin_consultar = {s for s, consulta in _SUJETOS if not consulta}
    nuevos = sin_consultar - DEUDA_AL_2026_09_04
    assert not nuevos, (
        f"Conectores nuevos que declaran licencia sin consultarla: {sorted(nuevos)}. "
        f"La lista de deuda no se amplía: se arregla el conector.")


def test_el_barrido_ENCUENTRA_clientes():
    """Un `@parametrize` vacío sale SKIPPED y un barrido vacío sale PASSED.

    Si el glob deja de encontrar los conectores —una mudanza de carpeta, un `rglob` mal
    escrito—, el test de arriba pasa sin haber mirado uno solo.
    """
    assert len(_SUJETOS) >= 30, f"solo {len(_SUJETOS)} sujetos: el barrido se quedó ciego"


def test_el_chequeo_DETECTA_el_defecto_que_lo_originó():
    """El conector de banca tal como estaba: declara la licencia y no la consulta."""
    arbol = ast.parse(
        "class SIBDataClient:\n"
        "    source = 'SB'\n"
        "    license = 'SB — estadísticas...'\n"
        "    def extract_banking_data(self):\n"
        "        return httpx.get(self.base_url)\n")
    clase = arbol.body[0]
    assert _declara(clase.body, _MARCAS_DE_CLIENTE)
    assert not _consulta_el_gate(clase)


def test_el_chequeo_NO_marca_al_que_hereda_el_gate():
    """`DGAClient` no llama al gate en su cuerpo y está bien: lo llama el `fetch` del padre.

    Sin esta distinción el detector marcaría casos correctos, y una lista de deuda con
    falsos positivos se vuelve ruido que nadie mira.
    """
    arbol = ast.parse(
        "class DGAClient(FixtureBackedClient):\n"
        "    source = 'DGA'\n"
        "    license_ok = True\n"
        "    fixture_file = 'dga.json'\n")
    clase = arbol.body[0]
    hereda = bool({b.id for b in clase.bases} & _BASES_DEL_CONTRATO)
    propio = any(isinstance(s, ast.FunctionDef) and s.name == "fetch" for s in clase.body)
    assert not _consulta_el_gate(clase)
    assert hereda and not propio, "debe quedar cubierto por herencia, no marcado"
