# Paridad Deep-Dive vs Fitch — Workstream

> **WORKSTREAM COMPLETO (2026-07-01): las 6 fases cerradas y verificadas en prod.**
> Seguimientos diferidos (cada uno su ciclo): **A — rating soberano automatizado** (abajo);
> **B — ajuste por riesgo en pensiones** (abajo).

## Diferido B — Ajuste por riesgo en el ISA (volatilidad realizada del NAV) (2026-07-01)

**Problema:** el ISA puntuaba rentabilidad NOMINAL sin ninguna lectura de riesgo. La única
serie de retorno que ingeríamos (XLSX Estadística Previsional) es **trailing-12m suavizada**
→ sacar volatilidad de ahí sería deshonesto.

**Hallazgo de datos (investigación 2026-07-01):** el **valor cuota (NAV) mensual por AFP**
NO está en el XLSX ni en CKAN, sino en el **Boletín Trimestral PDF, Cuadro 6.4** (base 100 en
2003). Encadenando boletines → serie NAV mensual → retornos mensuales → **volatilidad realizada
honesta**. Cobertura limpia y uniforme = **30 meses (bols 82–91, 2023-10 a 2026-03)**; los
boletines viejos (72–81) usan un layout divergente que contamina (un bug de año infló σ ~8×) →
se acota a la ventana reciente y uniforme.

**Decisiones del dueño (calibración con dato real, antes de código):**
- **Métrica: Sharpe** (volatilidad TOTAL σ) — no Sortino: el downside deviation ≈ 0 (casi no
  hay meses negativos) lo haría degenerado. Tasa libre = **TPM del BCRD** (para el ratio en
  narrativa).
- **Integración: 5ª dimensión "Consistencia/Riesgo"** (σ, menor=mejor), re-peso **solvencia .35
  / rentab .25 / riesgo .15 / escala .15 / costo .10**. El ratio Sharpe se muestra en narrativa.
- **Ventana: 30 meses limpios.**
- **Calibración: híbrido 0.7·banda-absoluta + 0.3·min-max** (más absoluta que el 0.5 de Fase 6b),
  banda σ [0.5%→100, 6.0%→0]. La σ real está ultra-comprimida (0.80%–1.64%, en parte por
  valoración a costo amortizado → caveat), así que el min-max puro la amplificaría a 0-100.

**σ realizada y riesgo (calibración):** JMMB 0.80%→96.2, Atlántico 0.87%→92.8, Romana 0.90%→91.3,
Crecer 1.11%→81.2, Siembra 1.12%→80.7, Reservas 1.55%→59.9, Popular 1.64%→55.5.

**Impacto proyectado en el ISA (aprobado):** Reservas 75.03 **Sólida → 73.66 Adecuada** (2ª más
volátil; en términos ajustados por riesgo baja de banda — aceptado como el dato honesto). Romana
sube a #2 (63.94→71.66), Crecer pasa a Popular. Los dos más chicos suben (Atlántico +10.9, JMMB
+9.3, los más suaves) pero siguen Frágil (los arrastra escala/solvencia).

**Piezas:** `external/nav_extractor.py` (parser puro Cuadro 6.4 + fixture real), `nav_sync.py`
(encadena boletines → serie `valor_cuota`, op `sipen-nav-sync`), `scoring/isa.py` (dimensión
`riesgo` derivada: `_realized_vol` + `_score_riesgo`, MODEL_VERSION 0.2→0.3). Recompute prod =
proyección exacta (compute_isa live) + persistido vía `POST /pension-intel/sync`. **Follow-up:**
headline Sharpe en narrativa (presentación, no muta).

## Diferido A — Rating soberano automatizado + multi-agencia (2026-07-01)

**Problema:** el rating soberano vivía hardcodeado en `regulatory.yaml` (solo S&P) y se pudrió
en silencio — el `as_of` de RD quedó en 2022 sin que nadie lo notara. Alimenta dos consumidores:
el IRMP (`sovereign_rating_score`, dimensión external, 5 países) y el techo del overlay de banca
(Fase 6a). El síntoma no era el valor (BB→45 seguía correcto) sino la **frescura**.

