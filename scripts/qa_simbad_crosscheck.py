"""QA: cross-check our banking_data against SIMBAD (the SB's public Superset).

SIMBAD exposes the same SIB data we ingest, monthly + public. Comparing per-entity-type
totals catches double-counting / period mis-sealing / classification drift that the
2026-06-14 audit found (cambiarias were ~6× inflated). Read-only; safe against prod.

Usage (prod):
    DATABASE_URL="$(railway variables --service Postgres --kv | grep ^DATABASE_PUBLIC_URL= | cut -d= -f2-)" \
        python scripts/qa_simbad_crosscheck.py --year 2025 --month 12

Exit code is non-zero if any type is off by more than the tolerance — so it can gate CI
or a post-sync sensor. Per-type ratio ≈ 1.0 means our totals match the source.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from shared.data.simbad_client import _post_chart_data, DATASET_BALANCE  # noqa: E402
from shared.database.session import engine  # noqa: E402

# prod bank_type → (SIMBAD TIPO_DE_ENTIDAD, SISTEMA)
TYPE_MAP = {
    "banca_multiple": ("BANCOS MÚLTIPLES", "FINANCIERO"),
    "banco_ahorro_credito": ("BANCOS DE AHORRO Y CRÉDITO", "FINANCIERO"),
    "aap": ("ASOCIACIONES DE AHORROS Y PRÉSTAMOS", "FINANCIERO"),
    "corporacion_credito": ("CORPORACIONES DE CRÉDITO", "FINANCIERO"),
}
TOLERANCE = 0.05  # ±5% — timing/revision noise; beyond this = a real discrepancy


def simbad_type_total(tipo: str, sistema: str, year: int, month: int) -> float:
    rows = _post_chart_data(
        DATASET_BALANCE, ["MONTO"],
        [
            {"col": "Año", "op": "==", "val": year},
            {"col": "Mes", "op": "==", "val": month},
            {"col": "SISTEMA", "op": "==", "val": sistema},
            {"col": "TIPO_DE_ENTIDAD", "op": "==", "val": tipo},
            {"col": "ENTIDAD", "op": "==", "val": "TODOS"},
            {"col": "CONCEPTO_NIVEL_1", "op": "==", "val": "Activos"},
            {"col": "CONCEPTO_NIVEL_2", "op": "==", "val": "TODOS"},
            {"col": "CONCEPTO_NIVEL_3", "op": "==", "val": "TODOS"},
        ], row_limit=10,
    )
    return float(rows[0]["MONTO"]) if rows and rows[0].get("MONTO") else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--month", type=int, default=12, help="closing month (3/6/9/12)")
    args = ap.parse_args()
    period_end = f"{args.year}-{args.month:02d}-{ {3: 31, 6: 30, 9: 30, 12: 31}[args.month] }"

    cambiaria_simbad = sum(
        simbad_type_total(t, "CAMBIARIO", args.year, args.month)
        for t in ("AGENTES DE CAMBIO", "AGENTES DE REMESAS Y CAMBIO")
    )

    print(f"QA cross-check prod↔SIMBAD · período {period_end}\n")
    print(f"{'tipo':24} {'SIMBAD':>20} {'prod':>20} {'ratio':>7}  veredicto")
    bad = []
    with engine.connect() as conn:
        def prod_sum(bt: str) -> float:
            r = conn.execute(text(
                "SELECT COALESCE(SUM(bd.activos_totales),0) FROM banks b "
                "JOIN banking_data bd ON bd.bank_id=b.id "
                "WHERE bd.period_end=:pe AND b.bank_type=:bt AND bd.activos_totales IS NOT NULL"
            ), {"pe": period_end, "bt": bt}).scalar()
            return float(r or 0)

        checks = [(bt, simbad_type_total(s, sys_, args.year, args.month)) for bt, (s, sys_) in TYPE_MAP.items()]
        checks.append(("cambiaria", cambiaria_simbad))
        for bt, simbad_total in checks:
            prod = prod_sum(bt)
            ratio = (prod / simbad_total) if simbad_total else 0.0
            ok = abs(ratio - 1.0) <= TOLERANCE
            verdict = "OK" if ok else ("DOBLE-CONTEO?" if ratio > 1.5 else "REVISAR")
            if not ok:
                bad.append(bt)
            print(f"{bt:24} {simbad_total:>20,.0f} {prod:>20,.0f} {ratio:>7.2f}  {verdict}")

    if bad:
        print(f"\n✗ FUERA DE TOLERANCIA (±{TOLERANCE:.0%}): {', '.join(bad)}")
        return 1
    print(f"\n✓ Todos los tipos dentro de ±{TOLERANCE:.0%} de SIMBAD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
