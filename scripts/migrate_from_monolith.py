#!/usr/bin/env python3
"""Migrate data from the Financial Analysis Agent monolith to SDQ Market Intelligence.

Usage:
    python scripts/migrate_from_monolith.py --source /path/to/monolith.db
    python scripts/migrate_from_monolith.py --source /path/to/monolith.db --verify
    python scripts/migrate_from_monolith.py --verify  # verify existing target DB

Monolith tables expected:
    companies          → banks
    sdq_banking_data   → banking_data
    sdq_rating_results → rating_results
    sdq_rating_actions → rating_actions
    sdq_reports        → reports

Also copies:
    - Report PDF files  (data/reports/)
    - XGBoost model     (data/models/*.pkl)
"""
import argparse
import logging
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("migrate")

# ─── Configuration ──────────────────────────────────────────────

TARGET_DB_PATH = PROJECT_ROOT / "data" / "sdq_market_intel.db"
REPORTS_DIR = PROJECT_ROOT / "data" / "reports"
MODELS_DIR = PROJECT_ROOT / "data" / "models"

# Mapping from monolith → new schema
BANK_TYPE_MAP = {
    "banca_multiple": "banca_multiple",
    "banco_multiple": "banca_multiple",
    "aap": "aap",
    "asociacion": "aap",
    "banco_ahorro_credito": "banco_ahorro_credito",
    "ahorro_credito": "banco_ahorro_credito",
}

BANKING_DATA_COLUMNS = [
    "patrimonio_tecnico", "apr", "capital_primario", "exposicion_total",
    "capital_tier1", "contingentes", "riesgo_mercado", "provisiones",
    "cartera_vencida_90d", "activos_totales", "cartera_bruta",
    "cartera_categoria_a", "cartera_total", "suma_top10",
    "hhi_sectorial_raw", "castigos", "exposicion_re", "cartera_a_prev",
    "utilidad_neta", "activos_promedio", "patrimonio_promedio",
    "ingresos_financieros", "gastos_financieros", "activos_productivos_avg",
    "gastos_operacionales", "ingresos_operacionales", "caja_valores",
    "pasivos_cp", "cartera_neta", "depositos_totales",
    "activos_liquidos", "pasivos_exigibles", "hhi_ingresos_raw",
]


# ─── Helpers ────────────────────────────────────────────────────

def dict_factory(cursor, row):
    """Convert sqlite3 rows to dicts."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with dict rows."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = dict_factory
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) as c FROM [{table}]").fetchone()["c"]


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ─── Migration Steps ───────────────────────────────────────────

def migrate_banks(src: sqlite3.Connection, tgt: sqlite3.Connection) -> dict:
    """Step 1: companies WHERE sector='banking' → banks."""
    id_map = {}  # old_id → new_id

    if not table_exists(src, "companies"):
        logger.warning("No 'companies' table found in source DB. Skipping banks migration.")
        return id_map

    rows = src.execute(
        "SELECT * FROM companies WHERE sector = 'banking' OR sector IS NULL"
    ).fetchall()

    for row in rows:
        old_id = row.get("id") or row.get("company_id")
        new_id = gen_uuid()
        id_map[str(old_id)] = new_id

        name = row.get("name") or row.get("company_name", "Unknown")
        sib_code = row.get("sib_code", "")
        bank_type_raw = (row.get("bank_type") or row.get("entity_type") or "banca_multiple").lower()
        bank_type = BANK_TYPE_MAP.get(bank_type_raw, "banca_multiple")

        # Check if bank already exists by name
        existing = tgt.execute("SELECT id FROM banks WHERE name = ?", (name,)).fetchone()
        if existing:
            id_map[str(old_id)] = existing["id"]
            logger.info("  Bank '%s' already exists, mapping to %s", name, existing["id"])
            continue

        tgt.execute(
            """INSERT INTO banks (id, name, sib_code, bank_type, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (new_id, name, sib_code, bank_type, datetime.utcnow(), datetime.utcnow()),
        )
        logger.info("  Migrated bank: %s → %s", name, new_id)

    tgt.commit()
    logger.info("Banks migrated: %d", len(id_map))
    return id_map


