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


# ── El desenlace PRIMARIO, y no el primero que aparezca ───────────

def test_la_credencial_lee_el_desenlace_que_el_motor_declara_TARGETEAR():
    """El caso real de `sector_intel`, encontrado en el catálogo generado el 2026-08-20.

    El motor mide dos desenlaces y declara que el de empleo «NO es lo que el IAI dice
    anticipar». Ninguno concluye, así que `headline_outcome` es None — y la credencial caía al
    primer bloque del reporte, que es justo el de empleo. El documento comercial publicaba el
    desenlace que el propio motor descarta.
    """
    from shared.products.credenciales import _cifra_principal

    reporte = {
        # La raíz es una copia del bloque de empleo, conservada por compatibilidad.
        "mean_yearly_ic": -0.03, "ic_ci": [-0.267, 0.208], "n_observations": 160,
        "headline_outcome": None,
        "outcome_primario": "inversion",
        "outcomes": {
            "empleo": {"mean_yearly_ic": -0.03, "ic_ci": [-0.267, 0.208],
                       "n_observations": 160, "conclusive": False, "invertido": False},
            "inversion": {"mean_yearly_ic": -0.321, "ic_ci": [-0.5, -0.142],
                          "n_observations": 144, "conclusive": False, "invertido": True,
                          "control_solo_tamano": {
                              "intensidad": {"mean_yearly_ic": -0.323}}},
        },
    }
    cifra = _cifra_principal("agribusiness", reporte)
    assert cifra["valor"] == -0.321, "Publicó el desenlace secundario en vez del primario."
    assert cifra["senal"] == "inversion"
    assert cifra["invertida"] is True, "Un IC entero bajo cero es un hallazgo, no una ausencia."
    assert cifra["control_de_tamano"]["intensidad"]["mean_yearly_ic"] == -0.323


def test_el_titular_declarado_se_lee_bajo_CUALQUIERA_de_los_dos_nombres():
    """Dos motores nombran lo mismo distinto: `headline_signal` y `headline_outcome`."""
    from shared.products.credenciales import _mejor_senal

    por_signal = {"headline_signal": "resultados",
                  "signals": {"resultados": {"gini": 0.2287, "conclusive": True}}}
    por_outcome = {"headline_outcome": "inversion",
                   "outcomes": {"inversion": {"mean_yearly_ic": 0.3, "conclusive": True}}}
    assert _mejor_senal(por_signal)["senal"] == "resultados"
    assert _mejor_senal(por_outcome)["senal"] == "inversion"


def test_una_señal_invertida_se_marca_en_la_fila_del_catalogo():
    """«No concluyente» y «ordena al revés» no son lo mismo y la tabla los distingue."""
    mod = _script()
    fila = mod._fila_credencial({
        "nombre": "SDQ Agribusiness", "publicable": True, "metrica": "IC medio anual",
        "valor": -0.321, "ic": [-0.5, -0.142], "n": 144, "eventos": None,
        "senal": "inversion", "invertida": True,
        "control_de_tamano": {"intensidad": {"mean_yearly_ic": -0.323}}})
    detalle = fila[-1]
    assert detalle.startswith("ordena INVERTIDO")
    assert "el TAMAÑO solo alcanza -0,323" in detalle, (
        "Sin el control al lado, «ordena invertido» afirma lo que el dato no sostiene: el "
        "signo lo produce el deflactor, no el índice."
    )


def test_sin_control_declarado_la_fila_no_lo_inventa():
    mod = _script()
    fila = mod._fila_credencial({
        "nombre": "SDQ X", "publicable": True, "metrica": "Gini", "valor": 0.23,
        "ic": [0.09, 0.37], "n": 314, "eventos": 87, "senal": None})
    assert "TAMAÑO solo" not in fila[-1]
    assert not fila[-1].startswith("ordena INVERTIDO")


def test_la_inversion_NUNCA_se_deduce_del_signo():
    """El error que llegó al deck generado: ESG marcado «ordena INVERTIDO» siendo correcto.

    En ESG el desenlace es mortalidad por desastres climáticos: un Spearman NEGATIVO es la
    dirección buena —más resiliencia, menos muertes— y el motor lo trata como concluyente. Al
    deducir la inversión del signo desde el consumidor, el resultado concluyente de ese eje
    salió marcado como invertido en el documento comercial.

    La dirección buena de una métrica la sabe el MOTOR. El consumidor copia, no deduce.
    """
    from shared.products.credenciales import _cifra_principal

    esg = {"spearman": -0.509, "spearman_ci": [-0.782, -0.084], "n_countries": 24}
    cifra = _cifra_principal("esg_climate", esg)
    assert cifra["valor"] == -0.509
    assert cifra["concluyente"] is True, "El IC no cruza cero: concluye."
    assert cifra["invertida"] is False, (
        "Un Spearman negativo contra mortalidad es la dirección CORRECTA. Solo el motor puede "
        "declarar una inversión."
    )
    # Y cuando el motor SÍ la declara, se copia.
    assert _cifra_principal("x", {**esg, "invertido": True})["invertida"] is True


