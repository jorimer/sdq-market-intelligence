/** Shape of a contextual AI insight returned by the backend (best-effort).
 * `model_used === "static_fallback"` signals the deterministic fallback (no API key
 * or generation failed) — the UI degrades gracefully when it sees that sentinel. */
export interface AiInsight {
  text: string;
  model_used: string;
  from_cache: boolean;
}
