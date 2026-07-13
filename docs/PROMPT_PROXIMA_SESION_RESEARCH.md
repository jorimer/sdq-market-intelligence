# Prompt de arranque — próxima sesión: mejoras al Motor de Research Custom

> Pegá este documento (o su contenido) al iniciar una sesión limpia para continuar.
> La memoria del proyecto ya tiene el detalle: `motor-research-custom-workstream`.

## Contexto en una frase
El **Motor de Research Custom** ya está construido y en prod (PRs #502–#511): toma una
pregunta libre, **cosecha el dato real de los varios motores que la pregunta convoca**
(entidad + dominios de contexto: macro, monetario…) y el Cerebro escribe un **dictamen
integrado circunscrito a lo recibido** (numeric_guard elimina cifras no trazables), con
brechas declaradas. **Decisión del dueño: NO se ofrece aún** — está construido para
**probarlo y perfeccionarlo internamente** hasta que sea producto público.

## Cómo probar/verificar en prod (rápido)
- App: `https://sdq-market-intelligence-production.up.railway.app`
- Admin E2E: `claude@sdqconsulting.com.do` / `Claude1234` (rol admin; ver [[e2e-test-superuser]]).
- UI: menú → Herramientas → **Research a Medida** (`/tools/research`).
- API: `POST /api/v1/research` (JSON) · `POST /api/v1/research/deliverable` (PDF/Word).
- 1ª consulta de una entidad tarda 40–80s (cosecha + Cerebro); la 2ª idéntica es instantánea
  (caché del narrative_engine).
- Pregunta de prueba canónica: *"¿Cuál es el perfil de riesgo de Banco Lafise frente a sus
  pares y su exposición a un shock de liquidez en los próximos 12 meses?"* → debe integrar
  banca + monetario (TPM) + macro en un dictamen con mecanismos de transmisión.

## Arquitectura actual (qué NO rehacer)
Todo en `shared/research/` salvo nota:
- `resolve.py` — detecta eje+entidad y **`context_axes`** (dominios de contexto por regla).
- `data_pull.py` — `pull_entity` (entidad) + `pull_axis` (sistema, scope=None) + summarizers
  por-eje (`_AXIS_SUMMARY`: banking/macro/monetary ricos; el resto genérico).
- `narrate.py` — `narrate_synthesis` (dictamen cross-dominio) + `narrate_answer`.
- `deep_report.py` — `build_synthesis_report` (cosecha + dictamen + evidencia por motor +
  gráficos/tablas). `orchestrator.py` — flujo async. `deliverable.py`/`export.py`/`assemble.py`
  — salida. `packaging.py` — SKU `special:research-custom` en el tarifario ($3,500 provisional).
- Templates thin del Cerebro `research_answer`/`research_synthesis` en
  `shared/narrative/claude_engine.py`. UI: `frontend/.../ResearchPage.tsx`.
- Tests: `shared/research/tests/` (28, correr con `/opt/anaconda3/bin/python -m pytest`).

## Roadmap de mejoras — en orden de impacto (para dejar de parecer "un Deep Dive con contexto")

1. **[PRIORIDAD] Descomposición SEMÁNTICA de dominios.** Hoy `resolve.context_axes` es un mapa
   curado por reglas. El salto: que el **Cerebro lea la pregunta** y decida qué motores del
   catálogo convoca (con su razón), en vez del mapa fijo. Ej.: "zonas francas + tipo de cambio +
   aranceles EEUU" → free_zones + trade + macro; "sostenibilidad de pensiones + demografía" →
   pension + macro + social. Esto es lo que más lo aleja de un molde rígido. Mantener el
   fallback determinista (el mapa curado) si el Cerebro no está disponible.

2. **Evidencia real por-eje para los ~11 sectores restantes.** Solo banking/macro/monetary
   tienen summarizer rico en `data_pull._AXIS_SUMMARY`. Añadir uno por sector leyendo la forma
   de su `snapshot().payload` (energy, telecom, insurance, pension, trade, tourism, free_zones,
   construction, esg, sector_intel). Patrón: mirar el `payload` real, extraer las 2-4 cifras que
   importan con etiqueta legible.

3. **Pares NOMBRADOS.** "Percentil 18.8 vs el sistema" es anónimo. Traer competidores concretos
   (Popular/BHD/Reservas) con su dato — vía el ranking de banking o `scope_options` + snapshot —
   y armar tabla + narrativa comparativa. Es lo que un Deep Dive (anónimo) no da.

4. **Fiabilidad/latencia.** 1ª consulta 40–80s. Evaluar prewarm del Deep Dive de la entidad al
   iniciar el research, o un modo cache-only. Ver la lección de `asyncio.wait_for(15s)` ya
   aplicada en `build_deep_report`.

5. **Calibrar la síntesis con preguntas REALES (piloto Fase 2).** El dueño elige 3-5 preguntas
   de compradores; correr `POST /api/v1/research/pilot` (admin) y leer si el Cerebro conecta los
   dominios bien. Params: `min_anchor_score=7.0`, `gap_threshold=0.40`.

## Reglas del proyecto a respetar (de la memoria)
- **Excelencia sobre velocidad**; verificar SIEMPRE en prod, no extrapolar de una muestra.
- **Anti-Frankenstein**: `shared/` no importa módulos de sector; usar el contrato del registro.
- **Nunca fabricar**: dato real / rúbrica / brecha declarada; el numeric_guard es la garantía.
- **Anti-slop**: no mostrar relleno genérico (secciones sin cifras se omiten).
- **Precios**: viven en el tarifario (`Tariff`), no hardcodeados ([[pricing-model-per-sector-intervals]]).
- Git: rama por PR, `--merge` a main dispara deploy Railway; verificar en prod tras cada merge.

## Sugerencia de primer paso
Arrancar por **(1) descomposición semántica**: diseñar un template thin del Cerebro que, dada
la pregunta + el catálogo de motores disponibles (del registry), devuelva la lista de dominios
relevantes con su rol (primario/contexto) y por qué; cablearlo en `resolve`/`orchestrator` con
el mapa curado como fallback. Verificar con 3-4 preguntas de distinto tipo en prod.
