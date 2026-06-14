"""QA per-entity: cross-check EVERY supervised entity's assets in prod vs SIMBAD.

Aggregate ratios can hide per-entity errors that offset (audit 2026-06-14: Banesco
deflated 0.04×, Bonao ~empty, Bonanza inflated 8.3× — yet the type aggregates passed).
This checks each entity against SIMBAD via an EXPLICIT, name-verified map (SIMBAD short
codes don't match our names cleanly, so fuzzy matching is unreliable). Cambiarias match
by sib_code (= the SIMBAD ENTIDAD). Read-only; safe against prod.

    DATABASE_URL="<prod>" python scripts/qa_simbad_per_entity.py --year 2025 --month 12
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from shared.database.session import engine  # noqa: E402

TOL = 0.10  # ±10% per entity (timing/revision noise); beyond = a real discrepancy

# SIMBAD ENTIDAD code → prod bank name (verified by value correspondence 2026-06-14).
SIMBAD_TO_PROD = {
    # Banca múltiple
    "BANRESERVAS": "Banco de Reservas de la República Dominicana",
    "POPULAR": "Banco Popular Dominicano", "BHD": "Banco Múltiple BHD",
    "SANTA CRUZ": "Banco Múltiple Santa Cruz", "SCOTIABANK": "Scotiabank República Dominicana",
    "PROMERICA": "Banco Múltiple Promérica de la República Dominicana",
    "CARIBE": "Banco Múltiple Caribe Internacional", "BANESCO": "Banesco Banco Múltiple",
    "BDI": "Banco Múltiple BDI", "BLH": "Banco Múltiple López de Haro",
    "CITIBANK": "Citibank N.A. Sucursal República Dominicana", "VIMENCA": "Banco Múltiple Vimenca",
    "ADEMI": "Banco Múltiple Ademi", "LAFISE": "Banco Múltiple Lafise",
    "QIK BANCO DIGITAL": "Qik Banco Digital Dominicano", "JMMB": "JMMB Bank Banco Múltiple",
    # AAyP
    "APAP": "Asociación Popular de Ahorros y Préstamos", "CIBAO": "Asociación Cibao de Ahorros y Préstamos",
    "LA NACIONAL": "Asociación La Nacional de Ahorros y Préstamos",
    "ALAVER": "Asociación La Vega Real de Ahorros y Préstamos",
    "DUARTE": "Asociación Duarte de Ahorros y Préstamos", "MOCANA": "Asociación Mocana de Ahorros y Préstamos",
    "BONAO": "Asociación Bonao de Ahorros y Préstamos", "ROMANA": "Asociación de Ahorros y Préstamos Romana",
    "PERAVIA": "Asociación Peravia de Ahorros y Préstamos", "MAGUANA": "Asociación Maguana de Ahorros y Préstamos",
    # Ahorro y crédito
    "BANFONDESA": "Banco de Ahorro y Crédito FONDESA", "MOTOR CREDITO": "Motor Crédito Banco de Ahorro y Crédito",
    "ADOPEM": "Banco ADOPEM de Ahorro y Crédito", "UNION": "Banco de Ahorro y Crédito Unión",
    "BANCO BACC": "Banco de Ahorro y Crédito del Caribe", "CONFISA": "Banco de Ahorro y Crédito Confisa",
    "ATLANTICO": "Banco de Ahorro y Crédito Atlántico", "FIHOGAR": "Banco de Ahorro y Crédito Fihogar",
    "BANCOTUI": "Banco de Ahorros y Créditos Bancotui",
    "LEASCONFISA": "Leasing Confisa Banco de Ahorro y Crédito",
    "GRUFICORP": "Banco de Ahorro y Crédito Gruficorp", "OPTIMA": "Banco de Ahorro y Crédito Óptima",
    "BONANZA": "Banco de Ahorro y Crédito Bonanza", "COFACI": "Banco de Ahorro y Crédito Cofaci",
    # Corp. crédito
    "NORPRESA": "Corporación de Crédito Nordestana de Préstamos",
    "MONUMENTAL": "Corporación de Crédito Monumental", "OFICORP": "Corporación de Crédito Oficorp",
}
_SYS = {"FINANCIERO": list(SIMBAD_TO_PROD), "CAMBIARIO": None}  # cambiarias handled by sib_code


def simbad_assets(sistema, year, month):
    qc = {"datasource": {"id": 35, "type": "table"}, "queries": [{"columns": ["ENTIDAD", "MONTO"], "filters": [
        {"col": "Año", "op": "==", "val": year}, {"col": "Mes", "op": "==", "val": month},
        {"col": "SISTEMA", "op": "==", "val": sistema},
        {"col": "CONCEPTO_NIVEL_1", "op": "==", "val": "Activos"},
        {"col": "CONCEPTO_NIVEL_2", "op": "==", "val": "TODOS"}, {"col": "CONCEPTO_NIVEL_3", "op": "==", "val": "TODOS"},
    ], "row_limit": 5000}], "result_format": "json", "result_type": "results"}
    r = urllib.request.Request("https://simbad.sb.gob.do/api/v1/chart/data", data=json.dumps(qc).encode(),
                               method="POST", headers={"Content-Type": "application/json"})
    return {x["ENTIDAD"]: (x["MONTO"] or 0) for x in json.loads(urllib.request.urlopen(r, timeout=60).read())["result"][0]["data"] if x["ENTIDAD"] != "TODOS"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--month", type=int, default=12)
    args = ap.parse_args()
    pe = f"{args.year}-{args.month:02d}-{ {3:31,6:30,9:30,12:31}[args.month] }"

    sim = {**simbad_assets("FINANCIERO", args.year, args.month), **simbad_assets("CAMBIARIO", args.year, args.month)}
    bad, missing, ok = [], [], 0
    with engine.connect() as conn:
        def prod_assets(name):
            return conn.execute(text("SELECT bd.activos_totales FROM banks b JOIN banking_data bd ON bd.bank_id=b.id "
                                     "WHERE b.name=:n AND bd.period_end=:pe"), {"n": name, "pe": pe}).scalar()
        # EIF: explicit map
        for code, name in SIMBAD_TO_PROD.items():
            sv = sim.get(code)
            if sv is None:
                continue
            pv = prod_assets(name)
            if pv is None:
                missing.append((code, name))
                continue
            ratio = float(pv) / sv if sv else 0
            if abs(ratio - 1.0) > TOL:
                bad.append((code, name, float(pv), sv, ratio))
            else:
                ok += 1
        # Cambiarias: match by sib_code (= SIMBAD ENTIDAD)
        cambs = conn.execute(text("SELECT b.sib_code, bd.activos_totales FROM banks b JOIN banking_data bd ON bd.bank_id=b.id "
                                  "WHERE b.bank_type='cambiaria' AND bd.period_end=:pe"), {"pe": pe}).fetchall()
        for code, pv in cambs:
            sv = sim.get(code)
            if sv is None or pv is None:
                continue
            ratio = float(pv) / sv if sv else 0
            if abs(ratio - 1.0) > TOL:
                bad.append((code, code, float(pv), sv, ratio))
            else:
                ok += 1

    print(f"QA por entidad · {pe} · tolerancia ±{TOL:.0%}\n")
    print(f"  OK (dentro de tolerancia): {ok}")
    if bad:
        print(f"  DISCREPANTES: {len(bad)}")
        for code, name, pv, sv, ratio in sorted(bad, key=lambda x: abs(x[4] - 1), reverse=True):
            print(f"    {code:16} {name[:34]:34} prod={pv:>16,.0f} SIMBAD={sv:>16,.0f} ratio={ratio:.2f}")
    if missing:
        print(f"  FALTANTES en prod: {len(missing)}")
        for code, name in missing:
            print(f"    {code:16} (esperado: {name})")
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
