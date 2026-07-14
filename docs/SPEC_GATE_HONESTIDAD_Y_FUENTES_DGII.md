# SPEC — Integridad del gate de honestidad + fuentes DGII para el motor de research custom

> v0.1 · 2026-07-14 · Documento de construcción (no de validación de mercado). Etiquetas de
> confianza: **[Certain]** verificable contra código/evidencia citada · **[Likely]** inferencia
> fuerte, no probada · **[Guessing]** supuesto a validar · **[Lock]** decisión ya tomada por el
> dueño. Complementa `docs/SPEC_MOTOR_RESEARCH_CUSTOM.md` y `docs/MOTOR_RESEARCH_PILOTO.md`.
> Regla Plan First: este documento se somete antes de tocar código.

**Origen.** Piloto manual de Fase 2 (§5 de `SPEC_MOTOR_RESEARCH_CUSTOM.md`), 3 preguntas reales
sobre el caso QSR/fast food (cuenta McDonald's), corridas el 2026-07-14:

| # | Pregunta | Gate | % dato real | % con ancla |
|---|---|---|---|---|
| 1 | Compuesta (macro + turismo + energía + construcción + monetaria + arancel, cadena QSR) | report | 75% | 75% |
| 2 | Control — entorno macro/costos puro, sin nada específico de QSR | report | 100% | 100% |
| 3 | Sonda — cuántas cadenas, participación de mercado por marca, crecimiento de locales | report | **0%** | **100%** |

La Pregunta 2 confirma el techo de la hipótesis (cuando la pregunta cae dentro de los 14 ejes, el
motor rinde al máximo, sin rúbrica). La Pregunta 3 dispara este spec: un header "100% con ancla"
que no refleja ninguna cobertura sustantiva real es un problema más serio que una brecha honesta,
porque erosiona la garantía central del producto (`docs/CLAIMS_COMERCIALES.md`: procedencia
auditable por variable).

## 0. Resumen ejecutivo (BLUF)

Dos hallazgos independientes del mismo piloto, complementarios:

1. **[Certain] Bug de integridad del gate de honestidad.** `_evidence_state()`
   (`shared/research/models.py:53-54`) etiqueta `RUBRIC` cualquier pasaje de tipo
   `doctrine`/`methodology`/`bulletin` que haya cruzado `min_anchor_score` en el retrieval —sin
   verificar que el pasaje responda al tema de la sub-pregunta. Demostrado en producción: la
   Pregunta 3 ancló como "rúbrica declarada" el §8 de `REPORT_STANDARD.md` (formatos de salida
   PDF/Word/in-app) y la metodología de escala del IRMP — ninguno de los dos tiene relación con
   cadenas de comida rápida. El resultado: un informe con apariencia de resuelto en la clase de
   pregunta (inteligencia competitiva) que un comprador sofisticado más va a auditar.
2. **[Certain] Brecha de fuente real para preguntas de sub-industria.** Ningún eje da hoy conteo
   de participantes por vertical (fast food, hoteles, supermercados, farmacias…) por debajo de los
   14 productos. El padrón de contribuyentes activos de DGII (CIIU rev.3 a nivel subclase, subido
   por el dueño el 2026-07-14) lo resuelve para varias verticales de una sola vez.

Se especifican juntos porque son complementarios, no porque dependan uno del otro: el fix de (1)
sin la fuente (2) simplemente hace que más sub-preguntas de este tipo caigan a brecha declarada
—mejor que hoy, pero sin aportar valor nuevo—; la fuente (2) sin el fix de (1) corre el riesgo de
seguir sin usarse porque el retrieval sigue anclando en rúbrica-ruido antes de llegar al dato real
nuevo. Se pueden construir en paralelo (no comparten archivos).

---

## Parte A — Integridad del gate de honestidad

### A.1 Qué existe hoy (verificado contra código)

| Pieza | Ubicación | Comportamiento |
|---|---|---|
| Umbral de ancla | `shared/research/decompose.py:36` `DEFAULT_MIN_ANCHOR_SCORE = 7.0` | Score BM25 mínimo; documentado como "[Guessing] calibrado sobre el corpus actual (match legítimo ≳8, ruido ≲6)" — el propio código admite que es una calibración provisional. |
| Filtro en retrieval | `shared/research/decompose.py:101` `retrieve(text, top_k=top_k, db=db, min_score=min_anchor_score)` | El umbral se aplica en `shared/knowledge/retrieve.py` → `index.search(query, top_k, min_score)`. No confirmé si el score se normaliza por longitud de la consulta (`shared/knowledge/ingest.py`, no revisado en este spec) — **[Guessing]**: una consulta larga y multi-tema (como la Pregunta 3, 27 palabras) acumula coincidencias parciales de vocabulario genérico más fácilmente que una corta, lo que facilita cruzar un umbral absoluto sin relevancia temática real. |
| Etiquetado de estado | `shared/research/models.py:42-55` `_evidence_state()` | `kind=="registry"` → REAL si `meta.state==REAL`, si no RUBRIC. `kind in ("doctrine","methodology","bulletin")` → **RUBRIC incondicional** (sin chequeo de relevancia adicional). Cualquier otro caso → GAP. |
| Agregación por sub-pregunta | `shared/research/decompose.py:86-92` `_aggregate_state()` | Toma el mejor estado entre toda la evidencia recuperada: `real > rúbrica > brecha`. Con un solo pasaje mal etiquetado RUBRIC, la sub-pregunta entera queda "anclada". |
| Partición en sub-preguntas | `shared/research/decompose.py:24-27,39-56` `_CONNECTORS` / `split_question()` | Parte solo en `.` `?` `;` `\n` o frases de coordinación explícitas ("y también", "además", "asimismo", "así como"). Una coma + "y" simple **no** parte. Por eso la Pregunta 3 (comas + "y", sin punto y coma) quedó como **una sola** sub-pregunta de 27 palabras, mientras la Pregunta 1 (con "; " entre cláusulas) se partió en ~8. |

### A.2 Evidencia del fallo (Pregunta 3, texto citado del PDF)

> Ancla: rúbrica declarada. Evidencia: *Metodología · Estándar de Reporte MIR* — "## 8. Salidas y
> paridad… Online (in-app)… PDF: motor de marca rico… Word (.docx): misma anatomía…"; *Metodología
> · Fuentes del IRMP* — "1. Escala absoluta 0–100 anclada a países benchmark fijos…"

Ninguno de los dos pasajes es método aplicable a "cuántas cadenas de comida rápida operan,
participación de mercado por marca, crecimiento de locales". El header del informe ("0% dato real
· 100% con ancla") es, en este caso, engañoso por diseño del sistema, no por intención.

### A.3 Causa raíz

La combinación de (a) un umbral de ancla absoluto que una consulta larga puede cruzar por
acumulación de coincidencias léxicas genéricas, y (b) un etiquetado de estado que trata "vino un
pasaje de tipo doctrina/metodología que cruzó el umbral" como suficiente para RUBRIC, sin
verificar que ese pasaje sea sobre el tema de la sub-pregunta.

### A.4 Arquitectura propuesta — three opciones incrementales, no mutuamente excluyentes

**A4.1 — Freno inmediato (bajo esfuerzo).** Subir `min_anchor_score` específicamente para
evidencia `doctrine`/`methodology`/`bulletin` (umbral más alto que para `registry`, que ya viene
de dato estructurado y es más confiable a score parejo). Requiere solo tocar la firma de
`retrieve()`/`map_subquestion()` para aceptar un umbral por-kind. Mitiga, no cierra: un pasaje
irrelevante pero muy largo (más términos coincidentes) puede seguir cruzando cualquier umbral
absoluto.

**A4.2 — Verificación de relevancia tema-pasaje (recomendada, fix estructural).** Antes de aceptar
RUBRIC para un pasaje `doctrine`/`methodology`, un paso adicional (barato: una llamada LLM de
clasificación sí/no, mismo patrón defensivo que ya usa `domain_router._parse_domains` para
descartar ejes inventados) que pregunte "¿este pasaje es método aplicable a esta sub-pregunta?".
Si no hay Cerebro disponible (sin API key), fallback determinista: degradar a GAP en vez de
RUBRIC (nunca al revés — el fallback sin IA debe ser el más conservador, no el más permisivo).

**A4.3 — Reusar la señal de ruteo de dominios (barata, complementaria).** Si `route_domains()` no
asoció ningún eje del catálogo a la sub-pregunta (lista de dominios vacía o sin relación), es una
señal fuerte de que la pregunta está fuera del alcance de los 14 ejes — exigir una barra más alta
para RUBRIC en ese caso, o forzar GAP salvo evidencia con score muy por encima del umbral normal.
No requiere una llamada adicional: la señal ya se computa en `orchestrator.py` (`route_domains` /
`merge_routing`), solo hay que pasarla a `decompose()`/`map_subquestion()`.

**Recomendación:** A4.1 ya (mitigación inmediata, un par de líneas), A4.3 en paralelo (barato,
reusa cómputo existente), A4.2 como el fix de fondo. Ninguna es excluyente.

### A.5 Efecto colateral a revisar (no bloqueante para A.4)

El comportamiento de partición (`split_question`, §A.1) hace que preguntas compuestas sin "; "
explícito se queden como una sola sub-pregunta larga, perdiendo granularidad de diagnóstico
(no se puede saber cuál de las 3 cláusulas de la Pregunta 3 tiene evidencia y cuál no — las tres
caen juntas). Vale la pena evaluar agregar la coma+"y"/"," como separador adicional, con cuidado
de no partir enumeraciones legítimas dentro de una sola cláusula. Prioridad menor a A.4.

---

## Parte B — Fuentes DGII

### B.1 Fuente A — DGII, Estadísticas de Contribuyentes por Actividad Económica (RNC, CIIU rev.3, subclase)

**Recomendación: aprobar.** Archivo ya en mano (`Cantidad de contribuyentes publicar.xlsx`,
190,652 filas, actualizado 29-ene-2026), página oficial fija
(`dgii.gov.do/estadisticas/Paginas/Estadisticas-Contribuyentes.aspx`, modificado 30-ene-2026),
descarga pública sin autenticación.

Evaluación (criterios `_CRITERIA` de `shared/source_intel/evaluator.py`, ya presentada en la
sesión previa): coverage 0.9 · cadence 0.5 (periodicidad no declarada, a confirmar con una segunda
descarga) · format 0.9 (xlsx/zip estructurado) · license 0.85 (pública, sin términos de reventa
revisados a fondo).

Cifras verificadas que la fuente aporta (contribuyentes activos):

| Vertical | Subclase(s) CIIU | Activos |
|---|---|---|
| Fast food / comida rápida | 552118 + 552113 | 1,966 |
| Universo Restaurantes, Bares y Cantinas | todas las subclases 552xxx de ese grupo | 13,183 |
| Hoteles | 551xxx | 1,897 |
| Supermercados | 513992 (mayorista) + 521120 (minorista) | 2,991 |
| Farmacias | 523110 (minorista) + 513310 (mayorista) | 4,329 |

**Caveat obligatorio (debe viajar con el dato, no quedar solo en este spec):** "cantidad de
contribuyentes" no es "cantidad de locales" (una cadena puede operar varias tiendas bajo un mismo
RNC) y la clasificación CIIU es auto-declarada por el contribuyente al registrarse (evidencia:
hilo de ayuda de DGII donde un contribuyente pregunta qué actividad asignar a venta de comida
rápida — indica inconsistencia de auto-clasificación). Esta nota debe quedar en el `note`/
metodología de cada entrada ingerida, para que el guardrail numérico la herede en cualquier
narrativa que la use — mismo patrón que la declaración de `ease_of_business` como rúbrica en el
IAI sectorial.

