// UI label maps for the social-dev module. The data comes live from the backend
// (ONE poverty by region + WDI national health + declared rubric) via
// `/social-dev/indicators` and `/social-dev/dataset` — no fixture here.

// The 10 development regions (ONE). Names for display; slugs come from the API.
export const REGION_NAMES: Record<string, string> = {
  cibao_norte: "Cibao Norte",
  cibao_sur: "Cibao Sur",
  cibao_nordeste: "Cibao Nordeste",
  cibao_noroeste: "Cibao Noroeste",
  valdesia: "Valdesia",
  enriquillo: "Enriquillo",
  el_valle: "El Valle",
  higuamo: "Higuamo",
  ozama: "Ozama o Metropolitana",
  yuma: "Yuma",
};

// Etiquetas de dimensión del IDM. La página del eje (SocialDevPage) usa i18n
// (social.dims.*); este mapa lo sigue usando la página de la sección Datos
// (DatosSocialPage) hasta el sweep de la sección Datos.
export const DIM_LABELS: Record<string, string> = {
  health: "Salud",
  education: "Educación",
  living_standards: "Nivel de vida",
  inclusion: "Inclusión",
};

// Which variables back each IDM dimension — to derive the real-vs-rubric tag per
// dimension from the dataset's `sources` map.
export const IDM_DIM_VARS: Record<string, string[]> = {
  health: ["life_expectancy", "child_mortality"],
  education: ["literacy_rate", "schooling_years", "secondary_coverage"],
  living_standards: ["income_per_capita", "poverty_rate"],
  inclusion: ["financial_inclusion", "informality_rate"],
};
