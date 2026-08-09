"""GDELT por ADM1 (provincia) — lógica pura, sin BigQuery.

La granularidad provincial de GDELT es real pero DESPAREJA: el geocodificado de las
noticias se concentra en Santo Domingo y Santiago. Estos tests fijan la regla de volumen
—lo que evita publicar ruido con cara de señal— y el mapeo derivado del nombre de lugar,
que existe para no escribir a mano una tabla de códigos FIPS.
"""
from shared.data.gdelt_bq_client import (
    MIN_ADM1_RECORDS,
    adm1_rows_to_records,
    adm1_volume_report,
    build_adm1_query,
    build_query,
)


def _row(adm1, name, n, tone=-1.5, protest=2.0, sanction=0.1):
    return {"adm1": adm1, "top_name": name, "n_records": n, "news_sentiment": tone,
            "unrest_shocks": protest, "sanctions_signal": sanction}


def test_la_consulta_de_pais_lee_el_offset_2_y_la_de_provincia_el_3():
    """El país y la provincia salen de la MISMA columna V2Locations, en offsets
    distintos. Es literalmente el cambio que habilita lo sub-nacional."""
    assert "SAFE_OFFSET(2)" in build_query()
    adm1 = build_adm1_query()
    assert "SAFE_OFFSET(2)] AS fips" in adm1
    assert "SAFE_OFFSET(3)] AS adm1" in adm1
    assert "GROUP BY adm1" in adm1


def test_la_consulta_adm1_conserva_el_filtro_de_particion():
    """Sin el filtro de partición la consulta escanea el GKG completo y se sale del
    tier gratuito: es el guardrail de costo del conector."""
    assert "_PARTITIONTIME" in build_adm1_query()
    assert "@days" in build_adm1_query() and "@fips" in build_adm1_query()


def test_provincia_con_volumen_entrega_las_tres_metricas():
    recs = adm1_rows_to_records([_row("DR01", "Distrito Nacional, Dominican Republic", 5000)],
                                period="2026")
    assert {r.series for r in recs} == {"news_sentiment", "unrest_shocks", "sanctions_signal"}
    assert all(r.dimension == "distrito_nacional" and r.period == "2026" for r in recs)
    assert all(r.value is not None and r.reason is None for r in recs)


def test_provincia_sin_volumen_entrega_nulo_honesto_con_razon():
    """Un cero acá lo leería el consumidor como 'sin tensión'. La ausencia de medición
    tiene que ser distinguible de la ausencia de conflicto."""
    recs = adm1_rows_to_records([_row("DR20", "Pedernales, Dominican Republic",
                                      MIN_ADM1_RECORDS - 1)])
    assert recs and all(r.dimension == "pedernales" for r in recs)
    assert all(r.value is None for r in recs)
    assert all("muestra insuficiente" in (r.reason or "") for r in recs)


def test_el_umbral_es_inclusivo_en_el_limite():
    justo = adm1_rows_to_records([_row("DR20", "Pedernales", MIN_ADM1_RECORDS)])
    assert all(r.value is not None for r in justo)


def test_adm1_que_no_resuelve_se_descarta_no_se_adivina():
    """El mapeo se deriva del nombre de lugar dominante. Un código nuevo o un nombre
    que no calza queda FUERA y registrado, en vez de caer en la provincia más parecida."""
    recs = adm1_rows_to_records([
        _row("DR99", "Some Unknown Place, Dominican Republic", 9000),
        _row("DR01", "Santiago, Dominican Republic", 9000),
    ])
    assert {r.dimension for r in recs} == {"santiago"}


def test_valor_nulo_de_la_fuente_sigue_nulo_aunque_haya_volumen():
    recs = adm1_rows_to_records([_row("DR01", "Santiago", 9000, tone=None)])
    tono = next(r for r in recs if r.series == "news_sentiment")
    assert tono.value is None


def test_informe_de_volumen_separa_medibles_delgadas_y_ausentes():
    """Es el gate previo a publicar: si solo dos provincias son medibles, la señal
    reparte dos valores y treinta nulos — y eso hay que verlo ANTES de cablearla."""
    rep = adm1_volume_report([
        _row("DR01", "Distrito Nacional", 8000),
        _row("DR25", "Santiago", 4000),
        _row("DR20", "Pedernales", 12),
        _row("DR99", "Nowhere", 500),
    ])
    assert rep["n_provinces_measurable"] == 2
    assert rep["n_provinces_thin"] == 1
    assert rep["n_provinces_absent"] == 29          # 32 − 2 medibles − 1 delgada
    assert rep["unresolved_adm1"] == ["DR99"]
    assert rep["share_measurable"] == round(2 / 32, 3)
    assert list(rep["measurable"]) == ["distrito_nacional", "santiago"]   # ordenado por volumen
