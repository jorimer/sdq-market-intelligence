# PLAN MAESTRO DE DESARROLLO — SDQ·MIP

**Versión:** v1.2 · **Fecha:** 2026-06-16 · **Estado:** vigente
**Propósito:** Documento rector que Claude Code debe leer **antes de tocar cualquier módulo**. Define el ORDEN de las fuentes y la MECÁNICA ESTRICTA por etapa. No es un handoff (esos viven en `SESSION_HANDOFF.md`); es el contrato de cómo se construye cada eje de aquí en adelante.

> **Changelog v1.2 (2026-06-16):** (1) Eje 4 (IRMP) **cerrado** por los 6 gates, metodología validada (panel amplio 24 países). (2) Eje 3 **abierto**: la espina sectorial = **BCRD valor agregado por sector** (decisión del dueño), no la ONE — que publica poco y queda como enriquecimiento. **T-E3-1 (Gate A) cerrado en prod.** §1 actualizada. Origen: reconocimiento de fuentes 2026-06-16.
> **Changelog v1.1 (2026-06-15):** ONE/Eje 3 ahora exige consumir el **contrato macro→sectorial** (§3, fila ONE). Origen: decisión del dueño tras el diagnóstico de hardening de Eje 2 (`docs/DIAGNOSTICO_MACRO_Y_HARDENING_2026-06-15.md`).

---

## 0. Cómo usar este plan

1. Este plan **gobierna**. Si un handoff o un ticket contradice este documento, gana este documento (o se actualiza este documento explícitamente, con versión nueva).
2. Respeta las reglas de proceso del `CLAUDE.md` global: **Plan First** (escribir plan en `tasks/todo.md` y confirmar antes de implementar para tareas de 3+ pasos), **Verify Done con Sensors**, **Reviewer Subagent** antes de cerrar tareas no triviales, **Causa raíz** (no parches), **Impacto mínimo**, y **Lecciones** en `tasks/lessons.md` tras cada corrección.
3. **Fuente de verdad de datos = PROD (Railway).** La DB local de dev (`data/sdq_market_intel.db`, ~700 filas) es una muestra pequeña; no concluyas cobertura desde ahí. Verifica contra los endpoints de prod (`/data/overview`, `/data/sync-status`).
4. Ningún módulo se considera "hecho" hasta pasar **los cinco gates** de la §2. En particular: **una página sin insight de IA NO está terminada** (requisito del dueño, §5) y **un score sin backtest NO se comunica como predictivo** (§6).

### 0.1 Doctrina de calidad — criterio permanente (NO negociable)

**Minuciosidad sobre velocidad. La calidad no se sacrifica por rapidez, nunca.** Esta es la prioridad declarada del dueño y gobierna todo el desarrollo. Operacionalmente, para Claude Code:

- **Una tarea a la vez, con su gate.** Prohibido ejecutar un lote de tareas de corrido. Cada tarea: plan fino → confirmación del dueño → implementación → sensor → cierre. (Plan First del `CLAUDE.md` global.)
- **Leer el código real antes de editar.** No asumir props, firmas, internals ni comportamiento. Si el plan depende de un detalle no leído, leerlo primero. Un plan escrito sobre supuestos es un atajo.
- **Causa raíz, no parche.** Si una solución se siente hacky, reimplementar con la solución elegante "sabiendo lo que sé ahora". No se cierra sobre un parche temporal.
- **Evidencia, no afirmación.** Ninguna tarea se marca completa sin el output de su sensor mostrado. Si el sensor falla, no se cierra: se itera o se documenta por qué se acepta.
- **Cobertura de más, no de menos.** Ante la duda de si algo necesita test, verificación o revisión humana → la necesita.
- **Reviewer subagent en lo no trivial.** Cambios multi-archivo, lógica de negocio, contratos públicos, migraciones, y todo PR que toque `banking_score` (activo en prod) pasan por revisor fresco antes de cerrar.
- **Ante la disyuntiva rápido vs. impecable → impecable.** Una pieza fea con cifras correctas es preferible a una linda con métricas vagas. Si el alcance no cabe con calidad, se reduce el alcance, no la calidad — **pero ver la guarda anti-falsa-imposibilidad abajo: reducir alcance por una imposibilidad NO probada es la falla de calidad más común, no su solución.**
- **El dueño es no-técnico:** Claude Code ejecuta todo lo técnico; no se le delegan pasos de terminal/Railway salvo lo que solo él puede hacer (secretos/login).

