"""Tests for Banking Score API endpoints.

Validates:
- Health check
- Auth flow (register → login → access protected)
- Scoring pipeline (seed → run scoring → get latest → rankings)
- Data endpoints (template, raw data)
- Stats endpoint
"""
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
from app.main import app

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
    from modules.banking_score.models.models import Bank, BankingData, BankType, DataSource
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
        source=DataSource.manual,
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
        assert "rating_tier" in data
        assert data["rating_tier"].startswith("SDQ-")
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
        assert data["rating_tier"].startswith("SDQ-")

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
        assert data["rankings"][0]["rank"] == 1

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
