# Línea base de validación del catálogo MIP

**Corrida:** 2026-08-19 · **Commit servido por producción:** `273ce5b` · **Evidencia:**
[`evidence/validacion_baseline_2026-08-19.json`](../evidence/validacion_baseline_2026-08-19.json)
**Cómo se reproduce:** `python scripts/capture_validation_baseline.py` (solo lee; el recálculo
se dispara con `python scripts/ops_trigger.py <operación>`).

Es la Fase 0 del [plan de cierre de brechas](PLAN_CIERRE_BRECHAS_VALIDACION.md): **ningún eje con
motor queda sin cifra vigente**. Las ocho operaciones de validación se recalcularon contra
producción hoy; antes de esto, cuatro reportes tenían sello de junio o julio.

## 1. Qué se recalculó

| Operación | Sello anterior | Sello nuevo | ¿Cambió la cifra? |
|---|---|---|---|
| `backtest` (banca) | 2026-08-17 | 2026-08-19 | no |
| `irmp-backtest` | 2026-07-27 | 2026-08-19 | no |
| `trade-backtest` | 2026-07-27 | 2026-08-19 | no |
| `esg-backtest` | 2026-06-27 | 2026-08-19 | no |
| `idm-convergent-validity` | 2026-08-10 | 2026-08-19 | no |
| `sector-gate-e` | 2026-07-11 | 2026-08-19 | no |
| `insurance-backtest` | 2026-08-17 | 2026-08-19 | no |
| `pension-backtest` | 2026-07-03 | 2026-08-19 | no |

El riesgo declarado en la certificación (§7: «hay que asumir que estas cuatro cifras pueden
moverse») **no se materializó**: IRMP, trade, ESG y sectorial devuelven exactamente lo mismo con
insumos de hoy. Eso no debilita el hallazgo de fondo —banca y seguros sí se habían movido, y
nadie se enteró— sino que acota cuáles reportes estaban además desactualizados en el dato.

## 2. Veredicto por eje

| Eje | Métrica | Valor | IC 95% | N | Eventos | Veredicto | Monótono |
|---|---|---|---|---|---|---|---|
| `banking_score` | Gini | **0,1615** | [0,083 · 0,242] | 1.693 | 301 | **concluyente** | **no** |
| `macro_political_risk` · gobernanza | Gini | **0,199** | [0,045 · 0,355] | 260 | 82 | **concluyente** | sí |
| `macro_political_risk` · crédito | Gini | 0,08 | [−0,052 · 0,21] | 288 | 129 | no concluyente (contraste declarado) | — |
| `trade_intel` · colapso exportador | Gini | **0,232** | [0,093 · 0,373] | 314 | 87 | **concluyente** | sí |
| `trade_intel` · macro externo | Gini | 0,03 | [−0,094 · 0,158] | 338 | 177 | no concluyente (contraste declarado) | — |
| `esg_climate` | Spearman | **−0,509** | [−0,782 · −0,084] | 24 países | — | **concluyente** | sí |
| `social_dev` | Spearman vs IDHr | **0,891** | [0,51 · 1,0] | 10 regiones | — | **concluyente (convergente)** | — |
| `pension_intel` · retorno | Gini | **0,1594** | [0,0988 · 0,2173] | 1.590 | 665 | **concluyente — pero no legible por API** | no |
| `pension_intel` · solvencia | Gini | −0,0044 | [−0,2296 · 0,2445] | 96 | 42 | no concluyente | no |
| `insurance_intel` · solvencia | Gini | 0,0927 | [−0,0751 · 0,2817] | 164 | 81 | **no concluyente** | no |
| `insurance_intel` · underwriting | Gini | 0,1563 | [−0,0148 · 0,3382] | 163 | 80 | **no concluyente** | no |
| `sector_intel` (IAI) | IC medio anual | **−0,03** | [−0,267 · 0,208] | 160 | — | **nulo/negativo** | — |
| `monetary_policy` (TPM) | macro-F1 | 0,5654 | — | panel 191 | — | **parcial** (empata al baseline en accuracy) | — |
| `tourism` · `free_zones` · `construction` · `energy` · `telecom` · `agribusiness` · `law` | — | — | — | — | — | **sin motor** | — |

**Cero ejes con motor y sin cifra vigente.** Nueve motores, nueve cifras del 19-ago —salvo el TPM,
cuyo reporte es del 07-ago y es el **único del catálogo que ya se invalida por evento**
(`bcrd-comunicados-sync` dispara `tpm-model-train`), no por reloj.

## 3. Lo que la línea base deja anotado para las fases siguientes

1. **Pensiones tiene la señal más fuerte que nadie puede leer.** `return` es concluyente
   (Gini 0,1594 sobre 1.590 observaciones y 665 eventos: el N más grande del catálogo después de
   banca) y **no existe ruta de validación de pensiones en producción** — `GET /api/v1/pension-intel/validation`
   devuelve el HTML del SPA con 200. → Fase 3.
2. **La curva de banca sigue en U.** Sólida 23,1 % (n=516) · Adecuada 13,7 % · En vigilancia 9,9 % ·
   Frágil 27,6 %. El caveat automático la sigue llamando «ruido muestral en tiers intermedios». → Fase 2.
3. **El reporte de seguros no publica sello.** `GET /api/v1/insurance-intel/validation` no expone
   `generated_at`: es el único eje donde ni siquiera se puede saber de cuándo es la cifra que se
   está sirviendo. → Fase 1.
4. **El disclaimer del IRMP dice «5 países (N pequeño)»** mientras el mismo reporte declara
   `n_countries: 24` y 260 observaciones. El 5 son los pares de validez convergente contra S&P. → Fase 3.
5. **Dos motores no admiten agenda por diseño** (`insurance-backtest` y `pension-backtest` son
   `on_demand`), así que «habilitar el schedule» no es la cura: la cura es la cascada
   `triggers=[...]` que `sector_intel` ya usa (`sector-snapshot` → `sector-gate-e`) y que
   `rescore` → `backtest` **no** tiene. → Fase 1.
