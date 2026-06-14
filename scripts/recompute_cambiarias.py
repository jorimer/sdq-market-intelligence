"""One-off (rerunnable): REPLACE all cambiaria data from SIMBAD and rescore.

Fixes the 2026-06-14 audit's inflated cambiaria balances. Rather than rely on the
partial upsert (which leaves stale fields / stale periods — reviewer S1), it deletes
the cambiaria rows and re-ingests from SIMBAD (the clean source, full history, public),
then rescores. Uses only the public SIMBAD API → safe to run locally against the prod DB.

    DATABASE_URL="<prod public url>" python scripts/recompute_cambiarias.py --dry-run
    DATABASE_URL="<prod public url>" python scripts/recompute_cambiarias.py --commit
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.database.session import SessionLocal  # noqa: E402
from shared.auth.models import User, UserRole  # noqa: E402
from modules.banking_score.models.models import (  # noqa: E402
    Bank, BankingData, BankType, DataSource, PeriodType, RatingAction, RatingResult,
)
from modules.banking_score.sib_sync import _match_or_create_bank  # noqa: E402
from modules.banking_score.scoring.batch import _upsert_rating  # noqa: E402
from modules.banking_score.scoring.engine import run_scoring  # noqa: E402
from modules.banking_score.external.simbad_client import extract_cambiaria_bulk  # noqa: E402

_FIELDS = ("activos_totales", "patrimonio_tecnico", "pasivos_exigibles",
           "activos_liquidos", "cartera_bruta", "utilidad_neta")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually mutate prod (default is dry-run)")
    ap.add_argument("--period-start", default="2021-01")
    args = ap.parse_args()
    dry = not args.commit

    db = SessionLocal()
    try:
        camb_ids = [b.id for b in db.query(Bank.id).filter(Bank.bank_type == BankType.cambiaria)]
        bd_before = db.query(BankingData).filter(BankingData.bank_id.in_(camb_ids)).count() if camb_ids else 0
        rr_before = db.query(RatingResult).filter(RatingResult.bank_id.in_(camb_ids)).count() if camb_ids else 0
        print(f"prod cambiarias: {len(camb_ids)} entidades · {bd_before} banking_data · {rr_before} ratings")

        print("Extrayendo cambiarias de SIMBAD…")
        simbad = extract_cambiaria_bulk(period_start=args.period_start)
        meta = simbad.pop("_entity_meta", {})
        n_periods = sum(len(v) for v in simbad.values())
        print(f"SIMBAD: {len(simbad)} entidades · {n_periods} (entidad×cierre)")

        if dry:
            # Preview: how many entities are new, and a sample value vs current.
            new_ents = [e for e in simbad if not any(
                b.sib_code == e or b.name == meta.get(e, {}).get("nombre")
                for b in db.query(Bank).filter(Bank.bank_type == BankType.cambiaria))]
            print(f"[DRY-RUN] borraría {bd_before} banking_data + {rr_before} ratings de cambiarias;")
            print(f"[DRY-RUN] escribiría {n_periods} filas (source=sib_simbad); ~{len(new_ents)} entidades nuevas.")
            print("[DRY-RUN] sin cambios. Re-correr con --commit para aplicar.")
            return 0

        admin = db.query(User).filter(User.role == UserRole.admin).first()
        created_by = admin.id if admin else None

        # 1) Clean replace: drop cambiaria actions → ratings → banking_data.
        if camb_ids:
            db.query(RatingAction).filter(RatingAction.bank_id.in_(camb_ids)).delete(synchronize_session=False)
            db.query(RatingResult).filter(RatingResult.bank_id.in_(camb_ids)).delete(synchronize_session=False)
            db.query(BankingData).filter(BankingData.bank_id.in_(camb_ids)).delete(synchronize_session=False)
            db.flush()

        # 2) Re-ingest from SIMBAD + rescore.
        written = scored = 0
        for short_name, periods in simbad.items():
            bank, _ = _match_or_create_bank(db, short_name, extra_codes=meta)
            if not bank:
                continue
            for rec in sorted(periods, key=lambda r: r["period_end"]):
                pe = rec["period_end"]
                row = BankingData(bank_id=bank.id, period_end=pe,
                                  period_type=PeriodType.quarterly, source=DataSource.sib_simbad)
                for f in _FIELDS:
                    if rec.get(f) is not None:
                        setattr(row, f, rec[f])
                db.add(row)
                db.flush()
                written += 1
                result = run_scoring(row, entity_type="cambiaria")
                _upsert_rating(db, bank.id, pe, result, created_by)
                scored += 1
        db.commit()
        print(f"✓ committed: {written} banking_data (sib_simbad) · {scored} ratings recalculados")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
