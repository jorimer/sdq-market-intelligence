"""El conector de la CMF de Chile lee lo que el emisor declara, o se detiene.

Los tres riesgos que estos tests vigilan salieron de medir el archivo real, no de imaginar:

1. **La escala.** La hoja declara «INDICADORES (en %)». Si deja de declararlo, 2,34 puede ser
   2,34 % o 234 % y no hay forma de saberlo. Este proyecto ya publicó una tasa cien veces mal.
2. **La versión del Compendio.** En enero de 2022 la CMF cambió el plan de cuentas y, en los
   archivos de balance, la escala de millones de pesos a pesos: para una misma cuenta,
   26.995.865 en 2021-12 y 26.458.735.676.131 en 2022-01. Seis órdenes de magnitud en el corte
   de un mes. El mapeo de este conector solo vale dentro de una versión.
3. **La desaparición silenciosa.** Un indicador que deja de reconocerse no rompe nada: el
   conector sirve de menos y el eje que lo consumía se queda mudo.
"""
import pytest

from shared.data.cmf_client import (
    CMFClient,
    INDICADORES,
    LICENSE,
    CmfError,
    descubrir_ediciones,
    leer_indicadores_sistema,
    parse_valor,
)

CABECERA_ESCALA = "INDICADORES (en %)"
CABECERA_CNCB = "Códigos según CNCB versión 2022"


def _fila(largo=9, **celdas):
    fila = [None] * largo
    for j, v in celdas.items():
        fila[int(j[1:])] = v
    return fila


def _hoja(escala=CABECERA_ESCALA, cncb=CABECERA_CNCB, quitar=(), mensual_al_final=False):
    """Reproduce el layout REAL de «Indicadores Sistema»: rótulo en B, valores en D/E/F,
    fórmula contable en I, y encabezados de sección sin valores ni fórmula."""
    import datetime as dt

    filas = [
        _fila(c1=escala, c8=cncb),
        _fila(),
        _fila(c3=dt.datetime(2025, 7, 31), c4=dt.datetime(2026, 6, 30),
              c5=dt.datetime(2026, 7, 31)),
    ]
    secciones = {
        "Actividad variación mensual": [("Colocaciones", "50000.00.00", 1.13)],
        "Actividad variación 12 meses": [("Colocaciones", "50000.00.00", 0.47)],
        "Rentabilidad Promedio (1)": [
            ("Rentabilidad sobre Patrimonio Promedio después de impuestos (ROAE)",
             "59000.00.00 / 30000.00.00", 15.52),
            ("Rentabilidad sobre Activos Promedio después de impuestos (ROAA)",
             "59000.00.00 / 10000.00.00", 1.37)],
        "Eficiencia operativa": [
            ("Total Gastos Operacionales a Total Ingresos Operacionales",
             "(56000.00.00 / 55000.00.00)", 43.10)],
        "Provisiones constituidas por riesgo de crédito de colocaciones a costo "
        "amortizado (2)": [
            ("Colocaciones a costo amortizado",
             "(14315.01.00+14325.01.00+14900.00.00) / 50500.00.00", 2.52)],
        "Cartera con morosidad de 90 días o más": [
            ("Colocaciones", "(85700.00.00+85800.00.00+85900.00.00) / 50000.00.00", 2.33),
            ("Comerciales", "85720.00.00 / 14500.00.00", 2.19),
            ("Personas", "(85730.00.00+85740.00.00) / (14600.00.00+14800.00.00)", 2.53),
            ("Consumo", "85740.00.00 / 14800.00.00", 2.39),
            ("Vivienda", "85730.00.00 / 14600.00.00", 2.57)],
        "Cartera deteriorada de colocaciones a costo amortizado": [
            ("Colocaciones a costo amortizado", "81100.00.00 / 50500.00.00", 5.88)],
    }
    orden = list(secciones)
    if mensual_al_final:
        # Con la variación MENSUAL después de la de 12 meses, un lector que clasifique por
        # fórmula sola se queda con el valor equivocado: el último escrito gana.
        orden.remove("Actividad variación mensual")
        orden.append("Actividad variación mensual")
    for seccion in orden:
        entradas = secciones[seccion]
        filas.append(_fila(c1=seccion))
        for etiqueta, formula, valor in entradas:
            if formula in quitar:
                continue
            filas.append(_fila(c1=etiqueta, c3=valor, c4=valor, c5=valor, c8=formula))
    return filas


