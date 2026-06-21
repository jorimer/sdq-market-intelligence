// IRC (climate resilience) UI maps — national, panel Caribe/LatAm.
// Las etiquetas de dimensión viven en i18n (esg.dims.*); aquí solo el mapeo de
// variables por dimensión (sin texto de UI).

// Which variables feed each IRC dimension (mirrors shared/doctrine/esg.yaml) —
// used to tag each dimension real-vs-rúbrica from the dataset's source map.
export const IRC_DIM_VARS: Record<string, string[]> = {
  physical_risk: ["hurricane_exposure", "climate_sensitivity"],
  transition_risk: ["fossil_dependence", "carbon_intensity"],
  adaptive_capacity: ["adaptation_readiness", "economic_readiness"],
  governance: ["governance_quality", "social_readiness"],
};
