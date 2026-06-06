// Illustrative sector ESG/climate dataset.
// Datos ilustrativos — en producción provienen de ONE ambiental + marcos TCFD/ISSB.

export const SECTOR_NAMES: Record<string, string> = {
  turismo: "Turismo",
  energia: "Energía",
  agropecuario: "Agropecuario",
};

export const SAMPLE_SECTORS: Record<string, Record<string, number>> = {
  turismo: {
    hurricane_exposure: 80, coastal_exposure: 90, carbon_intensity: 40, fossil_dependence: 55,
    adaptation_investment: 45, diversification: 50, disclosure_quality: 40, emissions_targets: 35,
  },
  energia: {
    hurricane_exposure: 50, coastal_exposure: 40, carbon_intensity: 85, fossil_dependence: 80,
    adaptation_investment: 55, diversification: 45, disclosure_quality: 60, emissions_targets: 55,
  },
  agropecuario: {
    hurricane_exposure: 70, coastal_exposure: 45, carbon_intensity: 55, fossil_dependence: 40,
    adaptation_investment: 35, diversification: 40, disclosure_quality: 30, emissions_targets: 28,
  },
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
