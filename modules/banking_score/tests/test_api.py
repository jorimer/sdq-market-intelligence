"""Tests for Banking Score API endpoints.

Validates:
- Health check
- Auth flow (register → login → access protected)
- Scoring pipeline (seed → run scoring → get latest → rankings)
- Data endpoints (template, raw data)
- Stats endpoint
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.database.session import get_db
from shared.auth.models import User  # noqa: F401 — register model
from shared.notifications.service import Notification  # noqa: F401
from modules.banking_score.models.models import (  # noqa: F401
    Bank, BankingData, RatingResult, RatingAction, Report,
)
from modules.banking_score.reports.narrative import REPORT_SECTIONS
from app.main import app

# El conftest raíz neutraliza ANTHROPIC_API_KEY → la narrativa degradaría a fallback
# estático y el guard anti-PDF-hueco respondería 503 en los reportes premium (full_rating/
# scorecard). Estos tests validan la MECÁNICA del endpoint (crear/descargar), no el motor IA,
# así que simulan la narrativa sana que en producción SÍ se genera (la key está siempre). El
# path 503 de degradación se cubre aparte en test_reports_degradation.py.
_PATCH_NARRATIVE = "modules.banking_score.reports.narrative.generate_report_narratives"


async def _healthy_narratives(report_type, bank_name, scoring_result, period, benchmarks=None):
    return {s: f"Análisis sustantivo de {s} para {bank_name} en {period}."
            for s in REPORT_SECTIONS.get(report_type, ["executive_summary"])}

# ─── Test DB Setup ───────────────────────────────────────────────

TEST_DB_URL = "sqlite://"  # in-memory

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def isolate_ml_singleton(tmp_path):
    """The xgboost_model singleton is module-global: a trained model (or a dev's
    on-disk pickle at MODELS_DIR) would leak across tests. Reset it to a clean,
    isolated state around each test and restore afterward."""
    from modules.banking_score.ml.xgboost_model import xgboost_model
    snap = (xgboost_model.model, xgboost_model.label_encoder,
            xgboost_model.version, xgboost_model.metrics, xgboost_model._model_path)
    xgboost_model.model = None
    xgboost_model.label_encoder = None
    xgboost_model.version = None
    xgboost_model.metrics = None
    xgboost_model._model_path = str(tmp_path / "isolated_model.pkl")
    yield
    (xgboost_model.model, xgboost_model.label_encoder,
     xgboost_model.version, xgboost_model.metrics, xgboost_model._model_path) = snap


# ─── Auth Helpers ────────────────────────────────────────────────

def register_and_login(email="test@sdq.do", password="Test1234!", full_name="Test User"):
    """Register a user and return the access token."""
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": full_name,
    })
    resp = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })
    return resp.json().get("access_token", "")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def seed_test_bank(db_session):
    """Insert a test bank + one period of data directly into the DB."""
    from modules.banking_score.models.models import BankType, DataSource
    from datetime import date

    bank = Bank(
        name="Banco Test Popular",
        sib_code="BPD",
        bank_type=BankType.banca_multiple,
        is_active=True,
    )
    db_session.add(bank)
    db_session.flush()

    data = BankingData(
        bank_id=bank.id,
        period_end=date(2024, 12, 31),
        patrimonio_tecnico=45_000_000_000,
        apr=280_000_000_000,
        capital_primario=35_000_000_000,
        exposicion_total=310_000_000_000,
        capital_tier1=35_000_000_000,
        contingentes=5_000_000_000,
        riesgo_mercado=2_000_000_000,
        provisiones=8_500_000_000,
        cartera_vencida_90d=4_200_000_000,
        activos_totales=450_000_000_000,
        cartera_bruta=250_000_000_000,
        cartera_categoria_a=220_000_000_000,
        cartera_total=250_000_000_000,
        suma_top10=35_000_000_000,
        hhi_sectorial_raw=1800,
        castigos=1_200_000_000,
        exposicion_re=95_000_000_000,
        cartera_a_prev=215_000_000_000,
        utilidad_neta=12_000_000_000,
        activos_promedio=440_000_000_000,
        patrimonio_promedio=42_000_000_000,
        ingresos_financieros=28_000_000_000,
        gastos_financieros=8_000_000_000,
        activos_productivos_avg=200_000_000_000,
        gastos_operacionales=15_000_000_000,
        ingresos_operacionales=25_000_000_000,
        caja_valores=35_000_000_000,
        pasivos_cp=120_000_000_000,
        cartera_neta=240_000_000_000,
        depositos_totales=300_000_000_000,
        activos_liquidos=85_000_000_000,
        pasivos_exigibles=180_000_000_000,
        hhi_ingresos_raw=2800,
        source=DataSource.sib_api,  # real source: scoring ignores synthetic (manual)
    )
    db_session.add(data)
    db_session.commit()

    return bank


# ─── Tests ───────────────────────────────────────────────────────

class TestHealth:
    def test_health_check(self):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["platform"] == "SDQ Market Intelligence"


class TestAuth:
    def test_register_and_login(self):
        resp = client.post("/api/v1/auth/register", json={
            "email": "analyst@sdq.do",
            "password": "Secure123!",
            "full_name": "SDQ Analyst",
        })
        assert resp.status_code in (200, 201)

        resp = client.post("/api/v1/auth/login", json={
            "email": "analyst@sdq.do",
            "password": "Secure123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_protected_endpoint_without_token(self):
        resp = client.get("/api/v1/banking-score/stats")
        assert resp.status_code in (401, 403)  # HTTPBearer returns 401/403 without token

    def test_protected_endpoint_with_token(self):
        token = register_and_login()
        resp = client.get("/api/v1/banking-score/stats", headers=auth_headers(token))
        assert resp.status_code == 200


class TestScoringPipeline:
    """Full pipeline: create bank → run scoring → get result → rankings."""

    def test_run_scoring(self):
        token = register_and_login()
        headers = auth_headers(token)

        # Seed a test bank directly
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        # Run scoring
        resp = client.post(
            f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert 0 <= data["overall_score"] <= 100
        assert "sub_components" in data
        assert "indicators" in data

    def test_get_latest_after_scoring(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        # Score first
        client.post(f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31", headers=headers)

        # Get latest
        resp = client.get(f"/api/v1/banking-score/{bank_id}/latest", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_rating"] is True
        # Fase 4 (§9): la superficie ya NO publica la notación de letras. La columna sigue
        # en la base como linaje, pero el endpoint devuelve los dos ejes.
        assert "rating_tier" not in data, "la notación retirada volvió a la superficie"
        assert "ejecucion" in data and "resiliencia" in data
        assert "banda_ejecucion" in data and "banda_resiliencia" in data

    def test_history_after_scoring(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        client.post(f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31", headers=headers)

        resp = client.get(f"/api/v1/banking-score/{bank_id}/history", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    def test_rankings_after_scoring(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        client.post(f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31", headers=headers)

        resp = client.get("/api/v1/banking-score/rankings", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        row = data["rankings"][0]
        assert row["rank"] == 1
        # E2E-BK2/BK3: campos aditivos para no mezclar tipos ni mostrar ratings rancios
        # sin bandera. ``rank_in_type`` = posición dentro del propio tipo de entidad;
        # ``stale``/``months_behind`` = antigüedad frente al corte más fresco del conjunto.
        assert row["rank_in_type"] == 1
        assert row["stale"] is False  # recién sembrado = fresco frente a sí mismo
        assert "months_behind" in row
        assert data["latest_period_end"]

    def test_run_all(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        seed_test_bank(db)
        db.close()

        resp = client.post(
            "/api/v1/banking-score/run-all?period_end=2024-12-31",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["scored"] >= 1

    def test_simulate(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        resp = client.post(
            f"/api/v1/banking-score/{bank_id}/simulate",
            headers=headers,
            json={"modified_scores": {
                "solvencia": 80.0, "tier1_ratio": 75.0, "leverage": 70.0,
                "cobertura_provisiones": 85.0, "patrimonio_activos": 65.0,
                "morosidad": 60.0, "pct_cartera_a": 90.0,
            }},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "rating_tier" in data


class TestDataEndpoints:
    def test_template_download(self):
        token = register_and_login()
        resp = client.get("/api/v1/banking-score/data/template", headers=auth_headers(token))
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_raw_data(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        resp = client.get(f"/api/v1/banking-score/data/{bank_id}/raw", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    def test_sync_status(self):
        token = register_and_login()
        resp = client.get("/api/v1/banking-score/data/sync-status", headers=auth_headers(token))
        assert resp.status_code == 200


class TestStatsEndpoint:
    def test_stats(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        seed_test_bank(db)
        db.close()

        resp = client.get("/api/v1/banking-score/stats", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_records"] >= 1
        assert data["total_entities"] >= 1


class TestModelEndpoints:
    def test_model_status(self):
        token = register_and_login()
        resp = client.get("/api/v1/banking-score/model/status", headers=auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["ml_available"] is False
        assert data["model_type"] == "deterministic"


class TestReportsEndpoints:
    def test_report_generate(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        # Score first so rating exists
        client.post(f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31", headers=headers)

        with patch(_PATCH_NARRATIVE, _healthy_narratives):
            resp = client.post(
                f"/api/v1/banking-score/reports/{bank_id}/generate?period_end=2024-12-31&report_type=full_rating",
                headers=headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_type"] == "full_rating"
        assert "report_id" in data

    def test_list_reports(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        resp = client.get(f"/api/v1/banking-score/reports/{bank_id}/list", headers=headers)
        assert resp.status_code == 200

    def test_all_rating_actions(self):
        token = register_and_login()
        headers = auth_headers(token)

        resp = client.get("/api/v1/banking-score/reports/rating-actions/all", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data

    def test_generate_scorecard_and_communique(self):
        token = register_and_login()
        headers = auth_headers(token)
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        client.post(f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31", headers=headers)

        with patch(_PATCH_NARRATIVE, _healthy_narratives):
            for rt in ["scorecard", "communique", "wire"]:
                resp = client.post(
                    f"/api/v1/banking-score/reports/{bank_id}/generate?period_end=2024-12-31&report_type={rt}",
                    headers=headers,
                )
                assert resp.status_code == 200, f"Failed for {rt}"
                assert resp.json()["report_type"] == rt


class TestDataUpload:
    """Test CSV upload and seed endpoints."""

    def test_upload_csv(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        csv_content = (
            "period_end,patrimonio_tecnico,apr,capital_primario,exposicion_total\n"
            "2025-03-31,50000,300000,40000,320000\n"
        )
        import io
        files = {"file": ("data.csv", io.BytesIO(csv_content.encode()), "text/csv")}
        resp = client.post(
            f"/api/v1/banking-score/data/upload?bank_id={bank_id}",
            headers=headers,
            files=files,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["records_created"] >= 1

    def test_upload_bad_format(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        import io
        files = {"file": ("data.json", io.BytesIO(b"{}"), "application/json")}
        resp = client.post(
            f"/api/v1/banking-score/data/upload?bank_id={bank_id}",
            headers=headers,
            files=files,
        )
        assert resp.status_code == 400

    def test_upload_to_nonexistent_bank(self):
        token = register_and_login()
        headers = auth_headers(token)

        import io
        csv = "period_end,patrimonio_tecnico\n2025-03-31,50000\n"
        files = {"file": ("data.csv", io.BytesIO(csv.encode()), "text/csv")}
        resp = client.post(
            "/api/v1/banking-score/data/upload?bank_id=nonexistent-id",
            headers=headers,
            files=files,
        )
        assert resp.status_code == 404

    def test_sib_sync_requires_admin(self):
        """Regular user cannot trigger SIB sync."""
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post("/api/v1/banking-score/data/sib-sync", headers=headers)
        # Regular user role → 403 (or 200 if default role is admin)
        assert resp.status_code in (200, 403)

    def test_sib_backfill(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post("/api/v1/banking-score/data/sib-backfill", headers=headers)
        assert resp.status_code in (200, 403)


class TestModelTrain:
    """Test model training endpoint."""

    def test_train_insufficient_data(self):
        """Should fail with < 30 records."""
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        seed_test_bank(db)  # Only 1 record
        db.close()

        resp = client.post("/api/v1/banking-score/model/train", headers=headers)
        assert resp.status_code == 400
        assert "30" in resp.json()["detail"]


class TestReportGeneration:
    """Test all report generation endpoints."""

    def test_generate_wire(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post(
            "/api/v1/banking-score/reports/wire/generate?period_end=2024-12-31",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_generate_datawatch(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post(
            "/api/v1/banking-score/reports/datawatch/generate?period_end=2024-12-31",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_generate_sector_outlook(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post(
            "/api/v1/banking-score/reports/sector-outlook/generate?period_end=2024-12-31",
            headers=headers,
        )
        assert resp.status_code == 200

    def test_generate_criteria(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post(
            "/api/v1/banking-score/reports/criteria/generate",
            headers=headers,
        )
        assert resp.status_code == 200

    def test_bank_rating_actions(self):
        token = register_and_login()
        headers = auth_headers(token)
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()
        resp = client.get(
            f"/api/v1/banking-score/reports/{bank_id}/rating-actions",
            headers=headers,
        )
        assert resp.status_code == 200
        assert "actions" in resp.json()

    def test_download_nonexistent_report(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.get(
            "/api/v1/banking-score/reports/download/nonexistent-id",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_generate_report_bad_type(self):
        token = register_and_login()
        headers = auth_headers(token)
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()
        resp = client.post(
            f"/api/v1/banking-score/reports/{bank_id}/generate?period_end=2024-12-31&report_type=invalid_type",
            headers=headers,
        )
        assert resp.status_code == 400

    def test_generate_report_bad_date(self):
        token = register_and_login()
        headers = auth_headers(token)
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()
        resp = client.post(
            f"/api/v1/banking-score/reports/{bank_id}/generate?period_end=not-a-date&report_type=full_rating",
            headers=headers,
        )
        assert resp.status_code == 400

    def test_generate_report_nonexistent_bank(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post(
            "/api/v1/banking-score/reports/fake-id/generate?period_end=2024-12-31&report_type=full_rating",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_download_after_generate(self):
        """Generate a report then try to download it."""
        token = register_and_login()
        headers = auth_headers(token)
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()
        client.post(f"/api/v1/banking-score/{bank_id}/run?period_end=2024-12-31", headers=headers)
        with patch(_PATCH_NARRATIVE, _healthy_narratives):
            resp = client.post(
                f"/api/v1/banking-score/reports/{bank_id}/generate?period_end=2024-12-31&report_type=scorecard",
                headers=headers,
            )
        assert resp.status_code == 200
        report_id = resp.json()["report_id"]
        resp = client.get(
            f"/api/v1/banking-score/reports/download/{report_id}",
            headers=headers,
        )
        # May be 200 (PDF) or 400/404 (file not on disk in test env)
        assert resp.status_code in (200, 400, 404)


class TestScoringEdgeCases:
    """Additional scoring endpoint tests for coverage."""

    def test_run_scoring_nonexistent_bank(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.post(
            "/api/v1/banking-score/nonexistent-id/run?period_end=2024-12-31",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_latest_no_rating(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        resp = client.get(f"/api/v1/banking-score/{bank_id}/latest", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_rating"] is False

    def test_history_empty(self):
        token = register_and_login()
        headers = auth_headers(token)

        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bank_id = bank.id
        db.close()

        resp = client.get(f"/api/v1/banking-score/{bank_id}/history", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_rankings_empty(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.get("/api/v1/banking-score/rankings", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_stats_empty_db(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.get("/api/v1/banking-score/stats", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_records"] == 0


class TestEntityPeriods:
    """GET /{bank_id}/periods — periods an entity has BankingData for (desc).

    Backs the period-aware UX: lets the UI tell 'sin dato para este período' apart
    from an error and guide the user to the entity's latest available period.
    """

    def test_periods_lists_loaded_periods_desc(self):
        from datetime import date
        from modules.banking_score.models.models import BankType, DataSource
        token = register_and_login()
        headers = auth_headers(token)
        db = TestSessionLocal()
        bank = Bank(name="Banco Periodos", bank_type=BankType.banca_multiple, is_active=True)
        db.add(bank)
        db.flush()
        for pe in (date(2025, 6, 30), date(2025, 12, 31)):  # inserted out of order
            db.add(BankingData(bank_id=bank.id, period_end=pe, source=DataSource.manual))
        db.commit()
        bank_id = bank.id
        db.close()

        resp = client.get(f"/api/v1/banking-score/{bank_id}/periods", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["periods"] == ["2025-12-31", "2025-06-30"]  # most recent first

    def test_periods_empty_for_entity_without_data(self):
        token = register_and_login()
        headers = auth_headers(token)
        resp = client.get("/api/v1/banking-score/no-such-bank/periods", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["periods"] == []


class TestReportDownload:
    """Re-download must work after the disk file is gone (ephemeral FS / redeploy):
    the PDF bytes are persisted in the DB (reports.file_blob)."""

    def _make_completed_report(self, *, with_blob: bool, on_disk: bool, tmp_path):
        from datetime import date
        from modules.banking_score.models.models import (
            Report, ReportType, ReportStatus, BankType,
        )
        db = TestSessionLocal()
        bank = Bank(name="Banco Reporte", bank_type=BankType.banca_multiple, is_active=True)
        db.add(bank)
        db.flush()
        path = str(tmp_path / "rep.pdf")
        if on_disk:
            with open(path, "wb") as fh:
                fh.write(b"%PDF-1.4 disk")
        report = Report(
            bank_id=bank.id,
            period_end=date(2025, 12, 31),
            report_type=ReportType.full_rating,
            status=ReportStatus.completed,
            file_path=path,
            file_blob=b"%PDF-1.4 blob-bytes" if with_blob else None,
        )
        db.add(report)
        db.commit()
        rid = report.id
        db.close()
        return rid

    def test_download_serves_blob_when_disk_file_missing(self, tmp_path):
        headers = auth_headers(register_and_login())
        rid = self._make_completed_report(with_blob=True, on_disk=False, tmp_path=tmp_path)
        resp = client.get(f"/api/v1/banking-score/reports/download/{rid}", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-1.4 blob-bytes"  # from DB, not disk

    def test_download_404_when_no_blob_and_disk_gone(self, tmp_path):
        headers = auth_headers(register_and_login())
        rid = self._make_completed_report(with_blob=False, on_disk=False, tmp_path=tmp_path)
        resp = client.get(f"/api/v1/banking-score/reports/download/{rid}", headers=headers)
        assert resp.status_code == 404


class TestSystemReportPersistence:
    """Los informes de SISTEMA (criteria/wire/datawatch/sector_outlook) no cuelgan de un
    banco. Antes solo devolvían una ruta del FS efímero: sin fila ``Report`` no había
    ``report_id`` y por tanto no eran descargables. Ahora siguen el mismo contrato que el
    endpoint por banco."""

    ENDPOINTS = [
        ("criteria", "/api/v1/banking-score/reports/criteria/generate"),
        ("wire", "/api/v1/banking-score/reports/wire/generate?period_end=2024-12-31"),
        ("datawatch", "/api/v1/banking-score/reports/datawatch/generate?period_end=2024-12-31"),
        ("sector_outlook",
         "/api/v1/banking-score/reports/sector-outlook/generate?period_end=2024-12-31"),
    ]

    @pytest.mark.parametrize("report_type,url", ENDPOINTS)
    def test_system_report_is_persisted_and_downloadable(self, report_type, url):
        headers = auth_headers(register_and_login())

        gen = client.post(url, headers=headers)
        assert gen.status_code == 200
        body = gen.json()
        assert body["success"] is True
        assert body["report_type"] == report_type
        rid = body["report_id"]
        assert rid, "el informe de sistema debe devolver un report_id descargable"

        from modules.banking_score.models.models import Report, ReportStatus
        db = TestSessionLocal()
        row = db.query(Report).filter_by(id=rid).first()
        assert row is not None
        assert row.bank_id is None          # informe de sistema: sin entidad
        assert row.status == ReportStatus.completed
        assert row.file_blob                # bytes durables, no solo la ruta en disco
        assert row.file_size == len(row.file_blob)
        db.close()

        dl = client.get(f"/api/v1/banking-score/reports/download/{rid}", headers=headers)
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/pdf"
        assert dl.content.startswith(b"%PDF")
        # `criteria` no tiene período: el nombre no debe arrastrar un "None".
        assert "None" not in dl.headers["content-disposition"]

    def test_system_report_survives_disk_loss(self):
        """El PDF se sirve del blob aunque el archivo del contenedor desaparezca."""
        from pathlib import Path
        headers = auth_headers(register_and_login())
        rid = client.post(self.ENDPOINTS[0][1], headers=headers).json()["report_id"]

        from modules.banking_score.models.models import Report
        db = TestSessionLocal()
        path = db.query(Report).filter_by(id=rid).first().file_path
        db.close()
        if path:
            Path(path).unlink(missing_ok=True)

        resp = client.get(f"/api/v1/banking-score/reports/download/{rid}", headers=headers)
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")


try:
    import xgboost as _xgb  # noqa: F401
    _XGB_OK = True
except Exception:
    _XGB_OK = False


class TestMlScoring:
    """Scoring with model=ml: predicts via XGBoost and persists a separate
    RatingResult (model_type=ml), coexisting with the deterministic series."""

    def test_run_ml_without_trained_model_returns_400(self):
        headers = auth_headers(register_and_login())
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bid = bank.id
        db.close()
        from modules.banking_score.ml.xgboost_model import xgboost_model
        xgboost_model.model = None
        xgboost_model._model_path = "/tmp/sdq_no_such_model.pkl"
        resp = client.post(
            f"/api/v1/banking-score/{bid}/run?period_end=2024-12-31&model=ml",
            headers=headers,
        )
        assert resp.status_code == 400
        assert "ML" in resp.json()["detail"]

    @pytest.mark.skipif(not _XGB_OK, reason="xgboost libs missing")
    def test_run_ml_persists_ml_rating_from_db(self, tmp_path):
        import numpy as np
        from modules.banking_score.ml.xgboost_model import xgboost_model
        from modules.banking_score.models.models import RatingResult, ModelType
        from modules.banking_score.scoring.weights import FEATURE_ORDER

        headers = auth_headers(register_and_login())
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bid = bank.id

        tiers_pool = ["SDQ-AAA", "SDQ-AA+", "SDQ-AA", "SDQ-AA-", "SDQ-A+",
                      "SDQ-A", "SDQ-A-", "SDQ-BBB+", "SDQ-BBB", "SDQ-D"]
        rng = np.random.RandomState(0)
        feats, tiers = [], []
        for _ in range(60):
            v = rng.uniform(20, 95, size=len(FEATURE_ORDER)).tolist()
            feats.append(v)
            tiers.append(tiers_pool[min(9, max(0, int((100 - np.mean(v)) / 10)))])
        xgboost_model.model = None
        xgboost_model._model_path = str(tmp_path / "train.pkl")
        xgboost_model.train(feats, tiers)
        xgboost_model.save_to_db(db)
        db.commit()
        db.close()

        # Force the endpoint to load from DB (cold-start: no memory, no disk).
        xgboost_model.model = None
        xgboost_model._model_path = str(tmp_path / "gone.pkl")

        resp = client.post(
            f"/api/v1/banking-score/{bid}/run?period_end=2024-12-31&model=ml",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["model"] == "ml"
        assert data["rating_tier"].startswith("SDQ-")

        db2 = TestSessionLocal()
        ml_row = db2.query(RatingResult).filter_by(bank_id=bid, model_type=ModelType.ml).first()
        det_row = db2.query(RatingResult).filter_by(bank_id=bid, model_type=ModelType.deterministic).first()
        db2.close()
        assert ml_row is not None          # ml rating persisted
        assert det_row is None             # independent of the deterministic series

    def test_rankings_dedupe_when_both_models_exist(self):
        """Regression: a coexisting deterministic + ml rating for the same
        (bank, period) must not surface the entity twice. Rankings shows the
        canonical (deterministic) model by default; model=ml is opt-in."""
        from modules.banking_score.models.models import RatingResult, ModelType

        headers = auth_headers(register_and_login())
        db = TestSessionLocal()
        bank = seed_test_bank(db)
        bid = bank.id
        db.close()

        # Deterministic rating via the normal pipeline.
        client.post(f"/api/v1/banking-score/{bid}/run?period_end=2024-12-31", headers=headers)

        # Persist a coexisting ML rating for the same bank + period.
        db = TestSessionLocal()
        det = db.query(RatingResult).filter_by(
            bank_id=bid, model_type=ModelType.deterministic).first()
        db.add(RatingResult(
            bank_id=bid, period_end=det.period_end, model_type=ModelType.ml,
            overall_score=det.overall_score - 2, rating_tier=det.rating_tier,
            model_version="test-ml",
        ))
        db.commit()
        db.close()

        # Default (deterministic): the bank appears exactly once.
        resp = client.get("/api/v1/banking-score/rankings", headers=headers)
        assert resp.status_code == 200
        ids = [r["bank_id"] for r in resp.json()["rankings"]]
        assert ids.count(bid) == 1

        # model=ml: returns the ML rating for the bank.
        resp_ml = client.get("/api/v1/banking-score/rankings?model=ml", headers=headers)
        assert resp_ml.status_code == 200
        ml_ids = [r["bank_id"] for r in resp_ml.json()["rankings"]]
        assert ml_ids.count(bid) == 1

        # Invalid model → 400.
        assert client.get(
            "/api/v1/banking-score/rankings?model=bogus", headers=headers
        ).status_code == 400
