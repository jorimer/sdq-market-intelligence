"""Post-deployment E2E smoke test (run as the Claude E2E user).

Exercises every delivered phase end-to-end through the real API:

  * Fase 0 — cimientos compartidos:
      - shared/indices + shared/doctrine vía IRMP /weights y POST /score
        (el motor genérico y la doctrina YAML se ejercitan de extremo a extremo).
      - shared/data vía macro-monitor /refresh (ingesta por conector con linaje).
  * Fase 1A — banking_score: /stats y /rankings responden.
  * Fase 1B — macro_political_risk: /snapshot (persistencia + evento), /latest, /history.
  * Fase 2 — macro_monitor: /refresh, /indicators, /snapshot, /signals.

Modes:
  * Si se define E2E_BASE_URL → httpx contra el despliegue real.
  * Si no → FastAPI TestClient in-process (local/CI).

    python scripts/e2e_smoke.py

Requiere que el usuario E2E exista (scripts/seed_e2e_user.py) en la DB destino.
Sale con código 1 si cualquier verificación falla.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

E2E_EMAIL = "claude@sdqconsulting.com.do"
E2E_PASSWORD = "Claude1234"

_PASS, _FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (_PASS if condition else _FAIL).append(name)
    mark = "✓" if condition else "✗"
    line = f"  {mark} {name}"
    if detail and not condition:
        line += f"  → {detail}"
    print(line)


class _Client:
    """Thin wrapper over httpx (deployed) or TestClient (in-process)."""

    def __init__(self):
        base = os.environ.get("E2E_BASE_URL")
        if base:
            import httpx
            self._c = httpx.Client(base_url=base.rstrip("/"), timeout=30)
            self.mode = f"httpx → {base}"
        else:
            from fastapi.testclient import TestClient
            from app.main import app
            self._c = TestClient(app)
            self.mode = "TestClient (in-process)"
        self.headers = {}

    def get(self, path, **kw):
        return self._c.get(path, headers=self.headers, **kw)

    def post(self, path, **kw):
        return self._c.post(path, headers=self.headers, **kw)


def run() -> int:
    c = _Client()
    print(f"E2E smoke · modo: {c.mode}\n")

    # ── Salud + Auth (Fase 1: auth + usuario E2E) ──────────────────
    print("Salud & Auth")
    r = c.get("/api/v1/health")
    check("health 200", r.status_code == 200)
    r = c.post("/api/v1/auth/login", json={"email": E2E_EMAIL, "password": E2E_PASSWORD})
    check("login usuario E2E 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        print("\nNo hay sesión; abortando. ¿Corriste scripts/seed_e2e_user.py en la DB destino?")
        return _summary()
    body = r.json()
    check("rol admin", body.get("role") == "admin", f"rol={body.get('role')}")
    c.headers = {"Authorization": f"Bearer {body['access_token']}"}

    # ── Fase 0: motor de índices + doctrina (vía IRMP) ─────────────
    print("\nFase 0 — shared/indices + shared/doctrine (vía IRMP)")
    r = c.get("/api/v1/macro-political-risk/weights")
    check("IRMP /weights 200", r.status_code == 200)
    w = r.json().get("dimension_weights", {}) if r.status_code == 200 else {}
    check("pesos de doctrina suman 1.0", round(sum(w.values()), 6) == 1.0, f"suma={sum(w.values())}")

    dataset = {
        "DO": {"gdp_cagr_3y": 5.0, "public_debt_gdp": 45.0, "wgi_rule_of_law": 55.0},
        "CR": {"gdp_cagr_3y": 3.0, "public_debt_gdp": 63.0, "wgi_rule_of_law": 65.0},
        "PA": {"gdp_cagr_3y": 1.0, "public_debt_gdp": 52.0, "wgi_rule_of_law": 50.0},
    }
    r = c.post("/api/v1/macro-political-risk/score",
               json={"country_code": "DO", "dataset": dataset})
    check("IRMP /score 200 (motor compartido)", r.status_code == 200)
    if r.status_code == 200:
        s = r.json()
        check("score IRMP en [0,100]", 0.0 <= s["irmp_score"] <= 100.0)
        contrib = sum(d["contribution"] for d in s["dimensions"].values())
        check("contribuciones ≈ score (auditable)", abs(contrib - s["irmp_score"]) <= 0.5)

    # ── Fase 1B: persistencia + eventos del IRMP ───────────────────
    print("\nFase 1B — macro_political_risk (persistencia + histórico)")
    r = c.post("/api/v1/macro-political-risk/snapshot",
               json={"country_code": "DO", "period_end": "2025-12-31",
                     "country_name": "República Dominicana", "region": "Caribe",
                     "dataset": dataset})
    check("IRMP /snapshot 200 (persiste + publica irmp.updated)", r.status_code == 200,
          f"status={r.status_code}")
    snap_id = r.json().get("snapshot_id") if r.status_code == 200 else None
    check("snapshot persistido con id", bool(snap_id))
    r = c.get("/api/v1/macro-political-risk/DO/latest")
    check("IRMP /DO/latest 200", r.status_code == 200 and r.json().get("has_snapshot") is True)
    r = c.get("/api/v1/macro-political-risk/DO/history")
    check("IRMP /DO/history ≥1", r.status_code == 200 and r.json().get("count", 0) >= 1)

    # ── Fase 1A: banking_score responde ────────────────────────────
    print("\nFase 1A — banking_score")
    r = c.get("/api/v1/banking-score/stats")
    check("banking /stats 200", r.status_code == 200)
    r = c.get("/api/v1/banking-score/rankings")
    check("banking /rankings 200", r.status_code == 200)

    # ── Fase 0 (shared/data) + Fase 2: macro_monitor ───────────────
    print("\nFase 2 — macro_monitor (+ shared/data vía ingesta)")
    r = c.post("/api/v1/macro-monitor/refresh")
    check("macro /refresh 200 (ingesta shared/data)", r.status_code == 200, f"status={r.status_code}")
    r = c.get("/api/v1/macro-monitor/indicators")
    check("macro /indicators ≥1", r.status_code == 200 and r.json().get("count", 0) >= 1)
    r = c.get("/api/v1/macro-monitor/snapshot")
    check("macro /snapshot presente", r.status_code == 200 and r.json().get("has_snapshot") is True)
    r = c.get("/api/v1/macro-monitor/signals")
    check("macro /signals 200", r.status_code == 200)

    # ── Fase 5: trade_intel ────────────────────────────────────────
    print("\nFase 5 — trade_intel (resiliencia comercial)")
    flows = [
        {"product": "instrumentos médicos", "direction": "export", "value": 2100.0},
        {"product": "ferroníquel", "direction": "export", "value": 1200.0},
        {"product": "cigarros", "direction": "export", "value": 900.0},
        {"product": "petróleo", "direction": "import", "value": 3800.0},
    ]
    r = c.post("/api/v1/trade-intel/snapshot", json={"period": "2025", "flows": flows})
    check("trade /snapshot 200 (persiste + publica trade.updated)", r.status_code == 200,
          f"status={r.status_code}")
    if r.status_code == 200:
        ts = r.json()
        check("resilience_score en [0,100]", 0.0 <= (ts.get("resilience_score") or -1) <= 100.0)
    r = c.get("/api/v1/trade-intel/concentration")
    check("trade /concentration 200", r.status_code == 200 and r.json().get("has_score") is True)
    r = c.get("/api/v1/trade-intel/score")
    check("trade /score 200", r.status_code == 200 and r.json().get("has_score") is True)

    # ── Fase 3: sector_intel (integrador: consume macro/irmp/trade) ─
    print("\nFase 3 — sector_intel (IAI + SGPS, consume eventos)")
    r = c.get("/api/v1/sector-intel/sectors")
    check("sector /sectors ≥3 (ancla)", r.status_code == 200 and r.json().get("count", 0) >= 3)
    r = c.get("/api/v1/sector-intel/weights")
    iw = r.json().get("iai_dimension_weights", {}) if r.status_code == 200 else {}
    check("pesos IAI suman 1.0", round(sum(iw.values()), 6) == 1.0)
    dataset = {
        "turismo": {"gdp_growth": 5.0, "inflation_stability": 70, "ease_of_business": 65,
                    "operating_cost": 40, "labor_availability": 75, "skills_index": 60,
                    "regulatory_quality": 62, "regulatory_volatility": 30,
                    "sector_growth": 8.0, "sector_size": 70},
        "energia": {"gdp_growth": 4.0, "inflation_stability": 68, "ease_of_business": 55,
                    "operating_cost": 60, "labor_availability": 50, "skills_index": 65,
                    "regulatory_quality": 58, "regulatory_volatility": 45,
                    "sector_growth": 6.0, "sector_size": 60},
    }
    r = c.post("/api/v1/sector-intel/snapshot", json={
        "period": "2025", "dataset": dataset,
        "sgps_inputs": {"turismo": {"historical": 75, "structural": 80}},
    })
    check("sector /snapshot 200 (persiste + publica sector.updated)", r.status_code == 200,
          f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check("acceleración integra upstream (componentes presentes)",
              len(body["acceleration"]["components"]) >= 1,
              f"components={body['acceleration']['components']}")
        check("2 sectores puntuados", len(body["sectors"]) == 2)
    r = c.get("/api/v1/sector-intel/turismo/latest")
    check("sector /turismo/latest 200", r.status_code == 200 and r.json().get("has_score") is True)

    return _summary()


def _summary() -> int:
    print(f"\nResultado: {len(_PASS)} OK, {len(_FAIL)} fallidas")
    if _FAIL:
        print("Fallidas: " + ", ".join(_FAIL))
        return 1
    print("E2E OK — Fase 0, 1A, 1B, 2, 3 y 5 verificadas.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
