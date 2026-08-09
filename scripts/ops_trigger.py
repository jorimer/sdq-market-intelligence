"""Dispara una operación de la consola contra un despliegue y espera su resultado.

Existe para que correr una sincronización no requiera ni la UI ni un comando ad-hoc con
credenciales a la vista. Un `curl` improvisado con usuario y contraseña en la línea de
comandos es, además de frágil, indistinguible de un uso indebido: queda en el historial
del shell, en los logs y en cualquier captura de pantalla. Acá las credenciales salen
del entorno o de las constantes E2E ya versionadas, nunca del argumento.

Uso::

    python scripts/ops_trigger.py one-social-sync
    python scripts/ops_trigger.py gdelt-adm1-volume-test --base-url http://localhost:8000
    python scripts/ops_trigger.py idm-snapshot --timeout 900

Credenciales: ``SDQ_OPS_EMAIL`` / ``SDQ_OPS_PASSWORD`` si están definidas; si no, la
cuenta E2E de ``scripts/seed_e2e_user.py`` (que es de pruebas y se desactiva antes del
go-live). Salida: el ``last_result`` de la operación, que es lo que uno quiere leer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

DEFAULT_BASE = "https://sdq-market-intelligence-production.up.railway.app"
POLL_SECONDS = 5


def _credentials() -> tuple:
    """Del entorno si están; si no, la cuenta E2E versionada. Nunca de un argumento."""
    email = os.environ.get("SDQ_OPS_EMAIL")
    password = os.environ.get("SDQ_OPS_PASSWORD")
    if email and password:
        return email, password
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.seed_e2e_user import E2E_EMAIL, E2E_PASSWORD

    return E2E_EMAIL, E2E_PASSWORD


def _login(client, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise SystemExit("El login no devolvió token de acceso.")
    return token


def _status(client, headers: Dict[str, str], name: str) -> Optional[Dict[str, Any]]:
    r = client.get("/api/v1/operations/status", headers=headers)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("operations") if isinstance(payload, dict) else payload
    return next((o for o in (items or []) if o.get("name") == name), None)


def trigger(name: str, base_url: str, timeout: int) -> Dict[str, Any]:
    """Dispara *name* y espera a que termine. Devuelve su ``last_result``."""
    import httpx

    email, password = _credentials()
    with httpx.Client(base_url=base_url, timeout=60, follow_redirects=True) as client:
        headers = {"Authorization": f"Bearer {_login(client, email, password)}"}

        before = _status(client, headers, name)
        if before is None:
            raise SystemExit(f"La operación '{name}' no está registrada en {base_url}.")
        previous_run = (before.get("status") or {}).get("last_run")

        print(f"→ disparando '{name}' en {base_url}", flush=True)
        r = client.post(f"/api/v1/operations/{name}/run", headers=headers, json={})
        r.raise_for_status()

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(POLL_SECONDS)
            current = _status(client, headers, name) or {}
            state = current.get("status") or {}
            # Terminó cuando dejó de correr Y su última corrida es posterior a la previa
            # (sin esa segunda condición, un sondeo temprano lee el resultado viejo).
            if not state.get("is_running") and state.get("last_run") != previous_run:
                if state.get("error"):
                    print(f"✗ '{name}' falló: {state['error']}", file=sys.stderr)
                    raise SystemExit(1)
                return state.get("last_result") or {}
            phase = state.get("phase")
            if phase:
                print(f"  … {phase}", flush=True)
        raise SystemExit(f"'{name}' no terminó en {timeout}s (sigue corriendo).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", help="Nombre registrado (p. ej. one-social-sync).")
    parser.add_argument("--base-url", default=os.environ.get("SDQ_OPS_BASE_URL", DEFAULT_BASE))
    parser.add_argument("--timeout", type=int, default=600, help="Segundos de espera.")
    args = parser.parse_args()

    result = trigger(args.operation, args.base_url, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
