import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from "axios";

const API_BASE = "/api/v1";

// withCredentials: la sesión viaja en cookies httpOnly (brecha 2 del DD) — el JS ya
// no guarda ni adjunta tokens; el navegador manda la cookie solo.
const client = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

/* ── Request interceptor ──────────────────────────────────────── */

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // Idioma para las narrativas IA (el backend lo lee vía dependencia global).
  if (config.headers) {
    config.headers["X-Lang"] = localStorage.getItem("lang") || "es";
  }
  return config;
});

/* ── Response interceptor: auto-refresh on 401 (vía cookie) ───── */

// Endpoints de auth donde un 401 es respuesta final (nunca se reintenta con refresh):
// login con credenciales malas, el propio refresh vencido, logout.
const AUTH_PATHS = ["/auth/login", "/auth/refresh", "/auth/logout"];

let isRefreshing = false;
let failedQueue: Array<{
  resolve: () => void;
  reject: (err: unknown) => void;
}> = [];

function processQueue(error: unknown) {
  failedQueue.forEach((p) => {
    if (error) p.reject(error);
    else p.resolve();
  });
  failedQueue = [];
}

function redirectToLogin() {
  // Nunca redirigir estando YA en /login: un /me 401 ahí causaría un loop de recargas.
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

/**
 * Una ruta de API que NO existe devuelve **HTTP 200 con el HTML del SPA**, porque el
 * mismo servicio sirve la aplicación y la API: el catch-all del frontend atiende antes
 * que el 404. Axios lo resuelve como éxito, el componente lee un campo de una cadena de
 * HTML y obtiene `undefined` — y revienta en el primer `.toFixed()`, `.map()` o `.length`.
 *
 * Pasó de verdad: la consola de Operaciones entera cayó con «Cannot read properties of
 * undefined» porque la réplica que atendió todavía no tenía el endpoint recién desplegado.
 * Le puede ocurrir a cualquier módulo durante cualquier despliegue.
 *
 * Convertirlo en un rechazo hace que el error aparezca donde el componente YA sabe
 * manejarlo —su estado de error— en vez de tumbar la pantalla.
 */
function esHtmlDeSpa(response: AxiosResponse): boolean {
  const tipo = String(response.headers?.["content-type"] ?? "");
  // ``config.url`` llega SIN la ``baseURL``, así que la ruta completa se arma con ambas:
  // mirar solo ``url`` dejaría fuera a todas las llamadas del cliente, que es el 100 %.
  const ruta = `${response.config?.baseURL ?? ""}${response.config?.url ?? ""}`;
  return tipo.includes("text/html") && ruta.includes("/api/");
}

client.interceptors.response.use(
  (response) => {
    if (esHtmlDeSpa(response)) {
      return Promise.reject(
        new Error(
          `La ruta ${response.config?.url} devolvió el HTML de la aplicación en vez de ` +
            "datos: el endpoint no existe en esta versión desplegada.",
        ),
      );
    }
    return response;
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };
    const url = originalRequest?.url ?? "";

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !AUTH_PATHS.some((p) => url.includes(p))
    ) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: () => resolve(client(originalRequest)),
            reject,
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // El refresh token viaja en su cookie httpOnly (path /api/v1/auth); body vacío.
        await axios.post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true });
        processQueue(null);
        return client(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError);
        redirectToLogin();
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  },
);

export default client;
