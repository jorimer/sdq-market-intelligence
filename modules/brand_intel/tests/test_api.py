"""API tests, focused on the isolation boundary.

This is the platform's only module serving private per-client data, so the access rules
are correctness properties. In particular: a caller from another organization must get a
**404, not a 403** — the existence of another client's engagement is itself private, and a
403 would confirm it.
"""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.database.session import get_db
from modules.brand_intel.api.router import router
from modules.brand_intel.models.models import BrandEngagement


def _client(db, role=UserRole.admin, org=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/brand-intel")

    class _U:
        def __init__(self, r, o):
            self.role = r
            self.organization_id = o
            self.email = "analista@sdq.test"      # destructive routes log the actor

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role, org)
    return TestClient(app)


# ── isolation ─────────────────────────────────────────────────────────

def test_other_organization_gets_404_not_403(db, engagement):
    """A 403 would confirm the engagement exists. It must be indistinguishable from absent."""
    engagement.organization_id = "org-1"
    db.commit()
    r = _client(db, role=UserRole.viewer, org="org-2").get(
        "/api/v1/brand-intel/engagements/demo")
    assert r.status_code == 404


def test_owning_organization_can_read(db, engagement):
    engagement.organization_id = "org-1"
    db.commit()
    r = _client(db, role=UserRole.viewer, org="org-1").get(
        "/api/v1/brand-intel/engagements/demo")
    assert r.status_code == 200
    assert r.json()["focal_brand"] == "Focal"


def test_staff_can_read_any_engagement(db, engagement):
    engagement.organization_id = "org-1"
    db.commit()
    r = _client(db, role=UserRole.admin, org=None).get(
        "/api/v1/brand-intel/engagements/demo")
    assert r.status_code == 200


def test_unknown_engagement_is_404(db, engagement):
    assert _client(db).get("/api/v1/brand-intel/engagements/fantasma").status_code == 404


def test_list_only_returns_visible_engagements(db, engagement):
    engagement.organization_id = "org-1"
    db.add(BrandEngagement(slug="otro", client_name="Otro", focal_brand="X",
                           market="RD", organization_id="org-2"))
    db.commit()
    body = _client(db, role=UserRole.viewer, org="org-1").get(
        "/api/v1/brand-intel/engagements").json()
    assert [e["slug"] for e in body] == ["demo"]


# ── engagements ───────────────────────────────────────────────────────

def test_create_engagement_and_reject_duplicate_slug(db):
    c = _client(db)
    payload = {"slug": "nuevo", "client_name": "Cliente", "focal_brand": "Marca"}
    assert c.post("/api/v1/brand-intel/engagements", json=payload).status_code == 201
    assert c.post("/api/v1/brand-intel/engagements", json=payload).status_code == 409


# ── template and ingest ───────────────────────────────────────────────

def test_template_downloads_as_xlsx(db, engagement):
    r = _client(db).get("/api/v1/brand-intel/template.xlsx?engagement=demo")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"          # xlsx is a zip container


def test_ingest_rejects_a_non_xlsx_upload(db, engagement):
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/ingest",
        files={"file": ("datos.csv", b"a,b,c", "text/csv")})
    assert r.status_code == 400


def test_ingest_accepts_a_valid_workbook(db, engagement):
    wb = Workbook()
    ws = wb.active
    ws.title = "Olas"
    ws.append(["codigo", "etiqueta", "orden", "fecha_referencia",
               "campo_inicio", "campo_fin", "base_nominal"])
    ws.append(["w4", "Ola 4", 4, "2026-07-01", None, None, 300])
    ws = wb.create_sheet("Marcas")
    ws.append(["slug", "nombre", "es_focal", "en_set_categoria", "orden"])
    ws.append(["focal", "Focal", "SI", "SI", 1])
    ws = wb.create_sheet("Observaciones")
    ws.append(["ola", "marca", "metrica", "segmento", "valor", "base_n", "unidad", "fuente"])
    ws.append(["w4", "focal", "reach_7d", "total", 50, 300, "pct", "test"])
    buf = io.BytesIO()
    wb.save(buf)

    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/ingest",
        files={"file": ("datos.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    body = r.json()
    assert body["olas"]["creadas"] == 1
    assert body["observaciones"]["creadas"] == 1
    assert body["total_rechazadas"] == 0


# ── analysis endpoints ────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "category", "attribution", "funnel", "ticket", "signal-filter",
    "forecast/backtest", "forecast/track-record", "decisions",
    "scenarios", "vigilance",
])
def test_analysis_endpoints_respond(db, engagement, path):
    r = _client(db).get(f"/api/v1/brand-intel/engagements/demo/{path}")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_category_endpoint_returns_the_share_series(db, engagement):
    body = _client(db).get("/api/v1/brand-intel/engagements/demo/category").json()
    assert body["available"] is True
    assert {b["brand"] for b in body["share"]} == {"focal", "rival"}