**Diseño (decisiones del dueño, 2026-07-01):**
- **Fuente:** scraper GRATIS de Wikipedia "List of countries by credit rating" vía la MediaWiki
  API (`action=parse&prop=wikitext`; la API es la ruta permitida — el HTML crudo lo bloquea la
  política de bots con 403; requiere User-Agent descriptivo con contacto). Descartada Trading
  Economics (paga, US$149-299/mes, no se justifica para 5 países). `shared/data/sovereign_ratings_client.py`
  (parser puro + fixture real committeado).
- **Store refrescable:** los ratings se mueven del yaml a un `AppSetting` (`sovereign_ratings`),
  con el yaml como **piso/fallback**. `shared/contracts/sovereign_ratings.py` centraliza la
  lectura (patrón `macro_sector`): `combined_anchor()` la usan `support.sovereign_anchor()` y
  `wdi_client.declared_sovereign_records()`.
- **Combinación multi-agencia — "S&P manda":** el store carga S&P + Fitch + Moody's, pero **solo
  el ancla S&P** alimenta el índice; Fitch/Moody's viajan como CONTEXTO (panel de convergencia en
  el Deep Dive). Cambiar el ancla es la constante `ANCHOR_AGENCY`. **No muta ningún score** vs hoy
  (verificado: delta IRMP = 0). Notación Moody's → equivalente S&P para el contexto (`MOODYS_TO_SP`).
- **Fecha:** última **acción** (convención del yaml) + nota opcional de **afirmación** (anotación
  manual; Wikipedia no la trae).
- **Freshness que PROPONE:** la `data-freshness-audit` diaria ahora vigila el `action_date` del
  ancla en el STORE (no el piso) y propone re-verificar si supera 24 meses (dedupe ~mensual). El
  sistema propone; el humano dispone (nunca sobrescribe una nota).

**Operación:** `sovereign-ratings-sync` (mensual, `modules/macro_political_risk/operations.py`).
Flujo de propagación de un cambio de nota: `sovereign-ratings-sync` → `wdi-sync` → `irmp-snapshot`.
Preserva anotaciones `affirm_date` y reporta `anchor_changes` (el disparador del protocolo de impacto).

## Fase 6 — Ejes estructurales (2026-07-01) ✅ CERRADA Y VERIFICADA EN PROD

Diseño-primero (spec + anclas aprobadas por el dueño antes de código). Dos partes.

### Parte A — Banca: capa de soporte/sistémico + techo soberano (PR #411, NO muta el standalone)
Overlay estilo Fitch (VR/GSR/IDR) en el Deep Dive: soporte estatal + importancia sistémica +
techo soberano como CONTEXTO separado. El score SDQ standalone (score/tier/vector 21-dim) queda
PURO. **Decisión del dueño: contexto separado, SDQ intacto** — el SDQ es fortaleza relativa
dentro de RD, no crédito (Fase 3), así que no se le aplica un cap soberano que importe semántica
crediticia. `scoring/support.py`: `STATE_OWNED={Banreservas}` (set de config, sin migración),
importancia sistémica (cuota activos/depósitos + rank CR; sistémica=CR5), `sovereign_anchor()`
(techo RD = BB, S&P, 45/100, desde regulatory.yaml). Sección + tabla + thin template
(regla dura: es contexto, NO sube/baja el SDQ). Verificado prod: Banreservas estatal, sistémica
top-1 (cuota 31.2%/32.7%), techo BB 45/100, standalone SDQ-AA 86.72 intacto.

### Parte B — Pensiones: hardening del min-max del ISA (PR #412, MUTA el ISA)
Reemplaza el min-max PURO (bordes del pack a 0/100, outlier re-ancla) por un HÍBRIDO:
`0.5·banda_absoluta + 0.5·min-max` — magnitud (inmune a outliers) + discriminación relativa.
costo mantiene su banda propia. MODEL_VERSION 0.1→0.2. **Anclas aprobadas por el dueño**
(calibradas a la distribución real + economía): rentabilidad 5%→0/12%→100, solvencia
0.5→0/1.0→100, escala 10bn→0/500bn→100 (log). Verificado prod (recompute exacto vs proyección
aprobada): Reservas #1 (75.03, Sólida), Siembra 3→2, Romana 2→3 (min-max le inflaba rentab.),
Atlántico/JMMB ya no en 0; live (compute_isa) + persistido (/rankings) consistentes.