### 0.2 Guarda anti-falsa-imposibilidad — el rigor de investigación NO es opcional

**El fallo histórico (verificado en `tasks/lessons.md`, líneas 123 y 198):** indicadores que se declararon "no publicados por el SIB" SÍ estaban — en slugs con guion, en árboles jerárquicos nivel 4-7, o **en un cubo que ya se estaba trayendo** (`carteras/creditos` para mayores deudores). La concentración top-10 quedó "N/D definitivo" ~4 sesiones por no investigar data que ya estaba en mano. Un 504 se leyó como "endpoint roto" cuando solo requería consulta acotada. **Causa raíz: investigación de una sola capa, superficial.**

**Regla dura.** Un *"no se puede" / "N/D" / "no existe el dato" / "fuera de alcance por imposibilidad"* es una **AFIRMACIÓN que debe ganar su barra de evidencia, exactamente como un dato.** Es el simétrico de "dato faltante = N/D, nunca fabricar": **dato alegado como inexistente = sospechoso, nunca asumir.** No se acepta una imposibilidad sin agotar:

- [ ] ¿Leíste el **catálogo/schema COMPLETO** de la fuente, no solo los endpoints obvios? (variantes de slug guion-vs-underscore, jerarquías profundas, parámetros no probados).
- [ ] ¿El dato ya está en **algo que YA estás trayendo**? (el cubo de carteras ya se streameaba para el HHI y traía mayores deudores).
- [ ] ¿Probaste **consultas acotadas** si la amplia da 504/timeout antes de concluir "roto"? (un trimestre / un tipo responde donde el rango completo falla).
- [ ] ¿Probaste **fuentes/portales alternativos del mismo emisor**? (el portal de supervisados de la SIB publica lo que la API de estadísticas no).
- [ ] ¿Agotaste, o te quedaste en la primera capa?

**Escalamiento, no decisión silenciosa.** Una imposibilidad **no se resuelve reduciendo alcance en silencio**: se **surfacea al dueño con el rastro de búsqueda** (qué se probó, qué devolvió). El dueño tiene conocimiento de dominio que repetidamente desbloqueó lo "imposible" (señaló el portal de supervisados; sugirió el ángulo del cubo). El humano es **activo de investigación, no solo aprobador**.

**Distinguir dos reducciones de alcance:**
- **Por DECISIÓN** (elegimos no hacerlo ahora, con rationale explícito) → legítima.
- **Por IMPOSIBILIDAD ALEGADA** (decimos que no se puede) → requiere la barra de arriba **+** surface al dueño. **Nunca silenciosa, nunca asumida.**

Anti-patrón con nombre: **"falsa imposibilidad"** / **"N/D prematuro"**. Tratarlo como bug, no como cierre aceptable.

### 0.3 Ambición AI-native — no estimar como humano, colapsar el costo marginal

> Memoria canónica: **`feedback-ai-native-ambicion`** (originada al enmarcar el ETL de 700 Excel del BCRD como "cientos de parsers a mano = meses"). Esta sección es su reflejo en el plan; si divergen, gana la memoria.

**El principio (la cara generativa).** El valor de usar a Claude **no es ejecutar trabajo manual más rápido** — es **volver tratable lo que para un humano es inviable**: analizar volúmenes enormes y heterogéneos e inferir estructura/relaciones a escala. Estimar una tarea en "horas-hombre de parsers a medida" es el anti-patrón exacto; es traer las trabas de un humano a un sistema que no las tiene.

**Cómo se aplica (concreto, no consigna):**
- Ante volumen/heterogeneidad, **NO defaultear a "es mucho, acotemos a un piloto".** Primero diseñar la solución AI-native que **colapsa el costo marginal por ítem**: p. ej. un parser auto-inferente, o usar a Claude para **interpretar la estructura de cada archivo y emitir config/series normalizadas a escala** (es lo que ya hizo el motor de ingesta del histórico BCRD).
- **Proponer además lo que la IA desbloquea más allá de cargar datos:** relaciones entre series, quiebres estructurales, narrativa sobre todo el corpus, auto-reparación. La ambición es parte del entregable.
- **Acotar solo por correctitud/validación, nunca por esfuerzo.** El alcance se reduce si un dato no se puede *validar*, no si "da mucho trabajo".