# ── Lo que la hoja tiene que declarar ─────────────────────────────
def test_lee_los_indicadores_declarados():
    d = leer_indicadores_sistema(_hoja())
    assert d["cncb"] == "2022"
    assert d["periodos"] == ["2025-07-31", "2026-06-30", "2026-07-31"]
    assert set(d["series"]) == set(INDICADORES.values())


def test_sin_la_declaracion_de_ESCALA_se_detiene():
    """Sin «(en %)» no se sabe si 2,34 son 2,34 % o 234 %. Adivinarlo no es una opción."""
    with pytest.raises(CmfError, match="porcentaje"):
        leer_indicadores_sistema(_hoja(escala="INDICADORES"))


def test_otra_version_del_COMPENDIO_se_detiene():
    """Los mismos códigos bajo otro Compendio pueden medir otra cosa — y en 2022 cambiaron
    además de escala. Seguir sirviendo sería publicar a ciegas."""
    with pytest.raises(CmfError, match="2027"):
        leer_indicadores_sistema(_hoja(cncb="Códigos según CNCB versión 2027"))


def test_sin_declaracion_de_compendio_se_detiene():
    with pytest.raises(CmfError, match="Compendio"):
        leer_indicadores_sistema(_hoja(cncb=None))


def test_un_indicador_que_DESAPARECE_no_pasa_en_silencio():
    """El modo de fallo caro: servir de menos. No rompe nada y el eje se queda mudo."""
    with pytest.raises(CmfError, match="mora_90_consumo"):
        leer_indicadores_sistema(_hoja(quitar={"85740.00.00 / 14800.00.00"}))


# ── La fórmula sola no alcanza ────────────────────────────────────
@pytest.mark.parametrize("mensual_al_final", [False, True])
def test_la_seccion_desambigua_una_formula_repetida(mensual_al_final):
    """`50000.00.00` es a la vez la variación MENSUAL y la de 12 MESES de las colocaciones.

    Sin la sección en la clave, una pisa a la otra y publicamos una variación mensual
    rotulada como anual: el número sería real y la etiqueta, falsa. Se prueba con las dos
    secciones en los DOS órdenes, porque clasificar por fórmula sola acierta por accidente
    cuando la sección correcta resulta ser la última — y con eso el guard queda ciego.
    """
    d = leer_indicadores_sistema(_hoja(mensual_al_final=mensual_al_final))
    assert d["series"]["colocaciones_var_12m"][0] == 0.47, (
        f"se sirvió {d['series']['colocaciones_var_12m'][0]}, que es la variación MENSUAL: "
        "la clave no distingue la sección y el indicador quedó mal atribuido")


# ── Valores ───────────────────────────────────────────────────────
@pytest.mark.parametrize("celda,esperado", [
    (2.34, 2.34), (0, 0.0), ("2,34", 2.34), ("2.34", 2.34), ("43,10%", 43.10),
    ("---", None), ("--", None), ("n/a", None), (None, None), ("", None),
])
def test_parse_valor(celda, esperado):
    assert parse_valor(celda) == esperado


def test_un_ausente_NO_es_un_cero():
    """La planilla usa `---` para el ausente y `0` para el cero real: los dos aparecen en la
    misma columna. En morosidad, un cero es la afirmación fuerte «ninguna cartera en mora»."""
    assert parse_valor("---") is None
    assert parse_valor(0) == 0.0


