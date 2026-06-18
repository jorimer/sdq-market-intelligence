"""Tests for the BCRD publications catalog, digest parsing and ingest service.

Network + Anthropic are never hit: the service exposes probe/download/extract/
digest seams that the tests inject.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.publications import catalog, service
from shared.publications.digest import _extract_json, normalize_digest
from shared.publications.models import Publication


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[Publication.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── catalog ───────────────────────────────────────────────────────
def test_report_catalog_has_three():
    # the BCRD catalog (ONE studies are catalogued too, filtered by source)
    assert set(catalog.report_keys("BCRD")) == {
        "estabilidad_financiera", "economia_dominicana", "politica_monetaria",
    }


def test_ipom_candidates_are_semestral():
    cands = catalog.REPORTS["politica_monetaria"].candidates(2025)
    periods = [p for p, _ in cands]
    assert periods == ["2025-12", "2025-06"]
    assert all(u.endswith(".pdf") and "informepm" in u for _, u in cands)


def test_estabilidad_candidates_include_month_and_year_variants():
    cands = catalog.REPORTS["estabilidad_financiera"].candidates(2024)
    urls = [u for _, u in cands]
    assert any("Septiembre2024.pdf" in u for u in urls)
    assert any("InformeEstabilidadFinanciera2024.pdf" in u for u in urls)


def test_infeco_candidates_prefer_definitivo():
    cands = catalog.REPORTS["economia_dominicana"].candidates(2025)
    urls = [u for _, u in cands]
    # -12 definitivo first; preliminar variants present as fallbacks
    assert urls[0].endswith("infeco_definitivo2025-12.pdf")
    assert any("infeco_preliminar2025-06.pdf" in u for u in urls)


def test_candidate_urls_newest_year_first():
    cands = catalog.candidate_urls("politica_monetaria", 2025, lookback_years=1)
    periods = [p for p, _ in cands]
    assert periods == ["2025-12", "2025-06", "2024-12", "2024-06"]


# ── digest parsing ────────────────────────────────────────────────
def test_extract_json_strips_code_fence():
    raw = '```json\n{"resumen": "ok", "hallazgos": []}\n```'
    assert _extract_json(raw)["resumen"] == "ok"


def test_extract_json_raises_without_object():
    with pytest.raises(ValueError, match="sin JSON"):
        _extract_json("no hay json aquí")


def test_extract_json_ignores_braces_in_strings():
    raw = '{"resumen": "usa {llaves} y [corchetes] dentro", "hallazgos": []}'
    assert "llaves" in _extract_json(raw)["resumen"]


def test_extract_json_repairs_truncation():
    raw = '{"resumen": "x", "hallazgos": ["a"'  # truncated
    out = _extract_json(raw)
    assert out["resumen"] == "x"


def test_normalize_digest_coerces_and_caps():
    messy = {
        "resumen": 123,
        "hallazgos": ["a", "", None, "b"],
        "cifras": [{"etiqueta": "PIB", "valor": "5%"}, {"nope": 1}, "junk"],
        "riesgos": ["r1"],
        "relevancia": {"banca": "importa", "x": ""},
    }
    out = normalize_digest(messy)
    assert out["resumen"] == "123"
    assert out["hallazgos"] == ["a", "b"]
    assert out["cifras"] == [{"etiqueta": "PIB", "valor": "5%"}]
    assert out["relevancia"] == {"banca": "importa"}


# ── service: resolution + ingest ──────────────────────────────────
def _fake_digest(text, name, period, sectors):
    return normalize_digest({"resumen": f"digest de {name} {period}", "hallazgos": ["h1"]})


def test_resolve_latest_url_picks_first_existing():
    # Only the 2025-06 IPOM "exists".
    def probe(url):
        return url.endswith("informepm2025-06.pdf")

    found = service.resolve_latest_url(
        "politica_monetaria", today=date(2025, 7, 1), probe=probe
    )
    assert found is not None
    period, url = found
    assert period == "2025-06"
    assert url.endswith("informepm2025-06.pdf")


def test_resolve_latest_url_none_when_nothing_exists():
    assert service.resolve_latest_url(
        "politica_monetaria", today=date(2025, 7, 1), probe=lambda u: False
    ) is None


def test_ingest_report_happy_path(db):
    row = service.ingest_report(
        db, "politica_monetaria",
        today=date(2025, 7, 1),
        probe=lambda u: u.endswith("informepm2025-06.pdf"),
        download=lambda u: "/tmp/fake.pdf",
        extract=lambda p: "texto del informe",
        make_digest=_fake_digest,
    )
    assert row is not None
    assert row.status == "ok"
    assert row.period == "2025-06"
    assert row.report_name == "Informe de Política Monetaria (IPOM)"
    assert row.sectors == ["macro"]
    assert "digest de" in row.digest["resumen"]
    assert row.raw_text == "texto del informe"


def test_ingest_report_idempotent_skip(db):
    common = dict(
        today=date(2025, 7, 1),
        probe=lambda u: u.endswith("informepm2025-06.pdf"),
        download=lambda u: "/tmp/fake.pdf",
        extract=lambda p: "t",
        make_digest=_fake_digest,
    )
    first = service.ingest_report(db, "politica_monetaria", **common)
    calls = {"n": 0}

    def counting_download(u):
        calls["n"] += 1
        return "/tmp/fake.pdf"

    second = service.ingest_report(
        db, "politica_monetaria",
        today=date(2025, 7, 1),
        probe=common["probe"], download=counting_download,
        extract=common["extract"], make_digest=_fake_digest,
    )
    assert second.id == first.id
    assert calls["n"] == 0  # skipped: already ok


def test_ingest_report_force_reingests(db):
    common = dict(
        today=date(2025, 7, 1),
        probe=lambda u: u.endswith("informepm2025-06.pdf"),
        download=lambda u: "/tmp/fake.pdf",
        extract=lambda p: "t",
        make_digest=_fake_digest,
    )
    service.ingest_report(db, "politica_monetaria", **common)
    calls = {"n": 0}

    def counting_download(u):
        calls["n"] += 1
        return "/tmp/fake.pdf"

    service.ingest_report(
        db, "politica_monetaria", force=True,
        today=date(2025, 7, 1),
        probe=common["probe"], download=counting_download,
        extract=common["extract"], make_digest=_fake_digest,
    )
    assert calls["n"] == 1


def test_ingest_report_records_error(db):
    def boom(_url):
        raise RuntimeError("CDN 404")

    row = service.ingest_report(
        db, "politica_monetaria",
        today=date(2025, 7, 1),
        probe=lambda u: u.endswith("informepm2025-06.pdf"),
        download=boom, extract=lambda p: "t", make_digest=_fake_digest,
    )
    assert row.status == "error"
    assert "CDN 404" in row.error


def test_ingest_report_none_when_unavailable(db):
    row = service.ingest_report(
        db, "politica_monetaria",
        today=date(2025, 7, 1),
        probe=lambda u: False,
        download=lambda u: "/x", extract=lambda p: "t", make_digest=_fake_digest,
    )
    assert row is None


def test_ingest_unknown_report_raises(db):
    with pytest.raises(ValueError, match="desconocido"):
        service.ingest_report(db, "no_existe")


def test_ingest_all_latest_covers_every_report(db):
    # Each report's first-probed candidate "exists"; one digest per report.
    seen = {}

    def probe(url):
        # accept the newest candidate of each report exactly once
        for key in catalog.report_keys():
            first_url = catalog.REPORTS[key].candidates(2025)[0][1]
            if url == first_url and key not in seen:
                seen[key] = True
                return True
        return False

    rows = service.ingest_all_latest(
        db, today=date(2025, 12, 1), probe=probe,
        download=lambda u: "/tmp/x.pdf", extract=lambda p: "t",
        make_digest=_fake_digest,
    )
    assert {r.report_key for r in rows} == set(catalog.report_keys())
    assert all(r.status == "ok" for r in rows)


# ── service: queries ──────────────────────────────────────────────
def _seed(db, report_key, period, sectors, status="ok"):
    row = Publication(
        report_key=report_key, report_name=report_key, period=period,
        sectors=sectors, status=status,
        digest={"resumen": f"{report_key} {period}", "hallazgos": []},
    )
    db.add(row)
    db.commit()
    return row


def test_get_latest_digests_filters_by_sector(db):
    _seed(db, "estabilidad_financiera", "2024-12", ["banca", "macro"])
    _seed(db, "politica_monetaria", "2025-06", ["macro"])
    banca = service.get_latest_digests(db, sector="banca")
    keys = {d["report_key"] for d in banca}
    assert keys == {"estabilidad_financiera"}  # IPOM is macro-only


def test_get_latest_digests_takes_most_recent_period(db):
    _seed(db, "politica_monetaria", "2024-12", ["macro"])
    _seed(db, "politica_monetaria", "2025-06", ["macro"])
    macro = service.get_latest_digests(db, sector="macro")
    ipom = [d for d in macro if d["report_key"] == "politica_monetaria"]
    assert len(ipom) == 1
    assert ipom[0]["period"] == "2025-06"


def test_get_latest_digests_skips_errored(db):
    _seed(db, "politica_monetaria", "2025-06", ["macro"], status="error")
    assert service.get_latest_digests(db, sector="macro") == []


def test_publication_prompt_context_is_compact(db):
    _seed(db, "estabilidad_financiera", "2024-12", ["banca", "macro"])
    # enrich the seeded digest with findings/cifras/riesgos beyond the trim limits
    row = service.list_publications(db, "estabilidad_financiera")[0]
    row.digest = {
        "resumen": "El sistema se mantiene estable.",
        "hallazgos": ["h1", "h2", "h3", "h4"],
        "cifras": [{"etiqueta": "solvencia", "valor": "17.4%"}] * 6,
        "riesgos": ["r1", "r2", "r3", "r4"],
        "relevancia": {},
    }
    db.commit()
    ctx = service.publication_prompt_context(db, sector="banca", max_findings=3)
    assert len(ctx) == 1
    block = ctx[0]
    assert block["informe"] == "estabilidad_financiera"
    assert block["periodo"] == "2024-12"
    assert len(block["hallazgos"]) == 3   # trimmed
    assert len(block["cifras"]) == 4      # max_findings + 1
    assert len(block["riesgos"]) == 3


def test_publication_prompt_context_filters_sector(db):
    _seed(db, "politica_monetaria", "2025-06", ["macro"])  # macro-only
    assert service.publication_prompt_context(db, sector="banca") == []


def test_publication_prompt_context_skips_empty_digest(db):
    row = _seed(db, "estabilidad_financiera", "2024-12", ["banca"])
    row.digest = {"resumen": "", "hallazgos": []}
    db.commit()
    assert service.publication_prompt_context(db, sector="banca") == []


def test_list_publications_orders_desc(db):
    _seed(db, "politica_monetaria", "2024-12", ["macro"])
    _seed(db, "politica_monetaria", "2025-06", ["macro"])
    pubs = service.list_publications(db, report_key="politica_monetaria")
    assert [p.period for p in pubs] == ["2025-06", "2024-12"]
