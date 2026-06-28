# PLAN FINO — Cerebro de Insights · Piloto `banking_score`

> v1 · 2026-06-22 · Desglose ejecutable, paso a paso. Eleva la **Gate D (insight IA)** del
> Eje 1 de "economista promedio" a juicio decision-grade.
> **Specs rectoras:** `../../Arquitectura_del_Cerebro_SDQMIP_v0.1.md` (porqué/diseño) y
> `../../Spec_Implementacion_Cerebro_Piloto_BankingScore_v0.1.md` (qué/cómo — textos literales).
>
> **Cómo se ejecuta (no negociable, doctrina de calidad):** UNA tarea a la vez. Antes de
> implementar cada T, Claude Code confirma su plan fino con el dueño. Antes de cerrar:
> sensor mostrado + reviewer subagent en lo no trivial. Prohibido correr el lote de corrido.
>
> Las firmas/llamadas citadas fueron leídas del código al 2026-06-21. Si un archivo cambió,
> **releer antes de tocar** — no asumir.

---

## Principios del piloto (no cambian)

- **No-rotura:** el cerebro se activa SOLO con `axis=`. Sin `axis`, ruta legacy idéntica. Los otros 7 módulos no se tocan.
- **Núcleo vs por-módulo:** identidad + estándar + Barra son núcleo (`cerebro.py`); doctrina, audiencia y templates thin son por-módulo. Generalizar = añadir, no editar el núcleo.
- **Anti-alucinación intacta:** sacar "no inventes cifras" a `EPISTEMIC_STANDARD` no la relaja; el sensor numérico la verifica. Cero cifras inventadas, no-negociable.
- **Audiencia única** en el piloto (`comite_credito`). Selector de audiencia = fase de generalización, fuera de alcance.
- **El texto del cerebro (§2 de la spec) está aprobado por el dueño (2026-06-22).** Cambios → PR a `cerebro.py`.

## Criterio de cierre del piloto (Gate D del Eje 1, recalificada)

Set congelado de **5 entidades reales**, viejo vs nuevo, puntuado por reviewer subagent contra los 5 tests de la Barra. **Acepta si** el nuevo pasa ≥4/5 donde el viejo pasaba ≤1/5, en ≥4 de los 5 casos · cero cifras inventadas · `pytest banking_score` verde · costo/latencia ±25% del baseline · endpoint best-effort nunca rompe. Evidencia en `evidence/PILOTO-banking-cerebro.md`.

---

## T-CB-1 · Crear el núcleo del cerebro — `shared/narrative/cerebro.py` (NUEVO)

### Pre-requisitos de lectura
- [ ] Releer `Spec_Implementacion_Cerebro_Piloto_BankingScore_v0.1.md` §2 (textos literales A–F y `build_system`).
- [ ] Confirmar `shared/doctrine/` (no se toca aquí; la doctrina §3 ya está transcrita a la spec, pero verificar que la postura del YAML banking no cambió).

### Pasos atómicos
- [ ] **1.** Crear `cerebro.py` con las constantes literales de la spec §2: `CEREBRO_IDENTITY`, `EPISTEMIC_STANDARD`, `BARRA_DE_INSIGHT`, `DEPTH_DIRECTIVE` (núcleo) + `AXIS_DOCTRINE = {"banking": ...}` y `AUDIENCE_FRAMES = {"banking": {"comite_credito": ...}}` (por-módulo).
- [ ] **2.** Implementar `build_system(axis, audience, mode) -> str` exactamente como §2.6: orden identidad → doctrina del eje → estándar → frame de audiencia (si existe) → Barra → DEPTH_DIRECTIVE (solo si `mode=="detailed"`).
- [ ] **3.** `build_system` tolera `axis` desconocido con error claro (no `KeyError` silencioso) y `audience=None` (omite el frame).

### Sensor T-CB-1
- [ ] `tests/narrative/test_cerebro.py`: `build_system("banking","comite_credito","detailed")` contiene las 6 secciones; con `mode="standard"` NO contiene `DEPTH_DIRECTIVE`; con `audience=None` NO contiene el frame; `axis` inválido levanta error explícito.

---

## T-CB-2 · Ruta cerebro en el motor — `shared/narrative/claude_engine.py` (EDIT)

### Pre-requisitos de lectura
- [ ] Releer `claude_engine.py`: firma actual de `generate()` (`context, template, mode, lang`), `_cache_key(context, template, mode, lang)`, y el `client.messages.create(...)` (hoy SIN `system=`, solo `user`). Confirmar que `mode=="detailed"` solo sube `max_tokens` 1024→2048.

