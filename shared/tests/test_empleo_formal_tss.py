"""El empleo formal de la TSS entra al perfil del sector SUMADO a la ENCFT, no en su lugar.

Decisión del dueño, 2026-09-15. Los números de los fixtures son los reales del reporte de
Cotizaciones de la TSS bajado ese día (totales mensuales y construcción).
"""
from datetime import date

import pytest

from shared.data.sector_crosswalk import cotizantes_by_slug, tss_shared_slugs
from shared.data.tss_salary import meses_completos, periodo_mensual
from shared.perfil_del_sector import (QUE_MIDE_EL_EMPLEO_FORMAL, contexto_del_perfil_del_sector,
                                      empleo_formal_del_sector, perfil_del_sector)
from shared.reference.sector_variables import LABOR_TSS_DIMENSION, SectorVariable

#: Totales mensuales reales (TSS, 2026-09-15): junio y julio seguían llegando.
_TOTALES = {"2026-03": 2458632.0, "2026-04": 2462574.0, "2026-05": 2461811.0,
            "2026-06": 2392217.0, "2026-07": 12153.0}


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.main  # noqa: F401
    from shared.database.base import Base
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e)()


def test_los_meses_que_siguen_llegando_se_descartan_desde_el_final():
    completos, descartados = meses_completos(_TOTALES)
    assert completos[-1] == "2026-05"
    assert descartados == ["2026-06", "2026-07"]


def test_un_mes_con_una_caida_real_pequena_no_se_descarta():
    completos, descartados = meses_completos({"2026-04": 2462574.0, "2026-05": 2461811.0})
    assert completos == ["2026-04", "2026-05"] and descartados == []


@pytest.mark.parametrize("crudo,esperado", [("202605", "2026-05"), (202612, "2026-12"),
                                             ("2026-05", "2026-05"), ("202613", None), ("", None)])
def test_el_periodo_de_la_tss_se_normaliza(crudo, esperado):
    assert periodo_mensual(crudo) == esperado


def test_los_cotizantes_se_SUMAN_por_slug_y_el_agregado_se_comparte():
    por_slug = cotizantes_by_slug({"cultivo_de_cereales": 10.0, "cultivos_tradicionales": 20.0,
                                   "ganaderia_silvicultura_y_pesca": 5.0,
                                   "servicios_agropecuarios": 1.0, "manufactura": 290652.0})
    assert por_slug["agropecuario"] == 36.0, "son conteos: se suman, no se promedian"
    assert por_slug["manufactura_local"] == por_slug["zonas_francas"] == 290652.0
    assert por_slug["construccion"] is None
    assert tss_shared_slugs("zonas_francas") == ["manufactura_local"]
    assert tss_shared_slugs("construccion") == []


def _filas(meses_valores):
    """Filas crudas del reporte: todas las actividades con un total que reparte el mes."""
    from shared.data.sector_crosswalk import SLUG_TO_TSS_ACTIVITIES
    actividades = sorted({a for acts in SLUG_TO_TSS_ACTIVITIES.values() for a in acts})
    return [(a, mes, total / len(actividades)) for mes, total in meses_valores.items()
            for a in actividades]


def test_el_sync_persiste_solo_meses_completos_y_no_duplica(db):
    from modules.sector_intel.sectors_sync import tss_empleo_formal_sync
    r = tss_empleo_formal_sync(db, filas=_filas(_TOTALES))
    assert r["ultimo_mes_completo"] == "2026-05" and r["descartados"] == ["2026-06", "2026-07"]
    n = db.query(SectorVariable).filter_by(dimension=LABOR_TSS_DIMENSION).count()
    tss_empleo_formal_sync(db, filas=_filas(_TOTALES))
    assert db.query(SectorVariable).filter_by(dimension=LABOR_TSS_DIMENSION).count() == n, (
        "re-sincronizar duplicó filas")
    periodos = {p for (p,) in db.query(SectorVariable.period).filter_by(
        dimension=LABOR_TSS_DIMENSION)}
    assert "2026-06" not in periodos and "2026-05" in periodos


def _sembrar(db, slug, pares):
    for mes, v in pares:
        db.add(SectorVariable(sector_code=slug, dimension=LABOR_TSS_DIMENSION,
                              variable="trabajadores_cotizantes", period=mes, value=v))
    db.commit()


def test_la_lectura_toma_el_ultimo_mes_HASTA_el_corte_y_su_interanual(db):
    _sembrar(db, "construccion", [("2024-12", 79402.0), ("2025-12", 84514.0),
                                  ("2026-05", 85936.0)])
    r = empleo_formal_del_sector(db, "construccion", date(2025, 12, 31))
    assert r["mes"] == "2025-12" and r["trabajadores_cotizantes_en_la_actividad"] == 84514.0
    assert r["variacion_interanual_pct"] == 6.44 and r["mes_de_comparacion"] == "2024-12"
    assert r["es_agregado"] is False


def test_sin_el_mes_del_anio_anterior_no_hay_variacion_inventada(db):
    _sembrar(db, "construccion", [("2026-05", 85936.0)])
    r = empleo_formal_del_sector(db, "construccion", date(2026, 12, 31))
    assert r["mes"] == "2026-05" and r["variacion_interanual_pct"] is None
    assert r["mes_de_comparacion"] is None


def test_zonas_francas_declara_el_agregado(db):
    _sembrar(db, "zonas_francas", [("2025-12", 290000.0)])
    r = empleo_formal_del_sector(db, "zonas_francas", date(2025, 12, 31))
    assert r["es_agregado"] and r["el_agregado_incluye"] == ["manufactura_local", "zonas_francas"]


def test_llega_al_perfil_JUNTO_a_la_ocupacion_y_al_contexto_con_lo_que_mide(db):
    _sembrar(db, "construccion", [("2024-12", 79402.0), ("2025-12", 84514.0)])
    perfil = perfil_del_sector(db, "construccion", date(2025, 12, 31))
    assert "empleo_formal" in perfil["cobertura"]["lecturas_servidas"]
    assert "ocupacion" in perfil["cobertura"]["lecturas_sin_dato_para_este_sector"], (
        "el empleo formal NO reemplaza a la ocupación: sigue siendo su propia lectura")
    ctx = contexto_del_perfil_del_sector(perfil, "construccion")
    bloque = ctx["empleo_formal_del_sector_construccion"]
    assert bloque["trabajadores_cotizantes_en_la_actividad_del_sector_construccion"] == 84514.0
    assert bloque["que_mide"] == QUE_MIDE_EL_EMPLEO_FORMAL
    assert "informal" in QUE_MIDE_EL_EMPLEO_FORMAL and "no las restes" in QUE_MIDE_EL_EMPLEO_FORMAL


def test_la_operacion_mensual_esta_registrada():
    import modules.sector_intel.operations  # noqa: F401
    from shared.operations.service import OPERATIONS
    op = OPERATIONS["tss-empleo-formal-sync"]
    assert op.default_interval_hours == 720
