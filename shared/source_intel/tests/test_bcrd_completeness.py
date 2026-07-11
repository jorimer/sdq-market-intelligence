"""Tests del audit de completitud de fuentes BCRD (hermanos del catálogo).

Offline: ``check_live=False`` evita el HEAD de red; corre contra el catálogo real
commiteado y los nombres cableados reales de los conectores.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.source_intel.bcrd_completeness import (
    _family_key,
    _wired_bcrd_files,
    find_uncabled_siblings,
    run_bcrd_completeness_audit,
)
from shared.source_intel.models import SourceSuggestion


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SourceSuggestion.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_family_key_groups_variants():
    fam = _family_key("pib_origen_2018.xlsx")
    assert _family_key("pib_origen_retro_2018_2007.xlsx") == fam
    assert _family_key("pib_origen_2007.xlsx") == fam
    # familias distintas no colisionan
    assert _family_key("imae_2018.xlsx") != fam


def test_wired_includes_sector_and_canonical():
    wired = _wired_bcrd_files()
    assert "pib_origen_2018.xlsx" in wired
    assert "pib_origen_retro_2018_2007.xlsx" in wired      # el retro que ya cableamos
    assert any("imae" in f for f in wired)                 # del set canónico


def test_finds_uncabled_retro_siblings_only():
    sibs = {s["filename"] for s in find_uncabled_siblings(check_live=False)}
    # el retropolado del PIB-gasto (variante de historia sin cablear) DEBE aflorar
    assert "pib_gasto_retro.xlsx" in sibs
    # nunca propone lo ya cableado
    assert "pib_origen_2018.xlsx" not in sibs
    assert "pib_origen_retro_2018_2007.xlsx" not in sibs
    # solo variantes de historia / base más nueva (todos los candidatos tienen razón válida)
    for s in find_uncabled_siblings(check_live=False):
        assert s["reason"] in ("variante de historia", "base más nueva")


def test_audit_creates_suggestions_and_is_idempotent(db):
    res = run_bcrd_completeness_audit(db, check_live=False)
    assert res["candidates"] >= 1 and res["created"] >= 1
    n = db.query(SourceSuggestion).count()
    assert n == res["created"]
    row = db.query(SourceSuggestion).filter(
        SourceSuggestion.title.like("BCRD · pib_gasto_retro%")).first()
    assert row is not None and row.origin == "catalog" and row.kind == "source"

    # segunda corrida: no duplica (idempotente por título)
    res2 = run_bcrd_completeness_audit(db, check_live=False)
    assert res2["created"] == 0
    assert db.query(SourceSuggestion).count() == n
