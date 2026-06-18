// Label maps for the ESG/climate UI (sector & dimension display names).
// The sector scores themselves come from the backend (no fixture dataset).

export const SECTOR_NAMES: Record<string, string> = {
  turismo: "Turismo",
  energia: "Energía",
  agropecuario: "Agropecuario",
};

export const DIM_LABELS: Record<string, string> = {
  physical_risk: "Riesgo físico",
  transition_risk: "Riesgo de transición",
  adaptive_capacity: "Capacidad de adaptación",
  governance: "Gobernanza",
};

export const MATERIALITY_TONE: Record<string, "ok" | "warn" | "alert"> = {
  baja: "ok",
  media: "warn",
  alta: "alert",
};
