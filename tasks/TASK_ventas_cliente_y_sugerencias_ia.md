# Tarea — Ventas del cliente + sugerencias de acción de la IA (brand_intel)

Para: Claude Code. Tipo: feature nueva (ingesta de una serie propietaria del cliente +
capa de recomendación gobernada + head-to-head plan-del-cliente vs sugerencia-IA).
Origen: Ricardo compartió el informe DIRECTAMENTE con McDonald's (ya no vía Ipsos).
Comentarios buenos y oportunidad comercial directa. McDonald's preguntó, textual:

> "Si tuvieras data de ventas se agregaría más profundidad al informe? Se puede sugerir
> algunos planes o puntos de acción de la lectura?"

Respuesta de Ricardo (compromisos que esta tarea debe cumplir, no reinterpretar):
- Sí a ambas. Hoy el sistema está **limitado a que no sugiera**; se puede habilitar.
- **En cada nueva subida de estudio se prueban LOS DOS**: los planes del cliente y los
  que sugiera la IA.
- Que la IA **haga estimaciones basadas en estadística y datos, que no invente sin
  información que lo valide**.
- Los datos de ventas deben ser **del mismo período de las olas**.

## Estado de entrada (bloqueo)

**BLOQUEADA hasta que McDonald's entregue el archivo de ventas.** El formato real decide
el parser; no escribir un parser especulativo. Al recibirlo: mirar el archivo primero,
luego implementar. Lo que sí se puede adelantar sin el archivo: el motor de correlación
(sobre serie sintética en tests), el registro de sugerencias y el head-to-head.

Pedir al cliente, junto al archivo: granularidad (mensual/semanal/diaria), alcance
(sistema completo vs por tienda/región), qué mide cada columna (ventas netas, tickets/
transacciones, unidades), moneda y si incluye impuestos, y si el corte por período es
comparable con la ventana de campo de cada ola.

## Decisiones de diseño (a confirmar con Ricardo solo si algo choca)

1. **Las ventas son dato PRIVADO del cliente**, como el tracker: viven en el encargo
   (`engagement_id`), fuera del catálogo y de la Data API, nunca agregadas con otros
   clientes ni usadas para benchmarks cruzados. Es material más sensible que el tracker
   — el aislamiento no se relaja en ningún endpoint.
2. **Las ventas NO entran al ledger de decisiones como una métrica más del tracker.**
   Son una serie propia (`BrandSalesPoint`) con su propia cadencia: el tracker mide
   percepción con base muestral; las ventas son censo del operador y no tienen umbral
   de detección muestral. Confundirlas rompería la disciplina de señal.
3. **La sugerencia de la IA es opt-in POR ENCARGO** (`suggestions_enabled`), apagada por
   defecto. El registro `REGISTER_NEUTRO` prohíbe hoy el vocabulario de recomendación
   (upside/timing) por doctrina de la casa; habilitarlo para todos sería cambiar la voz
   de 15 módulos. Se habilita donde el cliente lo pidió y se declara en el documento.
4. **Toda sugerencia nace ANCLADA o no nace.** Cada una lleva: la evidencia que la
   sostiene (indicadores del tracker, movimiento de ventas, factor macro — todos del
   contexto servido), la métrica con la que se verificaría, y el umbral que la haría
   comprobable. Una sugerencia sin ancla no se publica: se descarta en el ensamblado.
5. **Head-to-head**: las sugerencias de la IA se registran en el MISMO ledger que los
   planes del cliente, con `origin` (`cliente` | `sdq_ia`). Así, ola tras ola, el mismo
   motor de veredictos evalúa a ambos y el informe puede decir cuál acertó — que es
   exactamente lo que Ricardo prometió probar en cada subida.
6. **Portón humano igual que los planes**: la IA propone, una persona adopta. Nada
   sugerido llega al informe del cliente sin adopción explícita.

## Cambios

### A. Ingesta de ventas del cliente

