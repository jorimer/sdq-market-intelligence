// Illustrative sector dataset for IAI/SGPS (anchor sectors).
// Datos ilustrativos — en producción provienen de ONE/BCRD vía shared/data.

export const SECTOR_NAMES: Record<string, string> = {
  turismo: "Turismo",
  energia: "Energía",
  zonas_francas: "Zonas Francas",
};

export const SAMPLE_SECTORS: Record<string, Record<string, number>> = {
  turismo: {
    gdp_growth: 5.0, inflation_stability: 70, ease_of_business: 65, operating_cost: 40,
    labor_availability: 75, skills_index: 60, regulatory_quality: 62,
    regulatory_volatility: 30, sector_growth: 8.0, sector_size: 70,
  },
  energia: {
    gdp_growth: 4.0, inflation_stability: 68, ease_of_business: 55, operating_cost: 60,
    labor_availability: 50, skills_index: 65, regulatory_quality: 58,
    regulatory_volatility: 45, sector_growth: 6.0, sector_size: 60,
  },
  zonas_francas: {
    gdp_growth: 4.5, inflation_stability: 69, ease_of_business: 72, operating_cost: 45,
    labor_availability: 68, skills_index: 58, regulatory_quality: 66,
    regulatory_volatility: 25, sector_growth: 7.0, sector_size: 65,
  },
};

export const SGPS_INPUTS: Record<string, Record<string, number>> = {
  turismo: { historical: 75, structural: 80 },
  energia: { historical: 60, structural: 70 },
  zonas_francas: { historical: 70, structural: 76 },
};

export const IAI_LABELS: Record<string, string> = {
  macro: "Macro",
  business: "Negocios",
  talent: "Talento",
  regulation: "Regulación",
  sector: "Sector",
};

export const SGPS_LABELS: Record<string, string> = {
  historical: "Histórico",
  structural: "Estructural",
  acceleration: "Aceleración",
};
