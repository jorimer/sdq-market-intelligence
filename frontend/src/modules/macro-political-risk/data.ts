// Illustrative regional peer set for the IRMP (DR + Central America + Caribbean).
// Datos ilustrativos — en producción provienen de WGI/BCRD vía shared/data.

export const COUNTRY_NAMES: Record<string, string> = {
  DO: "República Dominicana",
  CR: "Costa Rica",
  PA: "Panamá",
  GT: "Guatemala",
  JM: "Jamaica",
};

export const SAMPLE_REGIONAL: Record<string, Record<string, number>> = {
  DO: {
    gdp_cagr_3y: 4.8, inflation_gap: 1.2, fiscal_balance_gdp: -3.1, public_debt_gdp: 45.0,
    reserves_import_months: 5.6, current_account_gdp: -3.5, fdi_gdp: 3.4, fx_volatility: 3.0,
    sovereign_rating_score: 55, wgi_rule_of_law: 42, wgi_gov_effectiveness: 48,
    wgi_control_corruption: 38, electoral_uncertainty: 30,
    wgi_regulatory_quality: 45, regulatory_volatility_5y: 25,
    news_sentiment: 15, unrest_shocks: 20, sanctions_signal: 5,
  },
  CR: {
    gdp_cagr_3y: 3.6, inflation_gap: 0.8, fiscal_balance_gdp: -3.5, public_debt_gdp: 63.0,
    reserves_import_months: 6.0, current_account_gdp: -2.8, fdi_gdp: 4.0, fx_volatility: 4.5,
    sovereign_rating_score: 52, wgi_rule_of_law: 66, wgi_gov_effectiveness: 62,
    wgi_control_corruption: 68, electoral_uncertainty: 22,
    wgi_regulatory_quality: 64, regulatory_volatility_5y: 18,
    news_sentiment: 18, unrest_shocks: 16, sanctions_signal: 3,
  },
  PA: {
    gdp_cagr_3y: 5.4, inflation_gap: 0.6, fiscal_balance_gdp: -3.0, public_debt_gdp: 52.0,
    reserves_import_months: 4.2, current_account_gdp: -4.2, fdi_gdp: 5.1, fx_volatility: 1.5,
    sovereign_rating_score: 58, wgi_rule_of_law: 50, wgi_gov_effectiveness: 56,
    wgi_control_corruption: 44, electoral_uncertainty: 28,
    wgi_regulatory_quality: 58, regulatory_volatility_5y: 22,
    news_sentiment: 8, unrest_shocks: 24, sanctions_signal: 12,
  },
  GT: {
    gdp_cagr_3y: 3.2, inflation_gap: 1.6, fiscal_balance_gdp: -1.8, public_debt_gdp: 30.0,
    reserves_import_months: 6.5, current_account_gdp: 1.5, fdi_gdp: 1.8, fx_volatility: 2.2,
    sovereign_rating_score: 46, wgi_rule_of_law: 28, wgi_gov_effectiveness: 34,
    wgi_control_corruption: 24, electoral_uncertainty: 45,
    wgi_regulatory_quality: 40, regulatory_volatility_5y: 35,
    news_sentiment: -10, unrest_shocks: 38, sanctions_signal: 8,
  },
  JM: {
    gdp_cagr_3y: 2.4, inflation_gap: 1.0, fiscal_balance_gdp: 0.3, public_debt_gdp: 72.0,
    reserves_import_months: 5.0, current_account_gdp: -1.2, fdi_gdp: 2.6, fx_volatility: 5.5,
    sovereign_rating_score: 48, wgi_rule_of_law: 45, wgi_gov_effectiveness: 50,
    wgi_control_corruption: 40, electoral_uncertainty: 25,
    wgi_regulatory_quality: 52, regulatory_volatility_5y: 20,
    news_sentiment: 12, unrest_shocks: 28, sanctions_signal: 4,
  },
};

// Las etiquetas de dimensión viven ahora en i18n (mpr.dims.*).