# ── decisions ─────────────────────────────────────────────────────────

def test_decision_check_reports_infeasibility(db, engagement):
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/decisions/check",
        json={"metric_code": "reach_7d", "baseline_wave_code": "w2",
              "brand_slug": "focal", "success_threshold": 1.0})
    assert r.status_code == 200
    assert r.json()["feasible"] is False


def test_decision_check_rejects_an_unknown_wave(db, engagement):
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/decisions/check",
        json={"metric_code": "reach_7d", "baseline_wave_code": "w9",
              "success_threshold": 5.0})
    assert r.status_code == 400


def test_unevaluable_decision_is_recorded_with_its_reason(db, engagement):
    """Recorded, not silently dropped: it has to be redesignable rather than re-proposed."""
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/decisions",
        json={"title": "Movimiento minúsculo", "metric_code": "reach_7d",
              "baseline_wave_code": "w2", "brand_slug": "focal",
              "target_wave_code": "w3", "success_threshold": 0.5})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "unevaluable"
    assert "inevaluable" in body["feasibility"]["reason"]


def test_feasible_decision_is_created_open(db, engagement):
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/decisions",
        json={"title": "Subir alcance 10 puntos", "metric_code": "reach_7d",
              "baseline_wave_code": "w2", "brand_slug": "focal",
              "target_wave_code": "w3", "success_threshold": 10.0,
              "owner": "Marketing"})
    assert r.status_code == 201
    assert r.json()["status"] == "open"


# ── forecast and report ───────────────────────────────────────────────

def test_issue_forecast_rejects_unknown_wave(db, engagement):
    r = _client(db).post("/api/v1/brand-intel/engagements/demo/forecast/issue?wave=w9")
    assert r.status_code == 400


def test_report_json_and_html(db, engagement):
    c = _client(db)
    body = c.get("/api/v1/brand-intel/engagements/demo/report").json()
    assert "executive" in body and "limits" in body

    r = c.get("/api/v1/brand-intel/engagements/demo/report.html")
    assert r.status_code == 200
    assert r.text.startswith("<!doctype html>")


# ── borrado ───────────────────────────────────────────────────────────

def test_delete_removes_the_engagement_and_every_row_that_belongs_to_it(db, engagement):
    """A surviving child row is private client data with no owner and no access path."""
    from modules.brand_intel.models.models import (
        BrandEntity, BrandObservation, BrandWave,
    )

    assert db.query(BrandObservation).filter(
        BrandObservation.engagement_id == engagement.id).count() > 0

    r = _client(db).delete(
        f"/api/v1/brand-intel/engagements/{engagement.slug}",
        params={"confirm": engagement.slug},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == engagement.slug

    for model in (BrandObservation, BrandEntity, BrandWave):
        assert db.query(model).filter(model.engagement_id == engagement.id).count() == 0
    assert db.query(BrandEngagement).filter(
        BrandEngagement.slug == engagement.slug).count() == 0


def test_delete_without_the_echoed_slug_changes_nothing(db, engagement):
    """A DELETE that fires on the URL alone is one stale tab away from a lost dataset."""
    r = _client(db).delete(
        f"/api/v1/brand-intel/engagements/{engagement.slug}", params={"confirm": "otra"})
    assert r.status_code == 400
    assert db.query(BrandEngagement).filter(
        BrandEngagement.slug == engagement.slug).count() == 1


def test_an_analyst_cannot_delete_an_engagement(db, engagement):
    r = _client(db, role=UserRole.analyst).delete(
        f"/api/v1/brand-intel/engagements/{engagement.slug}",
        params={"confirm": engagement.slug},
    )
    assert r.status_code == 403
    assert db.query(BrandEngagement).filter(
        BrandEngagement.slug == engagement.slug).count() == 1


def test_delete_is_gated_by_role_before_the_engagement_is_even_looked_up(db, engagement):
    """The refusal must not depend on the slug, or it becomes an existence oracle.

    Deletion is admin-only, and admins are staff who can already see every engagement, so
    here the isolation boundary is the role — not the organization check that guards
    reads. A non-admin gets the same 403 whether the engagement exists or not.
    """
    c = _client(db, role=UserRole.analyst, org="org-2")
    existing = c.delete(f"/api/v1/brand-intel/engagements/{engagement.slug}",
                        params={"confirm": engagement.slug})
    absent = c.delete("/api/v1/brand-intel/engagements/fantasma",
                      params={"confirm": "fantasma"})
    assert existing.status_code == absent.status_code == 403
    assert db.query(BrandEngagement).filter(
        BrandEngagement.slug == engagement.slug).count() == 1


def test_delete_of_an_unknown_engagement_is_404_for_an_admin(db, engagement):
    r = _client(db).delete("/api/v1/brand-intel/engagements/fantasma",
                           params={"confirm": "fantasma"})
    assert r.status_code == 404
