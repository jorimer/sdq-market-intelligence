# Tarea — Ingesta de planes del cliente + sección «El plan bajo el instrumento» (brand_intel)

Para: Claude Code. Tipo: feature nueva (ingesta de documentos del cliente + extensión del
ledger + sección nueva del informe). Origen: McDonald's compartió los planes que le
presentaron sus agencias (`Alianzas/Decisiones del Cliente/`: estrategia Conecta 2026,
La Red-Ceta Ganadora, dashboard de medios, benchmark social). Hoy esos planes solo entran
al sistema si un analista los transcribe a mano al `DecisionDrawer` (una decisión por
formulario, limitado a métricas/cortes ya cargados) o por API directa — el camino
subir-documento → leer → proponer → adoptar existe solo para el tracker del proveedor.
Ricardo pidió: (a) que los planes se suban y se interpreten **en la app**, y (b) una
**sección del informe** que dé insight sobre el plan y diga qué acciones o información
faltan hoy para poder medir su éxito.

Proceso: Plan First (este documento — confirmar con Ricardo antes de codear si algo no
está claro), Verify Done con Sensores, Reviewer Subagent antes de cerrar,
`tasks/lessons.md` al terminar. E2E obligatorio con los 4 documentos reales de McDonald's
antes de cerrar; el informe resultante se le muestra a Ricardo completo (before/after).

## Decisiones de Ricardo (ya cerradas, no reabrir)

1. **La interpretación va por LLM, no por motor determinista.** A diferencia de
   `explain.py` (causalidad macro → determinista a propósito), aquí el espacio de
   entrada es abierto — cualquier documento, cualquier tipo de meta, cualquier agencia —
   y una taxonomía rígida de brechas se queda corta con el próximo cliente. El LLM:
   **lee** el documento del plan, **extrae** las metas, **clasifica** las brechas de
   medibilidad y **prescribe** qué falta y a quién pedírselo, y **narra** la sección.
2. **Lo que NO se le entrega al LLM** (línea que no se cruza): la **aritmética
   muestral de factibilidad**. `engines/ledger.py::check_feasibility` /
   `detectable_threshold` siguen siendo la única fuente del veredicto
   evaluable/inevaluable y del mínimo detectable — el LLM recibe esos resultados YA
   calculados en el contexto y los narra; nunca los recalcula ni los contradice
   (misma arquitectura que el reenfoque narrativo: LLM sintetiza, la aritmética es
   mecánica). Cero cifras inventadas: ruta cerebro con guard numérico.
