"""REGLA ESTRUCTURAL: el disclaimer de una validación no lleva cifras escritas a mano.

**El caso que la motivó.** El reporte del IRMP declaraba `n_countries: 24` y 260
observaciones, y su propio disclaimer decía «5 países (N pequeño)». El 5 eran los pares de
validez convergente contra la calificación soberana — otra cosa, en otra sección del mismo
reporte. Cualquiera que comparara la frase con la tabla encontraba a la casa contradiciéndose,
y es exactamente el tipo de cifra que termina copiada en un documento comercial. El de
`social_dev` tenía la misma forma latente: «las mismas 10 regiones» y «N=10» escritos a mano,
ciertos hoy y falsos el día que una región se quede sin score.

**La regla.** En los constructores de reportes de validación (`modules/*/validation/*.py`), un
literal de texto asignado a `disclaimer` / `note` / `nota` / `caveat` no puede contener un
NÚMERO pegado a una palabra de POBLACIÓN (países, regiones, pares, observaciones, eventos…).
Esas cifras se computan del propio reporte y se interpolan; la prosa vive en constantes.

**Qué NO prohíbe.** Los UMBRALES (`≥10% interanual`, `solvencia <10%`, `caída ≥2 bandas`) son
parte de la definición del desenlace, no cuentas del panel: no cambian cuando cambia el dato.
Por eso la regla mira sustantivos de población, no cualquier dígito.
"""
import ast
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[3]
MODULOS = RAIZ / "modules"

_CLAVES = {"disclaimer", "note", "nota", "caveat", "caveats", "message", "mensaje"}

# Sustantivos que denotan el TAMAÑO del panel. Deliberadamente no incluye "bandas" ni "%":
# esos aparecen en definiciones de umbral, que son constantes de método.
_POBLACION = (
    "país", "países", "pais", "paises", "región", "regiones", "region",
    "par", "pares", "observacion", "observaciones", "observación",
    "evento", "eventos", "entidad", "entidades", "banco", "bancos",
    "aseguradora", "aseguradoras", "afp", "rama", "ramas", "año", "años",
)
_CIFRA_CON_POBLACION = re.compile(
    r"(?:\bN\s*=\s*\d+)|(?:\b\d[\d.,]*\s+(?:%s)\b)" % "|".join(_POBLACION),
    re.IGNORECASE,
)

# Excepciones declaradas: texto donde la cifra a mano es correcta y estable. Cada entrada
# explica por qué; una excepción sin motivo es un olvido con permiso.
EXCEPCIONES: dict = {}


def _archivos():
    for p in sorted(MODULOS.glob("*/validation/*.py")):
        if p.name == "__init__.py":
            continue
        yield p


def _literal_completo(nodo) -> str:
    """Concatena un literal partido en varias líneas; devuelve '' si no es literal puro."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        izq, der = _literal_completo(nodo.left), _literal_completo(nodo.right)
        return (izq + der) if (izq and der) else ""
    return ""


def _infracciones(path: pathlib.Path):
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    fallos = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Dict):
            for clave, valor in zip(nodo.keys, nodo.values):
                if not (isinstance(clave, ast.Constant) and clave.value in _CLAVES):
                    continue
                textos = []
                if isinstance(valor, ast.List):
                    textos = [_literal_completo(e) for e in valor.elts]
                else:
                    textos = [_literal_completo(valor)]
                for texto in textos:
                    if not texto:
                        continue  # f-string o llamada: la cifra se computa, que es la cura
                    m = _CIFRA_CON_POBLACION.search(texto)
                    if m and texto not in EXCEPCIONES:
                        fallos.append((nodo.lineno, m.group(0), texto[:90]))
    return fallos


def test_ningun_disclaimer_de_validacion_lleva_una_cuenta_escrita_a_mano():
    encontrados = []
    for path in _archivos():
        for lineno, cifra, muestra in _infracciones(path):
            encontrados.append(f"{path.relative_to(RAIZ)}:{lineno} → «{cifra}» en «{muestra}…»")
    assert not encontrados, (
        "Estas cifras del disclaimer están escritas a mano y el reporte computa las suyas "
        "aparte; cuando dejen de coincidir, el documento se contradice solo:\n  "
        + "\n  ".join(encontrados)
        + "\nComputalas del reporte e interpolálas (la prosa, en constantes)."
    )


def test_la_regla_atrapa_el_caso_que_la_motivo(tmp_path):
    """Sin esto, la regla podría quedar sin dientes y nadie se enteraría."""
    fuente = tmp_path / "report.py"
    fuente.write_text(
        'def build():\n'
        '    return {"disclaimer": ("Validación PRELIMINAR: 5 países (N pequeño). ")}\n',
        encoding="utf-8",
    )
    assert _infracciones(fuente), "La regla no reconoce el defecto original del IRMP."


def test_la_regla_no_confunde_un_umbral_con_una_cuenta(tmp_path):
    fuente = tmp_path / "report.py"
    fuente.write_text(
        'def build():\n'
        '    return {"caveats": ["Desenlace: caída ≥10% interanual y solvencia <10%.",\n'
        '                        "Se excluye el downgrade ≥2 bandas por sesgo de piso."]}\n',
        encoding="utf-8",
    )
    assert not _infracciones(fuente), "Un umbral de método no es una cuenta del panel."
