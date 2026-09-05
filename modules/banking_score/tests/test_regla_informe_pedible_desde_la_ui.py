"""Todo informe de SISTEMA del backend se puede pedir desde la interfaz.

**Cuarta pieza que le faltó al mismo tipo de informe.** El anuario del sistema llegó a
producción con su endpoint (#945), su plantilla de narrativa (#946) y su etiqueta de portada
(#947) — y sin registro en el frontend. Resultado: un producto terminado que **nadie podía
pedir desde la aplicación**, y que se reportó como completo porque se verificó por API.

Ninguna de las cuatro FALLÓ. Cada una hacía que el tipo DESAPARECIERA en una superficie
distinta, que es el modo de falla más caro de este repo. Y la lección escrita —«al agregar un
tipo, buscá TODOS los diccionarios que lo indexan por clave»— ya estaba en la memoria del
proyecto cuando ocurrió: se revisaron los del backend, y el registro del frontend es uno más.

**Por qué la regla vive del lado de Python.** El barrido necesita leer las DOS superficies, y
el test de TypeScript no puede: el build type-checkea los tests y traer `node:fs` mete APIs de
Node que el proyecto no tipa —lo documenta `frontend/src/shared/api/rutas-sin-prefijo.test.ts`,
que por eso usa `import.meta.glob`—, y ese glob no alcanza fuera de `frontend/src`. Desde acá
se leen las dos.

**Qué queda afuera, a propósito:** los informes POR ENTIDAD, que la UI ofrece desde el selector
de banco y no desde esta lista. Acá solo van los de sistema, que son los que tienen endpoint
propio (`/<tipo>/generate`) y `bank_id` nulo.
"""
import json
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
ROUTER = RAIZ / "modules" / "banking_score" / "api" / "router_reports.py"
API_TS = RAIZ / "frontend" / "src" / "modules" / "banking-score" / "api.ts"
I18N = RAIZ / "frontend" / "src" / "shared" / "i18n"
#: Los TRES idiomas. El mensaje de error de este test ya decía «en los tres idiomas» pero
#: la regla solo leía `es.json`: un tipo nuevo podía salir con su clave técnica en pantalla
#: para cualquier usuario que no fuera hispanohablante, y ningún test lo veía.
IDIOMAS = ("es.json", "en.json", "fr.json")
PDF_GENERATOR = RAIZ / "modules" / "banking_score" / "reports" / "pdf_generator.py"

#: `@router.post("/<algo>/generate")` — la forma de un informe de sistema.
_RUTA = re.compile(r'@router\.post\(\s*\n?\s*"/([a-z-]+)/generate"')


def tipos_del_backend() -> set:
    return {m.group(1).replace("-", "_") for m in _RUTA.finditer(ROUTER.read_text())}


def _lista_ts(nombre: str) -> set:
    """El contenido de un `export const <nombre> = [ … ] as const;`."""
    m = re.search(rf"export const {nombre} = \[(.*?)\] as const;",
                  API_TS.read_text(), re.S)
    return set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()


def _mapa_ts(nombre: str) -> set:
    """Las claves de un `const/export const <nombre>: Record<…> = { … };`."""
    m = re.search(rf"(?:export )?const {nombre}[^=]*= \{{(.*?)\n\}};",
                  API_TS.read_text(), re.S)
    return set(re.findall(r"^\s*([a-z_]+):", m.group(1), re.M)) if m else set()


def test_el_barrido_encuentra_rutas():
    """Prueba negativa: si el patrón deja de calzar, la regla pasa sin mirar nada."""
    assert len(tipos_del_backend()) >= 3, (
        "el barrido no encontró informes de sistema en el router — la regla no protege nada")
    assert _lista_ts("SYSTEM_REPORT_TYPES"), "no se pudo leer SYSTEM_REPORT_TYPES del frontend"


def test_todo_informe_de_sistema_se_puede_pedir_desde_la_interfaz():
    faltan = sorted(tipos_del_backend() - _lista_ts("SYSTEM_REPORT_TYPES"))
    assert not faltan, (
        f"Estos informes existen en el backend y NO se pueden pedir desde la aplicación: "
        f"{faltan}. Agregalos a SYSTEM_REPORT_TYPES, SYSTEM_REPORT_PATH y "
        "SYSTEM_REPORT_NEEDS_PERIOD en frontend/src/modules/banking-score/api.ts, y a "
        "banking.repType en los tres idiomas.")


def test_la_interfaz_no_ofrece_un_informe_sin_endpoint():
    """El contrapeso: sin él, la regla se satisface agregando tipos inventados y el usuario
    recibe un 404 al apretar el botón."""
    sobran = sorted(_lista_ts("SYSTEM_REPORT_TYPES") - tipos_del_backend())
    assert not sobran, f"la interfaz ofrece informes que el backend no tiene: {sobran}"


def test_cada_tipo_declara_su_ruta_y_si_necesita_periodo():
    tipos = _lista_ts("SYSTEM_REPORT_TYPES")
    # `SYSTEM_REPORT_ES_ANUAL` entra acá, y para eso dejó de ser un `Partial`: mientras lo
    # era, «ausente» significaba a la vez «no es anual» y «alguien se olvidó», y un tipo
    # anual sin su línea salía sin la advertencia de que resume el AÑO y no el corte.
    for mapa in ("SYSTEM_REPORT_NEEDS_PERIOD", "SYSTEM_REPORT_PATH",
                 "SYSTEM_REPORT_ES_ANUAL"):
        faltan = sorted(tipos - _mapa_ts(mapa))
        assert not faltan, f"{faltan} no están declarados en {mapa}"


@pytest.mark.parametrize("idioma", IDIOMAS)
def test_cada_tipo_tiene_etiqueta_y_no_es_la_clave_cruda(idioma):
    etiquetas = json.loads((I18N / idioma).read_text())["banking"]["repType"]
    for tipo in sorted(_lista_ts("SYSTEM_REPORT_TYPES")):
        assert etiquetas.get(tipo), (
            f"{tipo} saldría con su clave técnica en pantalla en {idioma}")
        assert etiquetas[tipo] != tipo, (
            f"la etiqueta de {tipo} repite la clave técnica en {idioma}")


def test_cada_tipo_tiene_su_etiqueta_de_PORTADA_en_el_PDF():
    """La etiqueta de portada fue UNA DE LAS CUATRO que le faltaron al anuario, y era la
    única de las cuatro sin guard de paridad.

    Sin ella el PDF sale rotulado con la clave técnica —o, peor, con el nombre de OTRO
    producto— en la portada y en el encabezado de cada página. Ya pasó: un informe salió
    como «Revisión Anual» siendo otra cosa.
    """
    fuente = PDF_GENERATOR.read_text()
    bloque = re.search(r"REPORT_TYPE_LABELS = \{(.*?)\n\}", fuente, re.S)
    assert bloque, "no se pudo leer REPORT_TYPE_LABELS de pdf_generator.py"
    etiquetas = set(re.findall(r'^\s*"([a-z_]+)":', bloque.group(1), re.M))
    faltan = sorted(tipos_del_backend() - etiquetas)
    assert not faltan, (
        f"{faltan} no declaran su etiqueta de portada en REPORT_TYPE_LABELS "
        f"(modules/banking_score/reports/pdf_generator.py): el PDF saldría rotulado con la "
        f"clave técnica.")
