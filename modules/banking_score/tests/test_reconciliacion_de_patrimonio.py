"""El sensor de T-VL-1: patrimonio y utilidad tienen que reconciliar con lo publicado.

**Por qué importa más acá que en cualquier otro eje.** El valuador se construye sobre estas
dos cifras. Un valuador que multiplica un patrimonio equivocado por un múltiplo correcto
entrega una valuación equivocada **con toda la apariencia de estar bien** — no falla, no
avisa, y el número sale firmado.

**Lo que este archivo prueba y lo que no.** La reconciliación contra el estado publicado por
la Superintendencia es una verificación EN VIVO y vive en
`scripts/qa_reconciliacion_patrimonio.py`, que sale con código distinto de cero si alguna
entidad queda fuera de tolerancia. Acá se fija lo que un test offline sí puede fijar: que el
script exista, que declare al menos tres entidades —menos no distingue un mapeo correcto de
una coincidencia—, y **que el campo del que lee contenga lo que la reconciliación supone**.

**La trampa que este test documenta.** `patrimonio_tecnico` NO contiene patrimonio técnico:
contiene el patrimonio CONTABLE del balance. La ETL lo hace a propósito y con el motivo
escrito —la métrica que lo consume es patrimonio/activos, que necesita el contable—, y las
cifras de Basilea de verdad viven aparte (`capital_primario`, `capital_tier1`, `apr`). Pero el
nombre miente, y quien lea el campo esperando capital regulatorio va a computar un índice de
solvencia que no lo es. Se deja fijado por test para que la próxima persona lo lea acá y no
lo descubra en un informe.
"""
import ast
import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[3]
_SCRIPT = _RAIZ / "scripts" / "qa_reconciliacion_patrimonio.py"
_ETL = _RAIZ / "shared" / "data" / "sib_data_client.py"


def _modulo(p: pathlib.Path):
    return ast.parse(p.read_text())


def _constante(arbol, nombre):
    for n in arbol.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == nombre:
                    return n.value
    return None


def test_el_script_de_reconciliacion_existe():
    assert _SCRIPT.exists(), (
        "sin la reconciliación contra el estado publicado, T-VL-1 no tiene sensor y el "
        "valuador se construiría sobre cifras que nadie contrastó")


def test_declara_al_menos_tres_entidades():
    """El mínimo del sensor. Con una o dos, un mapeo correcto no se distingue de un acierto
    por casualidad."""
    arbol = _modulo(_SCRIPT)
    equivalencias = _constante(arbol, "EQUIVALENCIAS")
    assert isinstance(equivalencias, ast.Dict)
    assert len(equivalencias.keys) >= 3

    minimo = _constante(arbol, "MINIMO_DE_ENTIDADES")
    assert isinstance(minimo, ast.Constant) and minimo.value >= 3


def test_las_equivalencias_de_nombre_se_DECLARAN(fixture=None):
    """No se emparejan por similitud de cadenas.

    Un emparejador difuso que acierta el 95 % de las veces falla en la entidad grande justo
    cuando importa, y el error se ve como una discrepancia de dato en vez de como lo que es.
    """
    fuente = _SCRIPT.read_text()
    for sospechoso in ("SequenceMatcher", "difflib", "fuzz", "get_close_matches"):
        assert sospechoso not in fuente, (
            f"el script empareja nombres con «{sospechoso}»: las equivalencias se declaran")


def test_reconcilia_las_DOS_cifras():
    """Patrimonio solo no alcanza: el valuador necesita las dos, y un ETL puede acertar una
    y errar la otra."""
    fuente = _SCRIPT.read_text()
    assert "patrimonio_tecnico" in fuente and "utilidad_neta" in fuente
    assert "Resultado del ejercicio" in fuente, "no consulta la utilidad publicada"


def test_patrimonio_tecnico_contiene_el_patrimonio_CONTABLE():
    """El campo se llama «técnico» y guarda el contable. Es deliberado y está documentado en
    la ETL; se fija acá porque la reconciliación lo supone y porque el nombre engaña.

    Si alguien "arregla" el nombre poniendo capital regulatorio, la reconciliación contra el
    estado publicado empieza a fallar — y este test explica por qué antes de que alguien lo
    investigue de cero.
    """
    fuente = _ETL.read_text()
    assert "patrimonio_tecnico = patrimonio_neto" in fuente, (
        "la ETL dejó de poner el patrimonio contable en `patrimonio_tecnico`; la "
        "reconciliación contra el «Patrimonio» publicado por la SB ya no aplica")


def test_las_cifras_de_basilea_viven_aparte():
    """El corolario que hace tolerable el nombre engañoso: el capital regulatorio de verdad
    NO se perdió, está en sus propios campos."""
    fuente = _ETL.read_text()
    for campo in ("capital_primario", "capital_tier1", "apr"):
        assert campo in fuente, f"falta {campo}: el capital regulatorio no tiene dónde vivir"
