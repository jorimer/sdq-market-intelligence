"""Captura la línea base de VALIDACIÓN del catálogo, tal como la sirve un despliegue.

Existe porque una certificación no se puede sostener con cifras leídas a mano: cada eje
con motor de validación publica su reporte por una ruta distinta, y esas rutas devuelven
un artefacto PERSISTIDO cuyo sello (``generated_at``) es tan importante como el número.
Sin una foto fechada y comiteada, la fase siguiente se compara contra el recuerdo.

Uso::

    python scripts/capture_validation_baseline.py                 # contra producción
    python scripts/capture_validation_baseline.py --base-url http://localhost:8000
    python scripts/capture_validation_baseline.py --out evidence/validacion_baseline_2026-08-19.json

Credenciales: las mismas que ``scripts/ops_trigger.py`` (``SDQ_OPS_EMAIL`` /
``SDQ_OPS_PASSWORD``, o la cuenta E2E versionada). Solo LEE: no dispara recálculos.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ops_trigger import DEFAULT_BASE, _credentials  # noqa: E402

# Eje → ruta de lectura de su validación en la API. Un eje que no figura acá es un eje
# SIN superficie de lectura: eso es un hallazgo, no una omisión de este script.
SURFACES: Dict[str, str] = {
    "banking_score": "/api/v1/banking-score/validation/backtest",
    "macro_political_risk": "/api/v1/macro-political-risk/validation/backtest",
    "trade_intel": "/api/v1/trade-intel/validation/backtest",
    "esg_climate": "/api/v1/esg-climate/backtest",
    "social_dev": "/api/v1/social-dev/validation/convergent",
    "sector_intel": "/api/v1/sector-intel/validation",
    "insurance_intel": "/api/v1/insurance-intel/validation",
    "monetary_policy": "/api/v1/macro-monitor/comunicados/model/backtest",
    "pension_intel": "/api/v1/pension-intel/validation",
}

# Operaciones cuyo estado de agenda importa para juzgar si la cifra está vigente.
OPS = (
    "backtest", "irmp-backtest", "trade-backtest", "esg-backtest",
    "idm-convergent-validity", "sector-gate-e", "insurance-backtest",
    "pension-backtest", "tpm-model-train", "rescore",
)


def capture(base_url: str) -> Dict[str, Any]:
    import httpx

    email, password = _credentials()
    with httpx.Client(base_url=base_url, timeout=120, follow_redirects=True) as client:
        token = client.post("/api/v1/auth/login",
                            json={"email": email, "password": password}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        health = client.get("/api/v1/health").json()
        ejes: Dict[str, Any] = {}
        for eje, path in SURFACES.items():
            r = client.get(path, headers=headers)
            # Una ruta inexistente devuelve el HTML del SPA con 200: el content-type es el
            # único juez confiable de si la superficie existe (ver memoria del acceso a prod).
            es_json = "json" in r.headers.get("content-type", "")
            ejes[eje] = {
                "path": path,
                "status": r.status_code,
                "servido": es_json,
                "reporte": r.json() if es_json else None,
            }

        payload = client.get("/api/v1/operations/status", headers=headers).json()
        items = payload.get("operations") if isinstance(payload, dict) else payload
        agendas = {
            o["name"]: {
                "schedule": o.get("schedule"),
                "last_run": (o.get("status") or {}).get("last_run"),
                "last_result": (o.get("status") or {}).get("last_result"),
            }
            for o in (items or []) if o.get("name") in OPS
        }

    return {
        "capturado_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "commit_servido": (health.get("deployment") or {}).get("commit_short"),
        "ejes": ejes,
        "operaciones": agendas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SDQ_OPS_BASE_URL", DEFAULT_BASE))
    parser.add_argument("--out", default=None, help="Ruta del JSON (default: evidence/validacion_baseline_<hoy>.json)")
    args = parser.parse_args()

    snapshot = capture(args.base_url)
    out = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "evidence", f"validacion_baseline_{datetime.now(timezone.utc):%Y-%m-%d}.json",
    )
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"✓ {out} — commit servido {snapshot['commit_servido']}")


if __name__ == "__main__":
    main()
