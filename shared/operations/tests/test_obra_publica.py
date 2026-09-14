"""La obra pública alimenta DOS ejes por evento: cada serie a su eje, y ningún módulo importa a otro."""
import ast
import pathlib
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data import dgcp_ocds_client as dg
from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.database.base import Base
from shared.observations.models import SectorObservation


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


def _reg(serie, periodo, valor):
    return Record(series=serie, period=periodo, value=valor, unit="adjudicaciones",
                  lineage=Lineage(source="DGCP", license="x", fetched_at=date(2026, 9, 14)))


def test_cada_serie_se_escribe_en_SU_eje(db):
    from shared.operations.obra_publica import escribir_obra_publica

    registros = [_reg(dg.SERIE_OBRAS, "2026-07", 109.0), _reg(dg.SERIE_OBRAS_ELECTRICAS, "2026-07", 4.0)]
    por_eje = escribir_obra_publica(db, registros, recuperado=date(2026, 9, 7), source="DGCP", license="x")
    db.commit()
    assert por_eje == {"construction": 1, "energy": 1}
    filas = {(f.sector_key, f.series_code): f for f in db.query(SectorObservation).all()}
    assert set(filas) == {("construction", dg.SERIE_OBRAS), ("energy", dg.SERIE_OBRAS_ELECTRICAS)}
    assert filas[("energy", dg.SERIE_OBRAS_ELECTRICAS)].nature == "flow"
    assert filas[("construction", dg.SERIE_OBRAS)].published_at == date(2026, 9, 7)


def test_toda_serie_del_conector_tiene_EJE_declarado():
    from shared.operations.obra_publica import EJE_DE_LA_SERIE

    del_conector = {dg.SERIE_OBRAS, dg.SERIE_MONTO, dg.SERIE_OBRAS_ELECTRICAS, dg.SERIE_MONTO_ELECTRICO}
    assert set(EJE_DE_LA_SERIE) == del_conector


def test_la_corrida_PUBLICA_el_evento_de_cada_eje_que_escribio(monkeypatch):
    from shared.events.event_bus import event_bus
    from shared.operations import obra_publica as op

    publicados = []
    monkeypatch.setattr(event_bus, "publish", lambda tipo, payload: publicados.append(tipo))

    class _Cliente:
        source, license = "DGCP", "x"

        def __init__(self, mode="live"):
            pass

        def leer(self):
            return ([_reg(dg.SERIE_OBRAS, "2026-07", 1.0), _reg(dg.SERIE_OBRAS_ELECTRICAS, "2026-07", 0.0)],
                    dg.RecuperacionDGCP(ultimo_mes_completo="2026-07", recuperado_el=date(2026, 9, 7)))

    class _Sesion:
        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(dg, "DGCPOCDSClient", _Cliente)
    monkeypatch.setattr(op, "SessionLocal", _Sesion)
    monkeypatch.setattr(op, "escribir_obra_publica", lambda db, r, **k: {"construction": 1, "energy": 1})
    out = op._run_obra_publica({}, None, lambda _m: None)
    assert sorted(publicados) == ["construction.updated", "energy.updated"]
    assert out["ultimo_mes"] == "2026-07"


def test_la_operacion_NO_importa_ningun_modulo():
    """Alimenta construcción y energía por evento: un import de `modules.` sería el acople prohibido."""
    fuente = pathlib.Path("shared/operations/obra_publica.py").read_text()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            nombre = getattr(nodo, "module", None) or ",".join(a.name for a in nodo.names)
            assert not str(nombre).startswith("modules"), nombre


def test_los_productos_declaran_el_feed_de_obra_publica(db):
    from modules.construction_intel.products import ConstructionProduct
    from modules.energy_intel.products import EnergyProduct

    claves_c = {f.clave for f in ConstructionProduct(db).feeds_mensuales()}
    claves_e = {f.clave for f in EnergyProduct(db).feeds_mensuales()}
    assert "dgcp_obras" in claves_c and "mivhed_mensual" in claves_c
    assert "dgcp_obras_electricas" in claves_e and "oc_seni_imte" in claves_e
