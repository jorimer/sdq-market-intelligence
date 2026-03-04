"""Banking Seed Service — Creates Dominican banking entities and historical data.

Extracted from financial-analysis-agent/backend/app/services/banking_seed_service.py.

Creates 35 SIB-regulated entities and 5 years of quarterly financial data
calibrated to SIB sector statistics (Q4-2024).
"""
import hashlib
import logging
import random
from datetime import date
from typing import Dict, List

from modules.banking_score.models.models import (
    Bank,
    BankingData,
    BankType,
    DataSource,
    PeriodType,
)
from shared.auth.models import User  # noqa: F401  — needed so SQLAlchemy resolves FK
from shared.database.session import SessionLocal

logger = logging.getLogger("sdq.seed.banking")

# ═══════════════════════════════════════════════════════════════════
#  DOMINICAN BANKING ENTITIES — Full SIB-regulated list
# ═══════════════════════════════════════════════════════════════════

BANKING_ENTITIES: List[Dict] = [
    # ── Banca Múltiple (15) ──────────────────────────────────────
    {"name": "Banco de Reservas de la República Dominicana",       "short": "Banreservas",   "type": "banca_multiple", "tier": "large",  "asset_base": 850_000},
    {"name": "Banco Popular Dominicano",                           "short": "Popular",       "type": "banca_multiple", "tier": "large",  "asset_base": 720_000},
    {"name": "Banco Múltiple BHD",                                 "short": "BHD",           "type": "banca_multiple", "tier": "large",  "asset_base": 550_000},
    {"name": "Scotiabank República Dominicana",                    "short": "Scotiabank",    "type": "banca_multiple", "tier": "large",  "asset_base": 210_000},
    {"name": "Banco Múltiple Santa Cruz",                          "short": "Santa Cruz",    "type": "banca_multiple", "tier": "medium", "asset_base": 85_000},
    {"name": "Banco Múltiple Caribe Internacional",                "short": "Caribe",        "type": "banca_multiple", "tier": "medium", "asset_base": 72_000},
    {"name": "Banco Múltiple Promérica de la República Dominicana","short": "Promérica",     "type": "banca_multiple", "tier": "medium", "asset_base": 58_000},
    {"name": "Banesco Banco Múltiple",                             "short": "Banesco",       "type": "banca_multiple", "tier": "medium", "asset_base": 45_000},
    {"name": "Banco Múltiple López de Haro",                       "short": "López de Haro", "type": "banca_multiple", "tier": "small",  "asset_base": 30_000},
    {"name": "Banco Múltiple Vimenca",                             "short": "Vimenca",       "type": "banca_multiple", "tier": "small",  "asset_base": 28_000},
    {"name": "Banco Múltiple BDI",                                 "short": "BDI",           "type": "banca_multiple", "tier": "small",  "asset_base": 15_000},
    {"name": "Banco Múltiple Lafise",                              "short": "Lafise",        "type": "banca_multiple", "tier": "small",  "asset_base": 12_000},
    {"name": "Citibank N.A. Sucursal República Dominicana",        "short": "Citibank",      "type": "banca_multiple", "tier": "small",  "asset_base": 10_000},
    {"name": "JMMB Bank Banco Múltiple",                           "short": "JMMB",          "type": "banca_multiple", "tier": "small",  "asset_base": 8_000},
    {"name": "Qik Banco Digital Dominicano",                       "short": "Qik",           "type": "banca_multiple", "tier": "small",  "asset_base": 5_000},
    # ── Asociaciones de Ahorros y Préstamos (10) ─────────────────
    {"name": "Asociación Popular de Ahorros y Préstamos",          "short": "APAP",          "type": "aap",            "tier": "large",  "asset_base": 180_000},
    {"name": "Asociación Cibao de Ahorros y Préstamos",            "short": "ACAP",          "type": "aap",            "tier": "medium", "asset_base": 95_000},
    {"name": "Asociación La Nacional de Ahorros y Préstamos",      "short": "La Nacional",   "type": "aap",            "tier": "medium", "asset_base": 88_000},
    {"name": "Asociación de Ahorros y Préstamos Romana",           "short": "ARAP",          "type": "aap",            "tier": "small",  "asset_base": 22_000},
    {"name": "Asociación Duarte de Ahorros y Préstamos",           "short": "Duarte",        "type": "aap",            "tier": "small",  "asset_base": 15_000},
    {"name": "Asociación La Vega Real de Ahorros y Préstamos",     "short": "La Vega Real",  "type": "aap",            "tier": "small",  "asset_base": 12_000},
    {"name": "Asociación Maguana de Ahorros y Préstamos",          "short": "Maguana",        "type": "aap",            "tier": "small",  "asset_base": 6_000},
    {"name": "Asociación Bonao de Ahorros y Préstamos",            "short": "Bonao",         "type": "aap",            "tier": "small",  "asset_base": 4_500},
    {"name": "Asociación Mocana de Ahorros y Préstamos",           "short": "Mocana",        "type": "aap",            "tier": "small",  "asset_base": 3_500},
    {"name": "Asociación Peravia de Ahorros y Préstamos",          "short": "Peravia",       "type": "aap",            "tier": "small",  "asset_base": 3_000},
    # ── Bancos de Ahorro y Crédito (10) ──────────────────────────
    {"name": "Banco ADOPEM de Ahorro y Crédito",                   "short": "ADOPEM",        "type": "banco_ahorro_credito", "tier": "medium", "asset_base": 42_000},
    {"name": "Banco ADEMI de Ahorro y Crédito",                    "short": "ADEMI",         "type": "banco_ahorro_credito", "tier": "medium", "asset_base": 38_000},
    {"name": "Banco de Ahorro y Crédito Confisa",                  "short": "Confisa",       "type": "banco_ahorro_credito", "tier": "medium", "asset_base": 25_000},
    {"name": "Banco de Ahorro y Crédito FONDESA",                  "short": "FONDESA",       "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 18_000},
    {"name": "Motor Crédito Banco de Ahorro y Crédito",            "short": "Motor Crédito", "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 15_000},
    {"name": "Banco de Ahorro y Crédito Fihogar",                  "short": "Fihogar",       "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 10_000},
    {"name": "Banco de Ahorro y Crédito del Caribe",               "short": "BACC",          "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 8_000},
    {"name": "Banco de Ahorro y Crédito Unión",                    "short": "Unión",         "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 6_000},
    {"name": "Banco de Ahorro y Crédito Gruficorp",                "short": "Gruficorp",     "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 5_000},
    {"name": "Banco de Ahorro y Crédito Bonanza",                  "short": "Bonanza",       "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 4_000},
]

# ═══════════════════════════════════════════════════════════════════
#  FINANCIAL PROFILE ARCHETYPES — Calibrated to SIB Q4-2024
# ═══════════════════════════════════════════════════════════════════

# Map monolith type keys to our BankType enum values
_TYPE_MAP = {
    "banca_multiple": "banca_multiple",
    "aap": "asociacion",
    "banco_ahorro_credito": "ahorro_credito",
}

PROFILE_ARCHETYPES = {
    ("banca_multiple", "large"): {
        "solvencia_pct": (16.0, 1.5), "tier1_pct": (12.5, 1.2), "leverage_pct": (9.0, 0.8),
        "morosidad_pct": (1.6, 0.5), "cobertura_pct": (165.0, 25.0), "cartera_a_pct": (93.0, 2.5),
        "concentracion_pct": (15.0, 4.0), "hhi_sectorial": (1400, 250), "castigos_pct": (1.5, 0.6),
        "re_exposure_pct": (18.0, 5.0), "migracion_pct": (2.0, 1.0), "roa_pct": (2.2, 0.4),
        "roe_pct": (19.0, 3.0), "nim_pct": (5.5, 0.6), "eficiencia_pct": (48.0, 5.0),
        "ltv_pct": (78.0, 8.0), "cobertura_liq_pct": (35.0, 6.0), "actliq_pasiex_pct": (32.0, 5.0),
        "hhi_ingresos": (3500, 500),
    },
    ("banca_multiple", "medium"): {
        "solvencia_pct": (17.5, 2.0), "tier1_pct": (13.5, 1.5), "leverage_pct": (8.5, 1.0),
        "morosidad_pct": (2.2, 0.7), "cobertura_pct": (145.0, 30.0), "cartera_a_pct": (90.0, 3.5),
        "concentracion_pct": (20.0, 5.0), "hhi_sectorial": (1700, 350), "castigos_pct": (2.0, 0.8),
        "re_exposure_pct": (22.0, 6.0), "migracion_pct": (2.8, 1.2), "roa_pct": (1.8, 0.5),
        "roe_pct": (16.5, 3.5), "nim_pct": (6.2, 0.8), "eficiencia_pct": (55.0, 6.0),
        "ltv_pct": (82.0, 9.0), "cobertura_liq_pct": (30.0, 7.0), "actliq_pasiex_pct": (28.0, 6.0),
        "hhi_ingresos": (4200, 600),
    },
    ("banca_multiple", "small"): {
        "solvencia_pct": (19.0, 3.0), "tier1_pct": (15.0, 2.5), "leverage_pct": (7.5, 1.5),
        "morosidad_pct": (2.8, 1.0), "cobertura_pct": (130.0, 35.0), "cartera_a_pct": (87.0, 4.0),
        "concentracion_pct": (28.0, 7.0), "hhi_sectorial": (2100, 450), "castigos_pct": (2.5, 1.0),
        "re_exposure_pct": (15.0, 6.0), "migracion_pct": (3.2, 1.5), "roa_pct": (1.3, 0.6),
        "roe_pct": (13.0, 4.0), "nim_pct": (7.0, 1.0), "eficiencia_pct": (62.0, 8.0),
        "ltv_pct": (75.0, 10.0), "cobertura_liq_pct": (38.0, 8.0), "actliq_pasiex_pct": (35.0, 7.0),
        "hhi_ingresos": (5000, 700),
    },
    ("asociacion", "large"): {
        "solvencia_pct": (14.5, 1.5), "tier1_pct": (11.0, 1.2), "leverage_pct": (8.0, 0.8),
        "morosidad_pct": (2.0, 0.6), "cobertura_pct": (140.0, 25.0), "cartera_a_pct": (91.0, 3.0),
        "concentracion_pct": (12.0, 3.0), "hhi_sectorial": (2200, 300), "castigos_pct": (1.8, 0.7),
        "re_exposure_pct": (55.0, 10.0), "migracion_pct": (2.2, 1.0), "roa_pct": (1.5, 0.4),
        "roe_pct": (14.0, 3.0), "nim_pct": (4.5, 0.5), "eficiencia_pct": (52.0, 6.0),
        "ltv_pct": (85.0, 6.0), "cobertura_liq_pct": (25.0, 5.0), "actliq_pasiex_pct": (22.0, 4.0),
        "hhi_ingresos": (4500, 500),
    },
    ("asociacion", "medium"): {
        "solvencia_pct": (15.0, 2.0), "tier1_pct": (11.5, 1.5), "leverage_pct": (7.5, 1.0),
        "morosidad_pct": (2.5, 0.8), "cobertura_pct": (130.0, 30.0), "cartera_a_pct": (88.0, 4.0),
        "concentracion_pct": (18.0, 5.0), "hhi_sectorial": (2500, 400), "castigos_pct": (2.2, 0.9),
        "re_exposure_pct": (50.0, 12.0), "migracion_pct": (3.0, 1.2), "roa_pct": (1.2, 0.4),
        "roe_pct": (12.0, 3.0), "nim_pct": (5.0, 0.7), "eficiencia_pct": (58.0, 7.0),
        "ltv_pct": (88.0, 7.0), "cobertura_liq_pct": (22.0, 5.0), "actliq_pasiex_pct": (20.0, 4.0),
        "hhi_ingresos": (5200, 600),
    },
    ("asociacion", "small"): {
        "solvencia_pct": (16.0, 3.0), "tier1_pct": (12.0, 2.5), "leverage_pct": (7.0, 1.5),
        "morosidad_pct": (3.5, 1.2), "cobertura_pct": (115.0, 30.0), "cartera_a_pct": (84.0, 5.0),
        "concentracion_pct": (25.0, 7.0), "hhi_sectorial": (2800, 500), "castigos_pct": (3.0, 1.2),
        "re_exposure_pct": (45.0, 12.0), "migracion_pct": (4.0, 1.5), "roa_pct": (0.8, 0.4),
        "roe_pct": (9.0, 3.0), "nim_pct": (5.5, 0.9), "eficiencia_pct": (65.0, 9.0),
        "ltv_pct": (90.0, 8.0), "cobertura_liq_pct": (20.0, 6.0), "actliq_pasiex_pct": (18.0, 5.0),
        "hhi_ingresos": (5800, 700),
    },
    ("ahorro_credito", "medium"): {
        "solvencia_pct": (18.0, 2.5), "tier1_pct": (14.0, 2.0), "leverage_pct": (7.0, 1.0),
        "morosidad_pct": (3.0, 1.0), "cobertura_pct": (125.0, 30.0), "cartera_a_pct": (86.0, 4.0),
        "concentracion_pct": (22.0, 6.0), "hhi_sectorial": (2000, 400), "castigos_pct": (2.5, 1.0),
        "re_exposure_pct": (10.0, 5.0), "migracion_pct": (3.5, 1.3), "roa_pct": (2.0, 0.5),
        "roe_pct": (15.0, 3.5), "nim_pct": (10.0, 2.0), "eficiencia_pct": (60.0, 8.0),
        "ltv_pct": (70.0, 10.0), "cobertura_liq_pct": (40.0, 8.0), "actliq_pasiex_pct": (35.0, 7.0),
        "hhi_ingresos": (4000, 600),
    },
    ("ahorro_credito", "small"): {
        "solvencia_pct": (20.0, 3.5), "tier1_pct": (16.0, 3.0), "leverage_pct": (6.5, 1.5),
        "morosidad_pct": (4.0, 1.5), "cobertura_pct": (110.0, 30.0), "cartera_a_pct": (82.0, 5.0),
        "concentracion_pct": (30.0, 8.0), "hhi_sectorial": (2500, 500), "castigos_pct": (3.5, 1.5),
        "re_exposure_pct": (8.0, 4.0), "migracion_pct": (4.5, 2.0), "roa_pct": (1.0, 0.5),
        "roe_pct": (10.0, 3.5), "nim_pct": (12.0, 2.5), "eficiencia_pct": (68.0, 10.0),
        "ltv_pct": (65.0, 12.0), "cobertura_liq_pct": (45.0, 10.0), "actliq_pasiex_pct": (40.0, 8.0),
        "hhi_ingresos": (5500, 700),
    },
}

# Quarterly macro factors: >1.0 = favorable, <1.0 = stress
MACRO_FACTORS: Dict[str, float] = {
    "2021-03-31": 0.92, "2021-06-30": 0.96, "2021-09-30": 1.02, "2021-12-31": 1.05,
    "2022-03-31": 1.03, "2022-06-30": 0.98, "2022-09-30": 0.95, "2022-12-31": 0.93,
    "2023-03-31": 0.94, "2023-06-30": 0.97, "2023-09-30": 1.00, "2023-12-31": 1.02,
    "2024-03-31": 1.01, "2024-06-30": 1.03, "2024-09-30": 1.05, "2024-12-31": 1.06,
    "2025-03-31": 1.04, "2025-06-30": 1.05, "2025-09-30": 1.06, "2025-12-31": 1.07,
}


# ─── Helpers ──────────────────────────────────────────────────────


def _deterministic_seed(entity_name: str, period: str) -> int:
    h = hashlib.md5(f"{entity_name}:{period}".encode()).hexdigest()
    return int(h[:8], 16)


def _sample_ratio(mean: float, std: float, rng: random.Random, macro: float = 1.0) -> float:
    adjusted_mean = mean * macro
    value = rng.gauss(adjusted_mean, std)
    return max(0.01, round(value, 2))


def _derive_absolute_values(
    ratios: Dict[str, float],
    asset_base_mm: float,
    growth_factor: float,
    rng: random.Random,
) -> Dict[str, float]:
    """Derive absolute DOP millions from ratio profiles."""
    activos = asset_base_mm * growth_factor * rng.uniform(0.97, 1.03)
    activos = round(activos, 2)

    cartera_bruta = activos * rng.uniform(0.55, 0.70)
    patrimonio = activos * (ratios["solvencia_pct"] / 100) * rng.uniform(0.65, 0.80)
    depositos = activos * rng.uniform(0.60, 0.78)

    apr = activos * rng.uniform(0.75, 0.90)
    contingentes = apr * rng.uniform(0.05, 0.12)
    riesgo_mercado = apr * rng.uniform(0.02, 0.06)

    patrimonio_tecnico = apr * (ratios["solvencia_pct"] / 100)
    capital_primario = patrimonio_tecnico * (ratios["tier1_pct"] / ratios["solvencia_pct"]) if ratios["solvencia_pct"] > 0 else 0
    capital_tier1 = capital_primario
    exposicion_total = activos * rng.uniform(1.05, 1.15)

    cartera_vencida = cartera_bruta * (ratios["morosidad_pct"] / 100)
    provisiones = cartera_vencida * (ratios["cobertura_pct"] / 100)
    cartera_cat_a = cartera_bruta * (ratios["cartera_a_pct"] / 100)
    cartera_neta = cartera_bruta - provisiones

    suma_top10 = cartera_bruta * (ratios["concentracion_pct"] / 100)
    castigos = cartera_bruta * (ratios["castigos_pct"] / 100)
    exposicion_re = activos * (ratios["re_exposure_pct"] / 100)
    cartera_a_prev = cartera_cat_a * (1 + ratios["migracion_pct"] / 100)

    activos_promedio = activos * rng.uniform(0.96, 1.02)
    patrimonio_promedio = patrimonio * rng.uniform(0.95, 1.05)
    utilidad_neta = activos_promedio * (ratios["roa_pct"] / 100)

    activos_productivos = activos * rng.uniform(0.70, 0.85)
    nim_spread = ratios["nim_pct"] / 100
    ingresos_financieros = activos_productivos * (nim_spread + rng.uniform(0.02, 0.04))
    gastos_financieros = ingresos_financieros - (activos_productivos * nim_spread)

    ingresos_operacionales = ingresos_financieros * rng.uniform(1.10, 1.30)
    gastos_operacionales = ingresos_operacionales * (ratios["eficiencia_pct"] / 100)

    caja_valores = activos * rng.uniform(0.08, 0.15)
    pasivos_cp = depositos * rng.uniform(0.40, 0.60)
    activos_liquidos = activos * (ratios["actliq_pasiex_pct"] / 100) * rng.uniform(0.95, 1.05)
    pasivos_exigibles = activos * rng.uniform(0.75, 0.88)
    cartera_total = cartera_bruta

    return {
        "patrimonio_tecnico": round(patrimonio_tecnico, 2),
        "apr": round(apr, 2),
        "capital_primario": round(capital_primario, 2),
        "exposicion_total": round(exposicion_total, 2),
        "capital_tier1": round(capital_tier1, 2),
        "contingentes": round(contingentes, 2),
        "riesgo_mercado": round(riesgo_mercado, 2),
        "provisiones": round(provisiones, 2),
        "cartera_vencida_90d": round(cartera_vencida, 2),
        "activos_totales": round(activos, 2),
        "cartera_bruta": round(cartera_bruta, 2),
        "cartera_categoria_a": round(cartera_cat_a, 2),
        "cartera_total": round(cartera_total, 2),
        "suma_top10": round(suma_top10, 2),
        "hhi_sectorial_raw": round(ratios["hhi_sectorial"], 0),
        "castigos": round(castigos, 2),
        "exposicion_re": round(exposicion_re, 2),
        "cartera_a_prev": round(cartera_a_prev, 2),
        "utilidad_neta": round(utilidad_neta, 2),
        "activos_promedio": round(activos_promedio, 2),
        "patrimonio_promedio": round(patrimonio_promedio, 2),
        "ingresos_financieros": round(ingresos_financieros, 2),
        "gastos_financieros": round(gastos_financieros, 2),
        "activos_productivos_avg": round(activos_productivos, 2),
        "gastos_operacionales": round(gastos_operacionales, 2),
        "ingresos_operacionales": round(ingresos_operacionales, 2),
        "caja_valores": round(caja_valores, 2),
        "pasivos_cp": round(pasivos_cp, 2),
        "cartera_neta": round(cartera_neta, 2),
        "depositos_totales": round(depositos, 2),
        "activos_liquidos": round(activos_liquidos, 2),
        "pasivos_exigibles": round(pasivos_exigibles, 2),
        "hhi_ingresos_raw": round(ratios["hhi_ingresos"], 0),
    }


def _generate_quarters(start_year: int = 2021, end_year: int = 2025) -> List[date]:
    quarters = []
    for year in range(start_year, end_year + 1):
        for m, d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            quarters.append(date(year, m, d))
    return quarters


def _map_entity_type(entity_type: str) -> BankType:
    """Map seed entity type to BankType enum."""
    mapping = {
        "banca_multiple": BankType.banca_multiple,
        "aap": BankType.aap,
        "banco_ahorro_credito": BankType.banco_ahorro_credito,
    }
    return mapping[entity_type]


def _get_profile_key(entity_type: str, tier: str) -> tuple:
    """Map our BankType values to monolith profile archetype keys."""
    type_map = {
        "banca_multiple": "banca_multiple",
        "aap": "asociacion",
        "banco_ahorro_credito": "ahorro_credito",
    }
    return (type_map[entity_type], tier)


# ═══════════════════════════════════════════════════════════════════
#  MAIN SEED FUNCTION
# ═══════════════════════════════════════════════════════════════════


def seed_banks(verbose: bool = True) -> Dict:
    """Create all 35 banking entities and populate 5 years of quarterly data.

    Can be called standalone or from the API endpoint.
    """
    session = SessionLocal()
    quarters = _generate_quarters(2021, 2025)
    entities_created = 0
    entities_existing = 0
    records_created = 0
    records_existing = 0

    try:
        # Step 1: Create Bank records
        entity_id_map: Dict[str, str] = {}

        for entity in BANKING_ENTITIES:
            existing = session.query(Bank).filter(
                Bank.name == entity["name"]
            ).first()

            if existing:
                entity_id_map[entity["short"]] = existing.id
                entities_existing += 1
                continue

            bank = Bank(
                name=entity["name"],
                bank_type=_map_entity_type(entity["type"]),
                peer_group=entity["tier"],
                total_assets=entity["asset_base"],
                is_active=True,
            )
            session.add(bank)
            session.flush()
            entity_id_map[entity["short"]] = bank.id
            entities_created += 1

        session.commit()
        if verbose:
            logger.info("Banks: %d created, %d existing", entities_created, entities_existing)

        # Step 2: Generate quarterly financial data
        for entity in BANKING_ENTITIES:
            short = entity["short"]
            bank_id = entity_id_map.get(short)
            if not bank_id:
                continue

            profile_key = _get_profile_key(entity["type"], entity["tier"])
            profile = PROFILE_ARCHETYPES.get(profile_key)
            if not profile:
                logger.warning("No profile for %s, skipping", profile_key)
                continue

            base_assets = entity["asset_base"]

            for q_idx, period_end in enumerate(quarters):
                existing = session.query(BankingData).filter_by(
                    bank_id=bank_id, period_end=period_end
                ).first()
                if existing:
                    records_existing += 1
                    continue

                period_str = str(period_end)
                macro = MACRO_FACTORS.get(period_str, 1.0)
                seed_val = _deterministic_seed(entity["name"], period_str)
                rng = random.Random(seed_val)

                years_from_start = q_idx / 4.0
                annual_growth = rng.uniform(0.05, 0.09)
                growth_factor = (1 + annual_growth) ** years_from_start

                ratios = {}
                for key, (mean, std) in profile.items():
                    if key in ("morosidad_pct", "castigos_pct", "migracion_pct",
                               "eficiencia_pct", "concentracion_pct", "hhi_sectorial",
                               "hhi_ingresos"):
                        adj_macro = 2.0 - macro
                    else:
                        adj_macro = macro
                    ratios[key] = _sample_ratio(mean, std, rng, adj_macro)

                abs_values = _derive_absolute_values(ratios, base_assets, growth_factor, rng)

                record = BankingData(
                    bank_id=bank_id,
                    period_end=period_end,
                    period_type=PeriodType.quarterly,
                    source=DataSource.manual,
                    **abs_values,
                )
                session.add(record)
                records_created += 1

            session.commit()

        result = {
            "entities_created": entities_created,
            "entities_existing": entities_existing,
            "records_created": records_created,
            "records_existing": records_existing,
            "total_entities": len(BANKING_ENTITIES),
            "total_quarters": len(quarters),
            "expected_records": len(BANKING_ENTITIES) * len(quarters),
        }

        if verbose:
            logger.info("Seed complete: %d entities, %d records", entities_created, records_created)
            print(f"Seed complete: {entities_created} entities, {records_created} records")

        return result

    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