**A.1 Modelo** `BrandSalesPoint` + migración: engagement_id, period_start/period_end
(la ventana real del dato), grain (`mensual`|`semanal`|`diario`), scope (`sistema` o
etiqueta de tienda/región), net_sales (Float, moneda del encargo), transactions
(Integer, nullable), units (Integer, nullable), currency, source_document_id, note.
Índice por (engagement_id, period_start). Unicidad por (engagement_id, scope, grain,
period_start) para que resubir corrija en vez de duplicar.

**A.2 Ingesta** `ingest/sales.py`: parser de Excel/CSV (el formato real manda; empezar
por lo que entregue McDonald's). Reglas duras:
- Validar que los períodos **calzan con las ventanas de campo de las olas** (
  `BrandWave.period_date` y el rango de campo si está): una serie desalineada produce
  correlaciones falsas. Lo que no calza se reporta como fila rechazada con su motivo,
  igual que la extracción de cifras, y NO se guarda.
- Staging + confirmación humana (patrón `BrandExtraction`): las ventas alimentan
  aritmética, así que llevan el mismo portón que las cifras del tracker.
- Moneda y cobertura declaradas; sin ellas la serie no se promociona.

**A.3 API + UI**: `POST /engagements/{slug}/sales` (subir), `GET .../sales` (serie),
panel «Ventas del cliente» junto a Planes, con la tabla de lo cargado y su cobertura
por ola. Aislamiento por engagement en todas.

### B. Motor de lectura de ventas (DETERMINISTA)

`engines/sales_link.py` — la aritmética, nunca el LLM:
- **Serie deflactada**: ventas nominales → reales con el mismo deflactor del ticket
  (`engines/deflate.py`, inflación BCRD del contrato macro). Un crecimiento nominal con
  inflación de 5.35% puede ser caída real; decirlo es medio producto.
- **Ventas por ola**: agregación al calendario de olas (suma del período de campo o del
  trimestre calendario — declarar cuál) para poder cruzar con el tracker.
- **Cruce percepción↔ventas**: por cada indicador núcleo, la co-variación con las ventas
  reales a lo largo de las olas disponibles. **HONESTIDAD ESTADÍSTICA (crítico)**: con
  2-5 olas NO hay potencia para una correlación defendible. El motor debe declarar el
  n y decir "insuficiente para inferencia" cuando lo sea (misma lección que el IC por
  cross-section en `lessons.md` 2026-06-19). Lo que sí se puede afirmar con pocas olas:
  dirección concordante/discordante y magnitud del movimiento — sin p-valores.
- **Descomposición del movimiento de ventas**: cuánto es precio (ticket) y cuánto es
  tráfico (transacciones), cuando el archivo trae transacciones. Es la lectura que el
  tracker NO puede dar y las ventas sí — probablemente el mayor aporte del dato nuevo.
- **Elasticidad observada**: si hay serie suficiente, cuánto se mueven las ventas por
  punto de penetración. Declarada como observación histórica, no como ley.

### C. Sugerencias de la IA (capa nueva, gobernada)

**C.1 Modelo** `BrandSuggestion` (o `BrandDecision.origin` + `suggested_*`): claim,
evidencia (lista de referencias a lo que la sostiene), métrica de verificación,
umbral propuesto, ola de evaluación propuesta, `status` (propuesta|adoptada|descartada),
`adopted_decision_id`. Y `BrandEngagement.suggestions_enabled` (bool, default False).

**C.2 Generación** — thin template `brand_action_suggestions` + doctrina:
- Contexto: TODO lo ya calculado (explicaciones, atribución, filtro de señal, plan del
  cliente con sus brechas, ventas con su lectura determinista). Cero datos crudos.
- REGLA DURA DE ANCLAJE: cada sugerencia declara (a) la evidencia del contexto que la
  sostiene, (b) la métrica que la verificaría y (c) el movimiento esperado. Si no puede
  declarar las tres, no la emite. El ensamblador descarta las que lleguen incompletas
  (garantía estructural, no confianza en el prompt).
- REGLA DURA DE CIFRAS/ESTIMACIONES (compromiso de Ricardo): una estimación solo se
  publica si se deriva de cifras servidas y el motor puede recomputarla; nada de
  proyecciones libres. Si la sugerencia requiere un dato que no existe, la sugerencia
  ES pedir ese dato.
- Máximo 3-5 sugerencias priorizadas. La disciplina de umbral aplica: una sugerencia
  cuyo efecto esperado es sub-detectable se declara como tal (misma vara que los planes
  del cliente — no se le baja el estándar a la IA porque sea nuestra).
- Registro: `suggestions_enabled` habilita el vocabulario de recomendación SOLO en esta
  sección y SOLO en ese encargo. `REGISTER_NEUTRO` no se relaja globalmente.

**C.3 Sección del informe** «Qué sugerimos y contra qué se mide» (opt-in): prosa, no
tabla (doctrina 2026-08-01), con las sugerencias adoptadas y su forma de verificación.
Si el encargo no tiene sugerencias habilitadas, la sección no existe.

### D. Head-to-head cliente vs IA

- `BrandDecision.origin` (`cliente`|`sdq_ia`) — migración con default `cliente`.
- `evaluate_decisions` y `plan_readiness` agrupan por origen.
- Cuando haya veredictos (Ola 5+), la narrativa puede leer el marcador: cuántas de cada
  origen se cumplieron, cuántas resultaron no detectables. **Sin declarar ganador con
  n pequeño**: 3 aciertos de 4 no es evidencia de nada, y decirlo es parte del producto.

### E. El informe con ventas

- Sección «Ventas y percepción» (o dentro de «Lectura del trimestre», decidir al ver el
  volumen real): la lectura determinista de ventas reales, precio vs tráfico, y la
  concordancia con lo que el tracker mostró. Esto es lo que responde el "¿agregaría más
  profundidad?" de McDonald's: el tracker dice qué piensa la gente, las ventas dicen qué
  hizo, y el cruce es la capa que nadie más les está dando.
- Límites: la cobertura de la serie, el n de olas, y la advertencia de no-causalidad.

## Salvaguardas — no negociables

- Ventas = dato privado del cliente; jamás sale del encargo ni alimenta agregados.
- Las ventas llevan portón humano (alimentan aritmética).
- Ninguna sugerencia sin anclaje llega al documento (garantía en el ensamblador).
- La honestidad estadística manda sobre la vistosidad: con pocas olas, no hay
  correlación publicable — se dice.
- `REGISTER_NEUTRO` y `EPISTEMIC_STANDARD` no se relajan globalmente; el permiso de
  recomendar es por-encargo y declarado en el documento.
- Frontera con Ipsos intacta: SDQ no re-analiza su tracker. Ventas y sugerencias son
  territorio propio; el informe sigue sin competir con el estudio del proveedor.

## Antes de cerrar

E2E con el archivo real de ventas de McDonald's: cargar, verificar el calce con las
olas, generar el informe con las secciones nuevas y mostrárselo COMPLETO a Ricardo antes
de mergear. Verificar explícitamente que ninguna sugerencia publicada carece de
evidencia+métrica+umbral, y que ninguna cifra estimada deja de ser recomputable.

## Sensores

```bash
ruff check shared/narrative modules/brand_intel
pytest modules/brand_intel/tests/ shared/narrative/tests/ -v
mypy shared modules app | mypy-baseline filter
cd frontend && npm run build
alembic -c infrastructure/alembic.ini upgrade head && alembic ... downgrade -1 && ... upgrade head
```

## NO hacer en esta tarea

- No escribir el parser de ventas antes de ver el archivo real.
- No habilitar sugerencias globalmente ni relajar el registro de la casa.
- No publicar correlaciones con n insuficiente (ni p-valores con 2-5 olas).
- No mezclar ventas con la aritmética muestral del tracker (no tienen base muestral).
- No cerrar sin que Ricardo vea el informe completo con datos reales.
