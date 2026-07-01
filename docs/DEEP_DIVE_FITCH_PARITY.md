# Paridad Deep-Dive vs Fitch — Workstream

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
- **Impacto en tier (testigos):**
  - Banreservas: cti score 22→56, overall 88.0→**89.3** (firma dentro de SDQ-AA).
  - BDI: cti score 19→68, overall 89.3→**91.1** → **graduación SDQ-AA → SDQ-AA+**.
- Confirma que Fase 1 NO es cosmética: cambia al menos un tier.

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
- ⏳ **Pre-deploy (pendiente):** re-batch contra dato real, diff de tiers de las ~43 entidades,
  verificar Banreservas (→89.3, SDQ-AA) y BDI (→91.1, **SDQ-AA+**). La validación peso-a-peso contra
  el API SIB en vivo ocurre en este gate (los tests locales usan fixtures modelados de SIMBAD).
- ⚠️ **Follow-up:** las cambiarias (ruta EIC) aún no reciben el componente real; su `cost_to_income`
  se beneficia de la curva nueva pero su valor viene de otro mapeo — corregir en un paso aparte.

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
