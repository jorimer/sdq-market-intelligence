"""Todo archivo que ALIMENTA el contexto del modelo está declarado en `AI_CONTEXT_FILES`.

**Por qué importa.** El contenido de esos archivos entra en la huella de la caché de
narrativas (`shared/products/assembler._contexto_ia_version`). Un arreglo de contexto en un
archivo DECLARADO invalida y regenera; en uno no declarado, no invalida nada — y la corrección
queda muerta en Postgres, que no tiene TTL. Es el defecto que esa huella existe para cerrar,
y que ya ocurrió una vez con `concentracion_top4_pct`.

**El caso que lo destapó (2026-08-26).** `scoring/indicator_detail.py` estaba FUERA de la
lista, y `INDICATOR_META["que"]` es literalmente lo que el prompt le dice al modelo que MIDE
cada indicador (`_semantica_indicadores` lo pasa como `"mide"`). Corregir la descripción de un
indicador no habría invalidado ninguna narrativa. Lo mismo con `scoring/weights.py`, de donde
salen los `pesos_sub_componentes` del contexto.

**La regla, mecánica:** si el constructor de contexto IMPORTA un módulo del propio eje, lo que
ese módulo aporta llega al modelo, y el archivo tiene que estar declarado. Se lee el fuente con
`ast` en vez de confiar en que alguien se acuerde.

**Qué queda afuera, a propósito:** los imports de `shared/` — su huella la cubre
`_narrative_logic_version` (prompts, doctrina, modelo, guard), que es otra pieza de la misma
receta. Acá se vigila lo del EJE.
"""
import ast
import pathlib
from typing import Dict

RAIZ = pathlib.Path(__file__).resolve().parents[1]

#: Los archivos que construyen contexto. Si aparece otro, va acá.
CONSTRUCTORES = ("reports/narrative.py", "products.py", "products_year_review.py")

#: Módulos del eje que un constructor puede importar sin aportar NADA al contexto, con el
#: motivo. Una excepción sin motivo escrito es una omisión disfrazada.
#: El criterio para excluir NO es «computa desde la DB» —casi todos lo hacen— sino que NINGÚN
#: texto de su fuente llegue al modelo. `anuario.py` y `revision_anual.py` parecían encajar y
#: no encajaban: llevan reglas y lecturas escritas a mano ("los agregados se computan SOLO
#: sobre…", "el score del año es el DEL CIERRE…") que viajan enteras al prompt.
NO_APORTAN_CONTEXTO = {
    "models.models": "solo tipos ORM: los valores vienen de la DB, no del fuente",
    "reports.criteria_doc": "genera el documento de metodología, que NO se narra",
    "reports.pdf_generator": "renderiza el PDF; no arma contexto",
    "scoring.amplitude": "solo series de números (período, score); sin prosa — verificado",
    "historical_service": ("lo importa `credencial_evento_real()`, que alimenta la TABLA "
                          "COMERCIAL de credenciales (`/products/credenciales`), no el "
                          "contexto del modelo. Ninguna narrativa lee la cohorte de "
                          "quiebras: si algún día una la leyera, este módulo tiene que "
                          "MUDARSE a AI_CONTEXT_FILES o el arreglo quedaría muerto contra "
                          "la caché."),
    "ai_context_files": ("DECLARA la lista, no aporta contexto. Vive aparte porque la "
                         "comparten los DOS productos de banca y `products.py` ya importa "
                         "del anual: duplicarla es cómo una lista se desincroniza."),
}


def _declarados() -> set:
    from modules.banking_score.products import AI_CONTEXT_FILES
    return set(AI_CONTEXT_FILES)


def _importados_del_eje() -> dict:
    """`{ruta_relativa: archivo_que_lo_importa}` de cada módulo del eje que un constructor usa."""
    fuera: Dict[str, str] = {}
    for rel in CONSTRUCTORES:
        f = RAIZ / rel
        if not f.exists():
            continue
        for n in ast.walk(ast.parse(f.read_text(), filename=str(f))):
            if not isinstance(n, ast.ImportFrom) or not n.module:
                continue
            if not n.module.startswith("modules.banking_score."):
                continue
            sub = n.module[len("modules.banking_score."):]
            fuera.setdefault(sub, rel)
    return fuera


def test_el_barrido_encuentra_imports():
    """Prueba negativa: si el patrón deja de calzar, la regla pasa sin mirar nada."""
    assert len(_importados_del_eje()) >= 3, "el barrido no encontró imports del eje"
    assert _declarados(), "no se pudo leer AI_CONTEXT_FILES"


def test_todo_modulo_que_alimenta_el_contexto_esta_declarado():
    declarados = {d.replace("/", ".").removesuffix(".py") for d in _declarados()}
    sin_declarar = {
        sub: quien for sub, quien in _importados_del_eje().items()
        if sub not in declarados and sub not in NO_APORTAN_CONTEXTO
    }
    assert not sin_declarar, (
        f"Estos módulos del eje alimentan el contexto y NO están en AI_CONTEXT_FILES: "
        f"{sin_declarar}. Sin declararlos, corregir lo que el modelo lee NO invalida la caché "
        "de narrativas —que vive en Postgres y no tiene TTL— y el arreglo queda muerto. "
        "Agregalos, o agregalos a NO_APORTAN_CONTEXTO con el motivo.")


def test_ninguna_excepcion_sin_motivo():
    vacias = sorted(k for k, v in NO_APORTAN_CONTEXTO.items() if not (v or "").strip())
    assert not vacias, f"excepción sin motivo escrito: {vacias}"


def test_no_se_declara_un_archivo_que_no_existe():
    """Una entrada muerta hace creer que algo está cubierto cuando ya no está."""
    from shared.products.assembler import ruta_de_contexto

    # Misma resolución que el ensamblador, pedida y no copiada: `shared/...` sale de la raíz.
    faltan = sorted(d for d in _declarados()
                    if not ruta_de_contexto(d, "banking_score").exists())
    assert not faltan, f"AI_CONTEXT_FILES declara archivos inexistentes: {faltan}"
