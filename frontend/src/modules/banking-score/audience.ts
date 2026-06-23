import { useCallback, useEffect, useState } from "react";

/** Audiencias del Cerebro de Insights (eje banking). Orientan SOLO el "y por tanto"
 * del insight de IA — los hechos y cifras no cambian. El default es el comité de crédito
 * (igual que el backend). Persisten en localStorage para toda la sesión del usuario. */
export const AUDIENCES = [
  "comite_credito",
  "entidad",
  "inversionista",
  "supervisor",
] as const;

export type Audience = (typeof AUDIENCES)[number];

export const DEFAULT_AUDIENCE: Audience = "comite_credito";

const STORAGE_KEY = "sdq.banking.audience";

function readStored(): Audience {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v && (AUDIENCES as readonly string[]).includes(v)) return v as Audience;
  } catch {
    /* localStorage no disponible → default */
  }
  return DEFAULT_AUDIENCE;
}

/** Audiencia seleccionada, persistida en localStorage. */
export function useAudience(): [Audience, (a: Audience) => void] {
  const [audience, setAudienceState] = useState<Audience>(readStored);

  // sincroniza entre instancias abiertas del drawer en la misma pestaña
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setAudienceState(readStored());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setAudience = useCallback((a: Audience) => {
    setAudienceState(a);
    try {
      localStorage.setItem(STORAGE_KEY, a);
    } catch {
      /* persistencia best-effort */
    }
  }, []);

  return [audience, setAudience];
}
