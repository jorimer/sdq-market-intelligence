"""El feed de construcción usa el municipio y el barrio/sector del MIVHED (decisión del dueño,
2026-09-15). Lo que se protege es el SUJETO —un barrio sin su municipio no identifica la
plaza— y el TOTAL: las filas finas llevan la provincia, y no pueden sumarse a ella.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.mivhed_client import parse_licenses_mensual
from shared.database.base import Base
from shared.observations import service as obs

_CSV = ("Fecha de Emisión,Mes,Año,Provincia,Municipio,Barrio/Sector,Número de Licencia,"
        "Tipologia,Metros Cuadrados,Inversión Total\n"
        "06/01/2026,JUNIO,2026,SANTO DOMINGO,SANTO DOMINGO ESTE,CENTRO,1,VIVIENDAS,100,1\n"
        "06/02/2026,JUNIO,2026,SANTO DOMINGO,SANTO DOMINGO ESTE,CENTRO,2,VIVIENDAS,50,1\n"
        "06/03/2026,JUNIO,2026,SANTIAGO,SANTIAGO,CENTRO,3,APARTAMENTOS,300,1\n"
        "06/04/2026,JUNIO,2026,SANTO DOMINGO,BOCA CHICA,LA CALETA,4,APARTAMENTOS,700,1\n")


@pytest.fixture()
def db():
    import app.main  # noqa: F401
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e)()


def test_el_parser_separa_barrios_homonimos_de_municipios_distintos():
    junio = parse_licenses_mensual(_CSV)["periodos"]["2026-06"]
    assert junio["by_barrio"][("SANTO DOMINGO", "SANTO DOMINGO ESTE", "CENTRO")]["sqm"] == 150.0
    assert junio["by_barrio"][("SANTIAGO", "SANTIAGO", "CENTRO")]["sqm"] == 300.0
    assert junio["by_municipio"][("SANTO DOMINGO", "BOCA CHICA")]["sqm"] == 700.0
    assert junio["by_province"]["SANTO DOMINGO"]["sqm"] == 850.0


def _ingestar(db):
    from modules.construction_intel.service import SECTOR_KEY_OBS, ingest_observaciones_mensuales
    mensual = parse_licenses_mensual(_CSV)
    mensual["publicado_el"] = "2026-07-21"
    ingest_observaciones_mensuales(db, mensual)
    db.commit()
    return SECTOR_KEY_OBS


def test_la_provincia_NO_suma_sus_municipios_ni_sus_barrios(db):
    from modules.construction_intel.service import SERIE_SQM
    sk = _ingestar(db)
    prov = {r["provincia"]: r["valor"] for r in obs.por_dimension(
        db, sector_key=sk, series_code=SERIE_SQM, period="2026-06", campo="provincia")}
    assert prov == {"SANTO DOMINGO": 850.0, "SANTIAGO": 300.0}
    tip = {r["tipologia"]: r["valor"] for r in obs.por_dimension(
        db, sector_key=sk, series_code=SERIE_SQM, period="2026-06", campo="tipologia")}
    assert sum(tip.values()) == 1150.0


def test_el_municipio_sale_con_su_provincia_y_el_barrio_con_su_municipio(db):
    from modules.construction_intel.service import SERIE_SQM
    sk = _ingestar(db)
    mun = obs.por_dimension(db, sector_key=sk, series_code=SERIE_SQM, period="2026-06",
                            campo="municipio")
    assert mun[0] == {"provincia": "SANTO DOMINGO", "municipio": "BOCA CHICA", "valor": 700.0,
                      "unidad": "m2"}
    barrios = obs.por_dimension(db, sector_key=sk, series_code=SERIE_SQM, period="2026-06",
                                campo="barrio")
    centros = [(b["municipio"], b["valor"]) for b in barrios if b["barrio"] == "CENTRO"]
    assert sorted(centros) == [("SANTIAGO", 300.0), ("SANTO DOMINGO ESTE", 150.0)]


def test_el_agregado_del_mes_sigue_siendo_uno_solo(db):
    from modules.construction_intel.service import SERIE_SQM
    sk = _ingestar(db)
    filas = obs.serie(db, sector_key=sk, series_code=SERIE_SQM)
    assert [(f.period, f.value) for f in filas] == [("2026-06", 1150.0)]


def test_una_dimension_desconocida_sigue_fallando():
    with pytest.raises(ValueError):
        obs.por_dimension(None, sector_key="x", series_code="y", period="z", campo="calle")
