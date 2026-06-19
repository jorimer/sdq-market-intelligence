"""Build (resumably) the Comtrade + WDI panel fixture for the Gate-E trade backtest.

Idempotent: re-run until every peer has trade. Keeps countries already present,
fetches only the missing ones, saves after each (survives the anonymous endpoint's
short-window 429 quota). WDI is fetched once. Real public data only.

    python scripts/build_comtrade_fixture.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.trade_intel.validation.peers import VALIDATION_PEERS  # noqa: E402
from shared.data import comtrade_client as cc  # noqa: E402

YEARS = list(range(2009, 2024))  # 2009–2023
OUT = Path("shared/data/fixtures/comtrade_panel.json")


def main() -> None:
    ds = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    ds.setdefault("trade", {})
    trade = ds["trade"]

    if not ds.get("wdi"):
        print("· WDI (World Bank)…", flush=True)
        ds["wdi"] = cc.fetch_wdi(VALIDATION_PEERS)

    for iso2, info in VALIDATION_PEERS.items():
        if iso2 in trade:
            continue
        print(f"· comercio {iso2}…", end=" ", flush=True)
        try:
            country = cc.fetch_country_trade(info["m49"], YEARS)
        except Exception as e:  # noqa: BLE001 — resumable: log and move on
            print(f"FALLÓ ({type(e).__name__})", flush=True)
            continue
        if country:
            trade[iso2] = country
            yrs = sorted(country)
            print(f"ok {yrs[0]}-{yrs[-1]} ({len(yrs)} años)", flush=True)
        else:
            print("vacío", flush=True)
        ds["meta"] = {
            "source": cc.SOURCE, "license": cc.LICENSE,
            "years": [YEARS[0], YEARS[-1]], "n_peers": len(VALIDATION_PEERS),
            "countries_with_trade": sorted(trade.keys()),
        }
        OUT.write_text(json.dumps(ds, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(3.0)

    missing = [c for c in VALIDATION_PEERS if c not in trade]
    print(f"\nDONE — trade: {len(trade)}/{len(VALIDATION_PEERS)}; missing: {missing}", flush=True)


if __name__ == "__main__":
    main()
