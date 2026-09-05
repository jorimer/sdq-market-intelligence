/**
 * Cloudflare Worker — proxy para fuentes detrás de un WAF
 * =======================================================
 * Reenvía peticiones desde Railway hacia emisores cuyo WAF bloquea las IPs de
 * datacenter. Los Workers corren en el borde de Cloudflare, con IPs que esos
 * WAF sí aceptan.
 *
 *   Railway → Cloudflare Worker → emisor
 *
 * Hoy sirve a DOS emisores, y los dos fueron medidos, no supuestos:
 *   - apis.sb.gob.do  — Superintendencia de Bancos (RD). WAF de Sucuri.
 *   - api.cmfchile.cl — Comisión para el Mercado Financiero (Chile). Desde una
 *     IP de escritorio responde con sus códigos propios (421/422); desde el
 *     datacenter devolvía 500 con una página «Web Page Blocked!» de 39 KB.
 *
 * `ALLOWED_TARGET_HOSTS` es la puerta: agregar una fuente detrás de un WAF del
 * lado Python y olvidarse de esta lista produce un 403 que NO viene del emisor.
 * Lo vigila `shared/settings/tests/test_la_lista_del_worker_y_el_catalogo.py`.
 *
 * No agrega límite de tasa propio: eso lo maneja cada cliente en la aplicación.
 *
 * Seguridad: secreto compartido (PROXY_SECRET), guardado como secret en
 * Cloudflare y NO en este archivo. Sobrevive a los despliegues.
 *
 * Los códigos discriminan a propósito, y el backend los lee así:
 *   401 → el secreto del proxy está mal. La petición no salió.
 *   403 → el destino no está en ALLOWED_TARGET_HOSTS. La petición no salió.
 *   cualquier otro, con cabecera `X-Proxy-Status` → responde el EMISOR.
 * Solo lo REENVIADO lleva esa cabecera; su ausencia en un error significa que
 * el rechazo es del Worker. De ahí sale `_has_proxy_relay` en el backend.
 *
 * Desplegar: ver README.md de esta carpeta (tiene dos trampas conocidas).
 */

// ── Configuration ──────────────────────────────────────────────
const ALLOWED_ORIGINS = [
  "https://sdq-financial-agent-production-be41.up.railway.app",
  "http://localhost:8000",
  "http://localhost:5173",
];

const ALLOWED_TARGET_HOSTS = [
  "apis.sb.gob.do",
  // CMF de Chile, para el boletín regional. Mismo obstáculo que el SIB y medido igual:
  // desde una IP de escritorio el emisor responde con sus códigos propios (421 «API key
  // no valida», 422 «no suministrada»); desde el datacenter devolvía 500 con una página
  // «Web Page Blocked!». La credencial viaja en la QUERY STRING (?apikey=…), no en un
  // header, así que no hay nada que reenviar aparte de la URL.
  "api.cmfchile.cl",
];

const MAX_REQUEST_TIMEOUT = 30000; // 30s

// ── Main Handler ───────────────────────────────────────────────
export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return handleCORS(request);
    }

    // Health check
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(
        JSON.stringify({
          status: "healthy",
          service: "sib-api-proxy",
          timestamp: new Date().toISOString(),
        }),
        { status: 200, headers: jsonHeaders(request) }
      );
    }

    // Main proxy endpoint
    if (url.pathname === "/proxy" && request.method === "POST") {
      return handleProxy(request, env);
    }

    // GET proxy — simpler alternative for direct URL passthrough
    // Usage: GET /proxy?url=https://apis.sb.gob.do/estadisticas/v2/...
    //        Headers: X-Proxy-Secret, Ocp-Apim-Subscription-Key
    if (url.pathname === "/proxy" && request.method === "GET") {
      return handleGetProxy(request, env, url);
    }

    return new Response(
      JSON.stringify({
        error: "Not found",
        endpoints: {
          "GET /health": "Health check",
          "POST /proxy": "Proxy SIB API request (JSON body with url + headers)",
          "GET /proxy?url=<target_url>": "Direct proxy (pass SIB headers directly)",
        },
      }),
      { status: 404, headers: jsonHeaders(request) }
    );
  },
};

