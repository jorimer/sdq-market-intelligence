"""Live HTTP access to the BCRD (Banco Central RD) statistics API.

Auth: the API takes the registration token in the POST **body** (``{"token": …}``),
not a header. Endpoints under ``/api/services/app/MacroVariables/`` return
``{"name": str, "values": [...]}``. Used by the diagnostic and, later, the live
``BCRDClient`` that feeds ``macro_monitor`` (Eje 2).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

BCRD_BASE_URL = "https://api.bancentral.gov.do"

# variable key → endpoint path
BCRD_VARIABLES: Dict[str, str] = {
    "inflacion": "/api/services/app/MacroVariables/Inflacion",
    "monetarias": "/api/services/app/MacroVariables/Monetarias",
    "sector_real": "/api/services/app/MacroVariables/SectorReal",
    "sector_externo": "/api/services/app/MacroVariables/SectorExterno",
    "historico_tasas": "/api/services/app/MacroVariables/HistoricoTasas",
    "historico_ipc": "/api/v2/HistoricoIPC",
}


def fetch_bcrd_variable(
    token: str, variable: str, base_url: str = BCRD_BASE_URL, timeout: int = 30,
) -> Dict[str, Any]:
    """POST to a BCRD MacroVariables endpoint with the token in the body.

    Returns the parsed JSON (typically ``{"name", "values": [...]}``). Raises
    ValueError on an unknown variable and httpx errors on transport/HTTP failures.
    """
    path = BCRD_VARIABLES.get(variable)
    if path is None:
        raise ValueError(
            f"Variable BCRD desconocida: {variable}. Opciones: {', '.join(BCRD_VARIABLES)}"
        )
    if not token:
        raise ValueError("Falta el token del BCRD (configúralo en Configuración → BCRD).")
    url = f"{base_url.rstrip('/')}{path}"
    resp = httpx.post(  # pragma: no cover — network I/O
        url, json={"token": token}, timeout=timeout,
        headers={"Content-Type": "application/json", "User-Agent": "SDQ-MIP/1.0"},
    )
    resp.raise_for_status()  # pragma: no cover — network I/O
    return resp.json()  # pragma: no cover — network I/O