## Fase 5 — Pensiones: rentabilidad real + asterisco al titular (2026-07-01) ✅ CERRADA Y VERIFICADA EN PROD

Expresa la rentabilidad de las AFP en términos REALES (deflactada por inflación BCRD) y sube
el caveat "relativo/parcial" del §5 a la portada. **NO muta el ISA**: deflactar por una
inflación común a todas las AFP es un desplazamiento aditivo común → el min-max entre pares es
invariante. El retorno real es honestidad económica de presentación; el ISA sigue sobre nominal.

- **Plumbing cross-módulo (respeta el aislamiento):** `macro_monitor` persiste la SERIE de
  inflación interanual del BCRD en un `AppSetting` compartido nuevo (`macro_inflation_series`),
  junto al contrato (que solo trae el último valor). `shared.contracts.load_inflation_series`
  la lee; pensiones NO importa macro_monitor ni toca `mm_series`. Se popula al correr el snapshot
  macro (`POST /macro-monitor/refresh`).
- **`scoring/real_return.py`:** `fisher_real` ((1+n)/(1+i)−1), `inflation_at` (match exacto +
  carry-forward), `deflate_trend` (omite períodos sin inflación).
- **Presentación:** dimensión rentabilidad enriquecida con `raw_real` + inflación (score intacto);
  titular `· rentab. real ±X%`; caveat en el `subtitle` de portada; tabla "Trayectoria real vs
  nominal"; narrativa (`pension_entity`) lee el real.
- **Ajuste por riesgo: DIFERIDO** (necesita serie de volatilidad y SÍ cambiaría scores).
- Verificado prod (AFP Reservas, 2026-05): nominal 7.84% → real 2.36% (inflación 5.35%), score
  66.31 intacto; trayectoria real de 60 puntos deflactada con la inflación de cada período
  (2021-06 nominal 10.77% → real 1.33%); titular "rentab. real +2.4%" + caveat en portada;
  narrativa cita real+inflación. +7 tests (round-trip productor→consumidor). PR #409.

## Fase 4 — Amplitud en banca (2026-07-01) ✅ CERRADA Y VERIFICADA EN PROD

Porta al deep dive de banca la amplitud tipo-Fitch que ya tenía (parcialmente) pensiones,
sobre dato que ya poseemos. **Ningún cambio muta scores** (capa de presentación/narrativa).
Hallazgo rector: `narratives()`/`render()` operan SIN `db` (para muestras sintéticas) → todo
enriquecimiento derivado de DB se calcula en `BankingProduct.snapshot` y viaja en el
`scoring_result`. 3 PRs, cada uno verificado en prod contra Banreservas/BDI.

- **PR #405 — trayectoria + percentil por indicador** (Insight + Deep Dive). `scoring/amplitude.py`:
  `entity_trajectories` (serie del score global, sub-componentes e indicadores, un query del
  historial) + `period_percentiles` (percentil vs sector completo + mismo tipo, un query del
  período). Se cablean al cerebro (los thin templates YA pedían "percentil"/"trayectoria") y al
  PDF (columnas Percentil/Tendencia + tabla "Trayectoria del Score"). Verificado: Banreservas
  8 períodos, sector p76.5/tipo p75.0; BDI sector p77.8/tipo p81.2.
- **PR #406 — sección "Entorno Operativo"** (Deep Dive). Telón macro del BCRD vía el contrato
  compartido `AppSetting["macro_sector_contract"]` (sin importar `macro_monitor`; lector
  centralizado `shared.contracts.load_macro_contract`). Nuevo thin template
  `banking_operating_env` + tabla macro en PDF. Sin contrato → sección no se emite (no fabrica).
  Verificado: Banreservas 7 factores reales 2026-06 (inflación 5.35% adverso, IMAE 5.4%
  favorable, TPM 5.25%, depreciación −1.54% favorable, reservas +7.7%, deuda/PIB 62.4% adverso).