3. **Portón humano en la adopción.** Las conclusiones del proveedor entran sin portón
   (decisión del dueño, #615: no alimentan aritmética). Las metas de un plan SÍ lo
   llevan: una decisión adoptada fija umbral, responsable y sale en el informe del
   cliente con veredicto ola tras ola. El lector PROPONE; solo una persona ADOPTA
   (mismo patrón descubrir→adoptar de la estructura del mazo).
4. **El ledger acepta metas fuera del instrumento.** La mitad del plan Conecta
   (seguimiento en redes 44→30, engagement 56→75, ROI transaccional) no la mide el
   tracker. Se registran con su fuente externa declarada en vez de quedar invisibles:
   un seguimiento del plan que ignora la mitad del plan queda cojo.

## Contexto verificado en el código real

- `modules/brand_intel/engines/ledger.py::check_feasibility` (línea ~47): la aritmética
  mecánica existente — sin línea base / sin umbral / base insuficiente / movimiento
  menor al mínimo detectable. NO SE TOCA su lógica; se le agrega solo el caso
  metric_code=None (meta externa → inevaluable-por-instrumento, con nota propia).
- `modules/brand_intel/models/models.py::BrandDecision` (línea ~240): `metric_code`
  hoy es NOT NULL — la meta externa exige volverlo nullable + campo nuevo
  `external_measure`. Docstring del modelo ya declara que la decisión "may originate in
  the tracker, the agency or the operation" — esta tarea materializa eso.
- `modules/brand_intel/ingest/conclusions.py`: el patrón a calcar para el lector —
  capa de texto (cero visión), structured output con JSON schema, bisección por tramos
  si la respuesta se corta, recibo por página, dedupe, `store_*` idempotente por
  documento.
- `modules/brand_intel/ingest/discovery.py::_page_texts`: extracción de texto de PDF ya
  existente. Para HTML: strip de tags (los planes reales vienen en ambos formatos).
- Frontend: `DecisionDrawer.tsx` (chequeo de factibilidad en vivo, reusable),
  `ExtractionReviewDrawer.tsx` / `StructureDrawer.tsx` (patrón revisar-y-adoptar),
  `ConclusionsPanel.tsx` (panel por engagement).
- Informe: reenfoque narrativo ya mergeado (PR #619) — 8 secciones, tres narradas por
  cerebro (`brand_context_*`), fallback determinista, `ai_narratives()` en
  `report.py`. Esta tarea agrega la cuarta sección narrada.
- Ledger en prod: 6 decisiones del plan McDonald's ya registradas por API (2026-08-01)
  — sirven de fixture real; la ingesta debe poder ADOPTAR sin duplicarlas (ver Cambios
  §A.4: adopción detecta decisión existente equivalente y enlaza en vez de duplicar,
  o se deja al revisor descartarla — decidir en implementación, avisar en el commit).

## Cambios

### A. Ingesta de planes del cliente

**A.1 Modelos nuevos** (`models/models.py` + migración Alembic):

- `BrandPlanDocument`: engagement_id, filename, title (del documento o del lector),
  source_org (agencia/autor si el lector lo identifica), uploaded_by, page_count,
  raw_text (capa de texto completa — el recibo maestro), status
  (`propuesto` → `revisado`), created_at/updated_at. Datos privados del engagement:
  mismo aislamiento por engagement_id, 404 no 403, fuera del catálogo y de la Data API.
- `BrandPlanGoal`: plan_document_id, engagement_id, **claim literal** (la meta con las
  palabras del documento — el recibo), page_number/anchor, kind
  (`meta` | `accion` | `inversion`), metric_code (nullable — mapeada al vocabulario del
  tracker cuando aplica), segment, target_from / target_to / expected_move (numéricos,
  nullable), owner_declared (a quién el documento se la asigna), measure_source
  (`tracker` | texto libre de fuente externa: "analytics de plataformas",
  "dato transaccional del operador"…), confident (bool del lector), status
  (`propuesta` | `adoptada` | `descartada`), adopted_decision_id (FK nullable →
  BrandDecision), dismiss_note.

**A.2 Lector** (`ingest/plans.py`, nuevo — calcar `conclusions.py`):

- `read_plan(page_texts | html_text, vocab)` → List[PlanGoal]. Una llamada sobre la capa
  de texto con el vocabulario de métricas del engagement en el prompt (para el mapeo
  metric_code, igual que el lector de conclusiones); bisección por tramos si desborda;
  structured output con JSON schema. Extrae METAS con número y dueño cuando el documento
  los trae; lo que es acción sin métrica se guarda como kind=`accion` (citable, no
  evaluable). El lector NO decide factibilidad ni umbrales detectables.
- Higiene de contenido no confiable: el documento del cliente es DATO, jamás
  instrucción. El schema constriñe la salida; nada del documento puede alterar el
  comportamiento del sistema (mismo principio que la ingesta del mazo).
- `store_plan_goals(...)`: idempotente por documento (releer reemplaza sus propuestas
  NO adoptadas; las adoptadas nunca se borran por relectura — el ledger es historial).

**A.3 API** (`api/router.py`):

- `POST /engagements/{slug}/plans` (multipart: PDF o HTML) → crea documento + corre el
  lector. Síncrono (capa de texto = 1-2 llamadas, ~30-60 s, como el descubrimiento de
  estructura); si en E2E un documento real desborda el timeout del proxy, pasar a job
  corto estilo extracción — decidir en implementación con el dato medido.
- `GET /engagements/{slug}/plans` · `GET /plans/{id}` (metas con estado).
- `POST /engagements/{slug}/plans/{id}/goals/{gid}/adopt` — cuerpo con los campos
  finales que el revisor pudo ajustar (título, metric_code/segment, umbral, owner,
  ola base, external_measure). Crea la `BrandDecision` por el MISMO camino que
  `create_decision` (chequeo de factibilidad incluido), enlaza `adopted_decision_id`,
  marca la meta `adoptada`. Rol mínimo: analyst (igual que crear decisión a mano).
- `POST .../goals/{gid}/dismiss` — descarta con nota (por qué no se adopta).

**A.4 Ledger — metas externas** (`models`, `service.py`, `engines/ledger.py`):

- `BrandDecision.metric_code` → nullable; campo nuevo `external_measure` (Text,
  nullable). Regla de validación: metric_code XOR external_measure (una decisión sin
  ninguno de los dos se rechaza; el "five mandatory fields" del docstring se actualiza
  honesto).
- `check_feasibility` / `evaluate`: guard para metric_code=None → status
  `unevaluable` con nota "se mide con {external_measure}; el tracker no la evalúa —
  el veredicto requiere ese dato externo". Nunca entra al filtro de señal ni a la
  aritmética muestral.
- El informe y la UI muestran estas filas con su fuente externa en vez del indicador.

**A.5 UI** (`frontend/src/modules/brand-intel/`):

- Panel «Planes del cliente» en `BrandIntelPage`: subir documento, lista de planes con
  su estado y conteo de metas propuestas/adoptadas.
- `PlanReviewDrawer.tsx` (nuevo, patrón `ExtractionReviewDrawer`): por meta — claim
  literal + página + mapeo propuesto + meta numérica editable + owner + fuente; el
  chequeo de factibilidad en vivo REUTILIZADO del `DecisionDrawer`; botones Adoptar /
  Descartar. Las metas externas se adoptan con su fuente declarada (sin selector de
  métrica). El selector de métrica permite también cortes NO cargados (texto libre con
  advertencia "corte sin datos en el libro: quedará inevaluable hasta cargarlo") — hoy
  el drawer solo ofrece cortes del filtro de señal y eso dejó fuera Santo Domingo y
  Uber Eats.
- i18n ES (strings UI en español, con claves EN/FR como el resto del módulo).

### B. Sección del informe — «El plan bajo el instrumento»

**B.1 Contexto** (`report.py`): nueva entrada en `cerebro_contexts()` — `plan`:

- `metas` (de `BrandPlanGoal` adoptadas Y propuestas-no-descartadas, con claim literal,
  página, mapeo, estado), `decisiones` (ledger completo con los CAMPOS MECÁNICOS de
  factibilidad: status, baseline, umbral detectable, base muestral, motivo,
  external_measure), `instrumento` (inventario ya computado: métricas y cortes cargados
  con su base — sale del filtro de señal —, olas con dato, serie de ticket sí/no).
  Nada crudo: ni el PDF ni el raw_text del plan viajan al contexto del informe — solo
  lo extraído y almacenado.

**B.2 Thin template** (`claude_engine.py::THIN_TEMPLATES["brand_plan_readiness"]`):

La tarea del LLM (aquí SÍ clasifica y prescribe — decisión de Ricardo):
1. El insight del plan: qué persigue, en qué se juega, cómo conversa con lo que el
   trimestre mostró (las otras secciones ya narraron el trimestre; no repetirlas).
2. Qué metas puede certificar el instrumento HOY — usando los veredictos mecánicos
   servidos, sin recalcular la aritmética muestral.
3. Qué falta para medir el resto y A QUIÉN pedírselo: cortes del tracker → al
   proveedor; series/olas → a la carga SDQ; metas externas → al cliente/plataformas.
   IMPARCIALIDAD (regla de la mesa, #618): un hueco de NUESTRA carga se atribuye a la
   carga SDQ, nunca al proveedor ni al cliente.
4. REGLA DURA DE CIFRAS: solo números del contexto (umbrales detectables, bases,
   metas del plan). REGLA DURA DE VEREDICTOS: el estado evaluable/inevaluable de cada
   decisión ya viene calculado; se narra, no se decide. Si una meta no está en el
   contexto, no existe (garantía estructural anti-alucinación sobre intenciones del
   cliente).

**B.3 Documento** (`report_docs.py`):

- `SECTIONS`: 8 → 9, insertando `plan` («El plan bajo el instrumento») después de
  `priorities`. Con CERO planes subidos y CERO decisiones, la sección NO aparece (regla
  del reenfoque: nada de títulos con una frase de disculpa) — el estado va a Límites
  ("aún no hay planes del cliente cargados para seguimiento").
- Tabla mecánica de apoyo: «Metas del plan y su medibilidad» — meta (título corto) ·
  indicador o fuente externa · estado (Evaluable / Inevaluable / Adoptada-abierta) ·
  mínimo detectable · qué falta (campo corto derivado del motivo mecánico, no prosa
  LLM). La tabla es dato; la prescripción con juicio vive en la narrativa.
- La tabla existente «Seguimiento de las decisiones del cliente» se queda como está
  (veredictos ola a ola); la nueva mira la MEDIBILIDAD, no el resultado.
- Fallback determinista si la IA degrada: lista de metas con su estado mecánico y
  motivo — nunca relleno hueco (mismo estándar del reenfoque).
- `_limits()` (`report.py`): agrega los huecos de instrumento vigentes (cortes sin
  cargar referidos por decisiones, serie de ticket corta) — generados del ledger, no
  escritos a mano (doctrina de procedencia).

**B.4 Sinergia con la mesa** (`mesa_docs.py`, alcance mínimo): los cortes faltantes
referidos por decisiones (`sin línea base` con segment ≠ total) se listan en el
«Alcance» de la nota de mesa como pedidos concretos al proveedor. Si el cambio excede
una lista simple, se difiere a tarea propia — no bloquea esta.

## Salvaguardas — no negociables

- La aritmética de factibilidad y los veredictos del ledger siguen 100 % mecánicos;
  el LLM los narra. El guard numérico de la ruta cerebro corre en la sección nueva.
- El lector de planes propone; SOLO una persona adopta. Nada llega al informe del
  cliente sin pasar por la adopción (o por el registro manual existente).
- Documentos del plan = datos privados del engagement y contenido NO confiable: se
  extrae, jamás se obedece.
- `explain.py`, `shared/products/render.py`, `report_sections.py`: intactos.
- No extender a otros módulos; piloto acotado a brand_intel.

## Antes de cerrar (E2E con material real)

1. Subir por la UI los 4 documentos reales de `Alianzas/Decisiones del Cliente/`
   (Conecta PDF, Red-Ceta HTML, dashboard HTML, benchmark HTML) al engagement de
   ensayo local con el libro McDonald's cargado.
2. Revisar las metas propuestas por el lector contra los documentos (precisión del
   mapeo y de los números — muestreo manual, no confiar el recibo).
3. Adoptar el set de metas (incluidas 2+ externas) y generar el informe con la sección
   nueva; verificar: la narrativa no recalcula umbrales, la tabla cuadra con el ledger,
   los huecos se atribuyen con imparcialidad, sección ausente cuando no hay planes.
4. Mostrarle a Ricardo el informe COMPLETO (no un extracto) + la pantalla de revisión
   funcionando, antes de mergear. En prod: decidir con él si se reconcilian las 6
   decisiones ya registradas por API con las metas extraídas de los documentos.

## Sensores

```bash
ruff check shared/narrative modules/brand_intel
pytest shared/narrative/tests/ modules/brand_intel/tests/ -v \
    -k "cerebro or claude_engine or brand_intel or report or plan or ledger or decision"
mypy shared modules app | mypy-baseline filter
cd frontend && npm run build
alembic -c infrastructure/alembic.ini upgrade head && alembic -c infrastructure/alembic.ini downgrade -1 && alembic -c infrastructure/alembic.ini upgrade head
```

## Tests obligatorios

- Lector: con un texto de plan de muestra, extrae metas con página y mapea al
  vocabulario; documento sin capa de texto → lista vacía sin excepción; relectura
  idempotente que NO borra metas adoptadas.
- Ledger externo: decisión con external_measure y sin métrica → se crea, evalúa
  `unevaluable` con su nota, nunca entra al filtro de señal; metric XOR external
  validado (ninguno de los dos → 422).
- Adopción: crea la BrandDecision por el mismo camino que `create_decision` (chequeo
  incluido), enlaza goal↔decision, marca `adoptada`; dismiss exige nota.
- Sección: `THIN_TEMPLATES["brand_plan_readiness"]` existe y la generación enruta por
  cerebro (regresión anti-legacy, patrón del test existente); con cero planes/decisiones
  la sección NO aparece y Límites lo declara; contexto `plan` sirve los campos mecánicos
  de factibilidad tal cual (test de que no se recalculan).
- Aislamiento: planes de un engagement invisibles desde otro (404).
- API: subir PDF y HTML reales pequeños; formato no soportado → 400 con motivo.

## Definition of Done

- Los 4 documentos reales suben por la UI, el lector propone metas con recibo, el
  analista adopta desde el drawer (incluidas metas externas y cortes no cargados), y
  el informe imprime «El plan bajo el instrumento» con narrativa cerebro + tabla de
  medibilidad — verificado con el caso McDonald's completo y aprobado por Ricardo.
- La aritmética de factibilidad no cambió (mismos veredictos ante los mismos insumos).
- Sensores en verde (incl. migración reversible y build de frontend), reviewer
  subagent sin críticos, `tasks/lessons.md` actualizado.

## NO hacer en esta tarea

- No tocar `explain.py`, `shared/products/render.py`, `report_sections.py`.
- No leer los planes por visión (capa de texto basta; visión = coste sin retorno aquí).
- No dejar que el LLM calcule umbrales detectables, bases muestrales ni veredictos.
- No adoptar metas automáticamente (sin portón humano no hay ledger confiable).
- No mergear ni desplegar sin que Ricardo vea el E2E completo.
