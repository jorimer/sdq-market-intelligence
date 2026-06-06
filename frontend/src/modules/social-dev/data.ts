// Illustrative regional social dataset (development index).
// Datos ilustrativos — en producción provienen de ONE (censos/ENHOGAR/ENCFT).

export const REGION_NAMES: Record<string, string> = {
  nacional: "Nacional",
  santo_domingo: "Santo Domingo",
  cibao: "Cibao",
  sur_profundo: "Sur Profundo",
  este: "Este",
};

export const SAMPLE_REGIONS: Record<string, Record<string, number>> = {
  nacional: {
    life_expectancy: 74, child_mortality: 28, literacy_rate: 94, schooling_years: 9,
    income_per_capita: 9000, poverty_rate: 23, financial_inclusion: 56, informality_rate: 55,
  },
  santo_domingo: {
    life_expectancy: 76, child_mortality: 22, literacy_rate: 96, schooling_years: 11,
    income_per_capita: 12000, poverty_rate: 18, financial_inclusion: 65, informality_rate: 48,
  },
  cibao: {
    life_expectancy: 75, child_mortality: 25, literacy_rate: 93, schooling_years: 9,
    income_per_capita: 8800, poverty_rate: 24, financial_inclusion: 54, informality_rate: 57,
  },
  sur_profundo: {
    life_expectancy: 70, child_mortality: 40, literacy_rate: 88, schooling_years: 6,
    income_per_capita: 5000, poverty_rate: 38, financial_inclusion: 40, informality_rate: 70,
  },
  este: {
    life_expectancy: 74, child_mortality: 30, literacy_rate: 92, schooling_years: 8,
    income_per_capita: 9500, poverty_rate: 26, financial_inclusion: 52, informality_rate: 60,
  },
};

export const DIM_LABELS: Record<string, string> = {
  health: "Salud",
  education: "Educación",
  living_standards: "Nivel de vida",
  inclusion: "Inclusión",
};
