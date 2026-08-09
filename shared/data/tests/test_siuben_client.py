"""Conector SIUBEN — lógica pura (sin red).

Los encabezados de los CSV usados acá son los REALES de ``datos.gob.do``, incluidos
sus defectos: espaciado inconsistente en el trimestre, columnas ``Periodo`` repetidas y
bytes de acento que ninguna decodificación recupera. Si el emisor los arregla, estos
tests siguen pasando; si los cambia de forma incompatible, fallan — que es el punto.
"""
import pytest

from shared.data.siuben_client import (
    DATASETS,
    discover_resources,
    parse_period,
    parse_siuben_csv,
    theme_spec,
)

ALFABETISMO = "\n".join([
    "Provincia,Sabe Leer y escribir ,Porcentaje,NO Sabe leer  ni escribir,Porcentaje,Periodo,A o",
    "Azua,80,80.0,20,20.0,Enero - Marzo ,2020",
    "Distrito Nacional,90,90.0,10,10.0,Enero - Marzo ,2020",
    "Elias Pina,60,60.0,40,40.0,Enero - Marzo ,2020",
])

HACINAMIENTO = "\n".join([
    "Provincia,hacinamiento extremo ,Porcentaje,hacinamiento moderado ,Porcentaje,"
    "hacinamiento leve ,Porcentaje,No hacinados ,Porcentaje,Periodo,A o",
    "Azua,10,10,20,20,30,30,40,40,Abril -  Junio,2024",
])

ICV = "\n".join([
    "Provincia,ICV-1 ,Porcentaje,ICV-2 ,Porcentaje,ICV-3,Porcentaje,ICV-4,Porcentaje,Periodo,Periodo",
    'Azua,"1,000",10,"4,000",40,"5,000",50,0,0,Abril -Junio,2022',
])


def _spec(theme):
    s = theme_spec(theme)
    assert s is not None
    return s


def test_proporcion_se_recalcula_desde_los_conteos():
    """No se suman los porcentajes publicados: se recalcula sobre el denominador
    explícito, para que componer categorías no arrastre redondeo."""
    out = dict((slug, v) for slug, _p, v in
               parse_siuben_csv(ALFABETISMO, _spec("siuben_illiteracy_head_share")))
    assert out == {"azua": 20.0, "distrito_nacional": 10.0, "elias_pina": 40.0}


def test_numerador_compuesto_suma_las_categorias_declaradas():
    """Hacinamiento = extremo + moderado sobre el total de las cuatro categorías."""
    rows = parse_siuben_csv(HACINAMIENTO, _spec("siuben_overcrowding_share"))
    assert rows == [("azua", "2024-Q2", 30.0)]


def test_separador_de_miles_y_periodo_duplicado():
    """El tablero de ICV trae conteos con coma y DOS columnas llamadas 'Periodo'."""
    rows = parse_siuben_csv(ICV, _spec("siuben_disability_icv1_share"))
    assert rows == [("azua", "2022-Q2", 10.0)]


@pytest.mark.parametrize("periodo,anio,expected", [
    ("Enero - Marzo ", "2020", "2020-Q1"),
    ("Abril -  Junio", "2024", "2024-Q2"),     # espaciado roto del emisor
    ("Abril -Junio", "2022", "2022-Q2"),
    ("Julio - Septiembre", "2019", "2019-Q3"),
    ("Octubre - Diciembre", "2025", "2025-Q4"),
])
def test_trimestre_se_deduce_del_primer_mes(periodo, anio, expected):
    assert parse_period(periodo, anio) == expected


@pytest.mark.parametrize("periodo,anio", [
    ("Enero - Marzo", ""), ("", "2020"), ("Trimestre 1", "2020"), ("Enero - Marzo", "20"),
])
def test_periodo_invalido_no_se_adivina(periodo, anio):
    assert parse_period(periodo, anio) is None


def test_fila_con_conteo_faltante_se_descarta_no_se_rellena():
    """Un denominador incompleto no se completa con supuestos: la fila cae."""
    csv_text = "\n".join([
        "Provincia,Sabe Leer y escribir ,Porcentaje,NO Sabe leer  ni escribir,Porcentaje,Periodo,A o",
        "Azua,80,80.0,,,Enero - Marzo,2020",
        "Barahona,0,0,0,0,Enero - Marzo,2020",      # denominador cero
        "Peravia,70,70,30,30,Enero - Marzo,2020",
    ])
    assert parse_siuben_csv(csv_text, _spec("siuben_illiteracy_head_share")) == [
        ("peravia", "2020-Q1", 30.0)
    ]