### B.2 Fuente B — DGII, Operaciones y Recaudaciones ITBIS por actividad económica

**Recomendación: investigar, no aprobar todavía.** Confirmado que la serie existe, desagregada
"por sector o actividad económica según CIIU, por mes", descargable en zip (2015-2026 y
2007-2014, `dgii.gov.do/estadisticas/Operaciones-Recaudaciones-ITBIS/`). El "Ranking de
Actividades Económicas 2023" (PDF anual) da la cifra agregada de referencia (Hoteles/Bares/
Restaurantes: RD$23,369.7MM ITBIS 2023, 4,512 contribuyentes declarantes, PIB sectorial
RD$470,779.5MM), pero esa cifra es a nivel de categoría amplia, no de subclase. **Falta**: bajar el
zip mensual y confirmar si llega a nivel subclase (552118) o se queda en la categoría amplia. Es
el siguiente paso de investigación, no de ingeniería.

### B.3 Arquitectura de integración

**Punto de enganche — decisión explícita:** NO se agrega a `shared/products/registry.py` (evitaría
reabrir la decisión ya tomada de no crear un sector/producto nuevo tipo Retail/Consumo). SÍ se
agrega a `shared/knowledge` (el corpus del motor de research libre), como entradas `kind="registry"`
con `meta.state="real"`, para que `_evidence_state()` (una vez con el fix de A.4) las trate como
REAL de forma consistente con el resto del Data Registry.