// ── POST /proxy handler ────────────────────────────────────────
async function handleProxy(request, env) {
  // Validate proxy secret
  const secret = request.headers.get("X-Proxy-Secret");
  if (!secret || secret !== env.PROXY_SECRET) {
    return new Response(
      JSON.stringify({ error: "Unauthorized — invalid or missing X-Proxy-Secret" }),
      { status: 401, headers: jsonHeaders(request) }
    );
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return new Response(
      JSON.stringify({ error: "Invalid JSON body" }),
      { status: 400, headers: jsonHeaders(request) }
    );
  }

  const { url: targetUrl, headers: targetHeaders = {}, method = "GET" } = body;

  if (!targetUrl) {
    return new Response(
      JSON.stringify({ error: "Missing 'url' in request body" }),
      { status: 400, headers: jsonHeaders(request) }
    );
  }

  // Validate target host
  try {
    const parsedUrl = new URL(targetUrl);
    if (!ALLOWED_TARGET_HOSTS.includes(parsedUrl.hostname)) {
      return new Response(
        JSON.stringify({
          error: `Target host '${parsedUrl.hostname}' not allowed`,
          allowed: ALLOWED_TARGET_HOSTS,
        }),
        { status: 403, headers: jsonHeaders(request) }
      );
    }
  } catch {
    return new Response(
      JSON.stringify({ error: "Invalid target URL" }),
      { status: 400, headers: jsonHeaders(request) }
    );
  }

  // Forward request to SIB API
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), MAX_REQUEST_TIMEOUT);

    const resp = await fetch(targetUrl, {
      method: method.toUpperCase(),
      headers: {
        ...targetHeaders,
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) FinancialAnalyst/1.0",
      },
      signal: controller.signal,
    });

    clearTimeout(timeout);

    // Stream response back
    const responseHeaders = jsonHeaders(request);
    responseHeaders["X-Proxy-Status"] = String(resp.status);
    responseHeaders["X-Proxy-Target"] = targetUrl.split("?")[0]; // URL without params

    const responseBody = await resp.text();

    return new Response(responseBody, {
      status: resp.status,
      headers: responseHeaders,
    });
  } catch (err) {
    const isTimeout = err.name === "AbortError";
    return new Response(
      JSON.stringify({
        error: isTimeout ? "Upstream timeout (30s)" : `Proxy error: ${err.message}`,
        target: targetUrl.split("?")[0],
      }),
      {
        status: isTimeout ? 504 : 502,
        headers: jsonHeaders(request),
      }
    );
  }
}

// ── GET /proxy?url=... handler ─────────────────────────────────
async function handleGetProxy(request, env, url) {
  const secret = request.headers.get("X-Proxy-Secret");
  if (!secret || secret !== env.PROXY_SECRET) {
    return new Response(
      JSON.stringify({ error: "Unauthorized — invalid or missing X-Proxy-Secret" }),
      { status: 401, headers: jsonHeaders(request) }
    );
  }

  const targetUrl = url.searchParams.get("url");
  if (!targetUrl) {
    return new Response(
      JSON.stringify({ error: "Missing 'url' query parameter" }),
      { status: 400, headers: jsonHeaders(request) }
    );
  }

  // Validate target host
  try {
    const parsedUrl = new URL(targetUrl);
    if (!ALLOWED_TARGET_HOSTS.includes(parsedUrl.hostname)) {
      return new Response(
        JSON.stringify({ error: `Target host '${parsedUrl.hostname}' not allowed` }),
        { status: 403, headers: jsonHeaders(request) }
      );
    }
  } catch {
    return new Response(
      JSON.stringify({ error: "Invalid target URL" }),
      { status: 400, headers: jsonHeaders(request) }
    );
  }

  // Forward SIB-related headers from the original request
  const forwardHeaders = {};
  const sibKey = request.headers.get("Ocp-Apim-Subscription-Key");
  if (sibKey) forwardHeaders["Ocp-Apim-Subscription-Key"] = sibKey;
  forwardHeaders["Accept"] = "application/json";
  forwardHeaders["User-Agent"] =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) FinancialAnalyst/1.0";

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), MAX_REQUEST_TIMEOUT);

    const resp = await fetch(targetUrl, {
      method: "GET",
      headers: forwardHeaders,
      signal: controller.signal,
    });

    clearTimeout(timeout);

    const responseHeaders = jsonHeaders(request);
    responseHeaders["X-Proxy-Status"] = String(resp.status);

    return new Response(await resp.text(), {
      status: resp.status,
      headers: responseHeaders,
    });
  } catch (err) {
    const isTimeout = err.name === "AbortError";
    return new Response(
      JSON.stringify({ error: isTimeout ? "Upstream timeout" : err.message }),
      { status: isTimeout ? 504 : 502, headers: jsonHeaders(request) }
    );
  }
}

// ── Helpers ────────────────────────────────────────────────────
function jsonHeaders(request) {
  const origin = request.headers.get("Origin") || "";
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers":
      "Content-Type, X-Proxy-Secret, Ocp-Apim-Subscription-Key, Authorization",
  };
  if (ALLOWED_ORIGINS.includes(origin) || origin.startsWith("http://localhost")) {
    headers["Access-Control-Allow-Origin"] = origin;
  }
  return headers;
}

function handleCORS(request) {
  return new Response(null, { status: 204, headers: jsonHeaders(request) });
}
