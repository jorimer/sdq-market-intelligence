# Paridad Deep-Dive vs Fitch — Workstream

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

Impacto proyectado (datos reales prod): la ventaja de Reservas sobre el #2 **colapsa de 17.3 a 0.9 pts**
(su liderazgo era ~94% artefacto del min-max); Popular/Crecer suben de "En vigilancia" a "Adecuada".
+3 tests. Suite pensiones verde, ruff limpio.

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

### Fase 4 — Amplitud en banca (lo que pensiones ya tiene) ✅/🔍
- Trayectoria multi-período por indicador (SIMBAD histórico).
- Percentil vs el sistema por indicador (distribución de las ~81 entidades).
- Sección "Entorno Operativo" auto-generada desde el módulo Macro/BCRD.
- Tabla de sensibilidades simétrica (qué sube / qué baja el score, con umbral).

### Fase 5 — Pensiones: rentabilidad real + asterisco al titular ✅/🔍
- Deflactar la rentabilidad nominal por la serie de inflación del BCRD → retorno real (AI-native,
  dato propio). Ideal: ajuste por riesgo.
- Cargar el asterisco "relativo/parcial + inputs no confiables" a la portada/titular, no solo a §5.

### Fase 6 — Ejes estructurales (EN ALCANCE AHORA · diseño-primero) ⚠️
Decisión del dueño: se construye ahora, no se aplaza (excelencia sobre velocidad). "Diseño-primero"
es un requisito de calidad para un cambio arquitectónico, NO una postergación — el spec se escribe
dentro de este workstream.
- **Banca — capa de soporte/sistémico (arquitectura tipo Fitch VR/GSR/IDR):**
  - El score standalone se mantiene PURO (5 sub-componentes / vector 21-dim intactos) = análogo VR.
  - Nueva capa SEPARADA de soporte (importancia sistémica, propiedad estatal, cuota de depósitos) +
    techo soberano (cap). NO un 6º peso (rompería la suma-a-1 y el vector ML).
  - Salida en dos partes: fortaleza standalone + vista ajustada por soporte + cap soberano.
  - Requiere: spec corto (fuentes de importancia sistémica, regla del techo) antes de código.
- **Pensiones — normalización híbrida:** reemplazar el min-max puro por híbrido con anclas absolutas,
  para que el score comunique magnitud (no solo rango) y un outlier no re-ancle el panel. Depende de
  las distribuciones reales de Fase 0.

---

## Dependencias y secuencia (todo en alcance; el orden es por dependencia, no por prioridad)
- Fase 0 bloquea Fases 1, 2 y la parte de pensiones de la 6.
- Fases 3, 4, 5 no mutan scores y pueden ir en paralelo tras Fase 0.
- Fase 6 banca (capa de soporte) arranca con su spec en paralelo a Fase 0; su código entra tras
  estabilizar el score standalone (Fases 1-3) para no mezclar cambios.