Esto además cierra —parcialmente— el hallazgo pendiente de la Pregunta 1: el informe declaró como
brecha "el desglose del PIB por subsector Hoteles-Bares-Restaurantes", cuando `economic_structure`
(`modules/sector_intel/structure_product.py:246,248`) ya tiene esa cifra de peso en el PIB. La
Fuente A no reemplaza esa investigación pendiente (sigue siendo prioridad confirmar si fue una
brecha real o un fallo de ruteo — ver conversación previa), pero si el ruteo falla otra vez, al
menos la sub-pregunta de conteo de participantes por vertical quedará anclada con dato real nuevo
en vez de caer a rúbrica-ruido o brecha.

**Conector nuevo:** `shared/data/dgii_rnc_client.py`, mismo patrón que los conectores estáticos ya
existentes (descarga de archivo publicado + parseo, no API en vivo).

**Persistencia — decisión del dueño (2026-07-14, refina B.3):** el agregado NO se publica como
un pre-cómputo suelto (JSON), sino que **se persiste en DB con historia**, coherente con que DGII
ya es una fuente sincronizada en la plataforma (pulso fiscal, `dgii_client.py` → MacroSeries) y con
que este dato es información estructurada que se querrá consultar de forma ágil (y el ITBIS por
subclase a futuro caería en la misma familia). Implementación en capas:
- **Tabla dedicada** `dgii_contribuyente_subclase` (área transversal nueva `shared/reference/`):
  `(corte, subclase)` único, columnas `activos`/`activos_fisica`/`activos_juridica` + lineage. La
  columna `corte` da historia multi-snapshot. Migración Alembic `f1a2c6e9b7d4`. NO es
  `shared/products/registry.py` (se respeta la decisión de no crear un sector/producto nuevo).
