// UI label maps for the sectorial module. The sector data itself comes live from
// the backend (BCRD value added + macro contract + declared rubric) via the
// `/sector-intel/dataset` and `/{code}/latest` endpoints — no fixture here.

// Las etiquetas de dimensión/factor viven ahora en i18n (sector.iai.* / sector.sgps.*).

// Which variables back each IAI dimension — used to derive the real-vs-rubric tag
// per dimension from the dataset's `sources` map.
export const IAI_DIM_VARS: Record<string, string[]> = {
  macro: ["macro_exposure"],
  business: ["ease_of_business", "operating_cost"],
  talent: ["labor_availability", "skills_index"],
  regulation: ["regulatory_quality", "regulatory_volatility"],
  sector: ["sector_growth", "sector_size"],
};
