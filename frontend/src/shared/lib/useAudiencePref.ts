import { useCallback, useEffect, useState } from "react";

/** Audience preference persisted in localStorage, generic across axes. `storageKey`
 * namespaces it per axis (e.g. "sdq.sector.audience"); `options[0]` is the default. */
export function useAudiencePref(
  storageKey: string,
  options: readonly string[],
): [string, (a: string) => void] {
  const read = useCallback((): string => {
    try {
      const v = localStorage.getItem(storageKey);
      if (v && options.includes(v)) return v;
    } catch {
      /* localStorage no disponible → default */
    }
    return options[0];
  }, [storageKey, options]);

  const [audience, setState] = useState<string>(read);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === storageKey) setState(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [storageKey, read]);

  const set = useCallback((a: string) => {
    setState(a);
    try {
      localStorage.setItem(storageKey, a);
    } catch {
      /* persistencia best-effort */
    }
  }, [storageKey]);

  return [audience, set];
}
