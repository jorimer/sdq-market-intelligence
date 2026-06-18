"""ONE studies in the publications catalog + ingestion (offline, stubbed I/O)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.publications import catalog, service
from shared.publications.models import Publication  # noqa: F401 — register table


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


def test_one_studies_in_catalog_separate_from_bcrd():
    one = catalog.report_keys("ONE")
    bcrd = catalog.report_keys("BCRD")
    assert set(one) == {"one_censo_2022", "one_enhogar", "one_pobreza", "one_vitales", "one_anuario"}
    assert "estabilidad_financiera" in bcrd and not (set(one) & set(bcrd))
    # every ONE spec pins a real one.gob.do PDF and routes to social/esg
    for k in one:
        spec = catalog.REPORTS[k]
        period, url = spec.candidates(2026)[0]
        assert url.startswith("https://www.one.gob.do/media/") and url.endswith(".pdf")
        assert "social" in spec.sectors or "esg" in spec.sectors


def test_ingest_one_study_stubbed(db):
    row = service.ingest_report(
        db, "one_pobreza", period="2023", url="https://www.one.gob.do/media/x/p.pdf",
        download=lambda u: "/tmp/stub.pdf",
        extract=lambda p: "texto del estudio de pobreza",
        make_digest=lambda text, name, period, sectors: {"resumen": "pobreza bajó", "hallazgos": ["a"]},
    )
    assert row.status == "ok"
    assert row.report_name.startswith("Boletín de Pobreza")
    assert row.sectors == ["social"]
    assert row.digest["resumen"] == "pobreza bajó"
