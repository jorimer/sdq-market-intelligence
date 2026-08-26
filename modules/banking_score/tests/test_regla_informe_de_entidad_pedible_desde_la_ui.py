"""Todo informe de ENTIDAD del backend se puede pedir desde la interfaz.

Hermana de `test_regla_informe_pedible_desde_la_ui`, que cubre los de SISTEMA. Hacen falta las
dos: la UI tiene DOS listas —una por el selector de entidad y otra por los boletines de
sistema— y un tipo nuevo cae en una o en otra. Cubrir solo una deja la mitad del hueco abierto,
que es literalmente el patrón que este repo repite («un guard existe en un motor y falta en el
otro», cinco instancias).

El backend es la fuente: `REPORT_SECTIONS` menos los tipos que tienen endpoint propio de
sistema. Duplicar la lista acá sería el mismo defecto con otra cara.
"""
import json
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[3]
PAGINA = RAIZ / "frontend" / "src" / "modules" / "banking-score" / "pages" / "ReportsPage.tsx"
ES_JSON = RAIZ / "frontend" / "src" / "shared" / "i18n" / "es.json"
ROUTER = RAIZ / "modules" / "banking_score" / "api" / "router_reports.py"

#: `criteria` no se ofrece desde el selector de entidad: es la METODOLOGÍA, no depende de un
#: banco, y vive en la lista de sistema. Su ausencia acá es una decisión, no un olvido.
NO_SON_DE_ENTIDAD = {"criteria"}


def _tipos_de_sistema() -> set:
    return {m.group(1).replace("-", "_") for m in
            re.finditer(r'@router\.post\(\s*\n?\s*"/([a-z-]+)/generate"', ROUTER.read_text())}


def tipos_de_entidad() -> set:
    from modules.banking_score.reports.narrative import REPORT_SECTIONS
    return set(REPORT_SECTIONS) - _tipos_de_sistema() - NO_SON_DE_ENTIDAD


def _ofrecidos_en_la_ui() -> set:
    m = re.search(r"const REPORT_TYPE_VALUES = \[(.*?)\];", PAGINA.read_text(), re.S)
    return set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()


def test_el_barrido_encuentra_tipos():
    """Prueba negativa: si los patrones dejan de calzar, la regla pasa sin mirar nada."""
    assert tipos_de_entidad(), "no se encontró ningún informe de entidad"
    assert _ofrecidos_en_la_ui(), "no se pudo leer REPORT_TYPE_VALUES del frontend"


def test_todo_informe_de_entidad_se_puede_pedir_desde_la_interfaz():
    faltan = sorted(tipos_de_entidad() - _ofrecidos_en_la_ui())
    assert not faltan, (
        f"Estos informes de entidad existen en el backend y NO se pueden pedir desde la "
        f"aplicación: {faltan}. Agregalos a REPORT_TYPE_VALUES en ReportsPage.tsx y a "
        "banking.repType en los tres idiomas.")


def test_la_interfaz_no_ofrece_un_informe_que_el_backend_no_sabe_generar():
    """El contrapeso: sin él, la regla se satisface con tipos inventados y el usuario recibe
    un error al apretar el botón."""
    from modules.banking_score.reports.narrative import REPORT_SECTIONS
    sobran = sorted(_ofrecidos_en_la_ui() - set(REPORT_SECTIONS))
    assert not sobran, f"la interfaz ofrece informes sin secciones registradas: {sobran}"


def test_cada_informe_de_entidad_tiene_etiqueta_y_no_es_la_clave_cruda():
    etiquetas = json.loads(ES_JSON.read_text())["banking"]["repType"]
    for tipo in sorted(_ofrecidos_en_la_ui()):
        assert etiquetas.get(tipo), f"{tipo} saldría con su clave técnica en el selector"
        assert etiquetas[tipo] != tipo, f"la etiqueta de {tipo} repite la clave técnica"