- **Sync + operación de consola** `dgii-contribuyentes-sync` (`shared/reference/dgii_sync.py`,
  `operations.py`), cadencia **manual** (`default_interval_hours=0`): el dueño la corre cuando DGII
  publica un corte nuevo; upsert por `(corte, subclase)` (re-correr no duplica).
- **Capa de research** `dgii_passages(db)` (`shared/knowledge/ingest.py`): lee el corte más reciente
  de la tabla y emite los pasajes `kind="registry"`/`meta.state="real"` — el consumo por el motor de
  research queda idéntico a lo previsto en B.3, solo cambia el origen (DB en vez de JSON).

**Pre-cómputo — no ingerir las 190k filas crudas.** Agregar a nivel de subclase (conteo activos,
por tipo de persona) y persistir con lineage (fuente, URL, fecha de corte, caveat de B.1). Se
guardan **todas** las subclases (~1.9k), no solo las del crosswalk: extender a un vertical nuevo es
una línea de crosswalk, sin re-parsear. El detalle por provincia/municipio y por año de
incorporación no se necesita para este caso de uso; si se necesita después, es una segunda pasada.

**Crosswalk:** tabla subclase CIIU → etiqueta de vertical en lenguaje natural (la de B.1), para que
el retrieval léxico pueda matchear "cuántas cadenas de comida rápida" contra la entrada de
552118+552113 sin que el usuario tenga que conocer el código CIIU.

**Cadencia:** manual / a confirmar — no se declara "viva" ni se promete actualización automática
hasta que una segunda descarga confirme periodicidad real de la publicación de DGII.

### B.4 Pasos (formato scaffold, para que calce con lo que `source_intel.scaffold()` produciría)

- **data_access:** descarga directa del zip/xlsx público de DGII, sin autenticación; re-descarga
  manual hasta confirmar cadencia (B.2 la definirá para la Fuente B; para la Fuente A queda
  pendiente la misma confirmación).
- **connector:** `shared/data/dgii_rnc_client.py` — parseo + agregación por subclase (no ingesta
  cruda).
- **crosswalk:** tabla subclase→vertical (B.3) + caveat de auto-clasificación (B.1) embebido en el
  `note` de cada entrada.
- **target:** tabla `dgii_contribuyente_subclase` (`shared/reference/`) como fuente persistida con
  historia; el motor de research la consume vía `dgii_passages(db)` → pasajes `kind="registry"`,
  `meta.state="real"`. NO `shared/products/registry.py`.