- **PR #407 — tabla de sensibilidades simétrica** (Deep Dive). `scoring/sensitivity.py`:
  palancas al alza / riesgos a la baja, **umbral en valor crudo** (inverso de la curva de
  `engine.py`, fijado por un test ROUND-TRIP de 16 curvas — si una se recalibra, CI falla) +
  Δ exacto al score global (recompute real con pesos por tipo + renormalización N/D). El cerebro
  ancla el umbral de acción (riesgo) y la palanca de mayor retorno (recomendación) en la tabla.
  Gatea entorno_operativo + sensibilidades a `tier==deep_dive` (Insight se queda con
  trayectoria+percentil). Verificado: Banreservas baseline_overall 86.72 = overall real
  (recompute exacto); solvencia <12.75% pierde banda (−1.2); Insight NO trae entorno/sensib.

Decisión de umbral (consultada al dueño, 2026-07-01): **valor crudo** (concreto tipo-Fitch),
no puntos de score — la fragilidad ante recalibraciones la cubre el test round-trip.

## Fase 3 — Framing/procedencia en banca (2026-07-01)

Portado de pensiones (que ya lo hacía). Capa de presentación — no muta scores.
- **Encuadre del score** (`products._LIMITATIONS_TEXT`, sección Limitaciones de cada deep dive):
  la calificación SDQ es **fortaleza financiera standalone** sobre dato público real; **NO es un
  rating de crédito**, no mide probabilidad de incumplimiento, y **no incorpora soporte soberano,
  importancia sistémica ni techo país** → no comparable con calificadoras internacionales. La escala
  SDQ-AAA…D ordena fortaleza relativa dentro del sistema RD, no riesgo de crédito absoluto.
- **`rating_scale.py`** docstring corregido (decía "10-tier credit rating system").
- **Nota de encuadre al cerebro** (`narrative._build_section_context`, secciones overview) para que la
  prosa AI no describa el score como rating crediticio.
- +1 test. Suite banca verde, ruff limpio.

## Fase 2 — Pensiones: costo del ISA (2026-07-01)

**Corrección del diagnóstico:** el audit inicial dijo "falso perfecto comisión≈0 → score 100 (guarda
solo chequea None)". **Falso.** Verificado en prod: `comisiones_anual` está poblado para las 7 AFP y
suma al total del sistema. El "0.0" era un **bug de unidades** — `comisiones_anual` en `RD$ MM`,
`fondos_administrados` en `RD$` → ratio ~6.5e-9 (muestra 0.0), real ~0.65%. AFP Reservas genuinamente
tiene la comisión/AUM más baja (0.65% vs 0.80–0.87%); su score=100 no era fabricado sino **min-max
amplificando un spread real de 0.2pp a un rango de 0-100**.

Fix (A+B+C):
- **A** — `isa.py`: ratio unit-aware (`_to_rd` usa el campo `unit`, `RD$ MM`↔`RD$`) + costo expresado
  como % → raw muestra 0.65%, no 0.0.
- **B** — `isa.py`: costo con banda **absoluta** (`_score_costo_absolute`, 0.4%→100 / 1.2%→0) en vez de
  min-max, para que un edge marginal no valga 100 pts.
- **C** — `financials_extractor`/`financials_sync`: comisiones cableadas del estado de resultados de la
  AFP (RD$, mismo período que AUM) → arregla frescura+unidades de raíz; la serie huérfana de 2025 (que
  ningún sync refrescaba) queda superada al próximo sync de financials.

