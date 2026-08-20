"""El deck comercial no puede citar un Gini sin decir sobre quién se midió.

El catálogo (`scripts/build_catalogo_v4.py`) se GENERA desde `/products/credenciales`, así que
ninguna cifra se escribe a mano — ese fue el fix del v4. Pero traía el N y no la población, y
«Gini 0,2287 · n=1.693» leído en un documento de venta se entiende como discriminación **entre
bancos**, cuando casi la mitad de ese panel son entidades que no otorgan crédito.

Estos tests fijan que el sufijo de población se COMPUTE de la credencial y que aparezca solo
cuando corresponde: una coletilla que sale siempre deja de leerse.
"""
import importlib.util
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[3]


def _script():
    ruta = RAIZ / "scripts" / "build_catalogo_v4.py"
    spec = importlib.util.spec_from_file_location("build_catalogo_v4", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _credencial(cuota, cuota_ev=0.63, tipos=("cambiaria", "fiduciaria")):
    return {
        "nombre": "SDQ Banking", "publicable": True, "metrica": "Gini", "valor": 0.2287,
        "ic": [0.147, 0.311], "n": 1693, "eventos": 250, "senal": "resultados",
        "poblacion": {"sin_libro_de_credito": {
            "tipos": list(tipos), "n": 814,
            "cuota_de_observaciones": cuota, "cuota_de_eventos": cuota_ev}},
    }


def test_la_poblacion_viaja_pegada_al_N_en_la_fila():
    mod = _script()
    fila = mod._fila_credencial(_credencial(0.481))
    detalle = fila[-1]
    assert "n=1.693" in detalle
    assert "48 % del panel NO otorga crédito" in detalle
    assert "cambiaria" in detalle and "fiduciaria" in detalle
    assert "63 % de los eventos" in detalle


def test_un_panel_que_SI_presta_no_arrastra_la_coletilla():
    """Una advertencia que sale siempre deja de leerse: solo aparece cuando es un hecho."""
    mod = _script()
    detalle = mod._fila_credencial(_credencial(0.02))[-1]
    assert "NO otorga crédito" not in detalle
    assert "n=1.693" in detalle


def test_un_eje_sin_poblacion_declarada_no_inventa_una():
    mod = _script()
    fila = mod._fila_credencial({
        "nombre": "SDQ Comercio", "publicable": True, "metrica": "Gini", "valor": 0.232,
        "ic": [0.093, 0.373], "n": 314, "eventos": 87, "senal": None})
    assert "NO otorga crédito" not in fila[-1]


def test_lo_no_publicable_sigue_diciendose_en_vez_de_borrarse():
    """El sufijo de población no puede tapar el veto de frescura."""
    mod = _script()
    fila = mod._fila_credencial({
        "nombre": "SDQ X", "publicable": False, "valor": 0.3, "n": 100,
        "stale_reason": "el insumo cambió después del cálculo"})
    assert "no publicable" in fila[1]
    assert "vetada" in fila[-1]
