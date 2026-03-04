"""Tests for PASO 5 — Report generation (PDF + Narrative)."""
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.banking_score.scoring.engine import BankingDataInput, run_scoring
from modules.banking_score.reports.pdf_generator import (
    generate_pdf_report,
    generate_radar_chart,
)
from modules.banking_score.reports.narrative import (
    REPORT_SECTIONS,
    generate_report_narratives,
)


# ── Test data ────────────────────────────────────────────────────

def _sample_scoring_result():
    data = BankingDataInput(
        patrimonio_tecnico=5_000,
        apr=30_000,
        capital_primario=4_000,
        exposicion_total=50_000,
        capital_tier1=4_000,
        contingentes=2_000,
        riesgo_mercado=1_000,
        provisiones=800,
        cartera_vencida_90d=500,
        activos_totales=80_000,
        cartera_bruta=50_000,
        cartera_categoria_a=45_000,
        cartera_total=50_000,
        suma_top10=12_000,
        hhi_sectorial_raw=1_800,
        castigos=200,
        exposicion_re=18_000,
        cartera_a_prev=44_000,
        utilidad_neta=1_500,
        activos_promedio=75_000,
        patrimonio_promedio=8_000,
        ingresos_financieros=6_000,
        gastos_financieros=2_000,
        activos_productivos_avg=60_000,
        gastos_operacionales=2_500,
        ingresos_operacionales=5_000,
        caja_valores=8_000,
        pasivos_cp=30_000,
        cartera_neta=48_000,
        depositos_totales=55_000,
        activos_liquidos=15_000,
        pasivos_exigibles=60_000,
        hhi_ingresos_raw=3_500,
    )
    return run_scoring(data)


# ── Radar chart tests ────────────────────────────────────────────

class TestRadarChart:
    def test_radar_chart_generates_png(self, tmp_path):
        sub_scores = {
            "solidez": 80.0,
            "calidad": 70.0,
            "eficiencia": 65.0,
            "liquidez": 75.0,
            "diversificacion": 50.0,
        }
        output = str(tmp_path / "charts" / "radar_test.png")
        result = generate_radar_chart(sub_scores, output)
        assert os.path.exists(result)
        assert result.endswith(".png")
        assert os.path.getsize(result) > 1000  # Not empty

    def test_radar_chart_with_zeros(self, tmp_path):
        sub_scores = {
            "solidez": 0,
            "calidad": 0,
            "eficiencia": 0,
            "liquidez": 0,
            "diversificacion": 0,
        }
        output = str(tmp_path / "charts" / "radar_zero.png")
        result = generate_radar_chart(sub_scores, output)
        assert os.path.exists(result)


# ── PDF generation tests ─────────────────────────────────────────

