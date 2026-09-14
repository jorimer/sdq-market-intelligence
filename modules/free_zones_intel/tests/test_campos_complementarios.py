"""Los cuatro campos del CNZFE que se parseaban y nadie usaba (Fase 5b, plan §3.4).

Salen al informe —payload, contexto del modelo y una tabla— y **no entran al IZF**: cambiar los
insumos de un score sin validación retrospectiva está prohibido. El test que importa es el
primero: con y sin los cuatro campos, el score es el MISMO.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base

from modules.free_zones_intel import service
from modules.free_zones_intel.scoring.attractiveness import compute_free_zone_index

_BASICAS = ("parks", "companies", "jobs", "exports_musd", "investment_musd")
_EXTRA = ("wage_operator_rd", "wage_technician_rd", "local_spend_musd", "occupied_area_sqft")


def _variables(con_extra=True):
    out = {}
    for n, y in enumerate(range(2018, 2025)):
        fila = {"parks": 70.0 + n, "companies": 700.0 + 10 * n, "jobs": 170000.0 + 5000 * n,
                "exports_musd": 6000.0 + 250 * n, "investment_musd": 5000.0 + 300 * n}
        if con_extra:
            fila.update({"wage_operator_rd": 3000.0 + 100 * n, "wage_technician_rd": 6000.0 + 150 * n,
                         "local_spend_musd": 1500.0 + 40 * n, "occupied_area_sqft": 40e6 + 1e6 * n})
        out[y] = fila
    return out


@pytest.fixture()
def db():
    import app.main  # noqa: F401

    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


def test_el_IZF_es_el_MISMO_con_y_sin_los_cuatro_campos(db, monkeypatch):
    monkeypatch.setattr(service, "publish_free_zones_updated", lambda _p: None)
    sin = compute_free_zone_index(_variables(con_extra=False))
    con = service.compute_and_persist(db, _variables(con_extra=True))
    assert con["fz_score"] == sin["fz_score"]
    assert con["band"] == sin["band"]
    fila = service.get_latest(db)
    assert fila.breakdown["dimensions"] == sin["dimensions"]


def test_el_breakdown_guarda_los_cuatro_campos_DEL_AÑO_con_su_sujeto(db, monkeypatch):
    monkeypatch.setattr(service, "publish_free_zones_updated", lambda _p: None)
    service.backfill_scores(db, _variables())
    for fila in service.get_scores(db):
        comp = fila.breakdown["complementarios"]
        y = int(fila.period)
        assert comp["salario_semanal_de_un_operario_de_zona_franca_rd"] == _variables()[y]["wage_operator_rd"]
        assert comp["area_de_naves_ocupada_en_zonas_francas_pies2"] == _variables()[y]["occupied_area_sqft"]


def test_un_campo_AUSENTE_es_None_nunca_cero():
    comp = service.complementarios_del_anio({"wage_operator_rd": 3100.0})
    assert comp["salario_semanal_de_un_operario_de_zona_franca_rd"] == 3100.0
    assert comp["gasto_operativo_local_de_las_zonas_francas_musd"] is None
    assert set(comp) == set(service.CAMPOS_COMPLEMENTARIOS.values())
    assert set(service.CAMPOS_COMPLEMENTARIOS) == set(_EXTRA)


def test_el_contexto_del_modelo_los_lleva_y_le_dice_que_NO_explican_el_score(db, monkeypatch):
    from modules.free_zones_intel.ai_context import free_zones_ai_context
    from modules.free_zones_intel.products import _index_dict

    monkeypatch.setattr(service, "publish_free_zones_updated", lambda _p: None)
    service.compute_and_persist(db, _variables())
    ctx = free_zones_ai_context(_index_dict(service.get_latest(db)), "2024")
    assert ctx["salario_semanal_de_un_tecnico_de_zona_franca_rd"] == _variables()[2024]["wage_technician_rd"]
    assert "NO son dimensiones del IZF" in ctx["complementarios_no_entran_al_indice"]


def test_la_tabla_lista_solo_los_que_TIENEN_valor():
    from modules.free_zones_intel.products import filas_complementarias

    filas = filas_complementarias({
        "salario_semanal_de_un_operario_de_zona_franca_rd": 3500.0,
        "gasto_operativo_local_de_las_zonas_francas_musd": None,
    })
    assert filas == [["Salario semanal de un operario (RD$)", "3.500"]]
    assert filas_complementarias({}) == []