**La cara defensiva (corolario, familia §0.2).** Desistir/recortar por tamaño es **cierre prematuro disfrazado de esfuerzo** — hermano de la "falsa imposibilidad". Dos errores que lo delatan: (1) **calibración humana importada** ("esto toma semanas" = throughput humano, inexacto e irrelevante; Claude muele 113k filas o un catálogo entero en minutos/horas); (2) **el esfuerzo como excusa para abandonar** en vez de descomponer y ejecutar (o secuenciar con el dueño).

**Lo único legítimo de "esfuerzo":** como **insumo de priorización del dueño** (uso en §3: "Esfuerzo: bajo/medio/alto" para ordenar fuentes) — para informar la secuencia, jamás para rendirse. Y debe ser **ganado por investigación**, no adivinado.

**Aplicación directa a este proyecto (Gate A, §4):** al onboardear una fuente nueva (WGI, ONE, DGA), el default es **ingestión AI-native** (Claude infiere estructura → emite series normalizadas), no escribir parsers a medida archivo por archivo. El molde existe: el motor de ingesta del Excel histórico del BCRD.

**Disparador:** cada vez que estés por escribir "esto tomaría semanas", "son cientos de parsers a mano", "mejor un piloto acotado", "es demasiado para ahora". Antes: ¿estás trayendo trabas humanas? ¿cuál es la solución que colapsa el costo por ítem? ¿qué desbloquea la IA aquí más allá de cargar el dato?

---

## 1. Estado actual — ground truth (verificado 2026-06-20)

> **DISCIPLINA (directiva del dueño 2026-06-20):** este §1 se mantiene **siempre
> actualizado** — es la fuente de verdad del status del plan. Al cerrar cualquier
> gate/eje, actualizar esta tabla en el mismo ciclo, no después.

Madurez real por módulo. Esto es lo que existe, no lo que la spec promete.

