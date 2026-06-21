#!/usr/bin/env python3
"""Backfill guiado del registro de deals (HistoricalDeal).

Carga las 4 señales de analista (promoter/financial/market/regulatory) y confirma
outcome/etapa deal por deal. Las señales NO existen en data pública: salen del juicio
SDQ. Este script es la vía para poblar las ~20 oportunidades reales hacia las 200.

USO (desde la raíz del repo):
  # 1) Exportar las que faltan a un CSV editable
  python scripts/backfill_deal_scores.py export-csv backfill.csv

  # 2) Llenar backfill.csv en Excel (columnas *_track_record, *_quality, etc.)
  #    Escala 0-100. closed_successfully: 1 / 0 / (vacío=abierto).

  # 3) Cargar de vuelta
  python scripts/backfill_deal_scores.py import-csv backfill.csv

  # Alternativa: deal por deal en consola
  python scripts/backfill_deal_scores.py interactive

Idempotente: import-csv solo escribe columnas con valor; deja el resto intacto.
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.database.session import SessionLocal  # noqa: E402
from modules.deal_scoring.models.models import (
    DealStage,
    DealType,
    HistoricalDeal,
    LabelConfidence,
    Sector,
)

SCORE_COLS = ["promoter_track_record", "financial_quality",
              "market_validation", "regulatory_readiness"]
EDITABLE = (["deal_size_usd", "equity_required_pct", "deal_stage",
             "days_since_first_contact"] + SCORE_COLS +
            ["closed_successfully", "outcome_date", "label_confidence", "note"])
CSV_COLS = ["deal_name", "deal_type", "sector", "country"] + EDITABLE


def needs_backfill(d: HistoricalDeal) -> bool:
    return (any(getattr(d, c) is None for c in SCORE_COLS)
            or d.closed_successfully is None)


def _val(x):
    return "" if x is None else (x.value if hasattr(x, "value") else x)


def export_csv(path: str) -> int:
    db = SessionLocal()
    try:
        deals = [d for d in db.query(HistoricalDeal).order_by(
            HistoricalDeal.label_confidence, HistoricalDeal.deal_name).all()
            if needs_backfill(d)]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS)
            w.writeheader()
            for d in deals:
                w.writerow({c: _val(getattr(d, c)) for c in CSV_COLS})
        print(f"Exportadas {len(deals)} oportunidades a {path}")
        print(f"Editá las columnas {SCORE_COLS} (0-100) y closed_successfully (1/0).")
        return len(deals)
    finally:
        db.close()


def _parse_bool(s):
    s = str(s).strip().lower()
    if s in ("1", "true", "sí", "si", "yes", "y", "cerrado"):
        return True
    if s in ("0", "false", "no", "n", "perdido"):
        return False
    return None


def _parse_int(s, lo=0, hi=100):
    """Entero acotado a [lo, hi]. Default 0-100 (escala de scores de analista)."""
    s = str(s).strip()
    if not s:
        return None
    v = int(float(s))
    if not lo <= v <= hi:
        raise ValueError(f"valor fuera de {lo}-{hi}: {v}")
    return v


def _parse_date(s):
    s = str(s).strip()
    if not s:
        return None
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def import_csv(path: str) -> int:
    db = SessionLocal()
    updated = 0
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row["deal_name"].strip()
                d = db.query(HistoricalDeal).filter_by(deal_name=name).one_or_none()
                if d is None:
                    print(f"  ⚠ no existe en DB, salto: {name}")
                    continue
                changed = False
                for c in SCORE_COLS:
                    v = _parse_int(row.get(c, ""))  # scores 0-100
                    if v is not None:
                        setattr(d, c, v)
                        changed = True
                days = _parse_int(row.get("days_since_first_contact", ""), hi=100_000)
                if days is not None:
                    d.days_since_first_contact = days
                    changed = True
                for c, ttype in (("deal_stage", DealStage),
                                 ("label_confidence", LabelConfidence)):
                    raw = row.get(c, "").strip()
                    if raw:
                        setattr(d, c, ttype(raw))
                        changed = True
                if row.get("deal_size_usd", "").strip():
                    d.deal_size_usd = float(row["deal_size_usd"])
                    changed = True
                if row.get("equity_required_pct", "").strip():
                    d.equity_required_pct = float(row["equity_required_pct"])
                    changed = True
                b = _parse_bool(row.get("closed_successfully", ""))
                if b is not None:
                    d.closed_successfully = b
                    changed = True
                od = _parse_date(row.get("outcome_date", ""))
                if od is not None:
                    d.outcome_date = od
                    changed = True
                if row.get("note", "").strip():
                    d.note = row["note"].strip()
                    changed = True
                if changed:
                    updated += 1
        db.commit()
        print(f"Actualizadas {updated} oportunidades desde {path}")
        return updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def interactive() -> int:
    db = SessionLocal()
    updated = 0
    try:
        deals = [d for d in db.query(HistoricalDeal).order_by(
            HistoricalDeal.deal_name).all() if needs_backfill(d)]
        print(f"{len(deals)} oportunidades por completar. Enter = dejar igual, 'q' = salir.\n")
        for d in deals:
            print(f"── {d.deal_name}  [{_val(d.deal_type)}/{_val(d.sector)}/{d.country}]"
                  f"  {d.note or ''}")
            try:
                for c in SCORE_COLS:
                    cur = getattr(d, c)
                    raw = input(f"   {c} (0-100) [{cur}]: ").strip()
                    if raw.lower() == "q":
                        raise KeyboardInterrupt
                    if raw:
                        setattr(d, c, _parse_int(raw))
                raw = input(f"   closed_successfully 1/0 [{_val(d.closed_successfully)}]: ").strip()
                if raw.lower() == "q":
                    raise KeyboardInterrupt
                b = _parse_bool(raw)
                if b is not None:
                    d.closed_successfully = b
                updated += 1
            except KeyboardInterrupt:
                break
        db.commit()
        print(f"\nActualizadas {updated} oportunidades.")
        return updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="Backfill del registro de deals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("export-csv")
    p1.add_argument("path")
    p2 = sub.add_parser("import-csv")
    p2.add_argument("path")
    sub.add_parser("interactive")
    args = ap.parse_args()
    if args.cmd == "export-csv":
        export_csv(args.path)
    elif args.cmd == "import-csv":
        import_csv(args.path)
    else:
        interactive()


if __name__ == "__main__":
    sys.exit(main())
