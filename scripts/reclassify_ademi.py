"""One-off (rerunnable): reclassify Banco Ademi to banca_multiple + rename + rescore.

ADEMI has been BANCA MÚLTIPLE since 2013 (was a microfinance NGO before). The 2026-06-14
audit found prod had it as banco_ahorro_credito — inflating the ahorro y crédito aggregate
(~+34%), understating banca múltiple, and scoring it with the wrong weight profile/peers.
The asset values are correct (match SIMBAD ~26.6B); only the type/name are wrong.

Run locally against the prod DB (no external API). Default dry-run; --commit to apply.

    DATABASE_URL="<prod>" python scripts/reclassify_ademi.py
    DATABASE_URL="<prod>" python scripts/reclassify_ademi.py --commit
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.database.session import SessionLocal  # noqa: E402
from shared.auth.models import User, UserRole  # noqa: E402
from modules.banking_score.models.models import Bank, BankingData, BankType  # noqa: E402
from modules.banking_score.scoring.batch import _upsert_rating  # noqa: E402
from modules.banking_score.scoring.engine import run_scoring  # noqa: E402

NEW_NAME = "Banco Múltiple Ademi"
NEW_TYPE = BankType.banca_multiple


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually mutate prod (default dry-run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        bank = (db.query(Bank).filter(Bank.sib_code == "ADM").first()
                or db.query(Bank).filter(Bank.name.ilike("%ademi%")).first())
        if not bank:
            print("ADEMI no encontrado en prod.")
            return 1
        periods = db.query(BankingData).filter(BankingData.bank_id == bank.id).all()
        print(f"ADEMI: '{bank.name}' [{bank.bank_type.value}] · {len(periods)} períodos de datos")

        if not args.commit:
            print(f"[DRY-RUN] cambiaría → '{NEW_NAME}' [{NEW_TYPE.value}] y recalcularía {len(periods)} ratings.")
            print("[DRY-RUN] sin cambios. Re-correr con --commit.")
            return 0

        admin = db.query(User).filter(User.role == UserRole.admin).first()
        created_by = admin.id if admin else None

        bank.name = NEW_NAME
        bank.bank_type = NEW_TYPE
        db.flush()
        scored = 0
        for rec in sorted(periods, key=lambda r: r.period_end):
            result = run_scoring(rec, entity_type=NEW_TYPE.value)
            _upsert_rating(db, bank.id, rec.period_end, result, created_by)
            scored += 1
        db.commit()
        print(f"✓ committed: '{NEW_NAME}' [{NEW_TYPE.value}] · {scored} ratings recalculados (perfil banca múltiple)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
