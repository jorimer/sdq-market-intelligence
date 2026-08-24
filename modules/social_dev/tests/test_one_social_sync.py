"""Tests for the ONE social connector + sync (Eje 6 Gate A). Offline."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.one_client import ONEClient, _parse_poverty_csv, region_catalog
from shared.database.base import Base
from modules.social_dev.models.models import SocialIndicator  # noqa: F401 — register table
from modules.social_dev.social_sync import one_social_sync


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


#: TODO sub-sync que pega a la red. Los tests que corren `one_social_sync` entero los
#: sustituyen a los 22, y la lista vive UNA sola vez porque mantenerla tres veces a mano ya
#: se desincronizo sola: `_sync_ied_total` estaba en un test y faltaba en otro.
#:
#: Y no alcanza con la lista: la guarda el test estructural del final de este archivo, que
#: lee `social_sync.py` con `ast` y exige que todo `_sync_*` este aca o en
#: `SUB_SYNCS_SIN_RED`. El defecto que lo motivo: `_sync_gasto_salud_funcional` entro sin
#: estar en ninguna lista, se ejecuto de VERDAD contra el emisor, bajo trece PDF de 30 a 60
#: MB y los parseo — la corrida paso de 5 minutos a 36 y dos tests cayeron por timeout.
#: Un test que pega a la red no prueba lo que dice probar, y encima tarda como si lo hiciera.
SUB_SYNCS_DE_RED = (
    "_sync_wdi_health", "_sync_bcrd_informality", "_sync_bcrd_mercado_laboral",
    "_sync_cepal_politica", "_sync_ipu_senado", "_sync_exportaciones_per_capita",
    "_sync_llece_niveles", "_sync_razon_exportaciones_importaciones", "_sync_pobreza_rural",
    "_sync_gei_per_capita", "_sync_confianza_partidos", "_sync_ied_total",
    "_sync_gasto_salud_funcional", "_sync_cobertura_salud",
    "_sync_participacion_exportadora", "_sync_mem_electrico", "_sync_sisdom_income",
    "_sync_minerd_coverage", "_sync_sisdom_schooling", "_sync_wb_findex",
    "_sync_endesa_child_mortality", "_sync_siuben_provincial",
)

#: Los que NO pegan a la red, y que por eso son justamente lo que estos tests ejercitan de
#: verdad. Hoy es uno: `_sync_conteos_regionales` computa sobre las filas que las otras
#: fuentes ya dejaron en la base, asi que sustituirlo seria no probar que el conteo cuadra.
SUB_SYNCS_SIN_RED = ("_sync_conteos_regionales",)


def test_parse_poverty_csv_maps_themes_and_regions():
    csv = (
        "Tasa de Pobreza ,Tipo de Regiones,Porcentaje,Año\n"
        "Pobreza General,Enriquillo,31,2024\n"
        "Pobreza Extrema, Cibao Norte ,2,2024\n"          # leading/trailing spaces
        "Pobreza General,Región Inexistente,99,2024\n"     # unknown region → skipped
    ).encode("utf-8")
    out = _parse_poverty_csv(csv)
    assert ("poverty_rate", "enriquillo", "2024", 31.0) in out
    assert ("poverty_extreme", "cibao_norte", "2024", 2.0) in out          # space-tolerant
    assert not any(slug not in dict(region_catalog()) for _, slug, _, _ in out)  # no unknowns


def test_ozama_alias_matches():
    # Ozama (Gran Santo Domingo) under a single-token rename must still map.
    for label in ("Ozama", "Metropolitana", "Gran Santo Domingo"):
        csv = f"a,b,c,d\nPobreza General,{label},20,2024\n".encode("utf-8")
        out = _parse_poverty_csv(csv)
        assert out and out[0][1] == "ozama"


def test_fixture_client_offline():
    recs = ONEClient(mode="fixture").fetch()
    assert recs, "fixture vacío — ¿se generó one.json?"
    assert {r.dimension for r in recs} == {slug for slug, _ in region_catalog()}  # 10 regions
    assert {r.series for r in recs} >= {"poverty_rate"}


def test_sync_persists_and_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(ONEClient, "_fetch_live", ONEClient._fetch_fixture)
    # Las demás fuentes pegan a la red — se sustituyen. Devuelven un conteo POSITIVO
    # porque hacen de sub-syncs que funcionan: un 0 ahora significa "la fuente no trajo
    # nada" y queda declarado en ``errors``, que es justo lo que este test NO mide.
    for _fn in SUB_SYNCS_DE_RED:
        monkeypatch.setattr(f"modules.social_dev.social_sync.{_fn}", lambda db, set_phase, *a: 1)

    first = one_social_sync(db)
    assert first["errors"] == []
    assert first["synced"] > 0
    assert first["regions"] == 10
    assert "poverty_rate" in first["themes"]
    # Las filas de la base son las del panel regional MÁS las derivadas: los conteos de los
    # indicadores 2.2 y 2.5 se computan sobre ese mismo panel y se persisten como serie
    # nacional propia. `synced` cuenta solo la ingesta de la ONE, así que sumarlas explícita
    # es lo que vuelve al test capaz de detectar una escritura que nadie declaró.
    assert first["conteos_regionales_synced"] > 0, (
        "el panel del fixture está completo: los conteos derivados tienen que salir")
    n1 = db.query(SocialIndicator).count()
    assert n1 == first["synced"] + first["conteos_regionales_synced"]

    second = one_social_sync(db)          # upsert in place — no duplicates
    assert db.query(SocialIndicator).count() == n1

    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="enriquillo", theme="poverty_rate", period="2024")
        .first()
    )
    assert row is not None and row.source == "ONE" and row.disaggregation == "region"


def test_una_fuente_caida_queda_declarada_en_errors(db, monkeypatch):
    """Un cero sin explicación es un éxito aparente. Pasó en producción el 2026-08-09:
    cuatro fuentes devolvieron cero y la operación reportó ``errors: []``, así que la
    consola mostró la corrida como buena. Un guard que no reporta no protege: esconde.

    Las dos causas se distinguen porque se actúan distinto — 'no pudimos llegar' es un
    problema a investigar; 'la fuente no publicó' puede ser legítimo."""
    monkeypatch.setattr(ONEClient, "_fetch_live", ONEClient._fetch_fixture)
    # PRIMERO se neutraliza todo, y RECIEN DESPUES se arma el escenario. Al reves —que es
    # como estaba— quedaban quince sub-syncs pegando al emisor de verdad, y entonces este
    # test afirmaba algo sobre `errors` mientras `errors` dependia de si el portal de un
    # tercero estaba arriba. Es el defecto que el archivo dice haber cerrado en agosto para
    # `_sync_ipu_senado`: se cerro en el test de al lado y quedo abierto en este.
    for _fn in SUB_SYNCS_DE_RED:
        monkeypatch.setattr(f"modules.social_dev.social_sync.{_fn}", lambda db, sp, *a: 5)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_wdi_health", lambda db, sp, *a: 7)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_sisdom_income", lambda db, sp, *a: 0)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_bcrd_informality", lambda db, sp, *a: 4)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_sisdom_schooling", lambda db, sp, *a: 0)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_wb_findex", lambda db, sp, *a: 0)

    def _boom(db, sp, *a):
        raise ConnectionError("403 Forbidden")

    monkeypatch.setattr("modules.social_dev.social_sync._sync_minerd_coverage", _boom)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_siuben_provincial", _boom)

    res = one_social_sync(db)
    errores = " · ".join(res["errors"])

    # No se pudo llegar → la causa VIAJA (tipo y mensaje), no se pierde en un log.
    # El rótulo nombra al EMISOR vigente: la cobertura ya no es de la ONE, y mandar a
    # mirar el portal equivocado es parte de no declarar bien la falla.
    assert "cobertura educativa (MINERD · SIIE)" in errores and "403 Forbidden" in errores
    assert "(ONE)" not in errores.split("cobertura educativa")[1][:30]
    assert "indicadores provinciales (SIUBEN)" in errores
    assert "ConnectionError" in errores
    # Cero sin excepción → también consta, con otra redacción.
    assert "la fuente respondió sin observaciones" in errores
    # Lo que sí trajo dato NO ensucia el reporte.
    assert "salud nacional" not in errores
    assert res["coverage_synced"] == 0 and res["provincial_synced"] == 0
    assert res["health_synced"] == 7


def test_sin_fallas_no_se_inventan_errores(db, monkeypatch):
    """El contrapeso del test anterior: si todo trajo dato, ``errors`` queda vacio.

    TODOS los sub-syncs de red se sustituyen, incluidos los que antes se dejaban pasar. El
    2026-08-22 este test se puso rojo porque el portal de la Union Interparlamentaria empezo
    a responder 403 y `_sync_ipu_senado` no estaba en la lista: el test afirmaba algo sobre
    NUESTRO codigo y fallaba por un tercero. Un test que depende de la red no prueba lo que
    dice probar."""
    monkeypatch.setattr(ONEClient, "_fetch_live", ONEClient._fetch_fixture)
    for fn in SUB_SYNCS_DE_RED:
        monkeypatch.setattr(f"modules.social_dev.social_sync.{fn}", lambda db, sp, *a: 3)
    assert one_social_sync(db)["errors"] == []


def test_el_uso_de_una_instantanea_viaja_al_resultado(db, monkeypatch, tmp_path):
    """El respaldo NO puede usarse en silencio.

    Producción no alcanza siuben.gob.do y el tablero del MINERD limita por tasa, así que
    la instantánea comiteada es un camino REAL, no teórico. Y un camino real que no se
    declara es exactamente cómo un fallback se vuelve permanente sin que nadie lo note
    (ya pasó acá con los 'promedios del sistema'). Por eso la procedencia sale en el
    resultado de la operación, al lado de los contadores."""
    from shared.data import snapshots

    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    snapshots.write_snapshot("siuben_provincial",
                             [("siuben_illiteracy_head_share", "elias_pina", "2024-Q4", 36.3)],
                             source="SIUBEN")

    import shared.data.siuben_client as siuben

    def _caido():
        raise ConnectionError("timed out")

    monkeypatch.setattr(siuben, "fetch_siuben_provincial", _caido)
    from modules.social_dev.social_sync import _sync_siuben_provincial

    prov = {}
    assert _sync_siuben_provincial(db, lambda _m: None, prov) == 1
    db.commit()
    # La cifra entró…
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="elias_pina", theme="siuben_illiteracy_head_share").first()
    )
    assert row is not None and row.value == 36.3
    # …y el resultado DICE que vino de una foto, con su fecha.
    assert prov["siuben_provincial"].startswith("snapshot:")
    assert len(prov["siuben_provincial"].split(":", 1)[1]) == 10


def test_con_la_fuente_viva_la_procedencia_dice_live(db, monkeypatch):
    """El contrapeso: si la fuente responde, no se rotula como foto."""
    import shared.data.siuben_client as siuben

    monkeypatch.setattr(
        siuben, "fetch_siuben_provincial",
        lambda: [("siuben_illiteracy_head_share", "azua", "2024-Q4", 20.0)])
    from modules.social_dev.social_sync import _sync_siuben_provincial

    prov = {}
    assert _sync_siuben_provincial(db, lambda _m: None, prov) == 1
    assert prov["siuben_provincial"] == "live"


def _ind(db, entity, theme, period, value, source="ONE"):
    db.add(SocialIndicator(entity_key=entity, theme=theme, period=period, value=value, source=source))


def test_assemble_idm_real_plus_rubric_with_sources(db):
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "nacional", "life_expectancy", "2024", 73.9, source="WDI")
    _ind(db, "nacional", "child_mortality", "2024", 27.7, source="WDI")
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    assert asm["period"] == "2024" and asm["has_live"]
    assert len(asm["dataset"]) == 10                         # the 10 development regions
    enr, src = asm["dataset"]["enriquillo"], asm["sources"]["enriquillo"]
    assert enr["poverty_rate"] == 31.0 and src["poverty_rate"] == "live"   # ONE, by region
    assert enr["life_expectancy"] == 73.9 and src["life_expectancy"] == "live"  # WDI national
    # No national labour yet → income/informality fall back to declared rubric 50.
    assert src["income_per_capita"] == "rubric" and enr["income_per_capita"] == 50
    assert src["informality_rate"] == "rubric" and enr["informality_rate"] == 50


def test_informalidad_nacional_va_live_a_todas_las_regiones(db):
    """La informalidad (ENCFT del BCRD) sí es nacional: la MISMA cifra a las 10 regiones."""
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "nacional", "informality_rate", "2024", 55.46, source="BCRD")
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    for slug in ("enriquillo", "valdesia"):                  # uniform across regions
        row, src = asm["dataset"][slug], asm["sources"][slug]
        assert row["informality_rate"] == 55.46 and src["informality_rate"] == "live"
    # financial_inclusion has no source → stays declared rubric.
    assert asm["sources"]["enriquillo"]["financial_inclusion"] == "rubric"


def _all_regions_income(db, period="2024", base=13000.0):
    from shared.data.one_client import REGIONS

    for i, (slug, _label) in enumerate(REGIONS):
        _ind(db, slug, "income_per_capita", period, base + i * 500, source="MEPyD")


def test_el_ingreso_ahora_DISTINGUE_regiones(db):
    """El corazón del cambio. El ingreso era el proxy horario de la ONE: una constante
    nacional, la misma cifra para las 10 regiones, que sostenía el NIVEL del índice pero
    no podía mover el orden entre demarcaciones. Con el SISDOM cada región trae la suya."""
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _all_regions_income(db)
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    valores = {slug: row["income_per_capita"] for slug, row in asm["dataset"].items()}
    assert len(set(valores.values())) == 10, (
        "el ingreso volvió a ser una constante con etiqueta geográfica: " f"{valores}")
    assert all(s["income_per_capita"] == "live" for s in asm["sources"].values())


def test_el_ingreso_incompleto_NO_entra_a_medias(db):
    """Nueve de diez regiones no es 'casi': el motor normaliza min-max ENTRE regiones, así
    que la que falta corre el mínimo o el máximo y cambia el score de las otras nueve.
    O están las 10 o la variable queda en rúbrica uniforme, que no discrimina ni finge."""
    from shared.data.one_client import REGIONS

    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    for slug, _label in REGIONS[:-1]:                       # falta una
        _ind(db, slug, "income_per_capita", "2024", 15000.0, source="MEPyD")
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    assert all(s["income_per_capita"] == "rubric" for s in asm["sources"].values())
    assert {row["income_per_capita"] for row in asm["dataset"].values()} == {50.0}


def test_el_ingreso_no_se_cae_si_la_pobreza_avanza_primero(db):
    """El SISDOM es anual y puede quedar un año detrás de la pobreza, que es la serie que
    fija el período objetivo. Se toma el ÚLTIMO valor disponible por región: si se atara
    al período, la variable desaparecería del panel el día que la pobreza publique antes."""
    _ind(db, "enriquillo", "poverty_rate", "2025", 30.0)
    _ind(db, "valdesia", "poverty_rate", "2025", 10.0)
    _all_regions_income(db, period="2024")                  # el ingreso va un año atrás
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    assert asm["period"] == "2025"
    assert asm["sources"]["enriquillo"]["income_per_capita"] == "live"
    assert asm["dataset"]["enriquillo"]["income_per_capita"] == 15500.0


def test_region_slug_es_el_padron_de_regiones_para_cualquier_emisor():
    """``region_slug`` sobrevivió al parser de cobertura de la ONE porque el padrón de
    regiones —con sus alias— no era de ese cuadro: hoy lo consume el conector del
    MINERD, que es otro emisor. Se fija acá para que un borrado futuro no se lo lleve."""
    from shared.data.one_client import region_slug

    assert region_slug("Región Metropolitana") == "ozama"      # alias + prefijo "Región"
    assert region_slug("Cibao Norte") == "cibao_norte"          # sin prefijo
    assert region_slug("Gran Santo Domingo") == "ozama"
    assert region_slug("Total país") is None                    # no se adivina
    assert region_slug(None) is None


def test_coverage_goes_live_by_region_and_period(db):
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "enriquillo", "secondary_coverage", "2024", 66.8)   # valdesia has none
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    enr = asm["dataset"]["enriquillo"]
    assert enr["secondary_coverage"] == 66.8                            # by region + period
    assert asm["sources"]["enriquillo"]["secondary_coverage"] == "live"
    # A region without coverage that period → rubric, value excluded (engine skips it).
    assert asm["sources"]["valdesia"]["secondary_coverage"] == "rubric"
    assert "secondary_coverage" not in asm["dataset"]["valdesia"]


def test_indicator_units_fit_postgres_varchar40():
    """sd_indicators.unit is VARCHAR(40): SQLite ignores it, Postgres truncates →
    every declared unit string must fit (dev↔prod parity guard)."""
    from shared.data.siuben_client import DATASETS as SIUBEN_DATASETS
    from shared.data.sisdom_income import UNIT as INCOME_UNIT
    from modules.social_dev.social_sync import COVERAGE_UNIT, FINDEX_UNIT, INFORMALITY_UNIT

    units = ([INFORMALITY_UNIT, INCOME_UNIT, COVERAGE_UNIT, FINDEX_UNIT, "años"]
             + [s.unit for s in SIUBEN_DATASETS])
    too_long = [u for u in units if len(u) > 40]
    assert not too_long, f"unit > 40 chars (rompe en Postgres): {too_long}"


def test_columnas_de_texto_provinciales_caben_en_postgres():
    """Los slugs provinciales y los códigos SIUBEN viajan por columnas acotadas:
    entity_key VARCHAR(60), theme VARCHAR(60), source VARCHAR(40), period VARCHAR(10)."""
    from shared.data.siuben_client import DATASETS as SIUBEN_DATASETS
    from shared.data.siuben_client import SOURCE as SIUBEN_SOURCE
    from shared.reference.provinces import PROVINCES

    assert all(len(slug) <= 60 for slug, _n, _r in PROVINCES)
    assert all(len(s.theme) <= 60 for s in SIUBEN_DATASETS)
    assert len(SIUBEN_SOURCE) <= 40
    assert len("2026-Q4") <= 10          # el período trimestral del SIUBEN


def test_sync_siuben_provincial_upserts_por_provincia(db, monkeypatch):
    """Las series provinciales entran rotuladas y son idempotentes."""
    import shared.data.siuben_client as siuben

    rows = [("siuben_illiteracy_head_share", "elias_pina", "2024-Q4", 36.3),
            ("siuben_illiteracy_head_share", "distrito_nacional", "2024-Q4", 7.5),
            ("siuben_overcrowding_share", "elias_pina", "2024-Q4", 22.1)]
    monkeypatch.setattr(siuben, "fetch_siuben_provincial", lambda: rows)
    from modules.social_dev.social_sync import _sync_siuben_provincial

    assert _sync_siuben_provincial(db, lambda _m: None, {}) == 3
    db.commit()
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="elias_pina", theme="siuben_illiteracy_head_share",
                   period="2024-Q4")
        .first()
    )
    assert row is not None and row.value == 36.3
    assert row.source == "SIUBEN" and row.disaggregation == "provincia"
    assert "padrón" in (row.unit or "")        # el universo viaja con el dato

    # Segunda corrida: upsert en el lugar, sin duplicar.
    assert _sync_siuben_provincial(db, lambda _m: None, {}) == 3
    db.commit()
    assert db.query(SocialIndicator).filter_by(source="SIUBEN").count() == 3


def test_siuben_no_contamina_el_idm(db, monkeypatch):
    """Mismo guardia que con la cobertura provincial: el IDM no debe moverse."""
    import shared.data.siuben_client as siuben
    from modules.social_dev.service import assemble_idm_dataset
    from modules.social_dev.social_sync import _sync_siuben_provincial

    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    db.commit()
    before = assemble_idm_dataset(db)

    monkeypatch.setattr(
        siuben, "fetch_siuben_provincial",
        lambda: [("siuben_illiteracy_head_share", "elias_pina", "2024-Q4", 36.3)])
    _sync_siuben_provincial(db, lambda _m: None, {})
    db.commit()

    after = assemble_idm_dataset(db)
    assert after["dataset"] == before["dataset"] and after["sources"] == before["sources"]


def test_findex_financial_inclusion_goes_live_latest_available(db):
    """WB Findex financial access is national + lags; the latest value goes live for
    the current IDM period (so inclusión is real even if the target year has no obs)."""
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "nacional", "financial_inclusion", "2023", 40.06, source="WB")  # 2023, not 2024
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    assert asm["period"] == "2024"
    for slug in ("enriquillo", "valdesia"):                     # national → every region, live
        assert asm["dataset"][slug]["financial_inclusion"] == 40.06
        assert asm["sources"][slug]["financial_inclusion"] == "live"


def test_sync_wb_findex_upserts_national(db, monkeypatch):
    import shared.data.wdi_client as wdi

    monkeypatch.setattr(
        wdi, "fetch_wb_indicator",
        lambda code, isos, mrv=25: ([{"date": "2023", "value": 40.06},
                                     {"date": "2022", "value": 38.5}], None),
    )
    from modules.social_dev.social_sync import _sync_wb_findex

    n = _sync_wb_findex(db, lambda _m: None)
    db.commit()
    assert n == 2
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="nacional", theme="financial_inclusion", period="2023")
        .first()
    )
    assert row is not None and row.value == 40.06 and row.source == "WB"


def test_sync_minerd_coverage_upserts_by_region(db, monkeypatch):
    import shared.data.minerd_coverage as mc_mod

    monkeypatch.setattr(
        mc_mod, "fetch_minerd_coverage_levels",
        lambda: [("secundaria", "region", "enriquillo", 2024, 66.8),
                 ("secundaria", "region", "ozama", 2024, 67.7),
                 ("secundaria", "provincia", "distrito_nacional", 2024, 73.1),
                 ("secundaria", "pais", "pais", 2024, 71.0),
                 ("basica", "pais", "pais", 2024, 93.2)],
    )
    from modules.social_dev.social_sync import _sync_minerd_coverage

    n = _sync_minerd_coverage(db, lambda _m: None, {})
    db.commit()
    assert n == 5
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="enriquillo", theme="secondary_coverage", period="2024")
        .first()
    )
    assert row is not None and row.value == 66.8 and row.source == "MINERD"
    # El TOTAL PAÍS llega a la base con su propia entidad: es la única cifra de cobertura
    # comparable contra una meta nacional, y antes se descartaba en el parser.
    pais = (db.query(SocialIndicator)
            .filter_by(entity_key="pais", theme="secondary_coverage", period="2024").first())
    assert pais is not None and pais.value == 71.0
    basica = (db.query(SocialIndicator)
              .filter_by(entity_key="pais", theme="primary_coverage", period="2024").first())
    assert basica is not None and basica.value == 93.2, "el nivel básico va a su propio tema"
    assert row.disaggregation == "region"
    # La provincia convive con la región bajo el mismo tema, distinguida por el nivel.
    prov = (
        db.query(SocialIndicator)
        .filter_by(entity_key="distrito_nacional", theme="secondary_coverage", period="2024")
        .first()
    )
    assert prov is not None and prov.value == 73.1 and prov.disaggregation == "provincia"


def test_cobertura_provincial_no_mueve_el_idm(db, monkeypatch):
    """Guardia estructural: el IDM se ensambla sobre las 10 regiones. Agregar filas
    provinciales —o la del TOTAL PAÍS— bajo el MISMO tema no debe cambiar ni un score ni
    una procedencia. Si algún día el ensamblador empezara a barrer entidades, este test lo
    detecta: la fila de país entraría al índice como si fuera una región más y movería
    todos los scores a la vez, que es la forma más difícil de notar el error."""
    import shared.data.minerd_coverage as mc_mod
    from modules.social_dev.service import assemble_idm_dataset
    from modules.social_dev.social_sync import _sync_minerd_coverage

    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "enriquillo", "secondary_coverage", "2024", 66.8)
    db.commit()
    before = assemble_idm_dataset(db)

    monkeypatch.setattr(
        mc_mod, "fetch_minerd_coverage_levels",
        lambda: [("secundaria", "provincia", "distrito_nacional", 2024, 73.1),
                 ("secundaria", "provincia", "elias_pina", 2024, 41.2),
                 ("secundaria", "pais", "pais", 2024, 71.0),
                 ("basica", "pais", "pais", 2024, 93.2)],
    )
    _sync_minerd_coverage(db, lambda _m: None, {})
    db.commit()

    after = assemble_idm_dataset(db)
    assert after["dataset"] == before["dataset"]
    assert after["sources"] == before["sources"]
    assert len(after["dataset"]) == 10          # sigue siendo el panel de regiones


def test_sync_sisdom_income_upserts_por_region(db, monkeypatch):
    """El ingreso entra rotulado por región y es idempotente."""
    import shared.data.sisdom_income as sisdom

    rows = [("enriquillo", 2024, 13499.35), ("cibao_norte", 2024, 19607.32),
            ("enriquillo", 2023, 11118.8)]
    monkeypatch.setattr(sisdom, "fetch_sisdom_income_per_capita", lambda: rows)
    from modules.social_dev.social_sync import _sync_sisdom_income

    assert _sync_sisdom_income(db, lambda _m: None) == 3
    db.commit()
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="enriquillo", theme="income_per_capita", period="2024")
        .first()
    )
    assert row is not None and row.value == 13499.35
    assert row.source == "MEPyD" and row.disaggregation == "region"
    assert "RD$" in (row.unit or ""), "la unidad monetaria viaja con el dato"

    assert _sync_sisdom_income(db, lambda _m: None) == 3     # upsert en el lugar
    db.commit()
    assert db.query(SocialIndicator).filter_by(theme="income_per_capita").count() == 3


def test_el_proxy_nacional_de_la_ONE_se_da_de_baja(db, monkeypatch):
    """Bajo el mismo tema convivirían RD$/hora (~167) y RD$/mes por persona (~18.000):
    dos órdenes de magnitud y dos unidades. El upsert no las alcanza porque cambió la
    entidad, así que quedarían para siempre esperando a que algo las lea."""
    import shared.data.sisdom_income as sisdom

    _ind(db, "nacional", "income_per_capita", "2024", 167.46, source="ONE")
    _ind(db, "nacional", "schooling_years", "2024", 9.61, source="ONE")   # NO se toca
    db.commit()

    monkeypatch.setattr(sisdom, "fetch_sisdom_income_per_capita",
                        lambda: [("enriquillo", 2024, 13499.35)])
    from modules.social_dev.social_sync import _sync_sisdom_income

    _sync_sisdom_income(db, lambda _m: None)
    db.commit()

    assert db.query(SocialIndicator).filter_by(
        entity_key="nacional", theme="income_per_capita").count() == 0
    # La baja es QUIRÚRGICA: la escolaridad nacional de la ONE sigue intacta.
    assert db.query(SocialIndicator).filter_by(
        entity_key="nacional", theme="schooling_years").first() is not None


def test_si_el_SISDOM_falla_NO_se_borra_lo_que_hay(db, monkeypatch):
    """El orden importa: primero traer, después dar de baja. Si se borrara antes, una
    caída del MEPyD dejaría la variable sin nada y con la vieja ya destruida."""
    import shared.data.sisdom_income as sisdom

    _ind(db, "nacional", "income_per_capita", "2024", 167.46, source="ONE")
    db.commit()

    def _boom():
        raise sisdom.SisdomUnavailable("el listado no respondió")

    monkeypatch.setattr(sisdom, "fetch_sisdom_income_per_capita", _boom)
    from modules.social_dev.social_sync import _sync_sisdom_income

    with pytest.raises(sisdom.SisdomUnavailable):     # sube a _best_effort, que la DECLARA
        _sync_sisdom_income(db, lambda _m: None)
    assert db.query(SocialIndicator).filter_by(theme="income_per_capita").count() == 1


def test_la_serie_de_ingreso_se_sirve_como_MONTO_no_como_tasa(db):
    """La Data API tenía la naturaleza clavada en 'rate' porque todas las series del eje
    eran porcentajes. El ingreso viene en RD$: servirlo como tasa haría que un consumidor
    leyera su variación en PUNTOS y publicara 'el ingreso subió 2.400 puntos'."""
    from shared.data.sisdom_income import UNIT
    from modules.social_dev.service import subnational_series

    db.add(SocialIndicator(entity_key="enriquillo", theme="income_per_capita",
                           period="2024", value=13499.35, source="MEPyD",
                           disaggregation="region", unit=UNIT))
    db.add(SocialIndicator(entity_key="enriquillo", theme="poverty_rate",
                           period="2024", value=31.0, source="ONE",
                           disaggregation="region", unit="% de la población"))
    db.commit()

    by = {s["code"]: s for s in subnational_series(db)}
    ingreso = by["income_per_capita.enriquillo"]
    assert ingreso["nature"] == "flow", "un monto en RD$ no es una tasa"
    assert by["poverty_rate.enriquillo"]["nature"] == "rate"   # el resto no se movió
    # La licencia y el emisor viajan: una serie sin licencia no se sabe si se puede citar.
    assert ingreso["license"] and "MEPyD" in ingreso["license"]
    assert "MEPyD" in ingreso["note"]
    assert "ONE" in by["poverty_rate.enriquillo"]["note"]


def test_escolaridad_por_region_da_de_baja_la_fila_nacional(db, monkeypatch):
    """El cambio es DESTRUCTIVO a propósito y por eso lleva guard.

    Bajo el mismo tema convivirían el valor país (9,18) y los diez regionales; el upsert
    no alcanza la fila nacional porque cambió la entidad, así que hay que darla de baja.
    Corre DESPUÉS de que la fuente nueva trajo dato: una caída del MEPyD no puede
    destruir lo que hay."""
    import shared.data.sisdom_schooling as sis

    _ind(db, "nacional", "schooling_years", "2024", 9.18)      # el proxy anterior
    db.commit()
    monkeypatch.setattr(sis, "fetch_sisdom_schooling",
                        lambda: [("ozama", 2024, 10.29), ("enriquillo", 2024, 7.98)])
    from modules.social_dev.social_sync import _sync_sisdom_schooling

    assert _sync_sisdom_schooling(db, lambda _m: None) == 2
    db.commit()
    assert db.query(SocialIndicator).filter_by(
        entity_key="nacional", theme="schooling_years").count() == 0
    fila = db.query(SocialIndicator).filter_by(
        entity_key="ozama", theme="schooling_years", period="2024").first()
    assert fila is not None and fila.value == 10.29
    assert fila.source == "MEPyD" and fila.disaggregation == "region"


def test_una_caida_del_mepyd_no_destruye_la_escolaridad_cargada(db, monkeypatch):
    """El contrapeso del test anterior: sin dato nuevo, no se borra el viejo."""
    import shared.data.sisdom_schooling as sis

    _ind(db, "nacional", "schooling_years", "2024", 9.18)
    db.commit()

    def _caido():
        raise ConnectionError("MEPyD no responde")

    monkeypatch.setattr(sis, "fetch_sisdom_schooling", _caido)
    from modules.social_dev.social_sync import _sync_sisdom_schooling

    with pytest.raises(ConnectionError):
        _sync_sisdom_schooling(db, lambda _m: None)
    assert db.query(SocialIndicator).filter_by(theme="schooling_years").count() == 1


def test_la_mortalidad_de_ENDESA_no_puede_entrar_al_IDM(db, monkeypatch):
    """Guard estructural, no de buena voluntad.

    La serie es de 2002/2007: si entrara al índice, todo período posterior quedaría con
    el mismo número — otra constante nacional, solo que con etiqueta provincial. No entra
    por dos razones independientes: usa OTRO tema (`endesa_child_mortality`) y escribe en
    entidades provinciales, mientras el ensamblador lee `child_mortality` de `nacional`."""
    import shared.data.sisdom_child_mortality as scm
    from modules.social_dev.service import assemble_idm_dataset

    for slug in ("enriquillo", "valdesia"):
        _ind(db, slug, "poverty_rate", "2024", 20.0)
    _ind(db, "nacional", "child_mortality", "2024", 27.7, source="WDI")
    db.commit()
    antes = assemble_idm_dataset(db)

    monkeypatch.setattr(scm, "fetch_endesa_child_mortality",
                        lambda: [("azua", 2007, 35.0), ("espaillat", 2007, 11.0)])
    from modules.social_dev.social_sync import _sync_endesa_child_mortality

    assert _sync_endesa_child_mortality(db, lambda _m: None) == 2
    db.commit()

    despues = assemble_idm_dataset(db)
    assert despues["dataset"] == antes["dataset"]
    assert despues["sources"] == antes["sources"]
    # La del índice sigue siendo la de WDI, nacional.
    assert all(s["child_mortality"] == "live" for s in despues["sources"].values())
    assert all(d["child_mortality"] == 27.7 for d in despues["dataset"].values())


def test_la_serie_de_ENDESA_sale_por_la_API_con_su_advertencia(db, monkeypatch):
    """Publicarla es legítimo; servirla como si fuera actual, no. La advertencia viaja
    en la nota del descriptor, que es lo que lee quien la consume."""
    import shared.data.sisdom_child_mortality as scm
    from modules.social_dev.service import subnational_series

    monkeypatch.setattr(scm, "fetch_endesa_child_mortality",
                        lambda: [("azua", 2007, 35.0)])
    from modules.social_dev.social_sync import _sync_endesa_child_mortality

    _sync_endesa_child_mortality(db, lambda _m: None)
    db.commit()

    serie = next(x for x in subnational_series(db)
                 if x["code"] == "endesa_child_mortality.azua")
    assert serie["period_latest"] == "2007"
    assert "ENDESA" in serie["label"]
    assert "no lo alimenta" in serie["note"]        # dice que NO entra al índice
    assert "no deben graficarse juntas" in serie["note"]
    assert serie["license"]                          # sin licencia iría a cuarentena


def test_todo_sub_sync_de_red_esta_sustituido_en_el_test_de_idempotencia():
    """Un sub-sync nuevo que nadie agregue a la lista de sustituidos sale a la RED en CI.

    Pasó al agregar el mercado laboral: el test no lo conocía, bajó el libro del BCRD de
    verdad e insertó 33 filas reales, y falló por un conteo que no tenía nada que ver con
    lo que el test mide. Peor que el falso rojo es el caso silencioso — un sub-sync que
    devuelva pocas filas no rompe ningún conteo y deja al CI dependiendo de que el CDN de
    un tercero esté en pie.

    Se lee el código con `ast` en vez de mantener la lista a mano: una lista a mano tiene
    exactamente el mismo problema que este test viene a resolver.
    """
    import ast
    import inspect

    from modules.social_dev import social_sync

    arbol = ast.parse(inspect.getsource(social_sync))
    definidos = {n.name for n in ast.walk(arbol)
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("_sync_")}
    # Los que este test SÍ deja correr: NO tocan la red.
    #   `_sync_one_regional`          lee del fixture comiteado.
    #   `_sync_conteos_regionales`    computa sobre las filas que las otras sub-syncs
    #                                 dejaron en la base — es justamente lo que hay que
    #                                 ejercitar de verdad para saber que el conteo cuadra.
    # ══ 2026-08-24 ══ Antes leía la lista LITERAL de dentro del test de idempotencia. Eso
    # lo volvió ciego el día que las tres listas del archivo se unificaron en
    # `SUB_SYNCS_DE_RED`: el guard seguía verde por no encontrar nada que revisar. Ahora
    # mira la constante, que es donde la lista vive.
    sin_sustituir = sorted(definidos - set(SUB_SYNCS_DE_RED) - set(SUB_SYNCS_SIN_RED))
    assert not sin_sustituir, (
        f"estos sub-syncs no están en ninguna lista y saldrán a la red en CI: "
        f"{sin_sustituir}.\nSi pega a la red va en `SUB_SYNCS_DE_RED`; si no, decilo en "
        f"`SUB_SYNCS_SIN_RED` y queda escrito por qué."
    )
    fantasmas = sorted((set(SUB_SYNCS_DE_RED) | set(SUB_SYNCS_SIN_RED)) - definidos)
    assert not fantasmas, (
        f"las listas nombran funciones que ya no existen: {fantasmas}. Un nombre viejo en un "
        f"`monkeypatch.setattr` no falla: sustituye un atributo que nadie llama."
    )


def test_ninguna_escritura_queda_del_otro_lado_del_COMMIT():
    """REGLA ESTRUCTURAL: ningún sub-sync corre después de `db.commit()`.

    El modo de fallar es el peor que existe. Los conteos regionales (2.2 y 2.5 de la END)
    quedaron un rato después del commit: los 50 upserts ocurrían, el contador devolvía 50,
    ningún error se levantaba, y las filas se perdían al cerrar la sesión. La operación
    reportaba éxito con un número correcto sobre datos que no existían.

    **El test de idempotencia no puede detectarlo** y por eso hace falta este: consulta con
    la MISMA sesión, donde lo no comiteado igual se ve. Solo apareció al pedirle el dato al
    Data Registry en producción, que usa otra sesión.
    """
    import ast
    import inspect

    from modules.social_dev import social_sync

    import textwrap

    # `cleandoc` desangra el docstring y rompe la indentación del cuerpo; `dedent` respeta
    # el bloque entero, que es lo que hay que parsear.
    arbol = ast.parse(textwrap.dedent(inspect.getsource(social_sync.one_social_sync)))
    commits = [n.lineno for n in ast.walk(arbol)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "commit"]
    assert commits, "la sync tiene que comitear"
    llamadas = [(n.lineno, n.func.id) for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id.startswith("_sync_")]
    tardias = [(ln, nm) for ln, nm in llamadas if ln > max(commits)]
    assert not tardias, (
        f"estos sub-syncs corren DESPUÉS del último commit y sus escrituras se pierden sin "
        f"error, con el contador devolviendo el número correcto: {tardias}")


def test_los_conteos_derivados_se_comitean_ANTES_de_las_fases_largas():
    """Railway REINICIA las tareas largas de este servicio: la sync muere durante SIUBEN
    (3.456 filas provinciales) y todo lo no comiteado se pierde. Tres corridas seguidas
    terminaron en «interrumpido por reinicio».

    Los conteos de los indicadores 2.2 y 2.5 solo necesitan el panel regional de la primera
    fase, así que ponerlos al final —que parecía lo natural, «que lean todo lo escrito»— los
    dejaba en el punto de máxima exposición sin ninguna ganancia.

    El test fija el orden y no el comentario: es la diferencia entre depender de que la sync
    entera termine y depender solo de su primera fase.
    """
    import ast
    import inspect
    import textwrap

    from modules.social_dev import social_sync

    arbol = ast.parse(textwrap.dedent(inspect.getsource(social_sync.one_social_sync)))
    llamadas = {n.func.id: n.lineno for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    commits = sorted(n.lineno for n in ast.walk(arbol)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "commit")
    conteos = llamadas["_sync_conteos_regionales"]
    largas = [llamadas[n] for n in ("_sync_siuben_provincial", "_sync_minerd_coverage")
              if n in llamadas]
    assert largas, "el test tiene que conocer las fases largas o no prueba nada"
    assert conteos < min(largas), (
        "los conteos corren después de una fase larga: un reinicio de la plataforma se los "
        "lleva sin dejar rastro")
    assert any(c > conteos for c in commits), "los conteos necesitan un commit después"
    assert min(c for c in commits if c > conteos) < min(largas), (
        "el commit de los conteos tiene que ocurrir ANTES de las fases largas, no al final")


def test_todo_test_que_corre_el_sync_ENTERO_neutraliza_la_lista_completa():
    """La lista no sirve si un test la usa a medias.

    `test_una_fuente_caida_queda_declarada_en_errors` sustituia SIETE de veintidos y los
    otros quince pegaban al emisor. No fallaba: afirmaba algo sobre `errors` mientras
    `errors` dependia de si el portal de un tercero estaba arriba ese dia. Un test asi no
    prueba lo que dice probar, y el dia que se pone rojo manda a investigar nuestro codigo.

    Se lee ESTE archivo con `ast`: toda funcion que llame a `one_social_sync` tiene que
    nombrar `SUB_SYNCS_DE_RED`. Sustituir de a uno es legitimo DESPUES, para armar el
    escenario — lo que no se puede es que sea el unico blindaje.
    """
    import ast

    arbol = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    en_falta = []
    for n in ast.walk(arbol):
        if not isinstance(n, ast.FunctionDef) or not n.name.startswith("test_"):
            continue
        nombres = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
        llamadas = {x.func.id for x in ast.walk(n)
                    if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)}
        if "one_social_sync" in llamadas and "SUB_SYNCS_DE_RED" not in nombres:
            en_falta.append(n.name)
    assert not en_falta, (
        f"estos tests corren el sync entero sin neutralizar la lista completa: {en_falta}. "
        f"Recorre `SUB_SYNCS_DE_RED` primero y despues sustitui de a uno lo que el escenario "
        f"necesite; al reves, lo que no nombraste se ejecuta contra el emisor.")