def migrate_banking_data(
    src: sqlite3.Connection, tgt: sqlite3.Connection, bank_id_map: dict
) -> int:
    """Step 2: sdq_banking_data → banking_data."""
    if not table_exists(src, "sdq_banking_data"):
        logger.warning("No 'sdq_banking_data' table in source. Skipping.")
        return 0

    rows = src.execute("SELECT * FROM sdq_banking_data").fetchall()
    migrated = 0

    for row in rows:
        old_bank_id = str(row.get("bank_id") or row.get("company_id", ""))
        new_bank_id = bank_id_map.get(old_bank_id)
        if not new_bank_id:
            logger.warning("  Skipping banking_data row: unmapped bank_id=%s", old_bank_id)
            continue

        period_end = row.get("period_end")
        if not period_end:
            continue

        # Check for existing record
        existing = tgt.execute(
            "SELECT id FROM banking_data WHERE bank_id = ? AND period_end = ?",
            (new_bank_id, period_end),
        ).fetchone()
        if existing:
            continue

        new_id = gen_uuid()
        cols = ["id", "bank_id", "period_end", "source", "created_at", "updated_at"]
        vals = [new_id, new_bank_id, period_end, "manual", datetime.utcnow(), datetime.utcnow()]

        for col in BANKING_DATA_COLUMNS:
            cols.append(col)
            vals.append(row.get(col))

        placeholders = ", ".join(["?"] * len(cols))
        col_str = ", ".join(cols)
        tgt.execute(f"INSERT INTO banking_data ({col_str}) VALUES ({placeholders})", vals)
        migrated += 1

    tgt.commit()
    logger.info("Banking data records migrated: %d", migrated)
    return migrated


def migrate_rating_results(
    src: sqlite3.Connection, tgt: sqlite3.Connection, bank_id_map: dict
) -> int:
    """Step 3: sdq_rating_results → rating_results."""
    if not table_exists(src, "sdq_rating_results"):
        logger.warning("No 'sdq_rating_results' table in source. Skipping.")
        return 0

    rows = src.execute("SELECT * FROM sdq_rating_results").fetchall()
    migrated = 0

    for row in rows:
        old_bank_id = str(row.get("bank_id", ""))
        new_bank_id = bank_id_map.get(old_bank_id)
        if not new_bank_id:
            continue

        period_end = row.get("period_end")
        model_type = row.get("model_type", "deterministic")

        existing = tgt.execute(
            "SELECT id FROM rating_results WHERE bank_id = ? AND period_end = ? AND model_type = ?",
            (new_bank_id, period_end, model_type),
        ).fetchone()
        if existing:
            continue

        new_id = gen_uuid()
        tgt.execute(
            """INSERT INTO rating_results
               (id, bank_id, period_end, overall_score, rating_tier,
                solidez_score, calidad_score, eficiencia_score,
                liquidez_score, diversificacion_score,
                indicator_details, model_type, model_version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id, new_bank_id, period_end,
                row.get("overall_score", 0), row.get("rating_tier", "N/A"),
                row.get("solidez_score"), row.get("calidad_score"),
                row.get("eficiencia_score"), row.get("liquidez_score"),
                row.get("diversificacion_score"),
                row.get("indicator_details"),
                model_type, row.get("model_version", "1.0"),
                datetime.utcnow(), datetime.utcnow(),
            ),
        )
        migrated += 1

    tgt.commit()
    logger.info("Rating results migrated: %d", migrated)
    return migrated


def migrate_rating_actions(
    src: sqlite3.Connection, tgt: sqlite3.Connection, bank_id_map: dict
) -> int:
    """Step 4: sdq_rating_actions → rating_actions."""
    if not table_exists(src, "sdq_rating_actions"):
        logger.warning("No 'sdq_rating_actions' table in source. Skipping.")
        return 0

    rows = src.execute("SELECT * FROM sdq_rating_actions").fetchall()
    migrated = 0

    for row in rows:
        old_bank_id = str(row.get("bank_id", ""))
        new_bank_id = bank_id_map.get(old_bank_id)
        if not new_bank_id:
            continue

        new_id = gen_uuid()
        tgt.execute(
            """INSERT INTO rating_actions
               (id, bank_id, period_end, action_type,
                previous_score, previous_tier, new_score, new_tier,
                score_delta, tier_levels_changed, outlook,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id, new_bank_id, row.get("period_end"),
                row.get("action_type", "confirmacion"),
                row.get("previous_score"), row.get("previous_tier"),
                row.get("new_score", 0), row.get("new_tier", "N/A"),
                row.get("score_delta"), row.get("tier_levels_changed", 0),
                row.get("outlook", "estable"),
                datetime.utcnow(), datetime.utcnow(),
            ),
        )
        migrated += 1

    tgt.commit()
    logger.info("Rating actions migrated: %d", migrated)
    return migrated