**Verificado en prod (recompute del ISA):** AFP Reservas costo raw 0.6511 (0.65%, no 0.0) score 68.62;
ISA 82.49→77.79 (sigue #1 Sólida). La ventaja sobre el #2 (Romana 71.15) se comprime de **17.3 → 6.6 pts**
(−62%); Popular/Crecer suben de "En vigilancia" a "Adecuada". (La proyección previa de "0.9 pts" usó
`present_weight`=0.65 asumiendo solvencia ausente; en realidad solvencia está presente → coverage 1.0 →
costo pesa 15% del índice completo, no 23% de uno parcial. El fix de costo cuadró exacto.) +3 tests, suite verde.

**Objetivo:** llevar los deep dives SDQ·MIP (banca y pensiones) al estándar de amplitud y
correctitud de un informe Fitch, corrigiendo los defectos metodológicos verificados y portando
las mejores prácticas entre módulos.

**Origen:** comparación de deep dives SDQ vs Fitch para Banreservas y BDI (banca) + auditoría
interna del deep dive de AFP Reservas (pensiones, ISA). Fitch RD no publica deep dives de AFP,
así que pensiones es auditoría interna contra un estándar Fitch-grade.

**Principio rector:** excelencia sobre velocidad. Ningún cambio que mute scores en prod se
despliega sin re-correr el batch, medir cuántas entidades cambian de tier, y verificar los casos
testigo (Banreservas, BDI, AFP Reservas) antes del deploy.

---

## Hallazgos verificados en código

| # | Módulo | Hallazgo | Evidencia |
|---|--------|----------|-----------|
| 1 | Banca | `cost_to_income` es el único indicador con inversión lineal cruda `100−raw`, sin constante de calibración | `engine.py:312` |
| 2 | Banca | El valor es la definición **SIB** ("Gastos Op / Ingresos Op"), denominador más estrecho que el *total operating income* de Fitch → 78-81% vs 59-65% para el mismo banco | `sib_data_client.py:1807` + estados Fitch |
| 3 | Banca | La tabla comparativa del informe contrasta el valor SIB contra "media regional 55-65%" (definición-Fitch) = apples-vs-oranges | PDF deep dive §7 |
| 4 | Banca | La brecha de cobertura (281 vs 365) NO es de denominador (ambos usan >90d); es timing + alcance de provisiones | `engine.py` INDICATOR_REQUIRES `cobertura_provisiones` |
| 5 | Banca | El "bug branch 20-vs-43" NO existe en prod: el fallback `go/io` reconstruye el ratio SIB por álgebra | `sib_data_client.py:1853-1857` |
| 6 | Pensiones | Falso perfecto de costo: `comisiones_anual=0.0` presente pasa la guarda (solo chequea `None`) y con min-max invertido → score 100; infla el #1 y deflacta a las otras AFP | `isa.py:116`, `_normalize` |
| 7 | Pensiones | Más maduro que banca en framing, procedencia, trayectoria, tabla peer y limitaciones | PDF deep dive pensiones §5, portada |
| 8 | Ambos | La DB dev es data semilla sintética (`src=manual`, 2025-12-31, sin tablas de pensiones) → no sirve para calibrar | consulta directa a `data/sdq_market_intel.db` |

---

## Resultados validados (Fase 0a + fundamento Fase 1)

Vía SIMBAD público (`simbad.sb.gob.do`, dataset 34 `FINANCIERO`, sin auth). Corte 2024-09 (9m acum.).

- **Mapeo estilo-Fitch validado** (robusto, sin doble-conteo del árbol):
  - numerador = `Gastos operativos` (L4) — coincide al peso con "Operating costs" de Fitch (44,347 MM).
  - denominador = `Margen financiero bruto` (L5, pre-provisión) + `Otros ingresos operacionales` (L4).
  - La variante con margen *neto* se descarta: se rompe con provisiones volátiles (BDI dio 212%).
- **Testigos vs Fitch:** Banreservas 60.2% (Fitch 64.5% ✓) · BDI 53.8% (hoy publicamos 80.85% → corrección 27pp).
- **Distribución real del sistema** (n=43): p10=36.2 · mediana=61.7 · p90=91.0.
- **Curva calibrada propuesta:** lineal `raw 36%→score 100` … `91%→score 0` (clamp). Reemplaza el `100−raw`.
- **Impacto en tier (testigos, contra baseline REAL de prod, período 2026-03-31):**
  - Banreservas: cti 76.73 (score 23.3) → 60.2% (score 59.6) · overall **85.2 → ~86.6** (sigue SDQ-AA).
  - BDI: cti 79.06 (score 20.9) → 53.8% (score 72.4) · overall **85.3 → ~87.2** (sigue SDQ-AA).
  - ⚠️ Corrección: una estimación previa usó los scores del PDF (88.0/89.3, corte viejo) y proyectaba
    "BDI → SDQ-AA+". Con el dato real de prod (85.x) NINGÚN testigo gradúa. El diff exacto de las ~40
    afectadas lo da el batch post-deploy.
- **Cambiarias NO afectadas:** su `cost_to_income` es N/D (sin estado de resultados) → la curva no las
  toca. El "follow-up EIC" queda descartado como no-issue (verificado en prod: Agc Damos, Quezada).
- Afectados ≈ 40 entidades con estado de resultados; suben ~+1 a +2 pts; los pegados a un umbral
  (Popular 89.0, Scotiabank 83.2, varias AAyP/BAC ~80) cruzan tier hacia arriba — corrección esperada.

## Fase 1b — Fix de infra que bloqueaba el deploy (2026-07-01)

El primer `force` backfill en prod falló tras 1.9h con un bug **pre-existente** (ajeno al cambio de
cost_income): `NoReferencedTableError: FK 'banking_data.uploaded_by' → 'users'`. La ruta del worker
Celery no importaba el modelo `User`, así que la tabla `users` no estaba en `Base.metadata` al escribir.
Prod quedó intacto (la transacción no persistió).

Fix (Opción B — mínimo + optimización):
- **FK:** `sib_sync.py` importa `shared.auth.models` (registra `users`). Verificado: `create_all`
  resuelve el FK desde la ruta del worker.
- **`skip_carteras`:** flag nuevo a través de `extract_one_tipo`/`extract_all_entities_bulk` →
  `run_backfill` → `start_backfill_background` → task Celery → endpoints `/sib-sync` y `/sib-backfill`.
  Omite el cubo de carteras (504s, el cuello de botella que falló); re-ingesta income/balance/
  indicadores/solvencia y **preserva** las métricas de carteras existentes (el upsert solo escribe
  no-None). Re-ingest de minutos en vez de ~2h, y no vuelve a tocar el paso frágil.
- Re-run: `force=true · tipos=BM,AAP,BAC,CC · skip_carteras=true`. Suite 342 passed, ruff limpio.

## Fase 1c — Guard de trimestre parcial (2026-07-01)

Verificación post-deploy (período **2026-03-31**, 81 entidades, completo): Banreservas 85.2→**86.72**,
BDI 85.3→**87.14** — ambos SDQ-AA, **coincide con el pronóstico** (~86.6 / ~87.2). Fix de cost_income
correcto en prod.

Pero el `force` jaló el trimestre **2026-06-30** (cerró el día anterior), del que el SIB solo tenía
**19 de 81** entidades — parcial, y sin carteras (por `skip_carteras`), inflando el "latest". El guard
`period_end > today` no lo atrapa (ya es pasado). Fix de raíz: `prune_partial_latest_quarter` detecta
el trimestre recién-cerrado incompleto por **cobertura** (< 50% de las entidades del trimestre previo —
auto-calibrante, sin número mágico de rezago). Corre al final de `run_backfill` (tras ingesta, antes de
scoring) y en la op `prune-future` (limpieza inmediata sin re-sync). +2 tests.

## Plan de fases

Leyenda: 🔍 = verificación en prod / fuente pública (bloqueante · read-only) ·
⚠️ = muta scores en prod (requiere re-batch + diff de tiers + verificación pre-deploy) ·
✅ = seguro (solo presentación / narrativa)

### Fase 0 — Verificación (bloqueante, read-only)
- 🔍 **0a Banca:** correr el conector SIB contra la fuente pública para (i) confirmar si expone los
  componentes del estado de resultados (margen financiero + comisiones + otros ingresos operativos)
  necesarios para el cost-to-income estilo-Fitch, y (ii) obtener la distribución real del ratio para
  calibrar la curva. Sin (i) confirmado, Approach B necesita cablear el estado de resultados detallado.
- 🔍 **0b Pensiones:** sacar el `comisiones_anual` real de las 7 AFP en SIPEN/ADAFP para saber si el
  0.0 es solo de AFP Reservas o transversal, y con qué reemplazarlo.
- **Entregable:** histogramas reales + confirmación de disponibilidad de componentes.

### Fase 1 — Banca: cost-to-income estilo-Fitch (Approach B) ⚠️  ✅ CÓDIGO HECHO (pendiente deploy)
- ✅ `sib_data_client.py`: helpers `_subtotal_valor` / `_operating_income` extraen opex (Gastos
  operativos) + ingreso operativo pre-provisión (Margen financiero bruto + Otros ingresos
  operacionales) del estado de resultados real; scan robusto a profundidad + fallback neto+provisiones;
  real-o-N/D (no reintroduce la definición SIB).
- ✅ `engine.py`: `calc_cost_to_income` usa go/io real + curva calibrada `(90−raw)/0.5` (40%→100,
  90%→0); quitado `cost_to_income` de `INDICATOR_PCT_FIELD` (el ratio SIB ya no cuenta).
- ✅ `indicator_detail.py`: descripción actualizada a la definición Fitch-comparable.
- ✅ Tests: `TestCostToIncome` recalibrado + test testigo Banreservas (60.2%→59.6). Suite completa
  342 passed, ruff limpio.
- ⏳ **Relabel del informe:** no requiere código — la narrativa es AI-generada; con el valor en ~60%
  el "media regional 55-65%" pasa a ser legítimo automáticamente.
- ⏳ **Deploy (en curso):** merge #399 → re-SYNC banca en prod (re-ingesta componentes reales) →
  re-score → diff de tiers vs baseline capturado. Validación peso-a-peso contra el API SIB en vivo
  ocurre en este gate. Testigos esperados: Banreservas 85.2→~86.6, BDI 85.3→~87.2 (ambos SDQ-AA).
- ✅ **Cambiarias (EIC): NO afectadas** (verificado en prod) — su `cost_to_income` es N/D, la curva no
  las toca. No hay follow-up pendiente aquí.

### Fase 2 — Pensiones: guarda de integridad de comisión ⚠️
- Extender la guarda para rechazar valores económicamente imposibles (comisión ≈ 0 → N/D, se cae la
  dimensión, se renormaliza el peso), no solo `None`. Doctrina portada de banca.
- **Pre-deploy:** re-correr ISA, verificar si AFP Reservas conserva o cede el #1 sin el artefacto.

### Fase 3 — Framing + procedencia (cross-pollination) ✅
- **Pensiones → Banca:** portar el encuadre "score standalone, no es rating de crédito, no incorpora
  soporte soberano ni techo país" (incluye corregir el docstring de `rating_scale.py` que se
  autodenomina "credit rating system"); portar la columna de procedencia del dato; notas al pie de
  definición SIB en cobertura y eficiencia.

