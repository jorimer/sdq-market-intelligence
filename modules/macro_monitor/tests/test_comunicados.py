"""Tests del conector de Comunicados de Política Monetaria del BCRD.

Red y Anthropic nunca se tocan: source expone el POST como seam y el service expone
list_fn/detail_fn/make_digest inyectables.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.macro_monitor.comunicados import service as com_service
from modules.macro_monitor.comunicados import source as src
from modules.macro_monitor.comunicados.models import ComunicadoTPM


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ComunicadoTPM.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


# ── source: parse de la decisión (determinista) ───────────────────

def test_parse_hold_takes_level_from_title():
    d = src.parse_decision("BCRD mantiene su tasa de política monetaria en 5.25 % anual")
    assert d == {"action": "hold", "tpm_level": 5.25, "bps_change": None}


def test_parse_cut_de_a_takes_resulting_level_and_bps():
    d = src.parse_decision(
        "BCRD reduce su tasa de política monetaria en 25 puntos básicos, de 5.50 % a 5.25 % anual")
    assert d["action"] == "cut"
    assert d["tpm_level"] == 5.25   # el ÚLTIMO % es el nivel resultante
    assert d["bps_change"] == 25


def test_parse_hike_level_falls_back_to_body():
    # El titular solo da el cambio en puntos básicos → el nivel sale del cuerpo.
    d = src.parse_decision(
        "BCRD incrementa su tasa de política monetaria en 25 puntos básicos",
        body_text="La Junta Monetaria decidió elevar su TPM a 6.00 % anual.")
    assert d["action"] == "hike"
    assert d["tpm_level"] == 6.00
    assert d["bps_change"] == 25


def test_parse_hold_ignores_bps_mentioned_in_body():
    # Un 'mantiene' no tiene cambio; el cuerpo menciona "puntos básicos" por el corredor
    # de tasas o una decisión previa → no debe confundirse con la magnitud del cambio.
    d = src.parse_decision(
        "BCRD mantiene su tasa de política monetaria en 5.25 % anual",
        body_text="En abril el BCRD había reducido la TPM en 25 puntos básicos. Ahora la mantiene.")
    assert d["action"] == "hold"
    assert d["tpm_level"] == 5.25
    assert d["bps_change"] is None


def test_parse_unknown_action_is_none():
    assert src.parse_decision("BCRD publica su informe anual")["action"] is None


def test_html_to_text_strips_tags_and_scripts():
    txt = src._html_to_text("<p>Hola <b>mundo</b></p><script>x=1</script><br>fin")
    assert "Hola mundo" in txt and "x=1" not in txt and "fin" in txt


def test_date_iso_ignores_sentinel():
    assert src._date_iso("2026-06-30T00:00:00Z") == "2026-06-30"
    assert src._date_iso("0001-01-01T00:00:00Z") is None
    assert src._date_iso(None) is None


def test_list_comunicados_parses_and_sorts_newest_first():
    payload = {"result": {"dynamicContent": {"articleList": {"articleList": {"items": [
        {"id": 6553, "stringId": "6553-bcrd-mantiene", "title": "BCRD mantiene ... 5.25 %",
         "auxiliarDatetime1": "2026-04-30T00:00:00Z", "previewContent": "<p>abril</p>"},
        {"id": 6606, "stringId": "6606-bcrd-mantiene", "title": "BCRD mantiene ... 5.25 %",
         "auxiliarDatetime1": "2026-06-30T00:00:00Z", "previewContent": "<p>junio</p>"},
    ]}}}}}
    refs = src.list_comunicados(limit=10, post=lambda _id: payload)
    assert [r.article_id for r in refs] == [6606, 6553]  # newest-first
    assert refs[0].date_iso == "2026-06-30"
    assert refs[0].preview == "junio"
    assert refs[0].url.endswith("/a/d/6606-bcrd-mantiene")


# ── service: ingesta + queries ────────────────────────────────────

def _ref(aid, date, title="BCRD mantiene su tasa de política monetaria en 5.25 % anual"):
    return src.ComunicadoRef(article_id=aid, string_id=f"{aid}-x", title=title,
                             date_iso=date, preview="resumen")


def _detail(aid):
    return src.ComunicadoDetail(article_id=aid, title="t", subtitle="",
                                body_text="La Junta Monetaria mantuvo la TPM en 5.25 % anual. Racional…",
                                url=f"https://x/a/d/{aid}")


def _fake_digest(text, name, period, sectors):
    return {"resumen": f"digest {period}", "hallazgos": ["h1"], "cifras": [], "riesgos": ["r1"],
            "relevancia": {}}


def _ingest(db, refs, **kw):
    return com_service.ingest_comunicados(
        db, list_fn=lambda limit=12: refs[:limit], detail_fn=_detail,
        make_digest=_fake_digest, **kw)


def test_ingest_creates_rows_with_parsed_decision(db):
    res = _ingest(db, [_ref(6606, "2026-06-30")])
    assert res["ingested_ok"] == 1
    row = db.query(ComunicadoTPM).filter_by(article_id=6606).first()
    assert row.status == "ok"
    assert row.action == "hold" and row.tpm_level == 5.25
    assert row.decision_date == "2026-06-30"
    assert row.digest["resumen"] == "digest 2026-06-30"


def test_ingest_is_idempotent(db):
    _ingest(db, [_ref(6606, "2026-06-30")])
    calls = {"n": 0}

    def counting_detail(aid):
        calls["n"] += 1
        return _detail(aid)

    res = com_service.ingest_comunicados(
        db, list_fn=lambda limit=12: [_ref(6606, "2026-06-30")],
        detail_fn=counting_detail, make_digest=_fake_digest)
    assert calls["n"] == 0  # ya estaba ok → no re-descarga
    assert res["results"][0]["status"] == "skip"


def test_ingest_force_reingests(db):
    _ingest(db, [_ref(6606, "2026-06-30")])
    res = _ingest(db, [_ref(6606, "2026-06-30")], force=True)
    assert res["ingested_ok"] == 1
    assert db.query(ComunicadoTPM).filter_by(article_id=6606).count() == 1  # upsert, no duplica


def test_ingest_records_error_without_aborting_batch(db):
    def boom_detail(aid):
        if aid == 6606:
            raise RuntimeError("timeout CMS")
        return _detail(aid)

    res = com_service.ingest_comunicados(
        db, list_fn=lambda limit=12: [_ref(6606, "2026-06-30"), _ref(6582, "2026-05-29")],
        detail_fn=boom_detail, make_digest=_fake_digest)
    assert res["ingested_ok"] == 1  # el segundo entra pese al fallo del primero
    bad = db.query(ComunicadoTPM).filter_by(article_id=6606).first()
    assert bad.status == "error" and "timeout CMS" in bad.error


def test_latest_and_prompt_context(db):
    _ingest(db, [_ref(6606, "2026-06-30"), _ref(6582, "2026-05-29")])
    assert com_service.latest_comunicado(db).article_id == 6606  # más reciente
    ctx = com_service.comunicado_prompt_context(db)
    assert ctx["fecha"] == "2026-06-30"
    assert ctx["decision"] == "mantuvo"      # hold → etiqueta legible
    assert ctx["tpm_nivel"] == 5.25
    assert ctx["hallazgos"] == ["h1"]


def test_prompt_context_none_when_empty(db):
    assert com_service.comunicado_prompt_context(db) is None