def test_la_fila_imprime_la_CONCLUSION_del_control_no_solo_las_dos_cifras():
    """«−0,321 contra −0,323» obliga al lector a concluir. El resultado se computa."""
    mod = _script()
    detalle = mod._fila_credencial({
        "nombre": "SDQ Agribusiness", "publicable": True, "metrica": "IC medio anual",
        "valor": -0.321, "ic": [-0.5, -0.142], "n": 144, "senal": "inversion",
        "invertida": True,
        "control_de_tamano": {"intensidad": {"mean_yearly_ic": -0.323,
                                             "el_tamano_alcanza_al_score": True}}})[-1]
    assert "el TAMAÑO solo alcanza -0,323" in detalle
    assert "NO agrega sobre el tamaño" in detalle


def test_cuando_el_score_SUPERA_al_tamano_la_fila_no_lo_desmiente():
    """Trade gana limpio: la fila trae el control pero no la frase de «no agrega»."""
    mod = _script()
    detalle = mod._fila_credencial({
        "nombre": "SDQ Trade", "publicable": True, "metrica": "Gini", "valor": 0.232,
        "ic": [0.093, 0.373], "n": 314, "eventos": 87, "senal": "export_collapse",
        "control_de_tamano": {"gini": 0.0699, "el_tamano_alcanza_al_score": False}})[-1]
    assert "el TAMAÑO solo alcanza 0,0699" in detalle
    assert "NO agrega" not in detalle


# ── Todas las señales, no solo la titular ─────────────────────────

def test_el_empate_se_IMPRIME_y_no_solo_se_computa():
    """El caso de seguros: 0,2575 contra 0,2404, indistinguibles, y la fila callaba.

    En el grupo de las concluyentes, dos cifras al lado sin conclusión se leen como «gana por
    poco». No gana por poco: no se distingue. Un veredicto computado que el documento no
    imprime es un veredicto que no existe para quien lo lee.
    """
    mod = _script()
    detalle = mod._fila_credencial({
        "nombre": "SDQ Seguros", "publicable": True, "metrica": "Gini", "valor": 0.2575,
        "ic": [0.1237, 0.3946], "n": 269, "eventos": 132, "senal": "underwriting",
        "control_de_tamano": {"gini": 0.2404, "el_tamano_alcanza_al_score": False,
                              "empata_con_el_score": True,
                              "veredicto": "empate: …"}})[-1]
    assert "INDISTINGUIBLE del tamaño" in detalle


def test_cuando_el_score_supera_tambien_lo_dice():
    mod = _script()
    detalle = mod._fila_credencial({
        "nombre": "SDQ Trade", "publicable": True, "metrica": "Gini", "valor": 0.232,
        "ic": [0.093, 0.373], "n": 314, "senal": "export_collapse",
        "control_de_tamano": {"gini": 0.0699, "el_tamano_alcanza_al_score": False,
                              "empata_con_el_score": False,
                              "veredicto": "el score ordena mejor…"}})[-1]
    assert "supera al tamaño" in detalle
    assert "INDISTINGUIBLE" not in detalle


def test_las_senales_no_titulares_salen_como_subfilas():
    """El resultado más incómodo de seguros no estaba en ninguna superficie."""
    mod = _script()
    filas = mod._filas_de_senales({
        "publicable": True, "senal": "underwriting",
        "senales": [
            {"senal": "underwriting", "metrica": "Gini", "valor": 0.2575, "ic": [0.12, 0.39],
             "n": 269, "concluyente": True},
            {"senal": "solvency", "metrica": "Gini", "valor": 0.0639, "ic": [-0.068, 0.198],
             "n": 272, "concluyente": False,
             "control_de_tamano": {"gini": 0.2548, "el_tamano_alcanza_al_score": True}},
        ]})
    assert len(filas) == 1, "La titular no se repite como subfila."
    fila = filas[0]
    assert "solvency" in fila[0] and fila[0].strip().startswith("↳")
    assert "no concluyente" in fila[-1]
    assert "NO agrega sobre el tamaño" in fila[-1], (
        "En solvency el TAMAÑO concluye donde el score no: es el dato que el documento "
        "escondía."
    )


def test_un_eje_con_UNA_sola_senal_no_agrega_subfilas():
    """Repetir la titular como subfila es ruido, y el ruido desactiva la señal."""
    mod = _script()
    assert mod._filas_de_senales({
        "publicable": True, "senal": "governance",
        "senales": [{"senal": "governance", "metrica": "Gini", "valor": 0.199,
                     "ic": [0.045, 0.355], "n": 260, "concluyente": True}]}) == []


def test_un_eje_no_publicable_no_arrastra_subfilas():
    mod = _script()
    assert mod._filas_de_senales({"publicable": False, "senales": [{"senal": "x"}]}) == []
