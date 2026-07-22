"""Cliente Python de la SDQ Data API — un solo archivo, vendoreable.

Diseñado para copiarse dentro del repo del cliente (no se publica en PyPI todavía): una
dependencia menos que administrar, y el cliente ve exactamente qué hace. Única dependencia
externa: ``httpx``.

    from sdq_data_client import SdqDataClient

    sdq = SdqDataClient(api_key=os.environ["SDQ_MIP_API_KEY"])

    for asset in sdq.catalog(kind="series"):          # DESCUBRIR, no cablear
        print(asset["code"], asset["frequency"], asset["n_obs"])

    obs = sdq.series("bcrd.inflacion.inflacion.interanual", start="2024-01")
    irmp = sdq.scores("macro", subject="DO")
    quality = sdq.quality("macro")                    # ¿cuánto de esto es dato real?

Lo que el cliente NO debe hacer y este SDK no facilita: cablear listas de códigos (el
inventario crece solo — use ``catalog()``), ignorar los ``caveats`` (viajan con el dato
porque son parte del dato), o tratar un ``None`` como cero (un faltante trae ``reason``).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import httpx

DEFAULT_BASE_URL = "https://sdq-market-intelligence-production.up.railway.app/api/data/v1"
SIGNATURE_HEADER = "X-SDQ-Signature"


class SdqApiError(RuntimeError):
    """Error devuelto por la API, con su código estable.

    Programar contra ``code`` (``series_not_found``, ``quota_exhausted``,
    ``as_of_unsupported``…), nunca contra el texto: el mensaje puede cambiar.
    """

    def __init__(self, status_code: int, code: str, message: str,
                 retry_after: Optional[int] = None):
        super().__init__(f"[{status_code}/{code}] {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass
class Response:
    """Respuesta completa: el dato NO viene solo — los caveats son parte del dato."""

    meta: Dict[str, Any]
    data: Any
    caveats: List[Dict[str, str]]

    @property
    def caveat_codes(self) -> List[str]:
        return [c.get("code", "") for c in self.caveats]


class SdqDataClient:
    """Cliente de la Data API con reintento respetuoso de la cuota."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        session: Optional[httpx.Client] = None,
    ):
        if not api_key:
            raise ValueError("Falta la llave de API.")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session

    # ── Transporte ────────────────────────────────────────────────────

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Response:
        url = f"{self._base}{path}"
        headers = {"Authorization": f"Bearer {self._key}",
                   "Accept": "application/json"}
        clean = {k: v for k, v in (params or {}).items() if v is not None}

        attempt = 0
        while True:
            attempt += 1
            client = self._session or httpx.Client(timeout=self._timeout)
            try:
                resp = client.get(url, params=clean, headers=headers)
            finally:
                if self._session is None:
                    client.close()

            if resp.status_code == 429 and attempt <= self._max_retries:
                # Respetar Retry-After es la diferencia entre un cliente educado y uno
                # que se gana una cuota más chica.
                wait = int(resp.headers.get("Retry-After") or 60)
                time.sleep(min(wait, 120))
                continue

            if resp.status_code >= 400:
                detail: Dict[str, Any] = {}
                try:
                    detail = (resp.json() or {}).get("detail") or {}
                except Exception:  # noqa: BLE001 — respuesta no-JSON (proxy, 502…)
                    detail = {}
                raise SdqApiError(
                    resp.status_code,
                    str(detail.get("code") or "http_error"),
                    str(detail.get("message") or resp.text[:200]),
                    retry_after=detail.get("retry_after_seconds"),
                )

            body = resp.json()
            return Response(meta=body.get("meta") or {}, data=body.get("data"),
                            caveats=body.get("caveats") or [])

    # ── Descubrimiento ────────────────────────────────────────────────

    def catalog(self, *, kind: Optional[str] = None, sector: Optional[str] = None,
                include_quarantined: bool = False) -> List[Dict[str, Any]]:
        """Inventario visible para la llave. **Este es el punto de partida correcto**:
        el catálogo crece solo, así que descubrir vence a cablear."""
        r = self._request("/catalog", {
            "kind": kind, "sector": sector,
            "include_quarantined": str(include_quarantined).lower(),
        })
        return r.data or []

    def changes(self, since: str) -> Dict[str, Any]:
        """Altas y bajas del inventario desde ``since`` (ISO). Llamarlo en cada corrida
        evita enterarse de una serie nueva —o de una que dejó de publicarse— por correo."""
        return self._request("/catalog/changes", {"since": since}).data or {}

    # ── Recursos ──────────────────────────────────────────────────────

    def series_response(self, code: str, **kw) -> Response:
        return self._request("/series", {"code": code, **kw})

    def series(self, code: str, *, sector: Optional[str] = None,
               start: Optional[str] = None, end: Optional[str] = None,
               as_of: Optional[str] = None, limit: Optional[int] = None
               ) -> List[Dict[str, Any]]:
        """Observaciones de una serie. Un faltante viene con ``value=None`` y ``reason``:
        NO lo trate como cero."""
        return self.series_response(code, sector=sector, start=start, end=end,
                                    as_of=as_of, limit=limit).data or []

    def scores(self, sector: str, *, code: Optional[str] = None,
               subject: Optional[str] = None, start: Optional[str] = None,
               end: Optional[str] = None, limit: Optional[int] = None
               ) -> List[Dict[str, Any]]:
        """Scores con desglose dimensional. **Lea ``direction`` en el descriptor**: en el
        IRMP un score MAYOR significa MENOR riesgo."""
        return self._request(f"/scores/{sector}", {
            "code": code, "subject": subject, "start": start, "end": end, "limit": limit,
        }).data or []

    def signals(self, sector: str, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Señales deterministas. Lista vacía = sin alerta activa (un resultado, no un
        hueco)."""
        return self._request(f"/signals/{sector}", {"limit": limit}).data or []

    def forecasts(self, sector: str, *, code: Optional[str] = None,
                  limit: Optional[int] = None) -> Response:
        """Pronósticos + track record. Se devuelve la respuesta COMPLETA a propósito: las
        métricas de acierto viven en ``meta.forecast`` y el caveat ``small_sample`` dice
        cuándo la tasa de acierto todavía no significa nada."""
        return self._request(f"/forecasts/{sector}", {"code": code, "limit": limit})

    def quality(self, sector: str) -> Dict[str, Any]:
        """Cobertura real, estado por variable y procedencia. **Consultarlo antes de meter
        un eje a un modelo**: dice cuánto es dato y cuánto supuesto declarado."""
        return self._request(f"/quality/{sector}").data or {}

    # ── Utilidades ────────────────────────────────────────────────────

    def quota(self) -> Dict[str, Any]:
        """Consumo del período, leído del sobre ``meta`` de una llamada barata."""
        return (self._request("/catalog", {"kind": "__none__"}).meta or {}).get("quota", {})

    def iter_series(self, codes: Iterable[str], **kw) -> Dict[str, List[Dict[str, Any]]]:
        """Varias series en una pasada. Secuencial a propósito: el paralelismo agota la
        cuota más rápido de lo que acelera la carga."""
        return {code: self.series(code, **kw) for code in codes}


# ── Verificación de webhooks ──────────────────────────────────────────


def verify_webhook(secret: str, body: bytes, signature: str) -> bool:
    """¿El aviso viene de SDQ? Comparación en tiempo constante.

    Una URL de webhook es pública por naturaleza: sin verificar la firma, cualquiera que
    la adivine puede hacer que su sistema recalcule con un aviso falso. El aviso NO trae
    el dato — tras verificarlo, vuelva por la API con su llave.

        @app.post("/hooks/sdq")
        def hook(request):
            raw = request.body
            if not verify_webhook(SECRET, raw, request.headers["X-SDQ-Signature"]):
                return 401
            ...
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature or "")
