"""Banking catalog seed — registers the Dominican SIB-regulated entities.

Creates the SIB-regulated entities (the entity *catalog* — Gate A, legitimate)
so a fresh database has the known institutions before the first SIB sync. It does
**not** create any financial data: house rule is no seeded/fixture values in the
DB — every source carries its own real backfill (SIB API / SIMBAD / CSV upload).
Financial records arrive exclusively via those real channels.

Historical note: this used to also fabricate 5 years of Gaussian-sampled
quarterly financials (``source=manual``). That synthetic path was removed when
the seed was sealed — `manual` is no longer produced anywhere, the scoring
ignores it, and `purge-synthetic` clears any residue.
"""
import logging
from typing import Dict, List

from modules.banking_score.models.models import Bank, BankType

logger = logging.getLogger("sdq.seed.banking")

# ═══════════════════════════════════════════════════════════════════
#  DOMINICAN BANKING ENTITIES — Full SIB-regulated list (catalog only)
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
    # Banco Ademi es BANCA MÚLTIPLE desde 2013 (antes ONG microfinanciera); el SIB lo
    # reporta bajo BM (verificado vs SIMBAD 2026-06-14). No es ahorro y crédito.
    {"name": "Banco Múltiple Ademi",                               "short": "ADEMI",         "type": "banca_multiple",       "tier": "medium", "asset_base": 38_000},
    {"name": "Banco de Ahorro y Crédito Confisa",                  "short": "Confisa",       "type": "banco_ahorro_credito", "tier": "medium", "asset_base": 25_000},
    {"name": "Banco de Ahorro y Crédito FONDESA",                  "short": "FONDESA",       "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 18_000},
    {"name": "Motor Crédito Banco de Ahorro y Crédito",            "short": "Motor Crédito", "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 15_000},
    {"name": "Banco de Ahorro y Crédito Fihogar",                  "short": "Fihogar",       "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 10_000},
    {"name": "Banco de Ahorro y Crédito del Caribe",               "short": "BACC",          "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 8_000},
    {"name": "Banco de Ahorro y Crédito Unión",                    "short": "Unión",         "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 6_000},
    {"name": "Banco de Ahorro y Crédito Gruficorp",                "short": "Gruficorp",     "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 5_000},
    {"name": "Banco de Ahorro y Crédito Bonanza",                  "short": "Bonanza",       "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 4_000},
    {"name": "Banco de Ahorros y Créditos Bancotui",               "short": "Bancotui",      "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 2_100},
    {"name": "Leasing Confisa Banco de Ahorro y Crédito",          "short": "Leasconfisa",   "type": "banco_ahorro_credito", "tier": "small",  "asset_base": 1_700},

    # ── Corporaciones de Crédito (3) ─────────────────────────────
    {"name": "Corporación de Crédito Monumental",                  "short": "Monumental",    "type": "corporacion_credito", "tier": "small", "asset_base": 1_200},
    {"name": "Corporación de Crédito Nordestana de Préstamos",     "short": "Nordestana",    "type": "corporacion_credito", "tier": "small", "asset_base": 900},
    {"name": "Corporación de Crédito Oficorp",                     "short": "Oficorp",       "type": "corporacion_credito", "tier": "small", "asset_base": 700},
]


def _map_entity_type(entity_type: str) -> BankType:
    """Map seed entity type to BankType enum."""
    mapping = {
        "banca_multiple": BankType.banca_multiple,
        "aap": BankType.aap,
        "banco_ahorro_credito": BankType.banco_ahorro_credito,
        "corporacion_credito": BankType.corporacion_credito,
    }
    return mapping[entity_type]


# ═══════════════════════════════════════════════════════════════════
#  CATALOG SEED — entities only, never financial data
# ═══════════════════════════════════════════════════════════════════


def seed_banks(verbose: bool = True) -> Dict:
    """Ensure the SIB-regulated entities exist (idempotent). No financial data.

    Only the entity catalog (name/type/peer group) is seeded — a legitimate Gate-A
    registry. Financial records come exclusively from real sources (SIB API /
    SIMBAD / CSV upload); this never writes ``BankingData``.
    """
    from shared.database.session import SessionLocal

    session = SessionLocal()
    entities_created = 0
    entities_existing = 0
    try:
        for entity in BANKING_ENTITIES:
            existing = session.query(Bank).filter(Bank.name == entity["name"]).first()
            if existing:
                entities_existing += 1
                continue
            session.add(Bank(
                name=entity["name"],
                bank_type=_map_entity_type(entity["type"]),
                peer_group=entity["tier"],
                total_assets=entity["asset_base"],
                is_active=True,
            ))
            entities_created += 1
        session.commit()

        result = {
            "entities_created": entities_created,
            "entities_existing": entities_existing,
            "total_entities": len(BANKING_ENTITIES),
            "records_created": 0,  # sealed: never seeds financial data
        }
        if verbose:
            logger.info("Catalog seed: %d created, %d existing (no financial data)",
                        entities_created, entities_existing)
            print(f"Catalog seed: {entities_created} created, {entities_existing} existing")
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
