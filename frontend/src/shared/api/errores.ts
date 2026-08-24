/**
 * Punto ÚNICO para convertir un error de la API en un mensaje que se le pueda mostrar a
 * alguien.
 *
 * **El caso que lo motivó.** FastAPI permite que `detail` sea texto, pero también un OBJETO o
 * una LISTA, y el backend usa las tres formas:
 *
 * - `str` — lo normal (`raise HTTPException(400, detail="...")`).
 * - `dict` — el 402 de upsell (`{message, tier, required_tier, user_tier}`) y el 429 de cuota
 *   de la API de datos (`{code, message, message_en, retry_after_seconds}`).
 * - `list` — el 422 de validación, que FastAPI arma solo: `[{loc, msg, type}, ...]`.
 *
 * Cada pantalla lo leía a mano, y las dos formas de leerlo mal estaban repartidas por todo el
 * frontend:
 *
 * 1. `detail || fallback` → con un objeto devuelve el OBJETO, que React no sabe renderizar
 *    («Objects are not valid as a React child») o imprime como `[object Object]`.
 * 2. `typeof detail === "string" ? detail : fallback` → no rompe, pero TIRA el mensaje que el
 *    backend sí mandó y muestra un genérico. Así, un usuario sin el plan para un Deep Dive
 *    leía «No se pudo cargar el producto» en vez de qué plan necesitaba: un problema de
 *    permisos disfrazado de falla técnica.
 *
 * `VigilarButton` ya resolvía el caso del 402 —bien— y ninguna otra pantalla se enteró. Es el
 * patrón de siempre: la lección vive en un archivo y el defecto reaparece en el de al lado.
 * Por eso esto es una función compartida con un test estructural detrás
 * (`errores.regla-estructural.test.ts`), y no una nota.
 */

/** Forma mínima de un error de axios; se lee defensivamente porque puede no serlo. */
type ErrorConRespuesta = {
  response?: { status?: number; data?: { detail?: unknown } };
};

function textoNoVacio(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

/** El `detail` crudo del error, sin interpretar. Para quien necesite sus CAMPOS (el tier
 *  requerido de un 402, el `retry_after_seconds` de un 429) y no solo el mensaje. */
export function detalleDeError(e: unknown): unknown {
  return (e as ErrorConRespuesta)?.response?.data?.detail;
}

/** El código HTTP del error, si lo hubo. `undefined` en un fallo de red. */
export function estadoDeError(e: unknown): number | undefined {
  return (e as ErrorConRespuesta)?.response?.status;
}

/**
 * Mensaje mostrable de un error de la API, sea cual sea la forma de su `detail`.
 *
 * Devuelve `fallback` cuando no hay nada que decir —un fallo de red, un cuerpo vacío, un
 * objeto sin `message`—: nunca `[object Object]`, y nunca un string vacío que deje el cartel
 * de error en blanco.
 */
export function mensajeDeError(e: unknown, fallback: string): string {
  const detail = detalleDeError(e);

  const texto = textoNoVacio(detail);
  if (texto) return texto;

  // 422 de FastAPI: lista de errores de validación. Se unen los `msg` legibles; si ninguno
  // lo es, el fallback — la forma interna (`loc`, `type`) no le dice nada a nadie.
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => textoNoVacio((d as { msg?: unknown })?.msg))
      .filter((m): m is string => m !== null);
    return msgs.length ? msgs.join(" · ") : fallback;
  }

  // 402 de upsell, 429 de cuota: el mensaje humano viaja en `message`.
  if (detail && typeof detail === "object") {
    return textoNoVacio((detail as { message?: unknown }).message) ?? fallback;
  }

  return fallback;
}