### Fase 4 — Amplitud en banca (lo que pensiones ya tiene) ✅ CERRADA Y VERIFICADA EN PROD (2026-07-01)
- ✅ Trayectoria multi-período por indicador (SIMBAD histórico) — PR #405.
- ✅ Percentil vs el sistema por indicador (distribución de las ~81 entidades) — PR #405.
- ✅ Sección "Entorno Operativo" auto-generada desde el módulo Macro/BCRD — PR #406.
- ✅ Tabla de sensibilidades simétrica (qué sube / qué baja el score, con umbral crudo) — PR #407.
- Detalle arriba (sección "Fase 4 — Amplitud en banca").

### Fase 5 — Pensiones: rentabilidad real + asterisco al titular ✅ CERRADA Y VERIFICADA EN PROD (2026-07-01)
- ✅ Deflactar la rentabilidad nominal por la serie de inflación del BCRD → retorno real — PR #409.
- ✅ Cargar el asterisco "relativo/parcial" a la portada/titular (subtítulo) — PR #409.
- Ajuste por riesgo DIFERIDO (cambiaría scores). Detalle arriba (sección "Fase 5").

### Fase 6 — Ejes estructurales ✅ CERRADA Y VERIFICADA EN PROD (2026-07-01)
- ✅ **Banca — capa de soporte/sistémico + techo soberano** (PR #411): overlay estilo Fitch
  VR/GSR/IDR como CONTEXTO separado; el standalone (score/tier/vector 21-dim) queda PURO.
  Decisión del dueño: contexto separado, SDQ intacto (no cap crediticio sobre una escala que no
  es de crédito). Detalle arriba (sección "Fase 6 · Parte A").
- ✅ **Pensiones — normalización híbrida** (PR #412): min-max puro → híbrido `0.5·absoluta +
  0.5·min-max`; comunica magnitud, un outlier no re-ancla. MUTA el ISA (anclas aprobadas por el
  dueño; recompute prod = proyección exacta). Detalle arriba (sección "Fase 6 · Parte B").

---

## Dependencias y secuencia (todo en alcance; el orden es por dependencia, no por prioridad)
- Fase 0 bloquea Fases 1, 2 y la parte de pensiones de la 6.
- Fases 3, 4, 5 no mutan scores y pueden ir en paralelo tras Fase 0.
- Fase 6 banca (capa de soporte) arranca con su spec en paralelo a Fase 0; su código entra tras
  estabilizar el score standalone (Fases 1-3) para no mezclar cambios.