### Pasos atómicos
- [ ] **1.** Añadir `THIN_TEMPLATES` (spec §3.1: `entity_rating`, `indicator_insight`, `subcomponent_focus`) — guardarraíles preservados (topes de palabras, dirección del indicador, percentil, peso de sub-componente, BCRD telón). NO duplicar la regla de cifras (vive en el estándar).
- [ ] **2.** Añadir params `axis: Optional[str] = None` y `audience: Optional[str] = None` a `generate()`.
- [ ] **3.** Bifurcar (spec §4.1): si `axis` → `system = build_system(...)`, `user = THIN_TEMPLATES[template]`, `messages.create(system=system, ...)`. Si no → ruta legacy idéntica.
- [ ] **4.** Extender `_cache_key` con `axis` y `audience` (spec §4.2) y actualizar su único call-site dentro de `generate`.
- [ ] **5.** No tocar: caching/TTL, `NarrativeResult`, `_generate_fallback`, `STATIC_FALLBACKS`, `_apply_lang`, manejo de errores.

### Sensor T-CB-2
- [ ] Test de no-regresión: `generate(..., axis=None)` produce el MISMO prompt de usuario que hoy (snapshot de un template legacy, p. ej. `executive_summary`). Sin `axis`, cero diferencia de comportamiento.
- [ ] Test ruta cerebro: `generate(..., axis="banking", audience="comite_credito")` pasa `system` no vacío y usa el template thin.

---

## T-CB-3 · Cablear banking — `modules/banking_score/api/router_scoring.py` (EDIT)

### Pre-requisitos de lectura
- [ ] Releer los call-sites: `_ai_insight` (~l.55), `indicator_insight` (~l.338), `entity_rating` (~l.383). Confirmar el patrón best-effort (try/except → `ai_insight=None`, nunca rompe el endpoint).
- [ ] Revisar `reports/narrative.py` (~l.156): si su template ∈ alcance, cablear; si usa `executive_summary`/`risk_assessment`, **dejar en legacy** y anotarlo (decisión, no olvido).

### Pasos atómicos
- [ ] **1.** En los 3 call-sites + cards, añadir `axis="banking", audience="comite_credito"` a `narrative_engine.generate(...)`. Único cambio por línea.
- [ ] **2.** Conservar intacto el try/except best-effort.

### Sensor T-CB-3
- [ ] Test best-effort: forzar fallo del cliente Claude → el endpoint responde con `ai_insight=None`, no 500.
- [ ] `pytest modules/banking_score/ -q` 100% verde.

---

## T-CB-4 · Sensores de calidad sobre datos reales — `evidence/PILOTO-banking-cerebro.md` (NUEVO)

### Pasos atómicos
- [ ] **1.** Elegir 5 entidades reales con calificaciones (mezcla de tiers/tipos para cubrir casos fuertes y débiles). Para cada una: generar `entity_rating` con la ruta vieja (sin `axis`) y la nueva (`axis="banking"`).
- [ ] **2.** Sensor anti-alucinación: script que extrae toda cifra del output nuevo y verifica que existe en el `context` de entrada. **Cero inventadas** o no cierra.
- [ ] **3.** Sensor de calidad: **reviewer subagent** fresco puntúa viejo vs nuevo contra los 5 tests de la Barra (postura, mecanismo, asimetría, falsabilidad, decisión). Tabla de puntajes + diffs al evidence.
- [ ] **4.** Registrar costo/tokens viejo vs nuevo (el `system` añade input; verificar ±25% y que el caching 1h sigue operando).

### Sensor T-CB-4 (criterio de cierre)
- [ ] El evidence muestra: nuevo ≥4/5 donde viejo ≤1/5 en ≥4 casos · cero cifras inventadas · costo en banda. **Si no alcanza, NO cerrar: iterar el texto de `cerebro.py` (no los datos) y re-medir.**

---

## T-CB-5 · Reviewer subagent + cierre

### Pasos atómicos
- [ ] **1.** Dispatch reviewer subagent fresco con: el diff completo, el `CLAUDE.md` del proyecto, y las dos specs. Que evalúe contra convenciones, no-rotura de los 7 módulos, guardarraíles preservados y los sensores. Arreglar lo crítico antes de cerrar.
- [ ] **2.** Actualizar `tasks/lessons.md` con cualquier corrección del dueño (síntoma, causa raíz, regla, disparador).
- [ ] **3.** Marcar el piloto cerrado en `tasks/todo.md` y dejar listo el **contrato de generalización** (spec §8) para el siguiente módulo (`sector_intel`).

---

## Fuera de alcance (explícito)
A/B Sonnet vs Opus · selector de audiencia en frontend + API · migración de los otros 7 módulos · reescritura de `STATIC_FALLBACKS`. Todo entra al generalizar, tras validar este piloto.