| Eje | Módulo | Fuente de datos (live) | ¿Datos reales? | ¿Insight IA? | ¿Backtest (Gate E)? |
|----|--------|-----------------|----------------|:------------:|:----------:|
| 1 | `banking_score` | SIB/SIMBAD + OCR fiduciarias/cambiarias | ✅ histórico backfilled | ✅ | ✅ Gini+IC |
| 2 | `macro_monitor` | BCRD (API + Excel histórico) + publicaciones | ✅ histórico completo | ✅ | n/a (monitor) |
| 3 | `sector_intel` | BCRD valor agregado + ENCFT empleo + TSS salario | ✅ **5/5 dims live** | ✅ (#187) | ✅ **IC-mean honesto** (#211/#213) |
| 4 | `macro_political_risk` | WGI+WDI+IMF+GDELT/BigQuery | ✅ 18/23 real | ✅ | ✅ validado (24 países) |
| 5 | `trade_intel` | DGA aduanas + UN Comtrade | ✅ real | ✅ | ✅ resiliencia (#197) |
| 6 | `social_dev` | ONE (pobreza/IDM/educación) | ✅ real (Findex pend.) | ✅ | ✅ |
| 7 | `esg_climate` | ND-GAIN + HURDAT2 + Ember | ✅ real | ✅ | ✅ validado (IRC) |

> **LOS 7 EJES CERRADOS A PROFUNDIDAD (A–F), en prod (2026-06-20).** El núcleo del
> blueprint —7 ejes con dato real, insight IA explicable y backtest honesto, todo
> operable desde la UI— está construido y corriendo. Restos NO bloqueantes (polish
> opcional + diferidos por decisión) en `tasks/todo.md`. Lo único que separa
> "construido" de "lanzable" es el endurecimiento pre-go-live (seguridad), dejado
> para el final por decisión del dueño (2026-06-20).

**Gaps estructurales que este plan cierra:**
- **G1 — Insight IA ~~solo en Eje 1~~ → resuelto en Ejes 1/2/4 (2026-06-16).** Los componentes (`AiInsightCard`, `useTwoPhaseInsight`, `InsightDrawerShell`, `AiInsightBody`) se promovieron a `shared/ui/` (T1) y se cablearon en `macro_monitor` (T3) y `macro_political_risk` (Gate D). Pendiente: Ejes 3/5/6/7. → §5.
- **G2 — Capa de outcomes sin construir.** `shared/data/outcomes.py` es un dataclass de 25 líneas referenciado solo en `__init__.py`. El foso de Dato del Blueprint depende de esto. → §6.
- **G3 — Deal Scoring huérfano.** `Modelos Propietarios/deal_scoring.py` sigue fuera de `modules/`. IP sin capitalizar (fuera del alcance inmediato de este plan; registrar como deuda).
- **G4 — fuentes en fixture → CERRADO (2026-06-20).** Las 7 fuentes principales están live (BCRD, WGI/WDI/IMF/GDELT, ONE/ENCFT/TSS, DGA/Comtrade, ND-GAIN/HURDAT2/Ember). Solo queda **DGII** como enriquecimiento opcional (datos abiertos ODbL — no bloqueado; RNC contribuyente diferido por riesgo legal). → §3.

---

## 2. Principio rector: lifecycle estricto por fuente

Cada eje recorre **cinco gates en orden**. Ningún gate se salta. El gate define el *Definition of Done* parcial.

```
Gate A   Integridad de fuente      → conector live, replicable por período, validado
Gate B   Prueba de la data cruda   → tests + verificación humana de cifras contra el portal oficial
Gate C   Analytics + score         → features e índice del eje, explicable y modelable
Gate D   Insight de IA por página  → patrón SCQA replicado (requisito del dueño)
Gate E   Backtest / validación     → score validado contra outcomes realizados
Gate F   Operabilidad (TRANSVERSAL)→ toda operación recurrente vive en UI, monitoreada y agendable (§7)
```

**Regla dura:** se completa un eje **a profundidad** (A→E, con F transversal) antes de abrir el siguiente. No se construyen seis cascarones en paralelo. La excepción es la promoción de componentes compartidos (§5.1) y la consola de operación (§7), que se hacen **una sola vez** y benefician a todos.

> **Gate F es transversal, no la última etapa.** Aplica a Gate A (sync/backfill de fuente), a Gate E (refresh del backtest) y a cualquier acción que mantenga el dato vivo. Si la operación nace en el backend, nace incompleta hasta tener su superficie de operación humana.

---

## 3. Orden de ejecución de fuentes

Ordenado por **valor descendente** (esfuerzo vs. IP desbloqueada), no por conveniencia.

| Prioridad | Fuente | Desbloquea | Esfuerzo estimado | Razón |
|----------|--------|-----------|-------------------|-------|
| ~~En curso~~ ✅ | BCRD | Eje 2 macro + overlay Eje 1 | hecho | Cerrado (A–F). |
| ~~1~~ ✅ | WGI/WDI/IMF/GDELT | Eje 4 IRMP | hecho | Cerrado, validado 24 países. |
| ~~2~~ ✅ | ONE + ENCFT + TSS (Power BI) | Eje 3 sectorial | hecho | Cerrado (A–F); IAI 5/5 dims live; Gate E IC-mean honesto. |
| ~~3~~ ✅ | DGA + Comtrade | Eje 5 trade | hecho | Cerrado (A–F). |
| ~~ESG~~ ✅ | ND-GAIN+HURDAT2+Ember | Eje 7 ESG/IRC | hecho | Cerrado, validado. |
| **Polish (opcional)** | DGII datos abiertos · Findex · país-socio Comercio · skills/ease_of_business | enriquecimiento | bajo-medio | NO bloqueante. DGII: ver nota abajo. |
| Diferido (decisión) | DGII **RNC** (nivel contribuyente) · Deal Scoring · capa traducción macro | — | — | RNC tiene riesgo legal/privacidad real; el resto, decisión de alcance. |

> **DGII (corregido 2026-06-20):** la org DGII en datos.gob.do tiene **4 datasets, TODOS bajo ODbL** (misma licencia que DGA/CNZFE/ONE) → **los datos abiertos agregados NO están bloqueados**. El "license must be…" del código era conservador y aplica solo al **RNC a nivel contribuyente** (entidad), que tiene riesgo legal/privacidad y NO necesitamos. Datasets abiertos: *Recaudación Efectiva* (por **tipo de impuesto** × mes, 2017-2026 — pulso fiscal NACIONAL, no por sector), *Retenciones ISR Salarios* (tabla de retención), *Gastos Educativos*, *Parque Vehicular*. El de **recaudación por sector económico** vive en la sección de estadísticas de `dgii.gov.do` (scrape + verificar licencia), no en el portal abierto. Decisión de alcance pendiente (ver `tasks/todo.md`).

---

## 4. Gate A — Mecánica estricta de Integridad de Fuente

Checklist obligatorio, derivado de los modos de falla que la SIB ya nos enseñó (codificados desde `tasks/lessons.md`). **Cada fuente nueva pasa este checklist antes de Gate B.** No se redescubren estos bugs.

- [ ] **Conector vivo** hereda de `shared/data/base_client.py`; modo `fixture` solo como fallback explícito y declarado (nunca silencioso).
- [ ] **Paginación sin truncamiento silencioso.** Si una página falla, reintentar 3× antes de cortar; loguear FUERTE si trunca (lección SIB: el 504 a mitad perdía 49k filas y mataba el HHI de ingresos).
- [ ] **Consistencia de unidades** explícita y verificada (lección SIB: balance en pesos, indicadores en millones). Documentar la unidad de cada serie.
- [ ] **Matching robusto** de nombres de entidad/concepto: acento-insensible y tolerante a renombres del proveedor (lección SIB: `Índice`/`Crédito` con acento no matcheaban; el SIB renombró el plan de cuentas).
- [ ] **Sin doble conteo** en jerarquías (lección SIB: subtotal `TODOS` + hijos; sumar todo infla).
- [ ] **Replicabilidad por período**: re-correr el mismo período produce el mismo resultado (idempotente). Probarlo.
- [ ] **Linaje** registrado vía `shared/data/lineage.py`: origen, fecha de extracción, versión del dato. Sin restatements silenciosos.
- [ ] **Rezago de publicación** conocido y declarado (crítico para el backtest, §6). No interpolar sin disclosure.
- [ ] **Jobs en background** muestran progreso + estado compartido entre workers (regla del dueño). Errores user-facing **en español legible**, nunca excepción cruda.

**Sensor de cierre Gate A:** sync de un período arbitrario completo, `errors: []`, cifras de 1 entidad verificadas a mano contra el portal oficial.

---

## 5. Gate D — Mecánica estricta de Insights de IA por página *(requisito del dueño)*

**Objetivo:** toda página que construyamos debe ofrecer, para el analista-curador, un insight de IA explicable (framework SCQA) al nivel correcto (entidad / indicador / serie / sector / país). Ya está 100% funcional en el Eje 1; aquí se vuelve **patrón obligatorio replicable**, no un extra opcional.

### 5.0 Lo que YA existe y se reutiliza (no reinventar)
- **Motor:** `shared/narrative/claude_engine.py` → `narrative_engine.generate(context: dict, template: str, mode: str)` → `NarrativeResult{content (markdown), model_used, tokens, cost}`. Cachea ~1h por hash de contenido. **Best-effort**: si no hay API key o falla, cae a fallback estático y **nunca rompe la página**.
- **Templates SCQA ya definidos** (reusar, no crear nuevos salvo necesidad real): `executive_summary`, `risk_assessment`, `trend_analysis`, `recommendation`, `comparative`, `sector_outlook`, `indicator_insight`, `subcomponent_focus`, `entity_rating`.
- **Renderer:** `frontend/src/shared/ui/Markdown.tsx` (tablas GFM, theme-aware) — ya es compartido. ✅

### 5.1 PRIMER PASO obligatorio — promover componentes a `shared/`
Hoy `IndicatorDetailDrawer.tsx`, `EntityInsightDrawer.tsx` y `AiInsightCard.tsx` viven en `frontend/src/modules/banking-score/components/`. Esto repite el anti-patrón que ya sufrimos (la narrativa antes "encerrada en los PDF"). Antes de cablear IA en módulo nuevo:
- [ ] Extraer `AiInsightCard` y un `InsightDrawer` genérico (parametrizado por endpoint + render del cuerpo) a `frontend/src/shared/ui/`.
- [ ] Refactorizar `banking-score` para consumir los compartidos (sin cambio de comportamiento; sensor: `tsc` + build OK + verificación visual claro/oscuro).
- [ ] A partir de ahí, cada módulo importa de `shared/ui/`, no duplica.

### 5.2 Mecánica BACKEND por endpoint con IA
Patrón a copiar de `modules/banking_score/api/router_scoring.py`:
- [ ] Endpoint expone **carga en dos fases** vía `?with_ai=bool` (default `true`): `with_ai=false` devuelve la data determinista **al instante**; `with_ai=true` adjunta `ai_insight`.
- [ ] Helper best-effort local (espejo de `_ai_insight(context, template)`): envuelve `narrative_engine.generate` en try/except, loguea warning en español, devuelve `None` si falla. **La IA jamás tumba el endpoint.**
- [ ] Función `*_ai_context(detail) -> dict` que arma un contexto **compacto** (solo lo relevante a ese nivel: valores, tendencia, pares, impulsor/lastre). No volcar el objeto entero (lección Eje 1: SCQA del banco entero en cada sub-componente = repetitivo → se creó `subcomponent_focus` con contexto acotado).
- [ ] Elegir el template correcto por página (ver tabla 5.4).

### 5.3 Mecánica FRONTEND por página
Patrón a copiar de `EntityInsightDrawer.tsx`:
- [ ] Dos `useEffect`: el primero carga data (`with_ai=false`) y pinta de inmediato; el segundo dispara `with_ai=true` en background con estado `aiLoading` y placeholder **"Generando análisis de IA… (~10–15s)"**.
- [ ] Renderizar `ai_insight.content` con `<Markdown/>` de `shared/ui`.
- [ ] Degradación elegante: si `ai_insight` viene `null`, mostrar la data determinista sin hueco roto.

### 5.4 Asignación de nivel + template por eje
| Eje / página | Nivel de insight | Template SCQA |
|---|---|---|
| 2 `macro_monitor` — serie/snapshot | Por serie (IPC, FX, IMAE) + lectura de coyuntura | `trend_analysis` + `executive_summary` |
| 4 `macro_political_risk` — país/dimensión | Por país (IRMP) + por dimensión | `risk_assessment` + `recommendation` |
| 3 `sector_intel` — sector | Por sector (atractivo IAI / potencial SGPS) | `sector_outlook` |
| 5 `trade_intel` — flujo | Por flujo / socio comercial | `trend_analysis` |
| 6/7 `social_dev` / `esg_climate` | Por indicador | `indicator_insight` |

### 5.5 Retrofit pendiente
- [ ] **`macro_monitor` (Eje 2) ya tiene datos reales y CERO IA.** Es el primer retrofit, en paralelo al cierre de su Gate E.

**Sensor de cierre Gate D:** en la página, la data aparece al instante; el insight IA carga después; al cortar la API key cae a fallback sin romper; consola limpia; verificado en navegador claro/oscuro.

---

## 6. Gate E — Mecánica estricta de Backtest / Validación

**Tesis:** un score sin backtest es un número confiado sin evidencia. Para una marca de Confiabilidad, el reporte de validación **es el artefacto de venta**, no QA interno. Se cablea sobre `shared/data/outcomes.py` (`LabeledOutcome{entity_key, outcome_type, label, observed_at, score_at_prediction, note}`).

### 6.1 Disciplina point-in-time (lo que evita el auto-engaño)
- [ ] **Rezago de publicación**: el sello de tiempo del score = fecha de **disponibilidad** del dato, no fin-de-período. Un score "2026-Q1" no existe hasta ~mediados de 2026.
- [ ] **Sin look-ahead**: usar la cifra **originalmente publicada** (vía `lineage.py`), nunca restatements posteriores.
- [ ] **Fuera de muestra**: el componente **determinista** es OOS por construcción (no se entrena) → backtest directo. El **XGBoost** exige **walk-forward / ventana expansiva** (calibrar 2021–2023 → predecir 2024; expandir → 2025; …). Sin walk-forward, el AUC del XGBoost es ficción.

### 6.2 Definición de desenlace (3 capas, por base-rate bajo)
- [ ] **Duro** (raro, oro): intervención/disolución/exclusión del registro SIB, absorción forzada. Contarlos en el histórico (los handoffs mencionan EMPIRE/ACTIVO/REIDCO que salieron).
- [ ] **Blando** (frecuente, da poder estadístico): incumplimiento de mínimo de solvencia (10% RD) o liquidez; downgrade ≥2 escalones en escala SDQ en 4T; morosidad que duplica; ROA negativo sostenido 2+T. **Derivado del histórico SIB ya backfilled.**
- [ ] **Externo** (validación independiente): para el subconjunto con rating de agencia (Feller, Fitch RD, Pacific Credit Rating, SCRiesgo) — correlación y, sobre todo, **lead time** (¿SDQ anticipó la migración?).

### 6.3 Métricas a reportar
| Métrica | Qué prueba | Referencia |
|---|---|---|
| **Gini / Accuracy Ratio** (=2·AUC−1) | Discriminación — la métrica titular | >0.5 decente, >0.7 fuerte |
| **Monotonicidad por tier** | Piso mínimo: tasa de deterioro SDQ-D > SDQ-A > SDQ-AAA | debe ser monótona |
| **Calibración** | Si se emite PD: realizada vs. predicha por bucket | Hosmer-Lemeshow / binning |
| **Matriz de migración** + PSI | Estabilidad y drift de distribución | transiciones graduales |
| **Lead/lag vs. agencias** | Event-study: trimestres de anticipación | adelanto > 0 |

### 6.4 MVP feo-pero-correcto (PRIMERO, en días, con data en DB)
1. Cada (entidad, trimestre) con score 2021–2024.
2. Desenlace binario "¿deterioro material en los siguientes 4T?" (capa blanda).
3. Componente **determinista** (OOS gratis).
4. Calcular **Gini + curva de tasa-de-deterioro-realizado por tier SDQ**.
5. Si la curva es monótona y Gini >0.6 → modelo funciona. Walk-forward del XGBoost y lead-lag vs. agencias = Fase 2.

### 6.5 Honestidad obligatoria
Con ~5 años y pocos eventos duros, esto es **validación preliminar y direccional, no grado-Basilea through-the-cycle** (eso exige un ciclo completo, 7–10 años). Reportar intervalos de confianza por bootstrap. No afirmar Gini alto desde 3 quiebras. Decir esto **es** la marca.

**Salida Gate E:** módulo `validation/` con (a) derivación de outcomes desde el histórico, (b) cálculo de métricas, (c) reporte de validación exportable. Cableado a `outcomes.py`.

---

## 7. Gate F — Operabilidad: UI + monitoreo + schedule *(requisito del dueño)*

**Problema que cierra:** durante el coding, los temas de datos se resuelven a nivel backend (endpoint + `curl`) cuando muchos son **operaciones recurrentes que un humano no-técnico debe monitorear y disparar**. Hoy esa operación depende de una sesión del agente. Para un producto de Confiabilidad que refresca dato cada período, eso es riesgo operativo: la plataforma no es operable por su dueño.

### 7.1 Criterio de clasificación (evita construir UI de más)
No todo endpoint necesita UI. Clasificar **toda** operación nueva:

| Clase | Criterio | Qué exige |
|---|---|---|
| **Recurrente-humana** | Un humano la corre periódicamente para mantener el dato vivo | **UI con control + progreso + estado compartido entre workers + historial/auditoría (quién, cuándo, resultado) + opción de schedule + errores en español.** Visible en la consola de Operación. |
| **Diagnóstico técnico** | Inspección puntual del desarrollador | Admin-only, `include_in_schema=False`, `curl` OK. Ej.: `sib-page-test`, `sib-explore`, `fiduciaria-pdf-test`. |
| **One-time / migración** | Se corre una vez | Script, sin UI. Ej.: Alembic, seed inicial. |

**Regla:** si dudas entre "recurrente-humana" y "diagnóstico", es recurrente-humana → va a la UI. El default se inclina a operabilidad, no a `curl`.

### 7.2 Deuda actual verificada (operaciones recurrentes SIN UI — curl-only hoy)
Subir a la consola de Operación con progreso + schedule:
- [ ] `POST /data/rescore` — recalcular ratings sin re-ingesta.
- [ ] `POST /data/recompute-carteras?period=` — re-stream de un trimestre + rescore.
- [ ] `POST /data/fiduciaria-sync` (+ `/fiduciaria-sync-status`) — sync de fiduciarias/fideicomisos.
- [ ] `POST /data/prune-future` — purgar trimestre en curso no cerrado.
- [ ] (futuro) refresh del backtest (§6) cuando entra un período nuevo.

Ya operables en UI (referencia del patrón a copiar): `sib-backfill`, `sync-status`, `seed-banks`, mantenimiento de series (`SeriesMaintenanceSection`), `ConfiguracionPage`.

### 7.3 Mecánica
- [ ] **Consola de Operación** única (extender la página Datos/Configuración existente, no crear silos): lista las operaciones recurrentes con botón, último resultado, estado en vivo y próximo run agendado.
- [ ] **Estado en DB compartido entre workers** (patrón `sib_sync_status`): nada de estado en memoria de un solo proceso.
- [ ] **Scheduler in-app** (P1 heredado): chequeo/refresh periódico sin worker Celery aparte; avisar de períodos nuevos. Cada operación recurrente declara su cadencia sugerida.
- [ ] **Auditoría**: registrar cada corrida (origen: manual UI / schedule / API; usuario; timestamp; resultado). Insumo además para `outcomes`/trazabilidad.
- [ ] **UI correspondiente, no solo backend**: ninguna operación recurrente se considera entregada con el endpoint suelto. La UI es parte del entregable, no un follow-up.

**Sensor Gate F:** la operación se dispara, se monitorea y se agenda **desde la UI por un humano no-técnico**, sin tocar `curl` ni Railway CLI.

---

## 8. Definition of Done (resumen accionable)

Un **eje** está hecho cuando: Gate A (integridad ✓) + B (data probada ✓) + C (score explicable ✓) + D (insight IA en todas sus páginas ✓) + E (backtest con métricas reportadas ✓) + **F (toda operación recurrente del eje es disparable, monitoreable y agendable desde la UI ✓)**.

Una **página** está hecha cuando: data en dos fases ✓ + insight IA degradable ✓ + Markdown render ✓ + verificada en navegador claro/oscuro ✓ + `tsc`+build OK ✓.

Una **operación recurrente** está hecha cuando: endpoint ✓ + **control en UI con progreso + estado en DB compartido + historial + schedule ✓** + errores en español ✓. **Un endpoint suelto sin UI NO está hecho** (§7).

Un **PR** está listo cuando: CI verde (backend-test/frontend-build/docker-build/security-scan) ✓ + `ruff check` sobre TODO el changeset (incl. tests) ✓ + reviewer subagent pasó ✓ + `tasks/lessons.md` actualizado si hubo corrección ✓ + merge `--no-ff`.

---

## 9. Sprint inmediato (propuesto — confirmar antes de implementar)

**Objetivo del sprint:** cerrar Eje 2 a profundidad (Gates D+E) y arrancar Eje 4 (WGI) por Gate A. En paralelo, la promoción de componentes compartidos.

1. **Refactor compartido (§5.1):** promover `AiInsightCard` + `InsightDrawer` genérico a `shared/ui/`; refactorizar `banking-score` sin cambio de comportamiento.
2. **Consola de Operación + retirar curl-only (§7.2):** subir `rescore`, `recompute-carteras`, `fiduciaria-sync`, `prune-future` a la UI con progreso + estado en DB + schedule. Cierra la deuda de operabilidad antes de replicarla en ejes nuevos.
3. **Retrofit IA en `macro_monitor` (§5.5):** insight por serie + lectura de coyuntura (`trend_analysis`/`executive_summary`), dos fases.
4. **Backtest MVP del Eje 1 (§6.4):** módulo `validation/`, desenlace blando, Gini + curva por tier. Primer reporte de validación **con su UI** (no solo endpoint) + refresh agendable.
5. **WGI Gate A (§4):** conector live `wgi_client` (World Bank API), integridad + linaje; poblar `macro_political_risk` con dato real (hoy referencia WGI sin cablear). Su sync entra a la Consola de Operación desde el día 1.

> Tras confirmar, el desglose fino vive en `tasks/todo.md` (regla Plan First) y se ejecuta tarea por tarea con su sensor.

---

## 10. Deuda registrada (fuera de alcance inmediato)
- **Deal Scoring** (`Modelos Propietarios/deal_scoring.py`) — integrar como módulo formal (api/models/tests). IP sin capitalizar.
- **DGII** — datos abiertos (4 datasets ODbL en datos.gob.do) **NO bloqueados**; construibles cuando se decida el alcance/uso. Solo el **RNC a nivel contribuyente** queda diferido por riesgo legal/privacidad. Ver §3 nota DGII.
- **Seguridad pre-go-live** — desactivar `claude@sdqconsulting.com.do`, crear admin real (requiere secretos del dueño). **Dejado para el final por decisión del dueño (2026-06-20).**
