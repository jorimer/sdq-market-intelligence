"""
SIB Financial Data Extraction Client

Connects to the Superintendencia de Bancos (SB) REST API v2
at https://apis.sb.gob.do/estadisticas/v2 to extract:
- Estados Financieros (financial statements)
- Indicadores (financial ratios)
- Solvencia/Componentes (capital adequacy)
- Captaciones (deposits)
- Carteras (loan portfolios)

Authentication: API Key (obtained from https://desarrollador.sb.gob.do)

Author: SDQ Financial Team
"""
import logging
import time
from datetime import date, datetime
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("sdq.external.sib_data")

# Lazy import httpx — only needed when actually calling the API
_httpx = None

def _get_httpx():
    global _httpx
    if _httpx is None:
        try:
            import httpx
            _httpx = httpx
        except ImportError:
            raise RuntimeError(
                "httpx is required for SIB API access. "
                "Install with: pip install httpx"
            )
    return _httpx


# ═══════════════════════════════════════════════════════════════════
#  SIB ENTITY CODES — Map short names to SIB entity identifiers
# ═══════════════════════════════════════════════════════════════════

SIB_ENTITY_CODES: Dict[str, Dict[str, Any]] = {
    # Banca Múltiple
    "Banreservas":   {"sib_code": "BRD",   "tipo_entidad": "BM", "nombre_sib": "BANCO DE RESERVAS DE LA REP. DOM."},
    "Popular":       {"sib_code": "BPD",   "tipo_entidad": "BM", "nombre_sib": "BANCO POPULAR DOMINICANO"},
    "BHD":           {"sib_code": "BHD",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE BHD"},
    "Scotiabank":    {"sib_code": "SCO",   "tipo_entidad": "BM", "nombre_sib": "SCOTIABANK REP. DOM."},
    "Santa Cruz":    {"sib_code": "SCR",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE SANTA CRUZ"},
    "Caribe":        {"sib_code": "CAR",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE CARIBE INTERNACIONAL"},
    "Promérica":     {"sib_code": "PRO",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE PROMERICA"},
    "Banesco":       {"sib_code": "BAN",   "tipo_entidad": "BM", "nombre_sib": "BANESCO BANCO MULTIPLE"},
    "López de Haro": {"sib_code": "LDH",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE LOPEZ DE HARO"},
    "Vimenca":       {"sib_code": "VIM",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE VIMENCA"},
    "BDI":           {"sib_code": "BDI",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE BDI"},
    "Lafise":        {"sib_code": "LAF",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE LAFISE"},
    "Citibank":      {"sib_code": "CIT",   "tipo_entidad": "BM", "nombre_sib": "CITIBANK N.A."},
    "JMMB":          {"sib_code": "JMM",   "tipo_entidad": "BM", "nombre_sib": "JMMB BANK BANCO MULTIPLE"},
    "Qik":           {"sib_code": "QIK",   "tipo_entidad": "BM", "nombre_sib": "QIK BANCO DIGITAL DOMINICANO"},
    # Asociaciones
    "APAP":          {"sib_code": "APAP",  "tipo_entidad": "AAP", "nombre_sib": "ASOC. POPULAR DE AHORROS Y PRESTAMOS"},
    "ACAP":          {"sib_code": "ACAP",  "tipo_entidad": "AAP", "nombre_sib": "ASOC. CIBAO DE AHORROS Y PRESTAMOS"},
    "La Nacional":   {"sib_code": "LNA",   "tipo_entidad": "AAP", "nombre_sib": "ASOC. LA NACIONAL DE AHORROS Y PRESTAMOS"},
    "ARAP":          {"sib_code": "ARAP",  "tipo_entidad": "AAP", "nombre_sib": "ASOC. ROMANA DE AHORROS Y PRESTAMOS"},
    "Duarte":        {"sib_code": "DUA",   "tipo_entidad": "AAP", "nombre_sib": "ASOC. DUARTE DE AHORROS Y PRESTAMOS"},
    "La Vega Real":  {"sib_code": "LVR",   "tipo_entidad": "AAP", "nombre_sib": "ASOC. LA VEGA REAL DE AHORROS Y PRESTAMOS"},
    # Bancos de Ahorro y Crédito
    "ADOPEM":        {"sib_code": "ADP",   "tipo_entidad": "BAC", "nombre_sib": "BANCO ADOPEM DE AHORRO Y CREDITO"},
    "ADEMI":         {"sib_code": "ADM",   "tipo_entidad": "BAC", "nombre_sib": "BANCO ADEMI DE AHORRO Y CREDITO"},
    "Confisa":       {"sib_code": "CON",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO CONFISA"},
    "FONDESA":       {"sib_code": "FND",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO FONDESA"},
    "Motor Crédito": {"sib_code": "MOT",   "tipo_entidad": "BAC", "nombre_sib": "MOTOR CREDITO BAC"},
    "Fihogar":       {"sib_code": "FIH",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO FIHOGAR"},
    "BACC":          {"sib_code": "BCC",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO DEL CARIBE"},
    "Unión":         {"sib_code": "UNI",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO UNION"},
    "Gruficorp":     {"sib_code": "GRU",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO GRUFICORP"},
    "Bonanza":       {"sib_code": "BON",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO BONANZA"},
}


class SIBDataClient:
    """
    Client for the Superintendencia de Bancos REST API v2.

    Correct endpoint paths (from desarrollador.sb.gob.do):
    - /estados/resultados/eif  → Income statement (P&L) for banks
    - /estados/situacion/eif   → Balance sheet for banks
    - /indicadores/financieros → Pre-computed financial ratios
    - /indicadores/principales → Main system indicators
    - /solvencia/componentes   → Capital adequacy breakdown
    - /carteras/creditos       → Loan portfolio
    - /captaciones/localidad   → Deposit data by location

    Rate limit: 120 calls/minute (Analista plan).

    Rate-limit strategy (adaptive token bucket):
    ─────────────────────────────────────────────
    • Tracks calls within a rolling 60s window
    • At 100 calls/min → inserts 600ms pause between calls (soft throttle)
    • At 110 calls/min → sleeps until the 60s window resets (hard throttle)
    • On HTTP 429 → exponential backoff (2s, 4s, 8s) with up to 3 retries
    • On HTTP 5xx / timeout → retry up to 2 times with linear backoff
    • Provides an async-aware sleep mode for use inside asyncio tasks
    """

    # ── Configurable limits ────────────────────────────────────
    RATE_LIMIT_PER_MIN = 120        # SIB documented limit
    SOFT_THRESHOLD     = 100        # Start slowing down here
    HARD_THRESHOLD     = 110        # Full pause here
    INTER_ENTITY_DELAY = 1.5        # Seconds between entities in bulk ops
    MAX_RETRIES_429    = 3          # Retries on rate-limit response
    MAX_RETRIES_ERR    = 2          # Retries on 5xx / timeout
    BASE_BACKOFF_429   = 2.0        # Seconds — doubles each retry
    BASE_BACKOFF_ERR   = 3.0        # Seconds — linear increase

    # ── Fail-fast settings ────────────────────────────────────
    CONNECTIVITY_CHECK_TIMEOUT = 8   # Seconds for initial connectivity test
    FAIL_FAST_THRESHOLD        = 3   # Consecutive timeouts before aborting bulk

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://apis.sb.gob.do/estadisticas/v2",
        async_mode: bool = False,
        proxy_url: str = "",
        proxy_secret: str = "",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.async_mode = async_mode  # Use asyncio.sleep instead of time.sleep
        self.proxy_url = proxy_url.rstrip("/") if proxy_url else ""
        self.proxy_secret = proxy_secret
        self.use_proxy = bool(self.proxy_url and self.proxy_secret)

        # Rolling window tracking
        self._call_timestamps: List[float] = []

        # Fail-fast: track consecutive timeouts to abort early
        self._consecutive_timeouts = 0

        # Stats for observability
        self.stats = {
            "total_calls": 0,
            "retries_429": 0,
            "retries_error": 0,
            "throttle_pauses": 0,
            "total_sleep_seconds": 0.0,
            "proxy_calls": 0,
            "direct_calls": 0,
            "fail_fast_aborted": False,
        }

    def _headers(self) -> Dict[str, str]:
        return {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) FinancialAnalyst/1.0",
        }

    def _sleep(self, seconds: float):
        """Sleep that respects async_mode (for use in sync context)."""
        self.stats["total_sleep_seconds"] += seconds
        time.sleep(seconds)

    def _rate_limit(self):
        """
        Adaptive rate limiter using a rolling 60s window.

        Three tiers:
        1. Under SOFT_THRESHOLD → no delay
        2. SOFT → HARD → 600ms delay per call
        3. At HARD → sleep until window resets
        """
        now = time.time()
        window_start = now - 60.0

        # Prune calls older than 60s
        self._call_timestamps = [
            t for t in self._call_timestamps if t > window_start
        ]

        calls_in_window = len(self._call_timestamps)

        if calls_in_window >= self.HARD_THRESHOLD:
            # Hard throttle: wait until oldest call falls out of window
            oldest = self._call_timestamps[0]
            sleep_time = (oldest + 60.0) - now + 0.5  # +0.5s safety margin
            if sleep_time > 0:
                logger.info(
                    f"Rate limit HARD ({calls_in_window}/{self.RATE_LIMIT_PER_MIN}/min) "
                    f"— pausing {sleep_time:.1f}s"
                )
                self.stats["throttle_pauses"] += 1
                self._sleep(sleep_time)

        elif calls_in_window >= self.SOFT_THRESHOLD:
            # Soft throttle: add small delay to spread calls
            logger.debug(
                f"Rate limit SOFT ({calls_in_window}/{self.RATE_LIMIT_PER_MIN}/min) "
                f"— adding 600ms delay"
            )
            self._sleep(0.6)

        # Record this call
        self._call_timestamps.append(time.time())
        self.stats["total_calls"] += 1

    # ── Connectivity check (fail-fast) ────────────────────────

    def check_connectivity(self) -> Dict[str, Any]:
        """
        Quick connectivity test before starting bulk operations.

        Tries a lightweight request (GET /indicadores/principales with 1 record)
        with a short timeout. Returns dict with 'reachable' bool.

        If proxy is configured, tests via proxy. Otherwise tests direct.
        """
        httpx = _get_httpx()
        test_url = f"{self.base_url}/indicadores/principales"
        test_params = {"periodoInicial": "2024-01", "registros": "1"}
        mode = "proxy" if self.use_proxy else "direct"

        logger.info(f"SIB connectivity check ({mode})...")
        start = time.time()

        try:
            if self.use_proxy:
                resp = self._proxy_request(
                    httpx, test_url, test_params,
                    timeout=self.CONNECTIVITY_CHECK_TIMEOUT
                )
            else:
                resp = httpx.get(
                    test_url, params=test_params,
                    headers=self._headers(),
                    timeout=self.CONNECTIVITY_CHECK_TIMEOUT,
                )

            elapsed = time.time() - start
            reachable = resp.status_code in (200, 401, 403)

            logger.info(
                f"SIB connectivity: {'OK' if reachable else 'FAIL'} "
                f"({resp.status_code} in {elapsed:.1f}s via {mode})"
            )
            return {
                "reachable": reachable,
                "status_code": resp.status_code,
                "elapsed_s": round(elapsed, 2),
                "mode": mode,
            }

        except Exception as e:
            elapsed = time.time() - start
            logger.warning(
                f"SIB connectivity: UNREACHABLE via {mode} "
                f"({elapsed:.1f}s — {e})"
            )
            return {
                "reachable": False,
                "error": str(e),
                "elapsed_s": round(elapsed, 2),
                "mode": mode,
            }

    # ── Proxy request helper ───────────────────────────────────

    def _proxy_request(self, httpx, target_url: str, params: Dict, timeout: int = 30):
        """
        Route a request through the Cloudflare Worker proxy.

        POST {proxy_url}/proxy
        Body: { "url": "<full_target_url_with_params>", "headers": {...} }
        Headers: X-Proxy-Secret
        """
        # Build full URL with query params
        from urllib.parse import urlencode, quote
        # SIB API expects array params like entidad and tipoEntidad
        # as repeated keys: entidad=BRD&entidad=BPD
        # urlencode with doseq=True handles lists properly
        encoded_params = {}
        for k, v in params.items():
            if isinstance(v, (list, tuple)):
                encoded_params[k] = v  # keep as list for doseq
            else:
                encoded_params[k] = v
        full_url = f"{target_url}?{urlencode(encoded_params, doseq=True)}" if encoded_params else target_url

        logger.debug(f"Proxy → {full_url}")

        proxy_body = {
            "url": full_url,
            "headers": self._headers(),
            "method": "GET",
        }

        resp = httpx.post(
            f"{self.proxy_url}/proxy",
            json=proxy_body,
            headers={
                "X-Proxy-Secret": self.proxy_secret,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self.stats["proxy_calls"] += 1
        return resp

    # ── Core GET with pagination ───────────────────────────────

    def _get(self, endpoint: str, params: Dict[str, Any]) -> List[Dict]:
        """Execute GET request with pagination, retry, and rate limiting."""
        httpx = _get_httpx()

        # Fail-fast: if too many consecutive timeouts, abort
        if self._consecutive_timeouts >= self.FAIL_FAST_THRESHOLD:
            if not self.stats["fail_fast_aborted"]:
                logger.error(
                    f"FAIL-FAST: {self._consecutive_timeouts} consecutive timeouts — "
                    f"SIB API unreachable. Aborting remaining requests."
                )
                self.stats["fail_fast_aborted"] = True
            return []

        url = f"{self.base_url}/{endpoint}"
        all_results = []
        page = 1
        max_pages = 200  # increased from 50 to handle dense endpoints

        while page <= max_pages:
            page_params = {**params, "paginas": page, "registros": 100}
            data = self._get_with_retry(httpx, url, page_params, endpoint, page)

            if data is None:
                break  # Unrecoverable error

            if isinstance(data, list):
                if not data:
                    break
                all_results.extend(data)
                if len(data) < 100:
                    break
            elif isinstance(data, dict):
                records = data.get("data", data.get("registros", []))
                if isinstance(records, list):
                    all_results.extend(records)
                    if len(records) < 100:
                        break
                else:
                    all_results.append(data)
                    break
            else:
                break

            page += 1

        return all_results

    def _get_with_retry(
        self, httpx, url: str, params: Dict, endpoint: str, page: int
    ) -> Any:
        """
        Single GET with rate limiting + retry logic.

        Routes through proxy if configured, otherwise direct.

        Retry strategy:
        - HTTP 429 → exponential backoff (2s, 4s, 8s), up to MAX_RETRIES_429
        - HTTP 5xx / timeout → linear backoff (3s, 6s), up to MAX_RETRIES_ERR
        - HTTP 404 → return None immediately (endpoint doesn't exist)
        - HTTP 4xx (other) → return None immediately
        """
        last_error = None
        retries_429 = 0
        retries_err = 0
        max_attempts = 1 + self.MAX_RETRIES_429 + self.MAX_RETRIES_ERR

        for attempt in range(max_attempts):
            self._rate_limit()

            try:
                if self.use_proxy:
                    resp = self._proxy_request(httpx, url, params)
                else:
                    resp = httpx.get(
                        url, params=params, headers=self._headers(), timeout=30
                    )
                    self.stats["direct_calls"] += 1

                # ── Success ──
                if resp.status_code == 200:
                    self._consecutive_timeouts = 0  # Reset fail-fast counter
                    return resp.json()

                # ── Rate limited ──
                if resp.status_code == 429:
                    retries_429 += 1
                    self.stats["retries_429"] += 1
                    if retries_429 > self.MAX_RETRIES_429:
                        logger.warning(
                            f"SIB 429 on {endpoint} p{page} — "
                            f"max retries ({self.MAX_RETRIES_429}) exhausted"
                        )
                        return None

                    # Read Retry-After header if present
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            backoff = float(retry_after)
                        except ValueError:
                            backoff = self.BASE_BACKOFF_429 * (2 ** (retries_429 - 1))
                    else:
                        backoff = self.BASE_BACKOFF_429 * (2 ** (retries_429 - 1))

                    logger.info(
                        f"SIB 429 on {endpoint} p{page} — "
                        f"retry {retries_429}/{self.MAX_RETRIES_429} "
                        f"in {backoff:.1f}s"
                    )
                    self._sleep(backoff)
                    continue

                # ── 404: endpoint doesn't exist ──
                if resp.status_code == 404:
                    self._consecutive_timeouts = 0
                    logger.debug(f"SIB 404 on {endpoint} — endpoint not available")
                    return None

                # ── Server error (5xx) ──
                if resp.status_code >= 500:
                    retries_err += 1
                    self.stats["retries_error"] += 1
                    if retries_err > self.MAX_RETRIES_ERR:
                        logger.warning(
                            f"SIB {resp.status_code} on {endpoint} p{page} — "
                            f"max retries ({self.MAX_RETRIES_ERR}) exhausted"
                        )
                        return None

                    backoff = self.BASE_BACKOFF_ERR * retries_err
                    logger.info(
                        f"SIB {resp.status_code} on {endpoint} p{page} — "
                        f"retry {retries_err}/{self.MAX_RETRIES_ERR} in {backoff:.1f}s"
                    )
                    self._sleep(backoff)
                    continue

                # ── Other client error (4xx) ──
                self._consecutive_timeouts = 0
                try:
                    err_body = resp.text[:1000]
                except Exception:
                    err_body = "<unreadable>"
                logger.warning(
                    f"SIB {resp.status_code} on {endpoint} p{page} — "
                    f"not retryable | body: {err_body}"
                )
                return None

            except Exception as e:
                last_error = e
                self._consecutive_timeouts += 1

                # Timeout or network error → retry
                retries_err += 1
                self.stats["retries_error"] += 1
                if retries_err > self.MAX_RETRIES_ERR:
                    logger.error(
                        f"SIB error on {endpoint} p{page} "
                        f"after {retries_err} retries: {e}"
                    )
                    return None

                backoff = self.BASE_BACKOFF_ERR * retries_err
                logger.info(
                    f"SIB error on {endpoint} p{page}: {e} — "
                    f"retry {retries_err}/{self.MAX_RETRIES_ERR} in {backoff:.1f}s"
                )
                self._sleep(backoff)

        logger.error(f"SIB {endpoint} p{page} — all retries exhausted: {last_error}")
        return None

    # ── High-level extraction methods ──────────────────────────
    #
    # Correct SIB API v2 endpoint paths (from desarrollador.sb.gob.do):
    #
    # EstadosFinancieros:
    #   estados/resultados/eif  → Income statement (P&L) for banks (EIF)
    #   estados/situacion/eif   → Balance sheet for banks (EIF)
    #   estados/resultados/eic  → Income statement for exchange houses
    #   estados/situacion/eic   → Balance sheet for exchange houses
    #
    # Indicadores:
    #   indicadores/principales   → Main system indicators ✓ (confirmed)
    #   indicadores/financieros   → Financial ratios ✓ (confirmed, needs tipoEntidad)
    #
    # SolvenciaComponentes:
    #   solvencia/componentes → Capital adequacy / solvency data
    #
    # Carteras:
    #   carteras/creditos → Total credit portfolio
    #
    # Captaciones:
    #   captaciones/localidad → Deposits by location
    #   captaciones/moneda    → Deposits by currency

    # SIB API entity type codes (from desarrollador.sb.gob.do portal):
    #   BM   = Banca Múltiple (commercial banks)
    #   BAyC = Bancos de Ahorro y Crédito (savings & credit banks)
    #   AAyP = Asociaciones de Ahorro y Préstamos (savings associations)
    # NOTE: our internal codes differ: BAC→BAyC, AAP→AAyP
    SIB_TIPO_ENTIDAD_MAP = {
        "BM": "BM",      # Same
        "BAC": "BAyC",   # Internal BAC → SIB BAyC
        "AAP": "AAyP",   # Internal AAP → SIB AAyP (to be confirmed)
    }
    # All candidate SIB entity types to try (we'll auto-discover which work)
    SIB_TIPO_ENTIDAD_CANDIDATES = ["BM", "BAyC", "AAyP", "BAC", "AAP"]
    # Will be set by _discover_working_tipo_codes()
    _discovered_tipo_codes: List[str] = []

    def _discover_working_tipo_codes(self) -> List[str]:
        """
        Auto-discover which tipoEntidad codes the SIB API accepts.

        Tests each candidate code against estados/resultados/eif with 1 record.
        Logs results as INFO so they appear in Railway logs.

        Returns list of working codes.
        """
        httpx = _get_httpx()
        test_endpoint = "estados/resultados/eif"
        test_url = f"{self.base_url}/{test_endpoint}"
        working = []
        entity_names_found = set()

        logger.info(
            "╔══ SIB API DIAGNOSTIC ══════════════════════════════════╗"
        )
        logger.info(
            f"║  Testing tipoEntidad codes: {self.SIB_TIPO_ENTIDAD_CANDIDATES}"
        )

        for code in self.SIB_TIPO_ENTIDAD_CANDIDATES:
            params = {
                "periodoInicial": "2024-01",
                "tipoEntidad": code,
                "registros": 2,
                "paginas": 1,
            }
            try:
                self._rate_limit()
                if self.use_proxy:
                    resp = self._proxy_request(httpx, test_url, params, timeout=15)
                else:
                    resp = httpx.get(
                        test_url, params=params,
                        headers=self._headers(), timeout=15,
                    )

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        count = len(data) if isinstance(data, list) else 0
                        # Extract entity names from response
                        if isinstance(data, list):
                            for rec in data[:5]:
                                ent = rec.get("entidad") or rec.get("Entidad") or ""
                                if ent:
                                    entity_names_found.add(ent)
                    except Exception:
                        count = -1
                    working.append(code)
                    logger.info(f"║  ✓ tipoEntidad={code} → 200 OK ({count} records)")
                else:
                    body = ""
                    try:
                        body = resp.text[:200]
                    except Exception:
                        pass
                    logger.info(f"║  ✗ tipoEntidad={code} → {resp.status_code} | {body}")
            except Exception as e:
                logger.info(f"║  ✗ tipoEntidad={code} → ERROR: {e}")

        # Also test a couple entidad codes for future reference
        for ent_code in ["ADEMI", "APAP", "BRD", "BANRESERVAS"]:
            params = {
                "periodoInicial": "2024-01",
                "entidad": ent_code,
                "registros": 1,
                "paginas": 1,
            }
            try:
                self._rate_limit()
                if self.use_proxy:
                    resp = self._proxy_request(httpx, test_url, params, timeout=15)
                else:
                    resp = httpx.get(
                        test_url, params=params,
                        headers=self._headers(), timeout=15,
                    )

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        count = len(data) if isinstance(data, list) else 0
                        if isinstance(data, list):
                            for rec in data[:3]:
                                ent = rec.get("entidad") or rec.get("Entidad") or ""
                                if ent:
                                    entity_names_found.add(ent)
                    except Exception:
                        count = -1
                    logger.info(f"║  ✓ entidad={ent_code} → 200 OK ({count} records)")
                else:
                    body = ""
                    try:
                        body = resp.text[:150]
                    except Exception:
                        pass
                    logger.info(f"║  ✗ entidad={ent_code} → {resp.status_code} | {body}")
            except Exception as e:
                logger.info(f"║  ✗ entidad={ent_code} → ERROR: {e}")

        logger.info("║")
        logger.info(f"║  Working tipoEntidad codes: {working}")
        logger.info(f"║  Entity names from API: {sorted(entity_names_found)[:10]}")
        logger.info(
            "╚══════════════════════════════════════════════════════════╝"
        )

        return working

    def _fetch_for_all_types(self, endpoint: str, period_start: str, period_end: str) -> List[Dict]:
        """
        Fetch data from an endpoint for ALL entity types by making one call
        per tipoEntidad (3 calls total per endpoint).

        With max_pages=200 (20,000 records per call), this handles all data
        without needing yearly chunking. Previous 50-page limit caused
        truncation; the fix was raising max_pages, not chunking.

        Uses auto-discovered working codes, or falls back to candidates.
        """
        codes_to_use = self._discovered_tipo_codes or self.SIB_TIPO_ENTIDAD_CANDIDATES[:3]

        all_records: List[Dict] = []
        for tipo in codes_to_use:
            params: Dict[str, Any] = {
                "periodoInicial": period_start,
                "periodoFinal": period_end,
                "tipoEntidad": tipo,
            }
            records = self._get(endpoint, params)
            if records:
                logger.info(f"    {endpoint} tipoEntidad={tipo} → {len(records)} records")
                all_records.extend(records)
            else:
                logger.info(f"    {endpoint} tipoEntidad={tipo} → 0 records")
        return all_records

    @staticmethod
    def _current_period() -> str:
        """Return current YYYY-MM for dynamic period defaults."""
        return datetime.now().strftime("%Y-%m")

    def get_income_statement(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch estado de resultados (income statement / P&L) for all EIF entities.

        Endpoint: /estados/resultados/eif
        Response fields: periodo, tipoEntidad, entidad, conceptoNivel1-5, valor

        SIB API requires tipoEntidad param. We call once per type (BM, BAyC, AAyP).
        """
        period_end = period_end or self._current_period()
        return self._fetch_for_all_types("estados/resultados/eif", period_start, period_end)

    def get_balance_sheet(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch estado de situación (balance sheet) for all EIF entities.

        Endpoint: /estados/situacion/eif
        """
        period_end = period_end or self._current_period()
        return self._fetch_for_all_types("estados/situacion/eif", period_start, period_end)

    def get_financial_statements(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch both income statement and balance sheet (combined).
        """
        period_end = period_end or self._current_period()
        income = self.get_income_statement(period_start=period_start, period_end=period_end)
        balance = self.get_balance_sheet(period_start=period_start, period_end=period_end)
        return income + balance

    def get_indicators(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch pre-computed SIB financial indicators.

        Endpoint: /indicadores/financieros
        """
        period_end = period_end or self._current_period()
        return self._fetch_for_all_types("indicadores/financieros", period_start, period_end)

    def get_solvency_components(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch capital adequacy / solvency component data.

        Endpoint: /solvencia/componentes
        """
        period_end = period_end or self._current_period()
        return self._fetch_for_all_types("solvencia/componentes", period_start, period_end)

    def get_loan_portfolio(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch loan portfolio (carteras) breakdown.

        Endpoint: /carteras/creditos
        """
        period_end = period_end or self._current_period()
        return self._fetch_for_all_types("carteras/creditos", period_start, period_end)

    def get_deposits(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        **_ignored,
    ) -> List[Dict]:
        """
        Fetch deposit data (captaciones).

        Endpoint: /captaciones/localidad
        """
        period_end = period_end or self._current_period()
        return self._fetch_for_all_types("captaciones/localidad", period_start, period_end)

    # ── ETL: Map SIB API data → SdqBankingData fields ──────────

    # ── SIB API entity names (discovered via auto-diagnostic) ──
    # The API returns short names like ADEMI, BANRESERVAS, etc.
    # We must map these to our internal short_name keys.
    SIB_API_NAME_MAP: Dict[str, str] = {
        # Banca Múltiple
        "BANRESERVAS": "Banreservas",
        "POPULAR": "Popular",
        "BHD": "BHD",
        "SCOTIABANK": "Scotiabank",
        "SANTA CRUZ": "Santa Cruz",
        "CARIBE": "Caribe",
        "PROMERICA": "Promérica",
        "BANESCO": "Banesco",
        "LOPEZ DE HARO": "López de Haro",
        "VIMENCA": "Vimenca",
        "BDI": "BDI",
        "LAFISE": "Lafise",
        "CITIBANK": "Citibank",
        "JMMB": "JMMB",
        "QIK": "Qik",
        # Asociaciones
        "APAP": "APAP",
        "CIBAO": "ACAP",
        "LA NACIONAL": "La Nacional",
        "ROMANA": "ARAP",
        "DUARTE": "Duarte",
        "LA VEGA REAL": "La Vega Real",
        # Bancos de Ahorro y Crédito
        "ADOPEM": "ADOPEM",
        "ADEMI": "ADEMI",
        "CONFISA": "Confisa",
        "FONDESA": "FONDESA",
        "MOTOR CREDITO": "Motor Crédito",
        "FIHOGAR": "Fihogar",
        "BACC": "BACC",
        "UNION": "Unión",
        "GRUFICORP": "Gruficorp",
        "BONANZA": "Bonanza",
    }

    # Build reverse lookup: nombre_sib → short_name
    # The SIB API returns entity names in the 'entidad' response field.
    _ENTITY_REVERSE_MAP: Dict[str, str] = {}
    # First: add explicit API name mappings (highest priority)
    for _api_name, _short in SIB_API_NAME_MAP.items():
        _ENTITY_REVERSE_MAP[_api_name.upper()] = _short
    # Then: add nombre_sib and sib_code mappings
    for _short, _info in SIB_ENTITY_CODES.items():
        _nombre = _info["nombre_sib"].strip().upper()
        _code = _info["sib_code"].strip().upper()
        _ENTITY_REVERSE_MAP[_nombre] = _short
        _ENTITY_REVERSE_MAP[_code] = _short
        _ENTITY_REVERSE_MAP[_short.upper()] = _short

    @classmethod
    def _match_entity_name(cls, api_entity_name: str) -> Optional[str]:
        """
        Match an entity name from the SIB API response to our short_name.

        The SIB API 'entidad' field format is unknown — could be full name,
        abbreviation, or code. We try exact match first, then fuzzy substring.
        """
        if not api_entity_name:
            return None

        name_upper = api_entity_name.strip().upper()

        # Exact match (nombre_sib, sib_code, or short_name)
        if name_upper in cls._ENTITY_REVERSE_MAP:
            return cls._ENTITY_REVERSE_MAP[name_upper]

        # Substring match: check if any known name is contained or contains
        for known_name, short in cls._ENTITY_REVERSE_MAP.items():
            if known_name in name_upper or name_upper in known_name:
                return short

        return None

    def extract_all_entities_bulk(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
    ) -> Dict[str, List[Dict]]:
        """
        BULK ETL: fetch data from ALL SIB endpoints using tipoEntidad filter
        (one call per entity type per endpoint = 5 endpoints × 3 types = 15 calls),
        then split by entity name and map to SdqBankingData schema.

        SIB API rules:
        - Must send either entidad OR tipoEntidad (not both, not neither)
        - tipoEntidad codes: BM, BAyC, AAyP
        - We use tipoEntidad to fetch all entities of each type

        Returns: dict mapping short_name → list of period dicts.
        Also includes a special "_unknown" key for entities we can't match,
        and "_entity_names" key with the raw entity names the API returned
        (for discovering the correct format).
        """
        period_end = period_end or self._current_period()
        logger.info(
            f"Bulk fetch: all SIB data for {period_start} to {period_end}"
        )

        # Step 0: Auto-discover working tipoEntidad codes
        if not self._discovered_tipo_codes:
            self._discovered_tipo_codes = self._discover_working_tipo_codes()
            if not self._discovered_tipo_codes:
                logger.error(
                    "NO working tipoEntidad codes found! "
                    "All candidates failed. Cannot fetch SIB data."
                )
                return {}

        # Step 1: Fetch all data (N endpoints × M types)
        logger.info("  Fetching income statements (estados/resultados/eif)...")
        income = self.get_income_statement(period_start=period_start, period_end=period_end)
        logger.info(f"    → {len(income)} records")

        logger.info("  Fetching balance sheets (estados/situacion/eif)...")
        balance = self.get_balance_sheet(period_start=period_start, period_end=period_end)
        logger.info(f"    → {len(balance)} records")

        logger.info("  Fetching indicators (indicadores/financieros)...")
        indicators = self.get_indicators(period_start=period_start, period_end=period_end)
        logger.info(f"    → {len(indicators)} records")

        logger.info("  Fetching solvency (solvencia/componentes)...")
        solvency = self.get_solvency_components(period_start=period_start, period_end=period_end)
        logger.info(f"    → {len(solvency)} records")

        # NOTE: carteras/creditos has historically returned 504 Gateway Timeout
        # for all tipoEntidad codes. Skip to avoid 18+ timeout+retry cycles
        # that add 30+ minutes of wasted time. Re-enable when SIB fixes this.
        logger.info("  Skipping loans (carteras/creditos) — endpoint returns 504")
        loans = []
        # loans = self.get_loan_portfolio(period_start=period_start, period_end=period_end)
        # logger.info(f"    → {len(loans)} records")

        all_data = income + balance + indicators + solvency + loans
        logger.info(f"  Total raw records: {len(all_data)}")

        # Log sample record structure to understand field names
        if income:
            sample = income[0]
            logger.info(f"  Sample income record keys: {list(sample.keys())}")
            logger.info(f"  Sample income record: {str(sample)[:500]}")
        if indicators:
            sample = indicators[0]
            logger.info(f"  Sample indicator keys: {list(sample.keys())}")
            logger.info(f"  Sample indicator record: {str(sample)[:500]}")
        if solvency:
            sample = solvency[0]
            logger.info(f"  Sample solvency keys: {list(sample.keys())}")
        if loans:
            sample = loans[0]
            logger.info(f"  Sample loan keys: {list(sample.keys())}")

        # Log ALL unique concepto values for mapping refinement
        # Use full dataset (not sample) to ensure we see every concepto name
        for src_name, records in [("income", income), ("balance", balance),
                                   ("indicator", indicators), ("solvency", solvency),
                                   ("loan", loans)]:
            if not records:
                continue
            # For hierarchical endpoints, show each level
            if src_name in ("income", "balance"):
                for nivel in ["conceptoNivel1", "conceptoNivel2"]:
                    vals = set()
                    for r in records:
                        v = r.get(nivel)
                        if v and v != "TODOS":
                            vals.add(v)
                    if vals:
                        logger.info(f"  {src_name} {nivel}: {sorted(vals)}")
            elif src_name == "indicator":
                indicadores = set()
                tipos = set()
                for r in records:
                    v = r.get("indicador")
                    t = r.get("tipoIndicador")
                    if v:
                        indicadores.add(v)
                    if t:
                        tipos.add(t)
                logger.info(f"  indicator tipoIndicador values: {sorted(tipos)}")
                logger.info(f"  indicator names ({len(indicadores)}): {sorted(indicadores)}")
            elif src_name == "solvency":
                componentes = set()
                for r in records:
                    v = r.get("componente")
                    if v:
                        componentes.add(v)
                logger.info(f"  solvency componentes ({len(componentes)}): {sorted(componentes)}")
            else:
                conceptos = set()
                for r in records:
                    for k in ["concepto", "conceptoNivel1"]:
                        v = r.get(k)
                        if v:
                            conceptos.add(v)
                if conceptos:
                    logger.info(f"  {src_name} conceptos ({len(conceptos)}): {sorted(conceptos)}")

        # Step 2: Discover entity names the API uses
        api_entity_names = set()
        for record in all_data:
            ent = record.get("entidad") or record.get("Entidad") or ""
            if ent:
                api_entity_names.add(ent)

        logger.info(
            f"  API entity names found ({len(api_entity_names)}): "
            f"{sorted(api_entity_names)[:10]}{'...' if len(api_entity_names) > 10 else ''}"
        )

        # Step 3: Build entity name → short_name mapping
        entity_mapping: Dict[str, str] = {}  # api_name → short_name
        unmatched = set()
        for api_name in api_entity_names:
            matched = self._match_entity_name(api_name)
            if matched:
                entity_mapping[api_name] = matched
            else:
                unmatched.add(api_name)

        logger.info(
            f"  Matched {len(entity_mapping)}/{len(api_entity_names)} entities. "
            f"Unmatched: {sorted(unmatched)[:5]}"
        )

        # Step 4: Split records by entity and source type
        # IMPORTANT: keep income and balance SEPARATE (not merged as "financial")
        # because they have different conceptoNivel1 trees:
        #   income: "Resultado del ejercicio" → P&L items
        #   balance: "Activos", "Pasivos", "Patrimonio" → balance sheet items
        entity_sources: Dict[str, Dict[str, List]] = {}
        for record_list, src_name in [
            (income, "income"), (balance, "balance"),
            (indicators, "indicators"), (solvency, "solvency"),
            (loans, "loans"),
        ]:
            for record in record_list:
                api_ent = record.get("entidad") or record.get("Entidad") or ""
                short = entity_mapping.get(api_ent, "_unknown")

                if short not in entity_sources:
                    entity_sources[short] = {
                        "income": [], "balance": [],
                        "indicators": [], "solvency": [], "loans": [],
                    }
                entity_sources[short][src_name].append(record)

        # Step 5: Map each entity's data to SdqBankingData fields
        results: Dict[str, List[Dict]] = {}
        for short_name, sources in entity_sources.items():
            if short_name == "_unknown":
                continue

            periods = self._group_by_period(
                sources["income"], sources["balance"],
                sources["indicators"], sources["solvency"],
                sources["loans"],
            )

            entity_results = []
            for period_date, data in periods.items():
                try:
                    mapped = self._map_to_sdq_fields(data)
                    mapped["period_end"] = period_date
                    mapped["period_type"] = (
                        "quarterly" if period_date.month in (3, 6, 9, 12) else "monthly"
                    )
                    mapped["source"] = "sib_api"
                    entity_results.append(mapped)
                except Exception as e:
                    logger.warning(f"Failed to map {short_name} {period_date}: {e}")

            results[short_name] = entity_results

        # Add metadata
        results["_entity_names"] = [
            {"api_name": n, "matched": entity_mapping.get(n)}
            for n in sorted(api_entity_names)
        ]
        results["_unmatched"] = sorted(unmatched)

        total_periods = sum(len(v) for k, v in results.items() if not k.startswith("_"))
        logger.info(
            f"  Bulk extract complete: {len(results) - 2} entities, "
            f"{total_periods} total period records"
        )

        return results

    def extract_banking_data(
        self,
        short_name: str,
        period_start: str = "2021-01",
        period_end: str = "",
    ) -> List[Dict]:
        """
        ETL for a single entity. Uses bulk fetch internally since
        the SIB API does not accept our entity codes.

        NOTE: For backfilling multiple entities, use extract_all_entities_bulk()
        instead — it's much more efficient (5 API calls vs 5 × N).
        """
        entity_info = SIB_ENTITY_CODES.get(short_name)
        if not entity_info:
            raise ValueError(f"Unknown entity: {short_name}")

        logger.info(f"Extracting SIB data for {short_name} (bulk mode)")

        bulk = self.extract_all_entities_bulk(period_start, period_end)
        return bulk.get(short_name, [])

    def _group_by_period(self, *data_sources) -> Dict[date, Dict]:
        """
        Group multiple data source responses by period date.

        SIB API returns many rows per entity per period (one per concepto/line item).
        We always store lists of records and extract values by searching through them.

        Sources: income, balance, indicators, solvency, loans (5 separate lists).
        """
        grouped: Dict[date, Dict] = {}
        source_names = ["income", "balance", "indicators", "solvency", "loans"]

        for src_name, records in zip(source_names, data_sources):
            for record in records:
                # SIB API uses 'periodo' field in YYYY-MM format
                periodo = record.get("periodo") or record.get("Periodo") or ""
                if not periodo:
                    continue
                try:
                    # Parse YYYY-MM to quarter-end date
                    parts = periodo.split("-")
                    year, month = int(parts[0]), int(parts[1])
                    # Map to quarter end
                    if month <= 3:
                        period_date = date(year, 3, 31)
                    elif month <= 6:
                        period_date = date(year, 6, 30)
                    elif month <= 9:
                        period_date = date(year, 9, 30)
                    else:
                        period_date = date(year, 12, 31)
                except (ValueError, IndexError):
                    continue

                if period_date not in grouped:
                    grouped[period_date] = {}
                # Always store as list (many rows per period is normal for SIB)
                if src_name not in grouped[period_date]:
                    grouped[period_date][src_name] = []
                grouped[period_date][src_name].append(record)

        return grouped

    @staticmethod
    def _find_value_in_records(
        records: List[Dict],
        concepto_keywords: List[str],
        value_field: str = "valor",
        nivel1_filter: str = "",
        nivel2_filter: str = "",
    ) -> Optional[float]:
        """
        Search a list of SIB records for a value matching concepto keywords.

        SIB financial/balance records have hierarchical structure:
            {periodo, tipoEntidad, entidad, conceptoNivel1..7, valor}
        SIB indicator records have:
            {periodo, tipoEntidad, entidad, indicador, tipoIndicador, valor, unidad}
        SIB solvency records have:
            {periodo, tipoEntidad, entidad, componente, valor, unidad}

        If nivel1_filter/nivel2_filter are given, we first require the record
        to match on those levels before checking keywords on deeper levels.
        This prevents false positives (e.g., "Provisiones" appearing under
        both Assets and Expenses in different conceptoNivel1 trees).
        """
        concepto_fields = [
            "conceptoNivel1", "conceptoNivel2", "conceptoNivel3",
            "conceptoNivel4", "conceptoNivel5", "conceptoNivel6",
            "conceptoNivel7",
            "concepto", "indicador", "componente",
        ]
        for record in records:
            # Optional hierarchy filter: require conceptoNivel1/2 match first
            if nivel1_filter:
                n1 = (record.get("conceptoNivel1") or "").upper()
                if nivel1_filter.upper() not in n1:
                    continue
            if nivel2_filter:
                n2 = (record.get("conceptoNivel2") or "").upper()
                if nivel2_filter.upper() not in n2:
                    continue

            for cf in concepto_fields:
                concepto = (record.get(cf) or "").upper()
                if not concepto or concepto == "TODOS":
                    continue
                for keyword in concepto_keywords:
                    if keyword.upper() in concepto:
                        val = record.get(value_field) or record.get("Valor")
                        if val is not None:
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                pass
        return None

    @staticmethod
    def _sum_all_values(records: List[Dict], value_field: str = "valor") -> Optional[float]:
        """Sum all 'valor' fields in a list of records (e.g., for total portfolio)."""
        total = 0.0
        found = False
        for record in records:
            val = record.get(value_field) or record.get("Valor")
            if val is not None:
                try:
                    total += float(val)
                    found = True
                except (ValueError, TypeError):
                    pass
        return total if found else None

    def _map_to_sdq_fields(self, period_data: Dict) -> Dict[str, Any]:
        """
        Map SIB API response fields to SdqBankingData model fields.

        REAL SIB API STRUCTURE (confirmed from production logs 2026-02-22):
        ══════════════════════════════════════════════════════════════

        INCOME (estados/resultados/eif) — VERY LIMITED:
          conceptoNivel1: ONLY "Resultado del ejercicio"
          conceptoNivel2: ONLY "Impuesto sobre la renta" | "Resultado antes del impuesto"
          → Only provides net result + tax. NO line items for ingresos/gastos.

        BALANCE (estados/situacion/eif) — RICH:
          conceptoNivel1: "Activos", "Pasivos", "Patrimonio", "Cuentas Contingentes", "Cuentas de Orden"
          conceptoNivel2 (22 values):
            Activos→ "Fondos disponibles", "Inversiones", "Cartera de créditos",
                     "Fondos Interbancarios", "Cuentas por cobrar", "Otros activos",
                     "Propiedad, muebles y equipos", "Bienes recibidos en recuperación",
                     "Deudores por aceptaciones", "Inversiones en acciones"
            Pasivos→ "Obligaciones con el público", "Fondos tomados a préstamo",
                     "Valores en Circulación", "Otros pasivos",
                     "Depósitos de instituciones financieras",
                     "Obligaciones por pactos de recompra", "Obigaciones subordinadas",
                     "Aceptaciones en circulación"
            Patrimonio→ "Patrimonio neto"
            Contingentes→ "Cuentas Contingentes"

        SOLVENCY (solvencia/componentes) — 9 componentes:
          "Patrimonio técnico ajustado", "Capital primario", "Capital secundario",
          "Activos y contingentes ponderados por riesgo crediticio y deducciones...",
          "Activos y contingentes ponderados por riesgo crediticio y riesgo de mercado",
          "Capital requerido por riesgo de mercado",
          "Índice de solvencia", "Sobrante o faltante", "Ajuste"

        INDICATORS (indicadores/financieros) — 77 pre-computed RATIOS (%):
          tipoIndicador: Capital, Gestión, Rentabilidad, Liquidez, Volumen,
                        Estructura de activos/pasivos/cartera/gastos
          Key ratios: ROA, ROE, Margen de Intermediación, Disponibilidades/Captaciones,
                     Gastos Financieros/..., Ingresos Financieros/Activos Productivos, etc.

        LOANS (carteras/creditos) — 504 timeout (endpoint unavailable)
        ══════════════════════════════════════════════════════════════
        """
        inc = period_data.get("income", [])
        bal = period_data.get("balance", [])
        ind = period_data.get("indicators", [])
        sol = period_data.get("solvency", [])
        lns = period_data.get("loans", [])

        fv = self._find_value_in_records

        # ══════════════════════════════════════════════════════════
        #  BALANCE SHEET — Direct values (SB_DO_2024: 1.x, 2.x, 3.x)
        #  conceptoNivel1 = "Activos" | "Pasivos" | "Patrimonio"
        #  conceptoNivel2 = specific account group
        # ══════════════════════════════════════════════════════════

        # 1.0T Total Activos (Activos Netos Totales available as indicator)
        activos_totales = fv(ind, ["ACTIVOS NETOS TOTALES"])

        # 1.0 Fondos disponibles (cash & equivalents)
        caja_valores = fv(bal, ["FONDOS DISPONIBLES"],
                          nivel1_filter="ACTIVOS")

        # 1.3 Cartera de créditos (gross and net)
        cartera_bruta = fv(bal, ["CARTERA DE CR"],
                           nivel1_filter="ACTIVOS")
        cartera_neta = cartera_bruta  # Balance reports net after provisions

        # 2.1 Obligaciones con el público (deposits)
        depositos_totales = fv(bal, ["OBLIGACIONES CON EL P"],
                               nivel1_filter="PASIVOS")

        # 2.0T Total Pasivos — use Endeudamiento indicator × patrimonio or
        # sum balance Pasivos. Try indicator "Activos Netos / Patrimonio" approach:
        pasivos_exigibles = None  # Derived below from activos - patrimonio

        # Short-term liabilities ≈ deposits + valores en circulación
        pasivos_cp = depositos_totales  # Deposits are primarily short-term

        # 3.0T Patrimonio neto
        patrimonio_neto = fv(bal, ["PATRIMONIO NETO"],
                             nivel1_filter="PATRIMONIO")

        # Derive pasivos = activos - patrimonio (accounting identity)
        if activos_totales and patrimonio_neto:
            pasivos_exigibles = activos_totales - patrimonio_neto

        # Cuentas Contingentes
        contingentes_balance = fv(bal, ["CUENTAS CONTINGENTES"],
                                  nivel1_filter="CUENTAS CONTINGENTES")

        # ══════════════════════════════════════════════════════════
        #  INCOME STATEMENT — Limited to net result only
        #  conceptoNivel2: "Resultado antes del impuesto" | "Impuesto sobre la renta"
        # ══════════════════════════════════════════════════════════

        # 5.0N Resultado neto (pre-tax result as best proxy for utilidad neta)
        utilidad_neta = fv(inc, ["RESULTADO ANTES DEL IMPUESTO"],
                           nivel1_filter="RESULTADO")

        # P&L LINE ITEMS NOT AVAILABLE from income endpoint.
        # We derive them from INDICATOR RATIOS × balance denominators.

        # ══════════════════════════════════════════════════════════
        #  SOLVENCY — Direct values from "componente" field
        #  EXACT names confirmed from API
        # ══════════════════════════════════════════════════════════

        patrimonio_tecnico = fv(sol, ["PATRIMONIO TECNICO AJUSTADO", "PATRIMONIO T"])
        apr = fv(sol, ["ACTIVOS Y CONTINGENTES PONDERADOS POR RIESGO CREDITICIO Y DEDUCCIONES"])
        capital_primario = fv(sol, ["CAPITAL PRIMARIO"])
        capital_tier1 = capital_primario
        riesgo_mercado = fv(sol, ["CAPITAL REQUERIDO POR RIESGO DE MERCADO"])
        exposicion_total = fv(sol, ["ACTIVOS Y CONTINGENTES PONDERADOS POR RIESGO CREDITICIO Y RIESGO DE MERCADO"])
        contingentes = contingentes_balance  # From balance sheet Cuentas Contingentes
        indice_solvencia = fv(sol, ["INDICE DE SOLVENCIA"])

        # ══════════════════════════════════════════════════════════
        #  INDICATORS — 77 pre-computed ratios (%)
        #  Use to derive P&L absolute values and fill quality metrics
        # ══════════════════════════════════════════════════════════

        # Rentabilidad
        roa = fv(ind, ["ROA"])
        roe = fv(ind, ["ROE"])
        margen_intermediacion = fv(ind, ["MARGEN DE INTERMEDIACI"])

        # Derive activos_promedio and patrimonio_promedio from ROA/ROE
        activos_promedio = None
        patrimonio_promedio = None
        if roa and utilidad_neta and abs(roa) > 0.001:
            activos_promedio = abs(utilidad_neta / (roa / 100.0))
        if roe and utilidad_neta and abs(roe) > 0.001:
            patrimonio_promedio = abs(utilidad_neta / (roe / 100.0))

        # Gestión ratios — derive absolute P&L values
        # "Gastos Financieros / Captaciones Totales + Obligaciones con Costo"
        gastos_fin_ratio = fv(ind, ["GASTOS FINANCIEROS / CAPTACIONES TOTALES + OBLIGACIONES CON COSTO"])
        # "Ingresos Financieros / Activos Productivos"
        ingresos_fin_ratio = fv(ind, ["INGRESOS FINANCIEROS / ACTIVOS PRODUCTIVOS"])
        # "Gastos Generales y Administrativos / Activos Netos Totales"
        gastos_gya_ratio = fv(ind, ["GASTOS GENERALES Y ADMINISTRATIVOS / ACTIVOS NETOS"])
        # "Gastos Operacionales / Ingresos Operacionales"
        gastos_op_ratio = fv(ind, ["GASTOS OPERACIONALES / INGRESOS OPERACIONALES"])

        # Activos productivos for derivations
        activos_prod_ratio = fv(ind, ["ACTIVOS PRODUCTIVOS / ACTIVOS BRUTOS"])
        activos_productivos_avg = None
        if activos_prod_ratio and activos_totales and activos_prod_ratio > 0:
            activos_productivos_avg = activos_totales * (activos_prod_ratio / 100.0)

        # Derive absolute P&L values from ratios × denominators
        ingresos_financieros = None
        gastos_financieros = None
        gastos_operacionales = None
        ingresos_operacionales = None

        if ingresos_fin_ratio and activos_productivos_avg:
            ingresos_financieros = activos_productivos_avg * (ingresos_fin_ratio / 100.0)
        if gastos_fin_ratio and depositos_totales:
            gastos_financieros = depositos_totales * (gastos_fin_ratio / 100.0)
        if gastos_gya_ratio and activos_totales:
            gastos_operacionales = activos_totales * (gastos_gya_ratio / 100.0)
        if gastos_op_ratio and ingresos_financieros and gastos_op_ratio > 0:
            # gastos_op_ratio = gastos_op / ingresos_op → ingresos_op = gastos_op / ratio?
            # Actually this ratio = Gastos Op / Ingresos Op, so if we have gastos_operacionales:
            if gastos_operacionales:
                ingresos_operacionales = gastos_operacionales / (gastos_op_ratio / 100.0)

        # Provisiones — try "Cobertura de Cartera" indicator
        provisiones_ratio = fv(ind, ["COBERTURA DE CARTERA DE CREDITO BRUTA"])
        provisiones = None
        if provisiones_ratio and cartera_bruta:
            provisiones = cartera_bruta * (provisiones_ratio / 100.0)

        # Liquidez
        disponib_captaciones = fv(ind, ["DISPONIBILIDADES / TOTAL DE CAPTACIONES"])
        disponib_inversion = fv(ind, ["DISPONIBILIDADES + INVERSIONES NETAS"])
        activos_liquidos = disponib_inversion  # ratio: liquid assets / total assets

        # Cartera quality
        cartera_vigente_ratio = fv(ind, ["CARTERA DE CREDITO VIGENTE / CARTERA DE CREDITO BRUTA"])
        cartera_mora_ratio = fv(ind, ["CARTERA DE CREDITO EN MORA Y VENCIDA"])
        cobertura_vencida_90 = fv(ind, ["COBERTURA DE CARTERA DE CREDITO VENCIDA MAYOR A 90"])

        cartera_vencida_90d = None
        cartera_categoria_a = None
        if cartera_vigente_ratio and cartera_bruta:
            cartera_categoria_a = cartera_bruta * (cartera_vigente_ratio / 100.0)
        if cartera_mora_ratio and patrimonio_neto:
            # This is "Mora y Vencida / Patrimonio" → absolute = ratio × patrimonio
            cartera_vencida_90d = patrimonio_neto * (cartera_mora_ratio / 100.0)

        cartera_total = cartera_bruta

        # Not directly available from SIB API
        castigos = None
        suma_top10 = None
        hhi_sectorial_raw = None
        hhi_ingresos_raw = None
        exposicion_re = None
        cartera_a_prev = None

        return {
            # Solvency / Capital
            "patrimonio_tecnico": patrimonio_tecnico,
            "apr": apr,
            "capital_primario": capital_primario,
            "exposicion_total": exposicion_total,
            "capital_tier1": capital_tier1,
            "contingentes": contingentes,
            "riesgo_mercado": riesgo_mercado,

            # Balance Sheet
            "activos_totales": activos_totales,
            "caja_valores": caja_valores,
            "cartera_bruta": cartera_bruta,
            "cartera_neta": cartera_neta,
            "cartera_total": cartera_total,
            "depositos_totales": depositos_totales,
            "pasivos_exigibles": pasivos_exigibles,
            "pasivos_cp": pasivos_cp,

            # Income (derived from indicators × balance denominators)
            "provisiones": provisiones,
            "utilidad_neta": utilidad_neta,
            "ingresos_financieros": ingresos_financieros,
            "gastos_financieros": gastos_financieros,
            "gastos_operacionales": gastos_operacionales,
            "ingresos_operacionales": ingresos_operacionales,
            "castigos": castigos,

            # Indicators & derived
            "activos_promedio": activos_promedio,
            "patrimonio_promedio": patrimonio_promedio,
            "activos_productivos_avg": activos_productivos_avg,
            "activos_liquidos": activos_liquidos,

            # Asset quality
            "cartera_vencida_90d": cartera_vencida_90d,
            "cartera_categoria_a": cartera_categoria_a,
            "suma_top10": suma_top10,
            "hhi_sectorial_raw": hhi_sectorial_raw,
            "exposicion_re": exposicion_re,
            "cartera_a_prev": cartera_a_prev,

            # Diversification
            "hhi_ingresos_raw": hhi_ingresos_raw,
        }

    # ── Bulk extraction for all entities ───────────────────────

    def extract_all_entities(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        progress_callback=None,
    ) -> Dict[str, List[Dict]]:
        """
        Extract data for ALL known banking entities.

        Includes inter-entity delay to stay well within rate limits.
        Optional progress_callback(entity_name, idx, total) for UI updates.

        Returns: {short_name: [list of period dicts]}
        """
        results = {}
        entity_names = list(SIB_ENTITY_CODES.keys())
        total = len(entity_names)

        for idx, short_name in enumerate(entity_names, 1):
            try:
                if progress_callback:
                    progress_callback(short_name, idx, total)

                data = self.extract_banking_data(short_name, period_start, period_end)
                results[short_name] = data

                # Inter-entity delay to spread load evenly
                if idx < total:
                    self._sleep(self.INTER_ENTITY_DELAY)

            except Exception as e:
                logger.error(f"Failed to extract {short_name}: {e}")
                results[short_name] = []

        logger.info(
            f"Bulk extraction complete: {total} entities, "
            f"{self.stats['total_calls']} API calls, "
            f"{self.stats['retries_429']} rate-limit retries, "
            f"{self.stats['retries_error']} error retries, "
            f"{self.stats['total_sleep_seconds']:.0f}s total throttle time"
        )
        return results

    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """Return rate limiting and retry statistics for observability."""
        return {
            **self.stats,
            "calls_in_current_window": len([
                t for t in self._call_timestamps
                if t > time.time() - 60.0
            ]),
            "rate_limit_per_min": self.RATE_LIMIT_PER_MIN,
        }


# ═══════════════════════════════════════════════════════════════════
#  CONVENIENCE — Create client from app settings
# ═══════════════════════════════════════════════════════════════════

_sib_data_client: Optional[SIBDataClient] = None


def _resolve_sib_config() -> Tuple[str, str, str, str]:
    """Resolve ``(api_key, base_url, proxy_url, proxy_secret)`` for the ``sb_do``
    provider from the in-app settings (Postgres), with env/config fallbacks.

    Credentials are managed from the app's Configuración screen
    (``shared.settings``); the service helpers already fall back to
    ``settings.SIB_API_KEY`` / ``settings.SIB_API_BASE_URL`` when unset.
    """
    from shared.database.session import SessionLocal
    from shared.settings import service as settings_service

    db = SessionLocal()
    try:
        api_key = settings_service.get_sector_api_key(db, "sb_do")
        base_url = settings_service.get_sector_api_base_url(db, "sb_do") or "https://apis.sb.gob.do/estadisticas/v2"
        proxy_url, proxy_secret = settings_service.get_sector_api_proxy(db, "sb_do")
        return api_key, base_url.rstrip("/"), proxy_url, proxy_secret
    finally:
        db.close()


def get_sib_data_client(force_new: bool = False) -> Optional[SIBDataClient]:
    """
    Get SIB data client. Returns None if API key not configured.

    Credentials come from the in-app settings (Configuración → APIs de
    Benchmarks por Sector). If a proxy URL is configured, routes requests
    through the Cloudflare Worker proxy to bypass the SIB WAF.

    Args:
        force_new: Force creation of a new client (ignores cached instance).
                   Use after changing settings (e.g. before a backfill).
    """
    global _sib_data_client
    if _sib_data_client is not None and not force_new:
        return _sib_data_client

    api_key, base_url, proxy_url, proxy_secret = _resolve_sib_config()
    if api_key:
        _sib_data_client = SIBDataClient(
            api_key=api_key,
            base_url=base_url,
            proxy_url=proxy_url,
            proxy_secret=proxy_secret,
        )
        mode = "proxy" if _sib_data_client.use_proxy else "direct"
        logger.info(
            f"SIB Data Client initialized ({mode}, base: {base_url}"
            + (f", proxy: {proxy_url})" if proxy_url else ")")
        )
        return _sib_data_client

    logger.warning("SIB API key not configured — data client unavailable")
    return None
