"""Live HTTP access to the BCRD (Banco Central RD) statistics API.

Auth: the API takes the registration token in the POST **body** (``{"token": …}``),
confirmed by the BCRD's own Swagger (``MacroInputDto`` = ``{token: string}``).
Endpoints under ``/api/services/app/MacroVariables/`` return an ABP envelope; a
rejected token comes back as HTTP 500 with ``{"success": false, "error":
{"message": "Credenciales de acceso inválidas"}}``. We unwrap that into a clear
:class:`BcrdApiError` instead of a generic transport failure.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

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


class BcrdApiError(RuntimeError):
    """The BCRD API returned an application-level error (e.g. a rejected token).

    ``is_auth`` flags credential rejections so callers can give a token-specific
    message; ``http_status`` carries the transport status when relevant.
    """

    def __init__(self, message: str, *, is_auth: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        self.is_auth = is_auth
        self.http_status = http_status


def _unwrap_abp(payload: Any) -> Any:
    """Validate/unwrap the ABP envelope; raise :class:`BcrdApiError` on failure.

    Success envelope: ``{"result": <data>, "success": true}`` → returns ``result``.
    Failure: ``{"success": false, "error": {"message": …}}`` → raises. Payloads
    that aren't ABP-wrapped (a bare ``{name, values}``) pass through unchanged.
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("success") is False:
        err = payload.get("error") or {}
        msg = err.get("message") or "El BCRD rechazó la solicitud."
        is_auth = "credencial" in msg.lower() or "token" in msg.lower()
        raise BcrdApiError(msg, is_auth=is_auth)
    if "success" in payload and "result" in payload:
        return payload.get("result")
    return payload


def fetch_bcrd_variable(
    token: str, variable: str, base_url: str = BCRD_BASE_URL, timeout: int = 30,
    extra: Optional[Dict[str, Any]] = None,
) -> Any:
    """POST to a BCRD MacroVariables endpoint with the token in the body.

    *extra* merges additional body fields (e.g. the date-range params of the
    Historico* endpoints: ``yearFrom``/``monthFrom``/… or ``fromDate``/``toDate``,
    plus ``skipCount``/``maxResultCount``).

    Returns the (unwrapped) data, typically ``{"name", "values": [...]}``. Raises
    :class:`ValueError` on an unknown variable / missing token, :class:`BcrdApiError`
    on an application error (rejected token), and ``httpx`` errors on transport.
    """
    path = BCRD_VARIABLES.get(variable)
    if path is None:
        raise ValueError(
            f"Variable BCRD desconocida: {variable}. Opciones: {', '.join(BCRD_VARIABLES)}"
        )
    token = (token or "").strip()
    if not token:
        raise ValueError("Falta el token del BCRD (configúralo en Configuración → BCRD).")
    body: Dict[str, Any] = {"token": token}
    if extra:
        body.update(extra)
    url = f"{base_url.rstrip('/')}{path}"
    resp = httpx.post(  # pragma: no cover — network I/O
        url, json=body, timeout=timeout,
        headers={"Content-Type": "application/json", "User-Agent": "SDQ-MIP/1.0"},
    )
    # The BCRD signals a rejected token as HTTP 500 with an ABP error body, so we
    # inspect the JSON before raising on status.
    try:  # pragma: no cover — network I/O
        data = resp.json()
    except ValueError:
        data = None
    if isinstance(data, dict):  # pragma: no cover — network I/O
        return _unwrap_abp(data)
    resp.raise_for_status()  # pragma: no cover — network I/O
    return data  # pragma: no cover — network I/O