def test_provincia_desconocida_se_descarta_no_se_reparte():
    csv_text = "\n".join([
        "Provincia,Sabe Leer y escribir ,Porcentaje,NO Sabe leer  ni escribir,Porcentaje,Periodo,A o",
        "Marte,80,80,20,20,Enero - Marzo,2020",
        "Azua,80,80,20,20,Enero - Marzo,2020",
    ])
    assert parse_siuben_csv(csv_text, _spec("siuben_illiteracy_head_share")) == [
        ("azua", "2020-Q1", 20.0)
    ]


def test_layout_cambiado_devuelve_vacio_en_vez_de_leer_otra_columna():
    """Si el emisor renombra la categoría del numerador, la serie queda VACÍA —
    visible— en lugar de sumar en silencio la columna equivocada."""
    csv_text = "\n".join([
        "Provincia,Alfabetizados,Porcentaje,Iletrados,Porcentaje,Periodo,A o",
        "Azua,80,80,20,20,Enero - Marzo,2020",
    ])
    assert parse_siuben_csv(csv_text, _spec("siuben_illiteracy_head_share")) == []


def test_descubrimiento_calza_por_nombre_de_recurso_y_exige_csv():
    packages = [{"resources": [
        {"format": "XLSX", "name": "Distribución de Jefes/as SIUBEN", "url": "x.xlsx"},
        {"format": "CSV", "name": "Distribución de Jefes/as, SIUBEN 2018 - 2026.", "url": "jefes.csv"},
        {"format": "CSV", "name": "Hogares según el Nivel de Hacinamiento", "url": "hac.csv"},
        {"format": "CSV", "name": "Recurso sin relación", "url": "otro.csv"},
    ]}]
    found = discover_resources(packages)
    assert found["siuben_illiteracy_head_share"] == "jefes.csv"
    assert found["siuben_overcrowding_share"] == "hac.csv"
    # Lo que no aparece, falta: no se inventa una URL.
    assert "siuben_disability_icv1_share" not in found


def test_falla_total_levanta_con_los_motivos_acumulados(monkeypatch):
    """Que fallen los cinco tableros no es un resultado vacío legítimo: es una caída.

    La primera versión devolvía ``[]`` tanto si la fuente no publicó como si no se pudo
    llegar, y aguas arriba se leyó lo segundo como lo primero — la corrida del
    2026-08-09 reportó 'la fuente respondió sin observaciones' cuando en realidad no
    había podido descargar nada."""
    import httpx

    import shared.data.siuben_client as sc

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"results": [{"resources": [
                {"format": "CSV", "name": "Distribución de Jefes/as", "url": "jefes.csv"}]}]}}

    def _get(url, **kw):
        if url == sc.CKAN_SEARCH:
            return _Resp()
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _get)
    with pytest.raises(sc.SiubenUnavailable) as exc:
        sc.fetch_siuben_provincial()
    mensaje = str(exc.value)
    assert "ningún tablero pudo leerse" in mensaje
    assert "ConnectError" in mensaje                       # la causa VIAJA
    assert "siuben_illiteracy_head_share" in mensaje       # y el tablero concreto


def test_catalogo_sin_recursos_se_distingue_de_una_caida_de_red(monkeypatch):
    """Dos fallas distintas necesitan dos mensajes distintos: 'no llegué a CKAN' se
    investiga en la red; 'CKAN respondió sin los recursos' se investiga en el emisor."""
    import httpx

    import shared.data.siuben_client as sc

    class _Empty:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"results": [{"resources": []}]}}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Empty())
    with pytest.raises(sc.SiubenUnavailable, match="ninguno expuso un recurso CSV"):
        sc.fetch_siuben_provincial()


def test_falla_parcial_no_tumba_a_los_demas(monkeypatch):
    """Tolerante en lo parcial: cuatro tableros caídos no deben perder al quinto."""
    import httpx

    import shared.data.siuben_client as sc

    class _Resp:
        def __init__(self, content=b""):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"results": [{"resources": [
                {"format": "CSV", "name": "Distribución de Jefes/as", "url": "jefes.csv"},
                {"format": "CSV", "name": "Nivel de Hacinamiento", "url": "hac.csv"}]}]}}

    def _get(url, **kw):
        if url == sc.CKAN_SEARCH:
            return _Resp()
        if url == "jefes.csv":
            return _Resp(ALFABETISMO.encode("utf-8"))
        raise httpx.ConnectError("caído")

    monkeypatch.setattr(httpx, "get", _get)
    rows = sc.fetch_siuben_provincial()
    assert {t for t, _s, _p, _v in rows} == {"siuben_illiteracy_head_share"}
    assert len(rows) == 3


def test_todo_tablero_declara_unidad_y_universo():
    """El caveat del universo viaja en el descriptor, no en una nota al pie."""
    for spec in DATASETS:
        assert spec.theme.startswith("siuben_")
        assert spec.unit and spec.note
        assert spec.numerator
