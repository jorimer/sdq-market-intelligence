"""REGLA ESTRUCTURAL: una acusación computada NO llega sola al informe.

**El aviso que la motiva (2026-08-19).** El emisor de la base normativa reportó un fallo
propio: hasta esa fecha, `tipo=decreto` no devolvía los reglamentos que su corpus clasificaba
aparte. Eran 38, y 18 caían dentro del rango donde el alcance sale `vacio_es_concluyente:
true`. Una consulta por uno de esos 18 devolvía CERO resultados con el vacío marcado como
concluyente — y siguiendo su guía correctamente, eso autoriza a publicar «no se dictó» sobre
una norma que existía en su propia base.

**Nuestra exposición fue cero, y conviene ser preciso sobre por qué.** Una sola obligación
declara consulta (art-54, `tipo: decreto`) y su veredicto es `cumplida_tarde`, no una
acusación. Pero si hubiera sido una de las 18, habríamos recibido `incumplida` con el alcance
diciendo que era concluyente, y no teníamos forma de saberlo.

Lo que sí nos protegió estructuralmente es que **el veredicto del API no alimenta el informe**:
se computa a pedido en su ruta, y el estado que la narrativa lee es el del expediente
comiteado. Entre el cómputo y la publicación hay una persona que promueve.

Eso era cierto por secuencia de implementación, no por decisión declarada. Este test lo
vuelve decisión: si alguien conecta la verificación en vivo al contexto de IA, una acusación
de un emisor con un fallo llega al PDF de un cliente sin que nadie la haya mirado. El
destinatario de estos informes suele ser el órgano acusado.
"""
import ast
import pathlib

MOD = pathlib.Path(__file__).resolve().parent.parent

#: El módulo que computa veredictos contra la base normativa externa.
_FUENTE_DE_ACUSACIONES = "normativa"
#: Superficies que ARMAN lo que el modelo redacta. Ninguna puede computar una acusación.
_SUPERFICIES_DE_NARRATIVA = ("ai_context.py", "products.py")


def _importa(archivo: pathlib.Path, modulo: str) -> bool:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    for n in ast.walk(arbol):
        if isinstance(n, ast.ImportFrom) and modulo in (n.module or ""):
            return True
        if isinstance(n, ast.Import) and any(modulo in a.name for a in n.names):
            return True
    return False


def test_la_narrativa_no_computa_acusaciones_contra_la_base_externa():
    culpables = [f for f in _SUPERFICIES_DE_NARRATIVA
                 if (MOD / f).exists() and _importa(MOD / f, _FUENTE_DE_ACUSACIONES)]
    assert not culpables, (
        f"{culpables} computa veredictos normativos en vivo. Una acusación de un emisor con "
        "un fallo llegaría al informe sin que nadie la mirara — y el destinatario suele ser "
        "el órgano acusado. El estado publicable es el del expediente COMITEADO.")


def test_el_contexto_de_IA_lee_el_expediente_comiteado():
    """La contracara: si dejara de leer el expediente, el informe perdería el único estado
    que pasó por una persona."""
    assert _importa(MOD / "ai_context.py", "obligaciones")


def test_la_regla_tiene_dientes():
    """Antes de confiar en un test estructural hay que verlo rechazar el código que veta."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write("from modules.law_intel.normativa import comprobar\n")
        ruta = pathlib.Path(f.name)
    assert _importa(ruta, _FUENTE_DE_ACUSACIONES), (
        "la forma exacta que el test prohíbe tiene que dar positivo")
    ruta.unlink()
