"""Tests del servicio de la vista Histórico (cohorte + forense por entidad)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.banking_score.models.models import SibHistoricalFinancials as F
from modules.banking_score import historical_service as svc


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[F.__table__])
    return sessionmaker(bind=eng)()


def _months(n, y0=2001):
    out, y, m = [], y0, 1
    for _ in range(n):
        out.append(date(y, m, 1))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _seed(db, nombre, specs, ultimo_extra=True):
    for d, s in zip(_months(len(specs)), specs):
        db.add(F(entidad_nombre=nombre, entidad_code=nombre.replace(" ", "_"), tipo_entidad="Bancos Múltiples",
                 sector="Privado", fecha=d, ano=d.year, mes=d.month,
                 activos_totales=1000, depositos_totales=s.get("dep", 600),
                 morosidad_pct=s["mora"], cobertura_pct=s["cob"], apalancamiento_pct=10.0))
    db.commit()


def test_list_entities_flags_exited(db):
    # 'Sana' reporta hasta 2002-06; 'Quebrada' hasta 2002-03 → salió antes que el sistema
    _seed(db, "Banco Sano", [dict(mora=1.0, cob=200.0)] * 18)
    _seed(db, "Banco Quebrado", [dict(mora=1.0, cob=200.0)] * 15)
    ents = {e["nombre"]: e for e in svc.list_entities(db)}
    assert ents["Banco Quebrado"]["salio_del_sistema"] is True
    assert ents["Banco Sano"]["salio_del_sistema"] is False
    # only_exited filtra
    exited = [e["nombre"] for e in svc.list_entities(db, only_exited=True)]
    assert exited == ["Banco Quebrado"]


def test_forensic_package_series_and_backtest(db):
    healthy = [dict(mora=1.0, cob=200.0)] * 12
    bad = [dict(mora=40.0, cob=20.0)] * 6
    _seed(db, "Banco Quebrado", healthy + bad)
    pkg = svc.forensic_package(db, "Banco Quebrado")
    assert pkg is not None
    assert pkg["meta"]["nombre"] == "Banco Quebrado"
    assert len(pkg["series"]) == 18
    # el cluster de deterioro se fecha (morosidad salta + cobertura se hunde)
    assert pkg["backtest"]["onset_cluster"] == "2002-01-01"
    # la serie trae los ratios para graficar
    assert pkg["series"][-1]["morosidad_pct"] == 40.0


def test_forensic_missing_entity_returns_none(db):
    assert svc.forensic_package(db, "No Existe") is None


def test_forensic_narrative_context(db):
    healthy = [dict(mora=1.0, cob=200.0)] * 12
    bad = [dict(mora=40.0, cob=20.0)] * 6
    _seed(db, "Banco Quebrado", healthy + bad)
    pkg = svc.forensic_package(db, "Banco Quebrado")
    ctx = svc.forensic_narrative_context(pkg)
    assert ctx["onset_deterioro"] == "2002-01-01"
    assert ctx["anticipacion_meses"] is not None
    assert ctx["morosidad_maxima_pct"] == 40.0
    assert "salto_morosidad" in ctx["cluster_en_onset"]
