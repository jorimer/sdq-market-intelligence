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
import unicodedata
from datetime import date, datetime
from typing import Dict, Any, Optional, List, Tuple


def _norm(s: str) -> str:
    """Uppercase + strip diacritics, so 'Índice de Crédito' matches 'INDICE DE
    CREDITO'. The SIB concept/indicator names carry accents; matching against
    accent-free keywords silently failed and left fields unmapped (false N/D)."""
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)
    ).upper().strip()

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
    "López de Haro": {"sib_code": "BLH",   "tipo_entidad": "BM", "nombre_sib": "BANCO MULTIPLE LOPEZ DE HARO"},
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
    "La Vega Real":  {"sib_code": "ALAVER", "tipo_entidad": "AAP", "nombre_sib": "ASOC. LA VEGA REAL DE AHORROS Y PRESTAMOS"},
    "Maguana":       {"sib_code": "MAGUANA", "tipo_entidad": "AAP", "nombre_sib": "ASOC. MAGUANA DE AHORROS Y PRESTAMOS"},
    "Mocana":        {"sib_code": "MOCANA",  "tipo_entidad": "AAP", "nombre_sib": "ASOC. MOCANA DE AHORROS Y PRESTAMOS"},
    "Peravia":       {"sib_code": "PERAVIA", "tipo_entidad": "AAP", "nombre_sib": "ASOC. PERAVIA DE AHORROS Y PRESTAMOS"},
    "Bonao":         {"sib_code": "BONAO",  "tipo_entidad": "AAP", "nombre_sib": "ASOC. BONAO DE AHORROS Y PRESTAMOS"},
    # Bancos de Ahorro y Crédito
    "ADOPEM":        {"sib_code": "ADP",   "tipo_entidad": "BAC", "nombre_sib": "BANCO ADOPEM DE AHORRO Y CREDITO"},
    "ADEMI":         {"sib_code": "ADM",   "tipo_entidad": "BM",  "nombre_sib": "BANCO MULTIPLE ADEMI"},  # banca múltiple desde 2013
    "Confisa":       {"sib_code": "CON",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO CONFISA"},
    "FONDESA":       {"sib_code": "FND",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO FONDESA"},
    "Motor Crédito": {"sib_code": "MOT",   "tipo_entidad": "BAC", "nombre_sib": "MOTOR CREDITO BAC"},
    "Fihogar":       {"sib_code": "FIH",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO FIHOGAR"},
    "BACC":          {"sib_code": "BCC",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO DEL CARIBE"},
    "Unión":         {"sib_code": "UNI",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO UNION"},
    "Gruficorp":     {"sib_code": "GRU",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO GRUFICORP"},
    "Bonanza":       {"sib_code": "BON",   "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORRO Y CREDITO BONANZA"},
    # API entity codes confirmed live (BAyC, 2026): BANCOTUI, LEASCONFISA.
    "Bancotui":      {"sib_code": "BANCOTUI",    "tipo_entidad": "BAC", "nombre_sib": "BANCO DE AHORROS Y CREDITOS BANCOTUI"},
    "Leasconfisa":   {"sib_code": "LEASCONFISA", "tipo_entidad": "BAC", "nombre_sib": "LEASING CONFISA BANCO DE AHORRO Y CREDITO"},

    # Corporaciones de Crédito (CC) — report via estados/situacion/eif like banks.
    # API entity codes confirmed live (2026): MONUMENTAL, NORPRESA, OFICORP.
    "Monumental":    {"sib_code": "MONUMENTAL", "tipo_entidad": "CC", "nombre_sib": "CORPORACION DE CREDITO MONUMENTAL"},
    "Nordestana":    {"sib_code": "NORPRESA",   "tipo_entidad": "CC", "nombre_sib": "CORPORACION DE CREDITO NORDESTANA DE PRESTAMOS"},
    "Oficorp":       {"sib_code": "OFICORP",    "tipo_entidad": "CC", "nombre_sib": "CORPORACION DE CREDITO OFICORP"},

    # Entities the SIB surfaced that weren't catalogued. Types verified against the
    # live SIB across 2021–2026 (estados/situacion). `nombre` is the display name;
    # `active=False` marks entities that exited the system — their historical data
    # is still ingested and kept, they're just excluded from "current" views.
    # — Active Bancos de Ahorro y Crédito (reporting as of 2026-Q1):
    "Atlántico":     {"sib_code": "ATLANTICO", "tipo_entidad": "BAC", "nombre": "Banco de Ahorro y Crédito Atlántico",  "nombre_sib": "BANCO DE AHORRO Y CREDITO ATLANTICO"},
    "Cofaci":        {"sib_code": "COFACI",    "tipo_entidad": "BAC", "nombre": "Banco de Ahorro y Crédito Cofaci",     "nombre_sib": "BANCO DE AHORRO Y CREDITO COFACI"},
    "Óptima":        {"sib_code": "OPTIMA",    "tipo_entidad": "BAC", "nombre": "Banco de Ahorro y Crédito Óptima",     "nombre_sib": "BANCO DE AHORRO Y CREDITO OPTIMA"},
    # — Exited the system (kept for historical analysis):
    "Empire":        {"sib_code": "EMPIRE",    "tipo_entidad": "BAC", "nombre": "Banco de Ahorro y Crédito Empire",     "nombre_sib": "BANCO DE AHORRO Y CREDITO EMPIRE",  "active": False},
    "Activo":        {"sib_code": "ACTIVO",    "tipo_entidad": "BM",  "nombre": "Banco Múltiple Activo",                 "nombre_sib": "BANCO MULTIPLE ACTIVO",            "active": False},
    "Reidco":        {"sib_code": "REIDCO",    "tipo_entidad": "CC",  "nombre": "Corporación de Crédito Reidco",         "nombre_sib": "CORPORACION DE CREDITO REIDCO",    "active": False},
}

# Intermediación cambiaria (estados .../eic). ARC = agentes de remesas y cambio;
# AC = agentes de cambio. Processed via the eic endpoints and a dedicated mapper.
# Entities are auto-registered generically (the EIC feed defines the universe), so
# new agents appear automatically — no per-entity catalog to maintain.
EIC_TIPOS = ("ARC", "AC")

# Friendlier display names for the material ARC agents (the AC universe is large
# and cryptic — those fall back to a title-cased code).
CAMBIARIA_DISPLAY_NAMES = {
    "CARIBEEXPRESS": "Caribe Express (Remesas y Cambio)",
    "CIBAOEXPRESS": "Cibao Express (Remesas y Cambio)",
    "MONEYCORPS": "MoneyCorps (Remesas y Cambio)",
    "GIROSOL": "GiroSol (Remesas y Cambio)",
    "REMVIMENCA": "Remesas Vimenca",
    "CAPLA": "Capla (Remesas y Cambio)",
}


def cambiaria_display_name(code: str) -> str:
    """Human-readable name for a cambiaria SIB code."""
    if code in CAMBIARIA_DISPLAY_NAMES:
        return CAMBIARIA_DISPLAY_NAMES[code]
    return f"{code.title()} (Agente de Cambio)"


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

    # Page size: the SIB API honors large `registros` (verified: 2000 returns a
    # full period in one page). Big pages = ~20x fewer round-trips AND no 20k
    # truncation (vs registros=100 capped at max_pages*100).
    PAGE_SIZE = 5000

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

        # Rolling window tracking (lock makes the limiter safe under concurrency)
        self._call_timestamps: List[float] = []
        import threading
        self._rate_lock = threading.Lock()

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
        self._rate_lock.acquire()
        try:
            now = time.time()
            window_start = now - 60.0

            # Prune calls older than 60s
            self._call_timestamps = [
                t for t in self._call_timestamps if t > window_start
            ]

            calls_in_window = len(self._call_timestamps)
        finally:
            self._rate_lock.release()

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
        with self._rate_lock:
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
            page_params = {**params, "paginas": page, "registros": self.PAGE_SIZE}
            data = self._get_with_retry(httpx, url, page_params, endpoint, page)

            if data is None:
                # A transient page failure (504/timeout) must NOT silently truncate
                # the dataset. Truncation here dropped deep income rows mid-period,
                # leaving hhi_ingresos (and other late-page concepts) N/D. Retry the
                # page a few more times with backoff before giving up, and if it still
                # fails, log loudly that the result is incomplete (never silent).
                for _retry in range(3):
                    self._sleep(5.0 * (_retry + 1))
                    data = self._get_with_retry(httpx, url, page_params, endpoint, page)
                    if data is not None:
                        break
                if data is None:
                    logger.error(
                        "SIB %s: TRUNCADO en página %d tras reintentos — %d filas "
                        "obtenidas; el dataset queda INCOMPLETO para este endpoint.",
                        endpoint, page, len(all_results),
                    )
                    break  # unrecoverable after extra retries

            if isinstance(data, list):
                if not data:
                    break
                all_results.extend(data)
                if len(data) < self.PAGE_SIZE:
                    break
            elif isinstance(data, dict):
                records = data.get("data", data.get("registros", []))
                if isinstance(records, list):
                    all_results.extend(records)
                    if len(records) < self.PAGE_SIZE:
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
        "CC": "CC",      # Corporaciones de Crédito (confirmed live)
    }
    # All candidate SIB entity types to try (we'll auto-discover which work).
    # CC (corporaciones de crédito) report via the same EIF endpoints as banks.
    SIB_TIPO_ENTIDAD_CANDIDATES = ["BM", "BAyC", "AAyP", "CC", "BAC", "AAP"]
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

    def _quarters_in_range(self, period_start: str, period_end: str = "") -> List[str]:
        """Quarter-end period strings (YYYY-MM, MM ∈ {03,06,09,12}) in the range."""
        period_end = period_end or self._current_period()
        try:
            sy, sm = (int(x) for x in period_start.split("-")[:2])
            ey, em = (int(x) for x in period_end.split("-")[:2])
        except (ValueError, IndexError):
            return []
        out: List[str] = []
        for y in range(sy, ey + 1):
            for m in (3, 6, 9, 12):
                if (y, m) < (sy, sm) or (y, m) > (ey, em):
                    continue
                out.append(f"{y}-{m:02d}")
        return out

    # Income-source buckets for the diversification HHI: the conceptoNivel4
    # subtotals (rows where conceptoNivel5 == "TODOS") of the positive income
    # streams in the estado de resultados tree.
    _INCOME_HHI_N4 = (
        "Margen financiero neto",
        "Otros ingresos operacionales",
        "Ingresos (gastos) por diferencia de cambio",
        "Otros ingresos",
    )

    @classmethod
    def _income_hhi_raw(cls, income_rows: List[Dict]) -> Optional[float]:
        """Income-diversification HHI from the estado de resultados tree. Sums the
        conceptoNivel4 income subtotals (conceptoNivel5 == 'TODOS') for the positive
        income streams and returns Σ(sᵢ²)·10000 (0–10000 scale, matching the engine
        thresholds). Returns None when no positive income is found."""
        wanted = {_norm(x) for x in cls._INCOME_HHI_N4}
        buckets: Dict[str, float] = {}
        for r in income_rows or []:
            if _norm(r.get("conceptoNivel5")) != "TODOS":
                continue  # nivel4 subtotal only → no double counting with children
            n4 = _norm(r.get("conceptoNivel4"))
            if n4 not in wanted:
                continue
            try:
                val = float(r.get("valor") or 0)
            except (TypeError, ValueError):
                continue
            if val > 0:  # only positive income streams contribute to the mix
                buckets[n4] = buckets.get(n4, 0.0) + val
        total = sum(buckets.values())
        if total <= 0:
            return None
        return round(sum((v / total) ** 2 for v in buckets.values()) * 10000.0, 4)

    def _compute_carteras_metrics(self, period_start: str, period_end: str = "",
                                  on_progress=None) -> Dict[str, Dict[date, Dict[str, float]]]:
        """Stream carteras/creditos ONE quarter at a time, aggregating per entity/quarter
        in a SINGLE pass over the loan-level cube:
          - sector HHI (Σ deuda by sectorEconomico → Σ shareᵢ²·10000)
          - total cartera (Σ deuda)
          - **mayores deudores** (Σ deuda where tipoCredito = "…Mayores Deudores") →
            the SIB's largest-borrowers concentration (fills the per-bank top-10 gap)
          - cartera vencida (Σ deudaVencida) and cartera clasificación A (Σ deuda, clas. A)

        Returns ``{short_name: {period_end: {"hhi","total","mayores","vencida","cartera_a"}}}``.
        Per-quarter querying keeps each call bounded (the full range 504s). Raw rows are
        discarded as we aggregate — the cube is hundreds of thousands of rows.

        *on_progress(msg)* refreshes the sync heartbeat (this loop is the long pole).
        """
        quarters = self._quarters_in_range(period_start, period_end)
        # acc[short][pe] = {"sectors": {sector: deuda}, "total","mayores","vencida","cartera_a"}
        acc: Dict[str, Dict[date, Dict[str, Any]]] = {}
        for qi, q in enumerate(quarters, 1):
            rows = self._fetch_for_all_types("carteras/creditos", q, q)
            if on_progress:
                on_progress(f"carteras {q} ({qi}/{len(quarters)})")
            if not rows:
                continue
            for r in rows:
                short = self._match_entity_name(r.get("entidad") or "")
                if not short:
                    continue
                pe = self._period_to_quarter_end(r.get("periodo") or q)
                if pe is None:
                    continue
                try:
                    deuda = float(r.get("deuda") or 0)
                except (TypeError, ValueError):
                    continue
                if deuda <= 0:
                    continue
                # Skip TODOS rollup rows entirely — they are subtotals that would
                # double-count every accumulator (the cube's real rows carry a concrete
                # economic sector, incl. mortgages → "Z - ... VIVIENDAS").
                sector = (r.get("sectorEconomico") or "").strip()
                if _norm(sector) == "TODOS":
                    continue
                bucket = acc.setdefault(short, {}).setdefault(
                    pe, {"sectors": {}, "total": 0.0, "mayores": 0.0, "vencida": 0.0, "cartera_a": 0.0})
                bucket["total"] += deuda
                tipo = _norm(r.get("tipoCredito") or "")
                if "MAYORES DEUDORES" in tipo:
                    bucket["mayores"] += deuda
                try:
                    bucket["vencida"] += float(r.get("deudaVencida") or 0)
                except (TypeError, ValueError):
                    pass
                if (r.get("clasificacionEntidad") or "").strip().upper() == "A":
                    bucket["cartera_a"] += deuda
                if sector:
                    bucket["sectors"][sector] = bucket["sectors"].get(sector, 0.0) + deuda
            logger.info(f"    carteras {q}: {len(rows)} rows aggregated")
        result: Dict[str, Dict[date, Dict[str, float]]] = {}
        for short, by_period in acc.items():
            for pe, b in by_period.items():
                total = b["total"]
                if total <= 0:
                    continue
                sectors = b["sectors"]
                stot = sum(sectors.values())
                hhi = (sum((v / stot) ** 2 for v in sectors.values()) * 10000.0) if stot > 0 else None
                result.setdefault(short, {})[pe] = {
                    "hhi": round(hhi, 4) if hhi is not None else None,
                    "total": round(total, 2),
                    "mayores": round(b["mayores"], 2),
                    "vencida": round(b["vencida"], 2),
                    "cartera_a": round(b["cartera_a"], 2),
                }
        return result

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
    #
    # Two maps with different roles:
    #  • _ENTITY_REVERSE_MAP — EXACT lookups. Holds every alias (API name,
    #    nombre_sib, sib_code, short). Codes/abbreviations are safe here because
    #    an exact key never collides.
    #  • _SUBSTRING_NAMES — SUBSTRING fallback. Holds ONLY full descriptive names
    #    (nombre_sib + explicit API names). Short codes are deliberately excluded:
    #    a fragment like "BON" (Bonanza's sib_code) is a substring of unrelated
    #    entities ("BONAO"), so using codes for substring matching misroutes data
    #    (Bonao's balance once landed on Bonanza this way).
    _ENTITY_REVERSE_MAP: Dict[str, str] = {}
    _SUBSTRING_NAMES: Dict[str, str] = {}
    # First: add explicit API name mappings (highest priority) — real names, so
    # they are valid substring candidates too.
    for _api_name, _short in SIB_API_NAME_MAP.items():
        _ENTITY_REVERSE_MAP[_api_name.upper()] = _short
        _SUBSTRING_NAMES[_api_name.upper()] = _short
    # Then: add nombre_sib and sib_code mappings. Only nombre_sib (the full
    # descriptive name) is eligible for substring matching.
    for _short, _info in SIB_ENTITY_CODES.items():
        _nombre = _info["nombre_sib"].strip().upper()
        _code = _info["sib_code"].strip().upper()
        _ENTITY_REVERSE_MAP[_nombre] = _short
        _ENTITY_REVERSE_MAP[_code] = _short
        _ENTITY_REVERSE_MAP[_short.upper()] = _short
        _SUBSTRING_NAMES[_nombre] = _short

    @classmethod
    def _match_entity_name(cls, api_entity_name: str) -> Optional[str]:
        """
        Match an entity name from the SIB API response to our short_name.

        The SIB API 'entidad' field format is unknown — could be full name,
        abbreviation, or code. We try exact match first, then a substring
        fallback restricted to full descriptive names (never short codes, whose
        fragments collide with unrelated entities).
        """
        if not api_entity_name:
            return None

        name_upper = api_entity_name.strip().upper()

        # Exact match (nombre_sib, sib_code, or short_name)
        if name_upper in cls._ENTITY_REVERSE_MAP:
            return cls._ENTITY_REVERSE_MAP[name_upper]

        # Substring match — full descriptive names only (codes excluded).
        for known_name, short in cls._SUBSTRING_NAMES.items():
            if known_name in name_upper or name_upper in known_name:
                return short

        return None

    def get_working_tipos(self) -> List[str]:
        """Discover (once) the EIF tipoEntidad codes that respond, then append the
        cambiaria (EIC) types so the backfill also ingests agentes de cambio y
        remesas. EIC types are routed to the eic endpoints in extract_all_entities_bulk.
        """
        if not self._discovered_tipo_codes:
            self._discovered_tipo_codes = self._discover_working_tipo_codes()
        tipos = list(self._discovered_tipo_codes)
        for t in EIC_TIPOS:  # ARC (remesas y cambio), AC (agentes de cambio)
            if t not in tipos:
                tipos.append(t)
        return tipos

    def extract_one_tipo(
        self,
        tipo: str,
        period_start: str = "2021-01",
        period_end: str = "",
        on_progress=None,
    ) -> Dict[str, List[Dict]]:
        """Extract just one tipoEntidad — enables incremental, resumable backfills
        (write each type as it completes instead of one 20-min all-or-nothing pass).

        *on_progress(msg)* is forwarded to the carteras loop so the caller can keep
        the sync heartbeat fresh during the long per-quarter aggregation.
        """
        saved = list(self._discovered_tipo_codes)
        self._discovered_tipo_codes = [tipo]  # truthy → bulk skips re-discovery
        try:
            return self.extract_all_entities_bulk(
                period_start=period_start, period_end=period_end, on_progress=on_progress)
        finally:
            self._discovered_tipo_codes = saved

    def extract_all_entities_bulk(
        self,
        period_start: str = "2021-01",
        period_end: str = "",
        on_progress=None,
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

        # Cambiarias (EIC) take a separate path: different endpoints, no
        # indicadores/solvencia, a dedicated mapper, and generic auto-registration.
        # The EIF flow below is left completely untouched.
        active = self._discovered_tipo_codes or []
        if active and all(t in EIC_TIPOS for t in active):
            return self._extract_eic_bulk(period_start, period_end)

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

        # Stressed-delinquency: 1 light row per entity per period, carries castigos
        # (write-offs) + carteraTotal → real castigos_pct. Slug uses a hyphen.
        logger.info("  Fetching stressed delinquency (indicadores/morosidad-estresada)...")
        morosidad_estresada = self._fetch_for_all_types(
            "indicadores/morosidad-estresada", period_start, period_end)
        logger.info(f"    → {len(morosidad_estresada)} records")

        # Credit-risk: a few rows per entity (tipoCartera × sector), carries deuda by
        # tipoCartera → real exposición inmobiliaria (Créditos Hipotecarios share).
        logger.info("  Fetching credit risk (indicadores/riesgo-credito)...")
        riesgo_credito = self._fetch_for_all_types(
            "indicadores/riesgo-credito", period_start, period_end)
        logger.info(f"    → {len(riesgo_credito)} records")

        # carteras/creditos is a huge loan-level cube; the full range at once 504s.
        # We aggregate sector HHI per (entity, quarter) by streaming ONE quarter at a
        # time and discarding the raw rows (memory-safe). Result keyed by short_name.
        logger.info("  Computing carteras metrics from carteras/creditos (per-quarter)...")
        carteras_metrics = self._compute_carteras_metrics(period_start, period_end, on_progress=on_progress)
        logger.info(f"    → carteras metrics for {len(carteras_metrics)} entities")
        loans: List[Dict] = []  # raw loan rows are never retained; metrics injected post-map

        all_data = income + balance + indicators + solvency + morosidad_estresada + riesgo_credito
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
        _SRC_NAMES = ["income", "balance", "indicators", "solvency",
                      "morosidad_estresada", "riesgo_credito"]
        entity_sources: Dict[str, Dict[str, List]] = {}
        for record_list, src_name in [
            (income, "income"), (balance, "balance"),
            (indicators, "indicators"), (solvency, "solvency"),
            (morosidad_estresada, "morosidad_estresada"),
            (riesgo_credito, "riesgo_credito"),
        ]:
            for record in record_list:
                api_ent = record.get("entidad") or record.get("Entidad") or ""
                short = entity_mapping.get(api_ent, "_unknown")

                if short not in entity_sources:
                    entity_sources[short] = {s: [] for s in _SRC_NAMES}
                entity_sources[short][src_name].append(record)

        # Step 5: Map each entity's data to SdqBankingData fields
        results: Dict[str, List[Dict]] = {}
        for short_name, sources in entity_sources.items():
            if short_name == "_unknown":
                continue

            periods = self._group_by_period(sources)

            entity_results = []
            for period_date, data in periods.items():
                try:
                    mapped = self._map_to_sdq_fields(data)
                    # Inject carteras-cube metrics aggregated period-by-period (avoids the
                    # 504 on the full range).
                    cm = carteras_metrics.get(short_name, {}).get(period_date)
                    if cm:
                        if cm.get("hhi") is not None:
                            mapped["hhi_sectorial_raw"] = cm["hhi"]
                        # Largest-debtors concentration (SIB "Mayores Deudores") fills the
                        # per-bank top-10 indicator that was N/D — numerator and denominator
                        # both from the cube (self-consistent). We deliberately do NOT touch
                        # cartera_vencida_90d / cartera_categoria_a: morosidad and %vigente
                        # already use the SIB pre-computed ratios, and overwriting them with
                        # cube figures distorts those indicators.
                        total = cm.get("total") or 0
                        mayores = cm.get("mayores") or 0
                        if total > 0 and mayores > 0:
                            mapped["cartera_total"] = total
                            mapped["suma_top10"] = mayores
                    mapped["period_end"] = period_date
                    mapped["period_type"] = (
                        "quarterly" if period_date.month in (3, 6, 9, 12) else "monthly"
                    )
                    mapped["source"] = "sib_api"
                    entity_results.append(mapped)
                except Exception as e:
                    logger.warning(f"Failed to map {short_name} {period_date}: {e}")

            # Migración: link each period's cartera_a_prev to the previous closed
            # period's category-A portfolio (chronological), so the migration
            # indicator can score the change in performing-loan share.
            entity_results.sort(key=lambda m: m["period_end"])
            prev_cat_a = None
            for m in entity_results:
                if prev_cat_a is not None:
                    m["cartera_a_prev"] = prev_cat_a
                if m.get("cartera_categoria_a") is not None:
                    prev_cat_a = m["cartera_categoria_a"]

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

    # ── Cambiarias (EIC) extraction ────────────────────────────

    def _extract_eic_bulk(self, period_start: str, period_end: str) -> Dict[str, List[Dict]]:
        """Extract intermediación cambiaria (EIC) balance + income for the active
        cambiaria types. Auto-registers every entity the feed returns (the EIC
        universe defines coverage) via the ``_entity_meta`` side-channel.
        """
        period_end = period_end or self._current_period()
        # The tipo CODE we queried with (ARC / AC). The SIB record's tipoEntidad
        # field holds the full Spanish NAME ("AGENTES DE..."), not the code, so we
        # must use the query code for the BankType mapping — both map to cambiaria.
        active = [t for t in (self._discovered_tipo_codes or []) if t in EIC_TIPOS]
        tipo_code = active[0] if active else "AC"

        balance = self._fetch_for_all_types("estados/situacion/eic", period_start, period_end)
        income = self._fetch_for_all_types("estados/resultados/eic", period_start, period_end)
        logger.info(f"  EIC: {len(balance)} balance, {len(income)} income records")

        by_ent: Dict[str, Dict[str, List]] = {}
        for src_name, recs in (("income", income), ("balance", balance)):
            for r in recs:
                ent = (r.get("entidad") or "").strip()
                if not ent or ent == "TODOS":
                    continue
                by_ent.setdefault(ent, {"income": [], "balance": []})[src_name].append(r)

        results: Dict[str, List[Dict]] = {}
        meta: Dict[str, Dict] = {}
        for ent, sources in by_ent.items():
            # EIC is monthly → group by exact month (NOT bucketed to the quarter, which
            # would mix months into one period and inflate stocks / scramble income).
            periods = self._group_by_exact_month({"income": sources["income"], "balance": sources["balance"]})
            out = []
            for period_date, data in periods.items():
                try:
                    mapped = self._map_eic_to_sdq_fields(data)
                    if not mapped.get("activos_totales"):
                        continue  # skip empty/near-empty periods
                    mapped["period_end"] = period_date
                    mapped["period_type"] = "quarterly" if period_date.month in (3, 6, 9, 12) else "monthly"
                    mapped["source"] = "sib_api"
                    out.append(mapped)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"EIC map failed {ent} {period_date}: {e}")
            if out:
                results[ent] = out
                meta[ent] = {
                    "sib_code": ent,
                    "tipo_entidad": tipo_code,  # ARC or AC → cambiaria
                    "nombre": cambiaria_display_name(ent),
                }

        results["_entity_meta"] = meta
        results["_unmatched"] = []
        results["_entity_names"] = []
        logger.info(f"  EIC extract complete: {len(meta)} cambiarias")
        return results

    @staticmethod
    def _map_eic_to_sdq_fields(period_data: Dict) -> Dict[str, Any]:
        """Map ONE PERIOD of EIC balance + income concept rows to the BankingData
        fields used by the cambiaria scoring path.

        Reads the **TODOS-cascade subtotal** of each node — never sums the children.
        The EIC tree carries, for every node, a subtotal row whose deeper levels are
        all ``TODOS`` (e.g. ``Activos/TODOS/…`` = total assets; ``Activos/Efectivo…/
        TODOS`` = cash subtotal). Summing the conceptoNivel children instead double-
        counts (subtotal + leaves); see lessons 2026-06-09/10. *period_data* must hold
        a single month's records (see ``_group_by_exact_month``) — mixing months
        inflates stocks and makes the income first-match non-deterministic.
        """
        balance = period_data.get("balance", [])
        income = period_data.get("income", [])

        def _sub(records, n1: str, n2: str = "TODOS"):
            """Value of node (n1[/n2]) read from its cascade subtotal row: this n1/n2
            with every deeper conceptoNivel == 'TODOS' (or absent)."""
            for r in records:
                if ((r.get("conceptoNivel1") or "").strip() != n1
                        or (r.get("conceptoNivel2") or "").strip() != n2):
                    continue
                if all((r.get(f"conceptoNivel{i}") or "TODOS").strip() == "TODOS"
                       for i in range(3, 8)):
                    try:
                        return float(r.get("valor") or 0)
                    except (TypeError, ValueError):
                        return None
            return None

        efectivo = _sub(balance, "Activos", "Efectivo y equivalentes de efectivo") or 0.0
        inversiones = _sub(balance, "Activos", "Inversiones") or 0.0
        # Net result of the year (YTD): the after-tax bottom line subtotal.
        resultado = _sub(income, "Resultado del ejercicio", "TODOS")
        if resultado is None:
            antes = _sub(income, "Resultado del ejercicio", "Resultado antes del impuesto")
            imp = _sub(income, "Resultado del ejercicio", "Impuesto sobre la renta")
            resultado = (antes or 0.0) + (imp or 0.0) if (antes is not None or imp is not None) else None

        return {
            "activos_totales": _sub(balance, "Activos", "TODOS"),
            "patrimonio_tecnico": _sub(balance, "Patrimonio", "TODOS"),
            "pasivos_exigibles": _sub(balance, "Pasivos", "TODOS"),
            "activos_liquidos": efectivo + inversiones,
            "cartera_bruta": _sub(balance, "Activos", "Cartera de créditos"),
            "utilidad_neta": resultado,
        }

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

    @staticmethod
    def _month_end(periodo: str) -> Optional[date]:
        """Parse a SIB 'YYYY-MM' period string to its month-end date.

        Used for EIC (cambiarias), which the SIB publishes **monthly** — each month
        must stay its own period so a quarter-end bucket holds only that month's data
        (bucketing to the quarter mixed Oct+Nov+Dec into Q4 → inflated stocks +
        non-deterministic income). Closing months (3/6/9/12) yield the quarter-end
        date, so the downstream quarterly filter keeps exactly the right snapshot."""
        if not periodo:
            return None
        try:
            parts = str(periodo).split("-")
            year, month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return None
        import calendar
        return date(year, month, calendar.monthrange(year, month)[1])

    def _group_by_exact_month(self, sources: Dict[str, List[Dict]]) -> Dict[date, Dict]:
        """Group records by their EXACT month (month-end date), not the quarter.

        Unlike ``_group_by_period`` (which buckets every month into its quarter-end
        and is correct only for quarterly feeds like EIF), this keeps each monthly EIC
        period separate. The caller marks closing months as quarterly; the sync then
        persists only those — each with a single month's records."""
        grouped: Dict[date, Dict] = {}
        for src_name, records in sources.items():
            for record in records or []:
                d = self._month_end(record.get("periodo") or record.get("Periodo") or "")
                if d is None:
                    continue
                grouped.setdefault(d, {}).setdefault(src_name, []).append(record)
        return grouped

    @staticmethod
    def _period_to_quarter_end(periodo: str) -> Optional[date]:
        """Parse a SIB 'YYYY-MM' period string to its quarter-end date."""
        if not periodo:
            return None
        try:
            parts = str(periodo).split("-")
            year, month = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return None
        if month <= 3:
            return date(year, 3, 31)
        if month <= 6:
            return date(year, 6, 30)
        if month <= 9:
            return date(year, 9, 30)
        return date(year, 12, 31)

    def _group_by_period(self, sources: Dict[str, List[Dict]]) -> Dict[date, Dict]:
        """
        Group data source responses by period date.

        SIB API returns many rows per entity per period (one per concepto/line item).
        We store lists of records per source and extract values by searching them.

        *sources* maps a source name (income, balance, indicators, solvency,
        morosidad_estresada, riesgo_credito, …) → its list of raw records.
        """
        grouped: Dict[date, Dict] = {}
        for src_name, records in sources.items():
            for record in records or []:
                # SIB API uses 'periodo' field in YYYY-MM format
                period_date = self._period_to_quarter_end(
                    record.get("periodo") or record.get("Periodo") or ""
                )
                if period_date is None:
                    continue
                grouped.setdefault(period_date, {}).setdefault(src_name, []).append(record)
        return grouped

    @staticmethod
    def _find_value_in_records(
        records: List[Dict],
        concepto_keywords: List[str],
        value_field: str = "valor",
        nivel1_filter: str = "",
        nivel2_filter: str = "",
        exact: bool = False,
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
        norm_keywords = [_norm(k) for k in concepto_keywords]
        for record in records:
            # Optional hierarchy filter: require conceptoNivel1/2 match first
            if nivel1_filter:
                if _norm(nivel1_filter) not in _norm(record.get("conceptoNivel1")):
                    continue
            if nivel2_filter:
                if _norm(nivel2_filter) not in _norm(record.get("conceptoNivel2")):
                    continue

            for cf in concepto_fields:
                concepto = _norm(record.get(cf))
                if not concepto or concepto == "TODOS":
                    continue
                for kw in norm_keywords:
                    # `exact` avoids matching near-duplicate names (e.g. the
                    # morosidad index vs its "(Capital)" variant).
                    if (concepto == kw) if exact else (kw in concepto):
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

        # The balance is a hierarchy: each conceptoNivel2 carries a conceptoNivel3=
        # TODOS subtotal PLUS its children. Keep only the subtotal rows so we never
        # double-count (that inflated activos → ROA≈0). All values are in pesos.
        bal_tot = [r for r in bal if _norm(r.get("conceptoNivel3")) in ("", "TODOS")]

        def _btot(n1: str):
            # Prefer the explicit conceptoNivel1 total (conceptoNivel2 == TODOS).
            for r in bal_tot:
                if _norm(r.get("conceptoNivel1")) == _norm(n1) and _norm(r.get("conceptoNivel2")) == "TODOS":
                    try:
                        return float(r.get("valor") or 0)
                    except (TypeError, ValueError):
                        pass
            # Fallback: sum the conceptoNivel2 subtotals (no double-count).
            tot, found = 0.0, False
            for r in bal_tot:
                if (_norm(r.get("conceptoNivel1")) == _norm(n1)
                        and _norm(r.get("conceptoNivel2")) not in ("", "TODOS")):
                    try:
                        tot += float(r.get("valor") or 0)
                        found = True
                    except (TypeError, ValueError):
                        pass
            return tot if found else None

        activos_totales = _btot("Activos")
        patrimonio_neto = _btot("Patrimonio")
        pasivos_exigibles = _btot("Pasivos")
        if pasivos_exigibles is None and activos_totales and patrimonio_neto:
            pasivos_exigibles = activos_totales - patrimonio_neto

        # 1.0 Cash & equivalents. The SIB renamed this concept: current statements
        # use "Efectivo y equivalentes de efectivo" (older ones "Fondos disponibles").
        caja_valores = fv(bal_tot, ["Efectivo y equivalentes de efectivo", "Fondos disponibles"],
                          nivel1_filter="ACTIVOS")
        inversiones = fv(bal_tot, ["Inversiones"], nivel1_filter="ACTIVOS")

        # 1.3 Cartera de créditos (gross and net)
        cartera_bruta = fv(bal_tot, ["CARTERA DE CR"],
                           nivel1_filter="ACTIVOS")
        cartera_neta = cartera_bruta  # Balance reports net after provisions

        # 2.1 Deposits — renamed to "Depósitos del público" (older: "Obligaciones con el público").
        depositos_totales = fv(bal_tot, ["Depositos del publico", "Obligaciones con el p"],
                               nivel1_filter="PASIVOS")
        pasivos_cp = depositos_totales  # Deposits are primarily short-term
        contingentes_balance = None  # not used: regulatory contingents live in APR

        # ══════════════════════════════════════════════════════════
        #  INCOME STATEMENT — Limited to net result only
        #  conceptoNivel2: "Resultado antes del impuesto" | "Impuesto sobre la renta"
        # ══════════════════════════════════════════════════════════

        # Pre-tax result. Must read the SUBTOTAL row (the cascade-TODOS convention:
        # conceptoNivel2="Resultado antes del impuesto" AND conceptoNivel3="TODOS"),
        # NOT a substring match — the latter returned the first matching row, which is
        # a leaf expense (e.g. "Otros gastos" = -403M), giving negative/bogus ROA/ROE.
        utilidad_neta = None
        for r in inc:
            if (_norm(r.get("conceptoNivel2")) == "RESULTADO ANTES DEL IMPUESTO"
                    and _norm(r.get("conceptoNivel3")) == "TODOS"):
                try:
                    utilidad_neta = float(r.get("valor") or 0)
                except (TypeError, ValueError):
                    utilidad_neta = None
                break

        # P&L LINE ITEMS NOT AVAILABLE from income endpoint.
        # We derive them from INDICATOR RATIOS × balance denominators.

        # ══════════════════════════════════════════════════════════
        #  SOLVENCY — Direct values from "componente" field
        #  EXACT names confirmed from API
        # ══════════════════════════════════════════════════════════

        # leverage (Basel) = capital_tier1 / exposicion_total — both from the
        # solvency endpoint, so the ratio is unit-safe even if those are in millions.
        apr = fv(sol, ["ACTIVOS Y CONTINGENTES PONDERADOS POR RIESGO CREDITICIO Y DEDUCCIONES"])
        capital_primario = fv(sol, ["CAPITAL PRIMARIO"])
        capital_tier1 = capital_primario
        riesgo_mercado = fv(sol, ["CAPITAL REQUERIDO POR RIESGO DE MERCADO"])
        exposicion_total = fv(sol, ["ACTIVOS Y CONTINGENTES PONDERADOS POR RIESGO CREDITICIO Y RIESGO DE MERCADO"])
        contingentes = None
        # patrimonio_activos = equity / assets → use accounting equity (balance, pesos).
        patrimonio_tecnico = patrimonio_neto

        # Pre-computed SIB ratios (%, dimensionless) — the engine prefers these.
        solvencia_pct = fv(sol, ["Indice de solvencia"], exact=True) or fv(ind, ["Indice de Solvencia"], exact=True)
        tier1_pct = fv(ind, ["Indice de Solvencia de Capital Primario"], exact=True)
        margen_pct = fv(ind, ["Margen de Intermediacion Neto"], exact=True)
        cost_income_pct = fv(ind, ["Gastos Operacionales / Ingresos Operacionales"], exact=True)

        # ══════════════════════════════════════════════════════════
        #  INDICATORS — 77 pre-computed ratios (%)
        #  Use to derive P&L absolute values and fill quality metrics
        # ══════════════════════════════════════════════════════════

        # Rentabilidad
        roa = fv(ind, ["ROA"])
        roe = fv(ind, ["ROE"])
        margen_intermediacion = fv(ind, ["MARGEN DE INTERMEDIACI"])

        # ROA/ROE are computed by US from the statements (utilidad_neta from the
        # income statement / balances), not lifted from the SIB ratio. Use the
        # period-end balance as the average-balance proxy.
        activos_promedio = activos_totales
        patrimonio_promedio = patrimonio_neto

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

        # Liquidez — liquid assets = cash & equivalents + investments, straight
        # from the balance (absolute values, like the cambiaria mapper).
        if caja_valores is not None or inversiones is not None:
            activos_liquidos = (caja_valores or 0.0) + (inversiones or 0.0)
        else:
            activos_liquidos = None

        # Cartera quality — from the pre-computed SIB ratios (the income/balance
        # statements lack loan-level detail; these are the only API source).
        # `exact` avoids the near-duplicate "(Capital)" variants.
        cartera_vigente_ratio = fv(ind, ["Cartera de Credito Vigente / Cartera De Credito Bruta"], exact=True)
        morosidad_idx = fv(ind, ["Indice de Morosidad mayor a 90 dias"], exact=True)
        cobertura_vencida_90 = fv(ind, ["Cobertura de Cartera de Credito Vencida Mayor A 90 Dias"], exact=True)

        cartera_vencida_90d = None
        cartera_categoria_a = None
        provisiones = None
        cartera_total = cartera_bruta
        if cartera_vigente_ratio is not None and cartera_bruta:
            cartera_categoria_a = cartera_bruta * (cartera_vigente_ratio / 100.0)
        if morosidad_idx is not None and cartera_bruta:
            cartera_vencida_90d = cartera_bruta * (morosidad_idx / 100.0)
        if cobertura_vencida_90 is not None and cartera_vencida_90d:
            provisiones = cartera_vencida_90d * (cobertura_vencida_90 / 100.0)

        # The cartera-quality ratios are the SIB pre-computed %s — the engine
        # prefers these directly (dimensionless, no unit issue).
        morosidad_pct = morosidad_idx
        cartera_vigente_pct = cartera_vigente_ratio
        cobertura_pct = cobertura_vencida_90

        # ── Cartera-quality from the dedicated SIB endpoints (fase 2) ──
        # castigos % from indicadores/morosidad-estresada (1 row/entity/period):
        # castigos / carteraTotal — both from the SAME endpoint → unit-safe ratio.
        castigos = None
        castigos_pct = None
        for r in period_data.get("morosidad_estresada", []):
            try:
                ct = float(r.get("carteraTotal") or 0)
                cg = float(r.get("castigos") or 0)
            except (TypeError, ValueError):
                continue
            if ct > 0:
                castigos = cg
                castigos_pct = round(cg / ct * 100, 4)
                break

        # real-estate exposure % from indicadores/riesgo-credito: gross debt in the
        # mortgage portfolio over total gross debt (same endpoint → unit-safe).
        re_debt = 0.0
        tot_debt = 0.0
        for r in period_data.get("riesgo_credito", []):
            try:
                d = float(r.get("deuda") or 0)
            except (TypeError, ValueError):
                continue
            if d <= 0:
                continue
            tot_debt += d
            if "HIPOTECARIO" in _norm(r.get("tipoCartera")):
                re_debt += d
        exposicion_re_pct = round(re_debt / tot_debt * 100, 4) if tot_debt > 0 else None

        # Income-diversification HHI from the estado de resultados tree (nivel4 subtotals).
        hhi_ingresos_raw = self._income_hhi_raw(inc)

        # hhi_sectorial_raw is injected post-map (aggregated from carteras/creditos,
        # per-quarter, in extract_all_entities_bulk). exposicion_re/suma_top10/
        # cartera_a_prev as absolutes are not published at this grain.
        suma_top10 = None
        hhi_sectorial_raw = None
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

            # Pre-computed SIB ratios (%, dimensionless) — engine prefers these.
            "solvencia_pct": solvencia_pct,
            "tier1_pct": tier1_pct,
            "morosidad_pct": morosidad_pct,
            "cartera_vigente_pct": cartera_vigente_pct,
            "cobertura_pct": cobertura_pct,
            "margen_pct": margen_pct,
            "cost_income_pct": cost_income_pct,
            # Cartera-quality ratios (fase 2) — each from a single SIB endpoint.
            "castigos_pct": castigos_pct,
            "exposicion_re_pct": exposicion_re_pct,
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
    """Resolve ``(api_key, base_url, proxy_url, proxy_secret)`` for the SIB
    banking source from the in-app settings (Postgres), with env/config fallbacks.

    The source is matched by sector (``find_banking_source``) — provider id
    ``sb_do`` preferred, else any enabled banking provider (country DO first) —
    so the operator can name the provider anything in the Configuración screen.
    """
    from shared.database.session import SessionLocal
    from shared.settings import service as settings_service

    db = SessionLocal()
    try:
        creds = settings_service.get_sib_credentials(db)
        base_url = (creds["base_url"] or "https://apis.sb.gob.do/estadisticas/v2").rstrip("/")
        return creds["api_key"], base_url, creds["proxy_url"], creds["proxy_secret"]
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