class TestPDFGenerator:
    @pytest.mark.asyncio
    async def test_generate_full_rating_pdf(self, tmp_path):
        result = _sample_scoring_result()
        narratives = {
            "executive_summary": "Este es un resumen ejecutivo de prueba.",
            "recommendation": "Recomendamos mantener la calificación actual.",
        }
        filepath = await generate_pdf_report(
            report_type="full_rating",
            bank_name="Banco Popular Dominicano",
            scoring_result=result,
            period="2024-Q4",
            narratives=narratives,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(filepath)
        assert filepath.endswith(".pdf")
        assert os.path.getsize(filepath) > 5000

    @pytest.mark.asyncio
    async def test_generate_scorecard_pdf(self, tmp_path):
        result = _sample_scoring_result()
        filepath = await generate_pdf_report(
            report_type="scorecard",
            bank_name="BHD León",
            scoring_result=result,
            period="2024-Q4",
            output_dir=str(tmp_path),
        )
        assert os.path.exists(filepath)
        assert "scorecard" in filepath

    @pytest.mark.asyncio
    async def test_generate_communique_pdf(self, tmp_path):
        result = {
            "overall_score": 85.0,
            "rating_tier": "SDQ-AA",
            "tier_color": "#10B981",
            "sub_components": {},
            "indicators": {},
        }
        filepath = await generate_pdf_report(
            report_type="communique",
            bank_name="Reservas",
            scoring_result=result,
            period="2024-12-31",
            narratives={"executive_summary": "Acción de rating: confirmación."},
            output_dir=str(tmp_path),
        )
        assert os.path.exists(filepath)

    @pytest.mark.asyncio
    async def test_generate_wire_pdf(self, tmp_path):
        result = {"overall_score": 0, "rating_tier": "N/A", "sub_components": {}, "indicators": {}}
        filepath = await generate_pdf_report(
            report_type="wire",
            bank_name="Sistema Bancario",
            scoring_result=result,
            period="2024-Q4",
            narratives={"executive_summary": "Resumen del sector."},
            output_dir=str(tmp_path),
        )
        assert os.path.exists(filepath)

    @pytest.mark.asyncio
    async def test_all_report_types_generate(self, tmp_path):
        result = _sample_scoring_result()
        for rt in ["full_rating", "scorecard", "communique", "datawatch", "wire", "criteria", "sector_outlook"]:
            filepath = await generate_pdf_report(
                report_type=rt,
                bank_name="Test Bank",
                scoring_result=result,
                period="2024-Q4",
                output_dir=str(tmp_path),
            )
            assert os.path.exists(filepath), f"Failed for {rt}"


# ── Narrative wrapper tests ──────────────────────────────────────

class TestNarrative:
    def test_report_sections_defined(self):
        assert "full_rating" in REPORT_SECTIONS
        assert len(REPORT_SECTIONS["full_rating"]) == 9
        assert "scorecard" in REPORT_SECTIONS

    @pytest.mark.asyncio
    async def test_generate_narratives_fallback(self):
        """Without API key, narratives use fallback templates."""
        result = _sample_scoring_result()
        narratives = await generate_report_narratives(
            report_type="scorecard",
            bank_name="Test Bank",
            scoring_result=result,
            period="2024-Q4",
        )
        assert isinstance(narratives, dict)
        assert "executive_summary" in narratives
        assert "recommendation" in narratives
        assert len(narratives["executive_summary"]) > 0

    @pytest.mark.asyncio
    async def test_generate_full_rating_narratives(self):
        result = _sample_scoring_result()
        narratives = await generate_report_narratives(
            report_type="full_rating",
            bank_name="Test Bank",
            scoring_result=result,
            period="2024-Q4",
        )
        assert len(narratives) == 9


# ── Integration: scoring → narratives → PDF ──────────────────────

class TestReportIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, tmp_path):
        """Scoring → Narrative generation → PDF creation."""
        # 1. Score
        data = BankingDataInput(
            patrimonio_tecnico=5_000, apr=30_000, capital_primario=4_000,
            exposicion_total=50_000, capital_tier1=4_000, contingentes=2_000,
            riesgo_mercado=1_000, provisiones=800, cartera_vencida_90d=500,
            activos_totales=80_000, cartera_bruta=50_000,
            cartera_categoria_a=45_000, cartera_total=50_000,
            suma_top10=12_000, hhi_sectorial_raw=1_800, castigos=200,
            exposicion_re=18_000, cartera_a_prev=44_000, utilidad_neta=1_500,
            activos_promedio=75_000, patrimonio_promedio=8_000,
            ingresos_financieros=6_000, gastos_financieros=2_000,
            activos_productivos_avg=60_000, gastos_operacionales=2_500,
            ingresos_operacionales=5_000, caja_valores=8_000,
            pasivos_cp=30_000, cartera_neta=48_000, depositos_totales=55_000,
            activos_liquidos=15_000, pasivos_exigibles=60_000,
            hhi_ingresos_raw=3_500,
        )
        scoring_result = run_scoring(data)

        # 2. Generate narratives (will use fallback since no API key)
        narratives = await generate_report_narratives(
            report_type="full_rating",
            bank_name="Banco Popular Dominicano",
            scoring_result=scoring_result,
            period="2024-Q4",
        )
        assert len(narratives) == 9

        # 3. Generate PDF
        filepath = await generate_pdf_report(
            report_type="full_rating",
            bank_name="Banco Popular Dominicano",
            scoring_result=scoring_result,
            period="2024-Q4",
            narratives=narratives,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(filepath)
        assert os.path.getsize(filepath) > 10_000  # Substantial PDF
