"""Una familia de relación NUEVA declara su unidad, o su forma derivada se vetará en silencio.

**El defecto que esto cierra ya reincidió dos veces en una semana.** El guard determinista
compara la cifra del texto contra los NÚMEROS del contexto, no contra sus formas. Cada vez que
`derived.py` sirve una magnitud relacional en una sola forma, el modelo puede decirla en otra
—«1,32 veces» / «132 % del promedio» / «un 32 % más»— y el guard la marca como inventada. En
los dos casos reales el desenlace fue un informe entregado como error a un cliente.

`FORMAS_POR_CLAVE` cura eso declarando la UNIDAD de cada clave relacional. Pero una declaración
que hay que acordarse de actualizar es exactamente la clase de lección que este repo ya vio
fallar siete veces. Por eso se lee el fuente con `ast`: si aparece en `derived.py` una clave con
vocabulario de magnitud relacional, o está en el mapa, o está en la lista de excepciones de
abajo con su motivo escrito.

**Qué queda afuera del barrido, a propósito:** solo se mira `shared/narrative/derived.py`. Es
el único lugar donde se computan relaciones —esa es la doctrina «las relaciones se COMPUTAN,
no se derivan»—, así que un módulo que se arme sus propias razones a mano ya está violando una
regla anterior a ésta. Si eso cambia, este glob tiene que crecer con ello.
"""
import ast
import pathlib

from shared.narrative.numeric_guard import FORMAS_POR_CLAVE

FUENTE = pathlib.Path(__file__).resolve().parents[1] / "derived.py"

#: Vocabulario que delata una magnitud relacional: un múltiplo, un factor, una cuota.
_VOCABULARIO = ("razon", "factor", "multiplo", "cuota", "veces", "proporcion")

#: Claves que TIENEN vocabulario relacional y aun así no admiten forma derivada, con el
#: motivo. Una excepción sin motivo es una omisión disfrazada.
EXCEPCIONES = {
    # Es texto, no una magnitud: la cláusula ya redactada para copiar.
    "razon_como_pct_del_referente_lectura": "no es un número",
}


def _claves_emitidas(arbol: ast.AST) -> set:
    """Toda clave que `derived.py` pone en una fila: literales de dict y kwargs de update()."""
    claves: set = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Dict):
            claves.update(k.value for k in nodo.keys
                          if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(nodo, ast.Call):
            claves.update(kw.arg for kw in nodo.keywords if kw.arg)
    return claves


def test_toda_clave_relacional_declara_su_unidad():
    arbol = ast.parse(FUENTE.read_text())
    candidatas = {k for k in _claves_emitidas(arbol)
                  if any(v in k.lower() for v in _VOCABULARIO)}
    assert candidatas, ("el barrido no encontró NINGUNA clave relacional en derived.py: el "
                        "test perdió su objeto y estaría pasando sin proteger nada")
    sin_declarar = sorted(candidatas - set(FORMAS_POR_CLAVE) - set(EXCEPCIONES))
    assert not sin_declarar, (
        "Estas claves de derived.py llevan una magnitud relacional y no declaran su unidad "
        f"en FORMAS_POR_CLAVE: {sin_declarar}. Sin la declaración, el modelo que diga esa "
        "misma cifra en otra forma —porcentaje, exceso, inversa— hará que el guard la marque "
        "como inventada y el informe no se entregue. Agregalas al mapa con su unidad, o a "
        "EXCEPCIONES con el motivo.")


def test_ninguna_excepcion_sin_motivo():
    vacias = sorted(k for k, v in EXCEPCIONES.items() if not (v or "").strip())
    assert not vacias, f"excepción sin motivo escrito: {vacias}"


def test_el_mapa_no_declara_claves_que_nadie_emite():
    """Una entrada muerta hace creer que una familia está cubierta cuando ya no existe."""
    claves = _claves_emitidas(ast.parse(FUENTE.read_text()))
    huerfanas = sorted(set(FORMAS_POR_CLAVE) - claves)
    assert not huerfanas, (
        f"FORMAS_POR_CLAVE declara claves que derived.py ya no emite: {huerfanas}. O se "
        "renombraron —y la familia real quedó sin declarar— o sobran.")