# ── Descubrir la edición ──────────────────────────────────────────
_PAGINA = '''
<h2 id="estadisticas_filtros_grupo_28911_Label">Reporte Mensual de Información Financiera del Sistema Bancario</h2>
<a href="articles-113057_recurso_1.xlsx?ts=1" aria-label="Descargar Julio 2026 (xlsx, se abre)"></a>
<a href="articles-112230_recurso_1.xlsx?ts=2" aria-label="Descargar Junio 2026 (xlsx, se abre)"></a>
<a href="articles-45674_recurso_1.xlsx?ts=3" aria-label="Descargar octubre 2013 (xlsx, se abre)"></a>
<h2 id="estadisticas_filtros_grupo_28913_Label">Reporte de Cartera Vencida del Sistema Bancario</h2>
<a href="articles-999_recurso_1.xlsx?ts=4" aria-label="Descargar Julio 2026 (xlsx, se abre)"></a>
<h2 id="estadisticas_filtros_grupo_29874_Label">Reporte de Cartera Vencida del Sistema Bancario</h2>
<a href="articles-888_recurso_1.xlsx?ts=5" aria-label="Descargar Julio 2026 (xlsx, se abre)"></a>
'''


def test_descubre_las_ediciones_por_TITULO_no_por_orden():
    ed = descubrir_ediciones(_PAGINA)
    assert ed["2026-07"] == "articles-113057_recurso_1.xlsx"
    # El emisor alterna mayúscula y minúscula en el mes dentro de la misma lista.
    assert ed["2013-10"] == "articles-45674_recurso_1.xlsx"
    # No se cuela el archivo de OTRO reporte que comparte el mes.
    assert "articles-999_recurso_1.xlsx" not in ed.values()


def test_un_titulo_DUPLICADO_no_se_resuelve_en_silencio():
    """En la página real hay tres títulos repetidos —cartera vencida, provisiones y Basilea
    III—. Tomar el primero sería elegir sin criterio y sin dejar rastro."""
    with pytest.raises(CmfError, match="2 reportes se titulan"):
        descubrir_ediciones(_PAGINA, "Reporte de Cartera Vencida del Sistema Bancario")


def test_un_titulo_INEXISTENTE_dice_cuales_hay():
    with pytest.raises(CmfError, match="no hay un reporte titulado"):
        descubrir_ediciones(_PAGINA, "Reporte que no existe")


# ── El cliente ────────────────────────────────────────────────────
def test_el_cliente_sirve_el_fixture_con_su_sujeto():
    records = CMFClient(mode="fixture").fetch()
    assert records, "el fixture no devolvió nada"
    assert {r.dimension for r in records} == {"CHL"}
    assert {r.unit for r in records} == {"%"}
    assert {r.series for r in records} == set(INDICADORES.values())
    mora = next(r for r in records if r.series == "mora_90_colocaciones"
                and r.period == "2026-07-31")
    # El valor del emisor para julio 2026, en escala 0-100. Si alguien "normalizara" a
    # fracción, esto se cae.
    assert 2.0 < mora.value < 3.0, f"la escala cambió: {mora.value}"


def test_la_advertencia_de_PROVISORIO_viaja_con_el_dato():
    """El emisor la pone en el archivo. Si vive en una nota al pie, se pierde en la primera
    reescritura del documento."""
    r = CMFClient(mode="fixture").fetch()[0]
    assert "provisoria" in (r.lineage.note or "").lower()


def test_la_licencia_esta_verificada_y_exige_enlace():
    from shared.data.licenses import LICENCIAS

    lic = LICENCIAS[LICENSE]
    assert lic.verificada, "la licencia de la CMF se leyó el 2026-09-05: no es deuda"
    assert lic.atribucion, "el emisor condiciona la publicación a nombrar la fuente"
    assert "http" in lic.atribucion, (
        "los términos exigen «una mención a la fuente MÁS un enlace»: sin URL, la atribución "
        "no cumple la condición de la licencia")


def test_la_licencia_no_cae_en_cuarentena_por_accidente():
    """El detector busca subcadenas, y una de ellas es `"sa "` (por ShareAlike): en prosa
    española se dispara sola. La CMF autoriza publicar, así que una cuarentena acá sería un
    falso positivo que retiene un dato que sí podemos usar."""
    from shared.data_api.manifest import license_restricts_redistribution

    assert not license_restricts_redistribution(LICENSE)
