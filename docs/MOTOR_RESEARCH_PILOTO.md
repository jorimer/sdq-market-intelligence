# Piloto del Motor de Research Custom (Fase 2) — protocolo

> Complemento operativo de `SPEC_MOTOR_RESEARCH_CUSTOM.md`. La Fase 2 es
> **instrumentación de build, no validación de mercado** (§5). Su objetivo: medir con
> preguntas reales si el motor cubre lo suficiente con dato real/rúbrica y si el gate de
> honestidad sobrevive a preguntas libres — antes de invertir en más automatización.

## Qué ya está construido (Fases 1, 3, 4)

- **Data Registry** (`shared/registry`): señal por-variable normalizada (real/rúbrica/
  brecha + peso + fuente + cadencia) de los 14 productos. API: `GET /api/v1/registry`,
  `GET /api/v1/registry/{sector_key}`, `GET /api/v1/registry/search?q=`.
- **Retrieval** (`shared/knowledge`): recuperación léxica (BM25) sobre corpus propio de
  licencia clara (doctrina + metodología) + el Data Registry vivo. Sin web abierta.
- **Orquestador + gate** (`shared/research`): descompone la pregunta, ancla cada
  sub-pregunta a evidencia con procedencia, y decide informe completo vs. scoping report
  según el umbral de brecha (§3.4). API: `POST /api/v1/research`.

## Cómo correr el piloto

1. El dueño elige **3-5 preguntas reales** de los compradores ya identificados (§8.2).
2. Admin llama `POST /api/v1/research/pilot` con `{"questions": [...]}`. Devuelve, por
   pregunta: gate, % dato real, % con ancla, conteo real/rúbrica/brecha, nº de fuentes,
   y un markdown con la tabla. (También cada pregunta suelta por `POST /api/v1/research`.)
3. El analista **completa a mano** en la tabla las columnas que el motor no puede saber:
   - `h DD actual`: horas del proceso DD manual actual para responder esa pregunta.
   - `h con motor`: horas con el motor asistiendo.
   - `costo IA US$`: 0 en el núcleo determinista actual; se poblará al enchufar el Cerebro.

## Qué mide / cómo se lee

| Señal | Lectura |
|---|---|
| **% dato real alto** | El motor responde con evidencia dura → candidato fuerte a acelerar el DD. |
| **% ancla alto pero % real bajo** | Se apoya en rúbrica/metodología; honesto, pero el valor está en la doctrina, no en dato vivo. |
| **Muchos scoping reports** | Falta **fuente**, no motor → la palanca es `source_intel` (ingesta), no más ingeniería (§5). |
| **Gate deja pasar una brecha** | Fallo del §4/§6: recalibrar `min_anchor_score` (default 7.0) y/o el umbral del gate (default 40%). Ambos son parámetros del request. |

## Decisiones que dependen del piloto (no antes)

- **Fase 3 ya construida**, pero si el piloto muestra baja cobertura por falta de fuentes,
  la prioridad es cerrarlas vía `source_intel`, no automatizar más (§8.3).
- **Fase 5** (integración a DD Full/Deep Dive como acelerador): la costura existe —
  `shared/research/export.to_markdown` produce el documento con la anatomía del
  REPORT_STANDARD, listo para alimentar el `ReportSpec`/motor PDF cuando esté (§7). El
  ahorro real de horas-analista se mide **con los números de este piloto**.
- **Fase 6** (tier comercial nuevo entre DD Express y DD Full): se decide en Fase 5 con
  datos reales, no en este documento (§8.4). No comprometer fecha ni precio antes.

## Calibración (parámetros tunables)

- `min_anchor_score` (default **7.0**): score BM25 mínimo para que un pasaje ancle. Bajo
  el umbral = roce léxico marginal → brecha (evita fabricar por vocabulario compartido).
  `[Guessing]` calibrado sobre el corpus actual; re-calibrar con las preguntas del piloto.
- `gap_threshold` (default **0.40**, §3.4): fracción del cuerpo sin ancla que dispara el
  scoping report.
