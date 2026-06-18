// Label maps for the IRC (climate resilience) UI — national, panel Caribe/LatAm.

export const DIM_LABELS: Record<string, string> = {
  physical_risk: "Riesgo físico",
  transition_risk: "Riesgo de transición",
  adaptive_capacity: "Capacidad adaptativa",
  governance: "Gobernanza",
};

// Which variables feed each IRC dimension (mirrors shared/doctrine/esg.yaml) —
// used to tag each dimension real-vs-rúbrica from the dataset's source map.
export const IRC_DIM_VARS: Record<string, string[]> = {
  physical_risk: ["hurricane_exposure", "climate_sensitivity"],
  transition_risk: ["fossil_dependence", "carbon_intensity"],
  adaptive_capacity: ["adaptation_readiness", "economic_readiness"],
  governance: ["governance_quality", "social_readiness"],
};