def migrate_reports(
    src: sqlite3.Connection, tgt: sqlite3.Connection, bank_id_map: dict
) -> int:
    """Step 5: sdq_reports → reports."""
    if not table_exists(src, "sdq_reports"):
        logger.warning("No 'sdq_reports' table in source. Skipping.")
        return 0

    rows = src.execute("SELECT * FROM sdq_reports").fetchall()
    migrated = 0

    for row in rows:
        old_bank_id = str(row.get("bank_id", ""))
        new_bank_id = bank_id_map.get(old_bank_id)
        if not new_bank_id:
            continue

        new_id = gen_uuid()
        tgt.execute(
            """INSERT INTO reports
               (id, bank_id, period_end, report_type, file_path,
                file_size, narrative_model, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id, new_bank_id, row.get("period_end"),
                row.get("report_type", "full_rating"),
                row.get("file_path"),
                row.get("file_size"),
                row.get("narrative_model"),
                row.get("status", "completed"),
                datetime.utcnow(), datetime.utcnow(),
            ),
        )
        migrated += 1

    tgt.commit()
    logger.info("Reports migrated: %d", migrated)
    return migrated


def copy_report_pdfs(source_dir: Path):
    """Step 6: Copy report PDF files from monolith data directory."""
    src_reports = source_dir / "data" / "reports"
    if not src_reports.exists():
        logger.warning("No source reports directory found at %s", src_reports)
        return 0

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pdf in src_reports.glob("*.pdf"):
        dest = REPORTS_DIR / pdf.name
        if not dest.exists():
            shutil.copy2(pdf, dest)
            copied += 1

    logger.info("PDF files copied: %d", copied)
    return copied


def copy_model_files(source_dir: Path):
    """Step 7: Copy XGBoost .pkl model files."""
    src_models = source_dir / "data" / "models"
    if not src_models.exists():
        logger.warning("No source models directory found at %s", src_models)
        return 0

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pkl in src_models.glob("*.pkl"):
        dest = MODELS_DIR / pkl.name
        if not dest.exists():
            shutil.copy2(pkl, dest)
            copied += 1

    logger.info("Model files copied: %d", copied)
    return copied


# ─── Verification ──────────────────────────────────────────────

def verify_integrity(tgt_path: str = None):
    """Step 8: Verify integrity of migrated data."""
    db_path = tgt_path or str(TARGET_DB_PATH)
    if not os.path.exists(db_path):
        logger.error("Target database not found: %s", db_path)
        return False

    tgt = connect(db_path)
    ok = True

    # Check tables exist
    for table in ["banks", "banking_data", "rating_results", "rating_actions", "reports"]:
        if not table_exists(tgt, table):
            logger.error("Missing table: %s", table)
            ok = False
            continue

        count = row_count(tgt, table)
        logger.info("  %-20s: %d rows", table, count)

    # Check no null FKs in banking_data
    if table_exists(tgt, "banking_data"):
        orphans = tgt.execute(
            """SELECT count(*) as c FROM banking_data bd
               WHERE NOT EXISTS (SELECT 1 FROM banks b WHERE b.id = bd.bank_id)"""
        ).fetchone()["c"]
        if orphans > 0:
            logger.error("  banking_data has %d orphan rows (missing bank_id FK)", orphans)
            ok = False
        else:
            logger.info("  banking_data FK integrity: OK")

    # Check no null FKs in rating_results
    if table_exists(tgt, "rating_results"):
        orphans = tgt.execute(
            """SELECT count(*) as c FROM rating_results rr
               WHERE NOT EXISTS (SELECT 1 FROM banks b WHERE b.id = rr.bank_id)"""
        ).fetchone()["c"]
        if orphans > 0:
            logger.error("  rating_results has %d orphan rows (missing bank_id FK)", orphans)
            ok = False
        else:
            logger.info("  rating_results FK integrity: OK")

    # Check rating_results scores in range
    if table_exists(tgt, "rating_results"):
        bad_scores = tgt.execute(
            "SELECT count(*) as c FROM rating_results WHERE overall_score < 0 OR overall_score > 100"
        ).fetchone()["c"]
        if bad_scores > 0:
            logger.warning("  rating_results has %d scores out of [0, 100] range", bad_scores)
        else:
            logger.info("  rating_results scores: all in [0, 100]")

    tgt.close()

    if ok:
        logger.info("Verification PASSED")
    else:
        logger.error("Verification FAILED — see errors above")

    return ok


# ─── Main ──────────────────────────────────────────────────────

def run_migration(source_db: str):
    """Execute the full migration pipeline."""
    if not os.path.exists(source_db):
        logger.error("Source database not found: %s", source_db)
        sys.exit(1)

    if not os.path.exists(TARGET_DB_PATH):
        logger.error(
            "Target database not found: %s. Run alembic upgrade head first.",
            TARGET_DB_PATH,
        )
        sys.exit(1)

    source_dir = Path(source_db).parent.parent  # e.g., /path/to/monolith/

    src = connect(source_db)
    tgt = connect(str(TARGET_DB_PATH))

    logger.info("=" * 60)
    logger.info("SDQ Market Intelligence — Monolith Migration")
    logger.info("  Source: %s", source_db)
    logger.info("  Target: %s", TARGET_DB_PATH)
    logger.info("=" * 60)

    # Step 1: Banks
    logger.info("\n[1/8] Migrating banks...")
    bank_id_map = migrate_banks(src, tgt)

    # Step 2: Banking data
    logger.info("\n[2/8] Migrating banking data...")
    migrate_banking_data(src, tgt, bank_id_map)

    # Step 3: Rating results
    logger.info("\n[3/8] Migrating rating results...")
    migrate_rating_results(src, tgt, bank_id_map)

    # Step 4: Rating actions
    logger.info("\n[4/8] Migrating rating actions...")
    migrate_rating_actions(src, tgt, bank_id_map)

    # Step 5: Reports
    logger.info("\n[5/8] Migrating reports...")
    migrate_reports(src, tgt, bank_id_map)

    # Step 6: Copy PDFs
    logger.info("\n[6/8] Copying report PDFs...")
    copy_report_pdfs(source_dir)

    # Step 7: Copy model files
    logger.info("\n[7/8] Copying model files...")
    copy_model_files(source_dir)

    src.close()
    tgt.close()

    # Step 8: Verify
    logger.info("\n[8/8] Verifying integrity...")
    verify_integrity()

    logger.info("\nMigration complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate data from Financial Analysis Agent monolith to SDQ Market Intelligence."
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Path to monolith SQLite database (e.g., /path/to/monolith/data/financial_analyst.db)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only run verification on existing target DB",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Override target DB path (default: data/sdq_market_intel.db)",
    )

    args = parser.parse_args()

    if args.verify:
        target = args.target or str(TARGET_DB_PATH)
        ok = verify_integrity(target)
        sys.exit(0 if ok else 1)

    if not args.source:
        parser.error("--source is required for migration (or use --verify)")

    run_migration(args.source)


if __name__ == "__main__":
    main()