- **steps:** (1) confirmar cadencia con segunda descarga en unos meses · (2) conector + agregador +
  tabla/migración + sync/operación (HECHO) · (3) el motor de research lee el corte más reciente de la
  tabla (HECHO) · (4) prueba de aceptación: la pregunta control ("¿cuántos contribuyentes activos en
  restaurantes de comida rápida?") ancla REAL citando DGII + corte + caveat (HECHO, test e2e) ·
  (5) evaluar Fuente B (bajar el zip ITBIS, confirmar granularidad) antes de decidir si se integra.
- **estado (2026-07-14):** implementado y verificado offline (conector reproduce las 5 cifras de B.1
  al dígito contra el archivo real; migración reversible; 11 tests). Falta correr
  `dgii-contribuyentes-sync` en prod para poblar la tabla del primer corte.
- **risks:** cadencia real desconocida (puede ser anual, no mensual) · auto-clasificación CIIU
  inconsistente (subestima el universo real de cada vertical, especialmente 552118 vs el catch-all
  552111) · el archivo de origen fue una subida manual del dueño, no un fetch automatizado — el
  conector debe apuntar a la URL pública de DGII, no al archivo subido, para ser reproducible.
- **effort:** S/M — no requiere motor nuevo, es un conector + agregador + una entrada al índice
  existente.

---

## Fuera de alcance (explícito)

- No se agrega "fast food" ni ninguna sub-industria como sector nuevo en el catálogo de 14
  productos.
- No se reabre la decisión de Retail/Consumo descartado.
- No se activa `special:research-custom` como SKU comercial — sigue vigente la decisión de no
  ofrecerlo aún; este spec es instrumentación de build (Fase 2), no lanzamiento comercial.
- No se ingieren las 190k filas crudas del padrón RNC al corpus de research — solo el agregado por
  subclase con lineage.
- La Fuente B (ITBIS) no se integra en este ciclo — solo se investiga su granularidad.
- No se toca `shared/products/` ni el framework de sectores/tiers — este spec es enteramente
  `shared/research/` + `shared/knowledge/` + un conector nuevo en `shared/data/`.

## Sensores y criterios de aceptación

- **Regresión dirigida:** re-correr la Pregunta 3 tal cual después del fix de A.4 — la sub-pregunta
  de participación de mercado debe salir **GAP**, no RUBRIC, con nota de brecha declarada (no un
  "100% con ancla" falso).
- **No-regresión:** re-correr Preguntas 1 y 2 — deben mantenerse en 75%/75% y 100%/100% (el fix no
  debe convertir rúbrica legítima existente en brecha; si baja la cobertura de la Pregunta 2, el
  umbral de A4.1 quedó demasiado alto).
- **Prueba de aceptación de la Fuente A:** una vez integrada, una pregunta de control ("¿cuántos
  contribuyentes activos hay en restaurantes de comida rápida en RD?") debe anclar **REAL**, citando
  la fuente DGII con su fecha de corte y el caveat de auto-clasificación en la narrativa.
- `pytest shared/research shared/knowledge shared/data -v`, cobertura ≥80% en el código nuevo/
  tocado (convención `CLAUDE.md`).
- Sensor de anti-fabricación: el guardrail numérico debe seguir en verde (0 cifras sin trazar) en
  las narrativas que ahora citan la Fuente A.
- Reviewer subagent sobre el diff antes de mergear (convención del repo para specs que tocan
  contratos/producción).

## Riesgos / decisiones abiertas

- **[Guessing]** Umbral exacto de A4.1/A4.3 — calibrar con más preguntas del piloto, no solo con
  este caso; riesgo de sobre-corregir y empezar a declarar brecha en rúbricas legítimas.
- **[Guessing]** Si el score de `shared/knowledge/ingest.py` se normaliza por longitud de consulta
  — no verificado en este spec; si no se normaliza, es un segundo lugar candidato para el fix,
  además de A.4.
- **[Lock pendiente del dueño]** ¿La Fuente A se somete también por el tablero `source_intel`
  (propuesta → evaluación → scaffold → aprobación) para quedar trazada en el sistema, o el
  contenido de este spec se toma como el scaffold ya hecho y se construye directo? Recomendación:
  someterla igual al tablero — es barato (un POST) y mantiene la disciplina de "el sistema propone,
  el dueño dispone" para futuras fuentes.
- **[Guessing]** Periodicidad real de la publicación DGII de contribuyentes — confirmar con una
  segunda descarga en unos meses antes de prometerla como cadencia "viva" en cualquier material de
  venta.
