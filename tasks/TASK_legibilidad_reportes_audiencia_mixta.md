# Tarea — Legibilidad de los Deep Dive para audiencia mixta (técnica + ejecutiva) + 3 bugs de template en producción

> **Para:** Claude Code. **Tipo:** corrección de bugs de producción ya confirmados en PDFs
> generados + mejora de legibilidad (glosario auto-detectado + doctrina de voz) + cierre de
> un gap real en la disciplina anti-fabricación fuera de la ruta cerebro.
> **Origen:** auditoría de tono/calidad de los 6 Deep Dive (Seguros, Política Monetaria,
> Estructura Sectorial, Turismo, Riesgo-País, Banca) entregados a Ricardo el 2026-07-17,
> más dos correcciones de Ricardo sobre el alcance: (1) el problema de audiencia es de
> FONDO y estilo, no solo de siglas sin glosario — la sustancia epistémica se preserva
> siempre, pero el vestuario en que se expresa en el cuerpo del texto sí cambia; (2) esto
> debe considerarse en TODAS las piezas donde SDQ·MIP genera una explicación o informe con
> IA, no solo en los 6 ejes de Deep Dive fijo.
> **Proceso:** Plan First (este documento — confirmar con Ricardo antes de codear si algo
> no está claro), Verify Done con Sensors, Reviewer Subagent antes de cerrar,
> `tasks/lessons.md` al terminar.
> **Sin migraciones. Sin tocar DB.** Cambios en `shared/products/*`, `shared/narrative/cerebro.py`,
> `shared/narrative/claude_engine.py`, `shared/publications/digest.py`,
> `modules/banking_score/reports/pdf_generator.py`, más tests nuevos.

## Revisión 2 (esta versión) — dos precisiones de Ricardo sobre el alcance

1. **Cobertura de toda la app, no solo los 6 ejes.** Se corrió un grep sistemático de
   `messages.create|Anthropic(|anthropic.Anthropic|openai.|chat.completions` y por separado
   de `narrative_engine|NarrativeEngine|from shared.narrative|import shared.narrative` sobre
   TODO `shared/` y `modules/` (excluyendo `.claude/worktrees/*`, que son 3 copias espejo del
   repo por workspaces previos de Claude Code — mismo contenido, no aportan superficie nueva;
   vale la pena que Claude Code las revise por separado por si tienen WIP sin mergear antes de
   tocar los mismos archivos). Resultado: además de las dos rutas ya mapeadas dentro de
   `claude_engine.py` (cerebro / legacy), hay una **tercera ruta de generación de narrativa,
   totalmente aparte, sin ningún gobierno de voz ni disciplina epistémica** —
   `shared/publications/digest.py` — ver hallazgo D y sección 8 más abajo. El resto de los
   call-sites directos a Anthropic (`shared/source_intel/{scaffolder,agent,evaluator}.py`,
   `shared/research/{domain_router,relevance}.py`, `shared/pdf/audited_extractor.py`,
   `shared/narrative/numeric_guard.py`, `shared/data/bcrd_excel/interpreter.py`,
   `modules/social_dev/education_extract.py`, y los scripts de eval en `scripts/`) se revisaron
   uno por uno y quedan fuera de alcance por diseño — ver "Cobertura verificada, no solo
   grep superficial" al final de la sección Contexto, con el motivo puntual de cada exclusión.
2. **El frame de audiencia NO cambia.** Ricardo decidió: `AUDIENCE_FRAMES` y
   `resolve_audience()` quedan exactamente como están — no se agrega un frame "ejecutivo", no
   cambia el default por tier. Lo que mejora es el WORDING de la prosa que ya se genera bajo
   cada frame, conservando el tipo de término que esa audiencia específica maneja (un comité de
   crédito sigue leyendo ICAP, ROA, IC 90%; no se le diluye el vocabulario). Esto es exactamente
   lo que ya hacían las secciones 6 y 6b de este plan (explicar el significado antes de citar la
   sigla, sin bajar el registro técnico) — ver "Decisión de Ricardo sobre el frame de audiencia"
   más abajo, que reemplaza la antigua "Decisión pendiente".

## Contexto / causas raíz (ya diagnosticadas — no re-investigar desde cero)

Se auditaron los 6 PDFs Deep Dive más recientes, más un mapeo sistemático de todo el flujo de
generación de narrativa con IA en el resto de la app (ver "Revisión 2" arriba). Los hallazgos,
cada uno con causa raíz confirmada en código (no son impresiones — se rastreó línea por línea):

**A. Tres bugs de template visibles en PDFs ya entregados a clientes potenciales:**

1. El Informe de Calificación Completa de banca imprime literalmente `deep_dive` sin
   traducir en la portada y en el encabezado de las 14 páginas ("Informe de Calificación
   Completa · deep_dive"). Causa: `modules/banking_score/reports/pdf_generator.py:857-859`
   concatena el tier crudo (`title_label = f"{title_label} · {tier}"`) sin mapeo de
   etiqueta — a diferencia de `REPORT_TYPE_LABELS`, que sí traduce `report_type`.
2. El header corrido de Política Monetaria y de Estructura Sectorial repite el nombre del
   eje dos veces ("Deep Dive · Política Monetaria · Política Monetaria · República
   Dominicana"; "Deep Dive Estructura Sectorial · Economía Dominicana · Estructura
   Sectorial"). Causa: `shared/products/render.py:323` concatena `title` y `display_name`
   sin dedupe, y varios módulos meten el nombre del eje en AMBOS strings de forma
   independiente (confirmado en `app/products_monetary_policy.py:234-235` y
   `modules/sector_intel/structure_product.py:41,323`; Turismo tiene el mismo patrón de
   forma más leve).
3. Las secciones estándar de metodología/fuentes en el reporte de banca se titulan "Std
   Methodology" / "Std Sources" — inglés y snake_case sin traducir, visible en el índice
   del documento. Causa: `modules/banking_score/reports/pdf_generator.py` tiene su propio
   `NARRATIVE_SECTION_TITLES` que nunca se sincronizó con
   `shared/products/report_sections.py:STANDARD_SECTION_TITLES` (que sí tiene "Metodología
   y fuentes" / "Fuentes y referencias" correctos) — cuando la clave no se reconoce, cae al
   fallback `key.replace("_"," ").title()`, que es exactamente `"std_methodology"` →
   `"Std Methodology"`.

**B. Fricción de audiencia (planteada por Ricardo, corregida en alcance por Ricardo — ver
abajo):** los reportes traen ISF, PTA, HHI, CAGR, WGI, IRMP, Gini, macro-F1, XGBoost, IC
90%, ICAP, Tier 1, etc. sin definir en ningún lugar del documento. Causa raíz en
`shared/narrative/cerebro.py`:
- El único llamado a "no recites siglas como un volcado de datos" vive SOLO en
  `AXIS_DOCTRINE["banking"]` (línea ~136) — los otros 5 ejes no lo tienen.
- No existe NINGÚN mecanismo de glosario en toda la base de código (`grep -rn glosario`
  no devuelve nada).
- `AUDIENCE_FRAMES` existe por eje (línea ~308) pero las 8 audiencias definidas son todas
  institucionales/técnicas (`comite_credito`, `inversionista`, `comite_inversion`); no hay
  ningún frame para lector ejecutivo generalista. El tiering comercial (Pulse/Insight/Deep
  Dive) controla CUÁNTA data se muestra, nunca CÓMO se explica — no hay rama condicional
  por tier en el registro/voz.

**Corrección de Ricardo sobre B:** el primer borrador de este plan trató esto como un
problema puramente de SUPERFICIE (siglas sin traducir) y dejó `EPISTEMIC_STANDARD`
—el bloque que instruye "esto sugiere con fuerza que…" / "es plausible, aunque no está
en los datos, que…"— fuera de alcance. Ricardo corrigió: la disciplina epistémica (nunca
inventar una cifra; distinguir siempre dato verificado / inferencia fuerte / conjetura;
declarar cuando la lectura es mayormente conjetura) es la ventaja diferencial real del
producto y NO se relaja — pero el REGISTRO en que esa disciplina se expresa en el cuerpo
del texto SÍ es, además de un problema de estilo, un problema de fondo: nombrar las
categorías epistémicas con su etiqueta técnica ("esto es una inferencia fuerte") es
vocabulario de metodólogo, no de decisión ejecutiva. Ver sección 6 más abajo — ahí se
resuelve manteniendo la regla intacta y cambiando solo cómo se nombra en prosa.

**C. Alcance real fuera de los 6 ejes de Deep Dive (hallazgo nuevo, a pedido explícito de
Ricardo: "debe considerarse en todas las piezas donde generamos una explicación o informe
con IA").** Se mapeó sistemáticamente dónde más se genera narrativa con IA en el repo
(`grep` de `client.messages.create` / `system_prompt` / imports de `cerebro` en todo
`shared/` y `modules/`). Hallazgo: existen DOS rutas de generación en
`shared/narrative/claude_engine.py::generate()`:
- **Ruta cerebro** (`axis=` set): el system prompt incluye `CEREBRO_IDENTITY` +
  `REGISTER_NEUTRO` + `EPISTEMIC_STANDARD` + `BARRA_DE_INSIGHT` + la doctrina del eje. Es
  la ruta de los 6 Deep Dive auditados, y también de `shared/research/narrate.py` cuando
  la pregunta cae en uno de los 13 `sector_key` mapeados en `_CEREBRO_AXIS` (banking,
  macro/monetary_policy, trade, tourism, free_zones, energy, telecom, construction,
  agribusiness, economic_structure, esg, pension — sector_intel vía "agribusiness").
- **Ruta legacy** (`axis=None`): `shared/narrative/claude_engine.py:1189-1199` — el
  system prompt es **SOLO `REGISTER_NEUTRO`**. NO incluye `EPISTEMIC_STANDARD`: sin regla
  dura anti-fabricación explícita en el prompt, sin distinción dato/inferencia/conjetura,
  sin Barra de Insight. Confirmado que `app/market_brief.py:237` (el producto "Market
  Brief") llama `narrative_engine.generate(...)` **sin `axis=`** → siempre ruta legacy.
  `cross_compare` y `deal_outlook` (mencionados en el docstring de `cerebro.py` como
  también-legacy) y cualquier pregunta del motor de research fuera de los 13 sector_key
  mapeados caen en la misma ruta.

Esto es más importante que la fricción de audiencia: no es que el registro sea denso para
un ejecutivo — es que el gate de honestidad ("nunca se fabrica una cifra", la garantía
central que se vende como diferencial del producto) no está en el prompt de esa ruta hoy.
Ver sección 7 más abajo.

**D. Tercera ruta, fuera de `claude_engine.py` por completo, sin ningún gobierno de voz
(hallazgo nuevo de esta revisión — más grave que C).** `shared/publications/digest.py::build_digest`
llama a `anthropic.Anthropic().messages.create(...)` de forma completamente independiente del
motor compartido: sin `system=` en absoluto (ni `REGISTER_NEUTRO` ni `EPISTEMIC_STANDARD`, cero
gobierno de voz, no solo falta la disciplina epistémica). El docstring del archivo lo confirma
como reader-facing: "consumed by the macro/banking insight engines and the **Publicaciones
view**" — es decir, su salida (`resumen`, `hallazgos`, `riesgos`, `relevancia`) se le muestra
directamente al usuario. El único texto que rige la salida es el `_PROMPT` inline del archivo
(línea ~27), que pide un JSON con "resumen ejecutivo", "hallazgos clave" y "riesgos" sin ninguna
instrucción de no fabricar ni de distinguir dato/inferencia/conjetura. Ver sección 8.

**Cobertura verificada, no solo grep superficial — qué quedó fuera de alcance y por qué:**
revisado archivo por archivo cada otro call-site directo a Anthropic encontrado en el grep:
- `shared/source_intel/{scaffolder,agent,evaluator}.py`: herramienta INTERNA de curación de
  fuentes de datos ("Increment 2/3/4 de la Capa 3") — la consume Ricardo/el equipo para decidir
  qué fuentes integrar, no un cliente. Ya declara su propia honestidad ajustada a ese contexto
  (`evaluator.py`: "Honestidad declarada: la evaluación es por conocimiento del modelo... NO
  verificación web en vivo", nunca sube a "approve" con heurística sin decirlo;
  `agent.py`: "Honestidad: las propuestas son CANDIDATAS a investigar... sin
  `ANTHROPIC_API_KEY` el agente no propone... no inventa fuentes con heurística"). Aplicarle el
  registro cliente-facing sería una categoría equivocada — es honesto para SU audiencia (un
  operador interno), que ya sabe leer "method=heuristic". No tocar en esta tarea.
- `shared/research/relevance.py`: es el propio verificador del "gate de honestidad A4.2"
  (`is_method_applicable`, `verify_rubric_relevance`) — devuelve booleanos/estado de evidencia,
  no prosa para un lector. Es un GUARDIÁN, no un generador de opinión.
- `shared/research/domain_router.py`: enrutamiento semántico de qué motores convoca una
  pregunta — orquestación interna, no produce texto que un cliente lea.
  `shared/narrative/numeric_guard.py`: el guardrail anti-alucinación que verifica los textos de
  la ruta cerebro — es el sensor, no la opinión que sensa.
- `shared/pdf/audited_extractor.py`, `shared/data/bcrd_excel/interpreter.py`,
  `modules/social_dev/education_extract.py`: extracción/interpretación de estructura de datos
  (qué celda es qué campo, qué texto de PDF corresponde a qué cifra) — no generan una
  interpretación u opinión sobre el dato, generan el dato estructurado en sí.
- `scripts/validate_guard_judge.py`, `scripts/ab_guard_judge_haiku.py`: scripts de evaluación
  offline del propio `numeric_guard`, no corren en producción.

## Cambios

Todos los diffs de abajo ya están escritos, aplicados sobre una copia de trabajo, y
verificados con `python3 -m py_compile` (sintaxis válida). Aplicarlos tal cual salvo que
al leer el archivo real encuentres que difiere de lo citado aquí (código movió desde el
2026-07-17) — en ese caso, adaptar manteniendo la misma intención y avisar en el commit.

### 1. `shared/products/render.py` — dedupe del header corrido (causa raíz #2)

Agregar, antes de `def build_branded_pdf(`:
```python
def _dedup_header(title: str, display_name: str) -> str:
    """Encabezado corrido sin repetir el nombre del sector cuando ``title`` y
    ``display_name`` lo comparten (p.ej. title='Deep Dive · Política Monetaria',
    display_name='Política Monetaria · República Dominicana' → sin este dedupe el
    header repite 'Política Monetaria' — bug real detectado en producción, uno de
    varios ejes país/sector construyen ambos strings con el nombre del eje incluido).

    Conservador por diseño: solo quita un segmento de ``display_name`` (separado por
    '·') si su texto ya aparece LITERAL (case-insensitive) dentro de ``title``. Si no
    hay coincidencia, no toca nada — mejor un header algo redundante que uno que
    pierda información por una coincidencia parcial mal cortada."""
    segs = [s.strip() for s in display_name.split("·") if s.strip()]
    t_cf = title.casefold()
    kept = [s for s in segs if s.casefold() not in t_cf]
    if len(kept) == len(segs):
        return f"SDQ·MIP — {title} · {display_name}"
    tail = " · ".join(kept)
    return f"SDQ·MIP — {title} · {tail}" if tail else f"SDQ·MIP — {title}"
```

Dentro de `build_branded_pdf`, reemplazar:
```python
    header_line = f"SDQ·MIP — {title} · {display_name}"
```
por:
```python
    header_line = _dedup_header(title, display_name)
```

Verificado contra los 3 casos reales: Política Monetaria y Estructura Sectorial quedan
sin duplicado; Turismo (solapamiento parcial "Turismo"/"Sector Turismo", no exacto) queda
sin tocar — el diseño es conservador a propósito, no intenta forzar ese caso.

### 2. `modules/banking_score/reports/pdf_generator.py` — 2 fixes (causas raíz #1 y #3)

**2a. Tier crudo en el título (causa raíz #1).** Tras `REPORT_TYPE_LABELS = {...}`, agregar:
```python
# Nivel comercial (metadato de portada/header) → etiqueta ES. Sin este mapeo, el valor
# crudo de ``tier`` (p.ej. "deep_dive") queda impreso tal cual en la portada del PDF —
# bug real detectado en producción ("Informe de Calificación Completa · deep_dive").
TIER_LABELS = {"pulse": "Pulse", "insight": "Insight", "deep_dive": "Deep Dive"}
```
Y en `generate_pdf_report`, reemplazar:
```python
    if tier:
        title_label = f"{title_label} · {tier}"
```
por:
```python
    if tier:
        title_label = f"{title_label} · {TIER_LABELS.get(tier, tier)}"
```

**2b. "Std Methodology"/"Std Sources" (causa raíz #3).** Justo después de la definición de
`NARRATIVE_SECTION_TITLES = {...}` (el dict con 17 entradas, termina en `"limitations":
"Limitaciones",\n}`), agregar:
```python
# Las secciones ESTÁNDAR auto-generadas (metodología/fuentes/glosario, ver
# shared/products/report_sections.py) llegan en ``narratives`` con esas claves. Sin este
# merge, ``_build_narrative_sections`` no las reconoce y cae al fallback
# ``key.replace("_", " ").title()`` → título roto en inglés/snake_case tal cual el código
# ("Std Methodology", "Std Sources") — bug real detectado en producción, visible en la
# portada y en cada página del Informe de Calificación Completa.
try:
    from shared.products.report_sections import STANDARD_SECTION_TITLES as _STD_TITLES
    NARRATIVE_SECTION_TITLES = {**NARRATIVE_SECTION_TITLES, **_STD_TITLES}
except ImportError:  # pragma: no cover — el reporte no debe romper por esto
    pass
```

### 3. `shared/products/glossary.py` — NUEVO archivo (fricción de audiencia)

Crear con el contenido completo que Claude Code debe generar siguiendo esta especificación
(no hace falta copiarlo literal, pero si Ricardo ya tiene una versión de trabajo pídesela):

- Diccionario `GLOSSARY: Dict[str, str]` — término tal como aparece en el texto →
  definición de una frase, español llano, SIN usar el término dentro de su propia
  definición. Cubrir como mínimo, agrupado por categoría: índices propios de SDQ (ISF,
  ITT, IRMP, IAI, SDQ-AA), indicadores oficiales/macro (TPM, IMAE, VAB, ICP, IAIS, WGI,
  GDELT, DIGEPRES, SIB, SIS, SIMBAD, BCRD, ONE), métricas financieras/bancarias (ROA, ROE,
  ICAP, "Tier 1", CR5, CR10, RevPAR, HHI, CAGR), estadística/validación de modelos (Gini,
  "macro-F1", XGBoost, backtest, "out-of-sample", "IC 90%"), unidades (pp, pb).
- `_term_pattern(term) -> re.Pattern`: borde de palabra (`\b`) en cada extremo SOLO si ese
  extremo es alfanumérico (el "%" de "IC 90%" no lleva `\b` — si no, el patrón no calza
  cuando el símbolo está seguido de espacio). Case-SENSITIVE si `term.isupper()` (siglas:
  ISF, ROA, ONE — evita que un "one" cualquiera dispare la entrada); case-INSENSITIVE para
  el resto (backtest, Gini, "Tier 1" — para calzar aunque el texto las capitalice distinto,
  p.ej. inicio de oración).
- `glossary_markdown(text: str) -> str`: recorre `GLOSSARY` en orden de definición,
  devuelve `"- **term** — definición"` SOLO para los términos cuyo patrón matchea en
  `text`. Cadena vacía si no hay ningún match — el llamador nunca debe imprimir un
  glosario vacío.

**Tests unitarios obligatorios para este archivo** (ver sección Tests abajo) antes de
integrarlo — la lógica de `\b` con símbolos en el borde es la parte más fácil de romper
sin darse cuenta.

### 4. `shared/products/report_sections.py` — enganchar el glosario al mismo tier-gate que metodología

Agregar `GLOSSARY_KEY = "std_glossary"` junto a `METHODOLOGY_KEY`/`SOURCES_KEY`, y
`GLOSSARY_KEY: "Glosario"` dentro de `STANDARD_SECTION_TITLES`. Agregar función nueva:
```python
def glossary_section(narrative_text: str, tier: ProductTier) -> Dict[str, str]:
    """``{std_glossary: markdown}`` con las siglas/términos técnicos que aparecen en
    ``narrative_text`` (el texto YA REDACTADO del producto, antes de anexar metodología/
    fuentes). Tier-gated igual que metodología (Pulse queda lean, sin glosario). Vacío
    si el texto no usa ningún término del diccionario."""
    tv = tier.value if isinstance(tier, ProductTier) else str(tier)
    if tv not in _TIERS_WITH_METHODOLOGY:
        return {}
    from shared.products.glossary import glossary_markdown
    md = glossary_markdown(narrative_text)
    return {GLOSSARY_KEY: md} if md else {}
```

### 5. `shared/products/assembler.py` — invocar el glosario en el punto único compartido

En `_content_from_snapshot`, justo después de `narratives = await _narratives_cached(...)`
y ANTES del merge de `std` (metodología/fuentes, que no llevan jerga propia del eje):
```python
    from shared.products.report_sections import glossary_section
    glossary = glossary_section("\n\n".join(narratives.values()), tier)
    if glossary:
        narratives = {**narratives, **glossary}
```
Y ajustar el cálculo de `order` al final de la función para que incluya la clave del
glosario además de `std` (hoy usa solo `std`):
```python
    extra = {**glossary, **std}
    order = tuple(level.sections) + tuple(k for k in extra if k not in level.sections)
```
Este es el ÚNICO punto de integración necesario — lo heredan automáticamente la vista
in-app (JSON) y el PDF/Word, para los 15+ módulos de sector, sin tocar cada uno.

### 6. `shared/narrative/cerebro.py` — generalizar "traduce el tecnicismo" al núcleo

Hoy esa instrucción vive solo en `AXIS_DOCTRINE["banking"]`. Agregar un bullet nuevo a
`REGISTER_NEUTRO` (núcleo, compartido por los 6 ejes), inmediatamente después del bullet
"• ENCABEZADOS Y GIROS FORMALES: ...":
```python
    "• TRADUCE EL TECNICISMO (audiencia mixta: lector técnico Y ejecutivo no especializado "
    "leen el mismo reporte): no recites siglas, ratios o jerga estadística como un volcado "
    "de datos. La primera vez que uses una sigla o un término técnico del eje (HHI, CAGR, "
    "backtest, IC 90%, ICAP...) dilo por lo que SIGNIFICA para la decisión —qué tan "
    "concentrado, qué tan rápido crece, qué tan confiable es la señal, qué tan protegido "
    "está el capital— y SOLO ENTONCES respáldalo con la cifra o la sigla entre paréntesis. "
    "No asumas que el lector conoce el vocabulario técnico del eje: el glosario automático "
    "del reporte cubre la definición de diccionario; tu prosa debe cubrir el significado "
    "para la decisión, que el glosario no puede dar.\n"
```
No borrar el bullet específico de `AXIS_DOCTRINE["banking"]` (línea ~136) — es más
detallado sobre ratios bancarios concretos y queda como refuerzo, no contradice al del
núcleo.

**6b. Revisar el REGISTRO de `EPISTEMIC_STANDARD`, sin tocar la REGLA.** Esto es el fondo
de la corrección de Ricardo: la disciplina se queda exactamente igual (nunca inventar una
cifra; interpretar es obligatorio; declarar procedencia real vs. rúbrica; marcar
verificado/inferencia-fuerte/conjetura; avisar en la primera línea si la lectura es
mayormente conjetura) — lo que cambia es el vocabulario de superficie en el CUERPO del
texto, moviendo la etiqueta técnica a Metodología/Limitaciones, donde el lector que la
busca la encuentra. Reemplazar el párrafo `PROCEDENCIA` y el párrafo `INCERTIDUMBRE EN
PROSA` dentro de `EPISTEMIC_STANDARD`:
```python
    "PROCEDENCIA: el contexto marca dimensiones como \"real\" (BCRD, SIB, fuentes "
    "oficiales) o \"rúbrica declarada\" (supuesto de la casa, no dato oficial). Apóyate "
    "con firmeza en lo real. Sobre lo de rúbrica: úsalo para la lectura pero NO "
    "construyas una conclusión fuerte sobre él, y cuando sea material para tu "
    "conclusión, dilo en prosa llana —'esto es un supuesto nuestro, no viene de la "
    "fuente oficial'— en vez del término técnico 'rúbrica declarada'; ese término se "
    "reserva para la sección de Metodología, donde el lector que lo busca lo "
    "encuentra definido.\n\n"
    "INCERTIDUMBRE EN PROSA (sin corchetes, sin vocabulario de metodólogo en el cuerpo "
    "del texto): la disciplina de distinguir lo verificado, la inferencia fuerte y la "
    "conjetura es OBLIGATORIA y no se relaja nunca — lo que cambia es el vestuario, no "
    "la regla. En el cuerpo de la narrativa, señala la distinción con lenguaje llano: lo "
    "verificable ('los datos del SIB muestran…', 'confirmado'), la inferencia fuerte "
    "('todo indica que…', 'la lectura más consistente con los datos es…') y la "
    "conjetura ('no lo podemos confirmar con la información disponible, pero…', 'es un "
    "supuesto de trabajo'). EVITA nombrar las categorías con su etiqueta técnica ('esto "
    "es una inferencia fuerte', 'esto es conjetura') dentro del cuerpo — son "
    "instrucciones para VOS, no vocabulario para el lector. Si necesitás nombrarlas "
    "explícitamente por precisión metodológica, resérvalo para Metodología/Limitaciones. "
    "Si la mayoría de tu lectura es conjetura, dilo en la primera línea, en lenguaje "
    "llano."
```
Mantener intacta la `REGLA DURA` y la `REGLA DE JUICIO` (los dos párrafos anteriores de
`EPISTEMIC_STANDARD`) — no las toca esta edición, y son las que de verdad importan para
la garantía anti-fabricación.

### 7. `shared/narrative/claude_engine.py` — llevar la disciplina epistémica a la ruta legacy (hallazgo C)

Este es el cambio de mayor impacto de la tarea: hoy `market_brief`, `cross_compare`,
`deal_outlook` y las preguntas del motor de research fuera de los 13 `sector_key`
mapeados en `_CEREBRO_AXIS` se generan SIN la regla anti-fabricación explícita en el
prompt. En el bloque de la ruta legacy (línea ~1186-1199), reemplazar:
```python
        # Aun en la ruta legacy (market_brief, cross_compare, deal_outlook, etc.) se aplica el
        # registro de voz: español latinoamericano neutro corporativo-consultivo, sin la
        # doctrina/Barra del cerebro pero con el MISMO tono que el resto de la plataforma.
        from shared.narrative.cerebro import REGISTER_NEUTRO
        ...
                response = await asyncio.to_thread(
                    client.messages.create,
                    model=settings.ANTHROPIC_MODEL,
                    max_tokens=max_tokens,
                    system=REGISTER_NEUTRO,
                    messages=[{"role": "user", "content": prompt}],
                )
```
por (agrega `EPISTEMIC_STANDARD` al system; deliberadamente NO agrega `BARRA_DE_INSIGHT`
ni `CEREBRO_IDENTITY` — esas sí son la profundidad analítica específica del cerebro, y
extenderlas es una decisión de producto más grande que "no fabricar ni ocultar
incertidumbre", que debe aplicar siempre):
```python
        # Aun en la ruta legacy (market_brief, cross_compare, deal_outlook, etc.) se aplica el
        # registro de voz Y la disciplina anti-fabricación/incertidumbre — hallazgo del
        # 2026-07-17: esta ruta corría con SOLO el registro de voz, sin la regla dura que
        # prohíbe inventar cifras ni la distinción dato/inferencia/conjetura. No hay razón
        # de producto para que esa garantía exista en 6 ejes y no en el resto.
        from shared.narrative.cerebro import REGISTER_NEUTRO, EPISTEMIC_STANDARD
        legacy_system = REGISTER_NEUTRO + "\n\n" + EPISTEMIC_STANDARD
        ...
                response = await asyncio.to_thread(
                    client.messages.create,
                    model=settings.ANTHROPIC_MODEL,
                    max_tokens=max_tokens,
                    system=legacy_system,
                    messages=[{"role": "user", "content": prompt}],
                )
```
**Antes de cerrar esta pieza:** generar un Market Brief real (o de muestra) con el prompt
viejo y con el nuevo, y mostrarle el diff de tono/contenido a Ricardo — es un cambio de
comportamiento real sobre un producto que ya está en manos de clientes, no un fix
puramente mecánico como los de las secciones 1-3. Si el resultado alarga demasiado el
Market Brief (que por diseño es corto/rápido), considerar una versión recortada de
`EPISTEMIC_STANDARD` solo con la `REGLA DURA` + `PROCEDENCIA` (sin el párrafo de
`INCERTIDUMBRE EN PROSA`, que es lo que más añade longitud) — proponerlo como alternativa
si el diff completo se ve desproporcionado para un brief corto.

### 8. `shared/publications/digest.py` — gobierno de voz a la ruta del Digest (hallazgo D)

Esta ruta hoy no tiene NI SIQUIERA `REGISTER_NEUTRO` — es la más urgente de las tres. Pero
tiene una restricción que las secciones 6/7 no tenían: `build_digest` exige salida JSON
estricta ("Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional, sin \`\`\`") y
la parsea con `_extract_json`. Pegar el `REGISTER_NEUTRO` completo (que trae instrucciones de
formato en prosa — encabezados, giros discursivos) arriesga romper el contrato JSON. Enfoque:

En `build_digest`, donde hoy `client.messages.create(...)` no pasa `system=`, agregar un
`system` propio, ACOTADO — no el `REGISTER_NEUTRO` completo, solo la disciplina
anti-fabricación (la `REGLA DURA` de `EPISTEMIC_STANDARD`) reformulada para no chocar con el
contrato JSON:
```python
from shared.narrative.cerebro import EPISTEMIC_STANDARD

_DIGEST_SYSTEM = (
    "Responde ÚNICAMENTE con el objeto JSON pedido — nada de prosa fuera del JSON, "
    "nada de encabezados. Dentro de los campos de texto ('resumen', 'hallazgos', "
    "'riesgos', 'relevancia'), aplica esta disciplina: nunca inventes una cifra, "
    "hallazgo o riesgo que no esté en el texto del informe — si el informe no lo dice, "
    "no lo pongas. Si una lectura es tu interpretación (no una cifra u oración literal "
    "del informe), dilo en el propio texto del campo con lenguaje llano ('el informe "
    "sugiere que…'), nunca preséntala con la misma certeza que un dato citado."
)
...
resp = client.messages.create(
    model=model or settings.ANTHROPIC_MODEL,
    max_tokens=_MAX_TOKENS,
    system=_DIGEST_SYSTEM,
    messages=[{"role": "user", "content": prompt}],
)
```
No importar `EPISTEMIC_STANDARD` tal cual (se muestra el import arriba solo como referencia de
dónde vive la doctrina fuente) — escribir `_DIGEST_SYSTEM` como una versión corta y propia,
consistente en ESPÍRITU con `EPISTEMIC_STANDARD` pero que no meta instrucciones de formato en
prosa que rompan el JSON. **Antes de cerrar:** correr `build_digest` sobre 2-3 informes BCRD
reales (o de muestra) con el prompt viejo y el nuevo, confirmar que (a) el JSON sigue
parseando sin error con `_extract_json`, y (b) el contenido de `hallazgos`/`riesgos` no
cambió de forma drástica — es una salida que ya está en la vista "Publicaciones" de clientes.
Mismo criterio que la sección 7: no cerrar sin que Ricardo vea el antes/después.

## Sensores (correr y reportar output antes de cerrar)

```bash
ruff check shared/products shared/narrative shared/publications modules/banking_score/reports
pytest shared/products/tests/ shared/narrative/tests/ shared/publications/tests/ \
    modules/banking_score/tests/ -v \
    -k "render or glossary or report_sections or assembler or pdf_generator or claude_engine or cerebro or digest"
python3 -m py_compile shared/products/render.py shared/products/report_sections.py \
    shared/products/assembler.py shared/products/glossary.py shared/narrative/cerebro.py \
    shared/narrative/claude_engine.py shared/publications/digest.py \
    modules/banking_score/reports/pdf_generator.py
```
Si no existen suites de test para `shared/products/` o `shared/publications/`, crear
`shared/products/tests/test_glossary.py`, `shared/products/tests/test_render.py` y
`shared/publications/tests/test_digest.py` nuevos (ver Tests obligatorios).

## Tests obligatorios

- `glossary_markdown`: (a) texto con "ISF" y "HHI" → devuelve las 2 entradas, en el orden
  de `GLOSSARY`, ninguna otra; (b) texto sin ningún término conocido → `""`; (c) "Backtest"
  capitalizado al inicio de oración matchea `backtest` (case-insensitive); (d) "IC 90%"
  seguido de coma o cierre de paréntesis matchea correctamente (el caso `\b` + símbolo);
  (e) un texto con la palabra "app" NO dispara falso positivo con el término "pp" (word
  boundary correcto en ambos extremos).
- `_dedup_header`: los 3 casos reales (Política Monetaria, Estructura Sectorial → dedupeado;
  Turismo → sin cambios) más un caso sin ningún solapamiento (Seguros: título/display
  distintos → sin cambios, idéntico al comportamiento anterior).
- `pdf_generator.NARRATIVE_SECTION_TITLES` incluye `"std_methodology"` y `"std_sources"`
  con los valores en español tras el merge (test de regresión directo del bug #3).
- `generate_pdf_report` con `tier="deep_dive"` → el título resultante contiene "Deep Dive",
  nunca el string crudo `"deep_dive"` (test de regresión directo del bug #1).
- E2E ligero: generar un Deep Dive real de cualquier eje con datos de muestra
  (`assemble_sample_report` si existe) y confirmar que el PDF trae sección "Glosario" con
  al menos un término, y que el header corrido no repite el nombre del eje.
- Ruta legacy: mockear `client.messages.create` y confirmar que el `system` enviado en
  una llamada con `axis=None` contiene tanto `REGISTER_NEUTRO` como `EPISTEMIC_STANDARD`
  (test de regresión directo del hallazgo C — hoy solo contiene `REGISTER_NEUTRO`).
- `build_digest`: mockear `client.messages.create` y confirmar (a) que ahora se envía un
  `system` no vacío con la disciplina anti-fabricación (hoy no se envía ninguno — regresión
  directa del hallazgo D), y (b) que una respuesta JSON válida sigue parseando exactamente
  igual que antes (el cambio de `system` no debe alterar `_extract_json`/`normalize_digest`).
- Revisión manual (no automatizable): releer el texto nuevo de `PROCEDENCIA` e
  `INCERTIDUMBRE EN PROSA` en voz alta — si suena a manual de estilo y no a algo que un
  analista senior diría en una llamada con un cliente, no está listo. Igual para 2-3
  `resumen`/`hallazgos` reales de `build_digest` antes/después.

## Definition of Done

- Los 3 bugs de template no reaparecen en ningún PDF generado de los 6 ejes auditados
  (re-generar los 6 Deep Dive de muestra y confirmar visualmente portada + header +
  índice de secciones).
- El glosario aparece en Insight y Deep Dive (no en Pulse) de todos los ejes, con solo
  los términos que el texto de ESE reporte usa.
- La ruta legacy (`axis=None`) incluye `EPISTEMIC_STANDARD` en su system prompt; Ricardo
  vio y aprobó el diff de un Market Brief antes/después.
- `build_digest` (ruta del Digest, `shared/publications/digest.py`) envía un `system` con
  disciplina anti-fabricación (hoy no envía ninguno); Ricardo vio y aprobó 2-3 digests
  reales antes/después; el JSON sigue parseando sin regresión.
- `AUDIENCE_FRAMES`/`resolve_audience()` en `shared/narrative/cerebro.py` quedan sin cambios
  de estructura (diff vacío en esa parte del archivo) — confirmado explícitamente, no es un
  olvido.
- La disciplina epistémica (regla dura + regla de juicio + distinción
  dato/inferencia/conjetura) es idéntica a la de hoy en sustancia; solo cambió el
  vocabulario de superficie en el cuerpo del texto — confirmar releyendo 2-3 narrativas
  generadas con el prompt nuevo, no solo corriendo tests.
- Sensores en verde, reviewer subagent sin críticos.
- `tasks/lessons.md`: síntoma (3 bugs de template + falta de glosario/anti-jerga fuera de
  banking + `EPISTEMIC_STANDARD` ausente en la ruta legacy + una tercera ruta,
  `shared/publications/digest.py`, generando narrativa reader-facing sin NINGÚN gobierno de
  voz), causa raíz (fallbacks silenciosos a `key.title()` y a tier crudo sin mapeo; doctrina
  de voz y disciplina epistémica ambas sin generalizar más allá de lo que cada eje/ruta pidió
  explícitamente; superficies de generación de narrativa nuevas se construyeron ad-hoc con su
  propio `client.messages.create` en vez de pasar por el motor compartido), regla (todo dict
  de labels con fallback debe fallar ruidoso o loguear en dev, no imprimir la clave cruda en
  un PDF de cliente; toda ruta de generación de narrativa nueva hereda `EPISTEMIC_STANDARD`
  por defecto, no opt-in; antes de dar por cerrado un mapeo de "todas las piezas que generan
  narrativa con IA", correr el grep sistemático de `messages.create`/`Anthropic(`/imports del
  motor sobre TODO el repo, no confiar en la lista de módulos de sector conocidos), disparador
  (agregar un nuevo tier/report_type/sección estándar/ruta de generación/superficie de AI
  nueva sin actualizar el mapeo de labels o sin heredar la disciplina epistémica del núcleo).

## Decisión de Ricardo sobre el frame de audiencia (resuelta — reemplaza la antigua "Decisión pendiente")

Ricardo decidió NO agregar un `AUDIENCE_FRAMES` nuevo tipo "ejecutivo" ni cambiar el default
por tier. `AUDIENCE_FRAMES` y `resolve_audience()` en `shared/narrative/cerebro.py` quedan
byte-a-byte como están hoy — comité de crédito sigue siendo comité de crédito, inversionista
sigue siendo inversionista, con el vocabulario técnico que a esa audiencia le corresponde
(ICAP, ROA, IC 90%, lo que sea). Lo único que se toca es el WORDING de la prosa que ya se
genera dentro de cada frame — exactamente lo que ya hacen las secciones 6 (TRADUCE EL
TECNICISMO: explica el significado antes de citar la sigla, sin quitarla) y 6b (registro de
la disciplina epistémica en lenguaje llano, sin diluir la regla). No hay trabajo adicional
que hacer para esta decisión más allá de lo que ya cubren esas dos secciones — se documenta
acá para que quede explícito que la pregunta se cerró y no hace falta re-abrirla ni pedirle
a Ricardo que elija entre frames.

## NO hacer en esta tarea

- No relajar la REGLA DURA ni la REGLA DE JUICIO de `EPISTEMIC_STANDARD` — solo cambia el
  párrafo `PROCEDENCIA` y el párrafo `INCERTIDUMBRE EN PROSA` (sección 6b), y solo el
  registro de superficie, nunca la disciplina de fondo.
- No extender `BARRA_DE_INSIGHT` ni `CEREBRO_IDENTITY` a la ruta legacy en esta tarea —
  sección 7 agrega SOLO `EPISTEMIC_STANDARD`. Extender la profundidad analítica completa
  del cerebro a market_brief/cross_compare/deal_outlook es una decisión de producto más
  grande (cambia longitud/estructura de esos productos) y no la pidió Ricardo.
- No cerrar la sección 7 (ruta legacy) ni la sección 8 (`digest.py`) sin que Ricardo haya
  visto el diff antes/después de un Market Brief real y de 2-3 digests reales — son las dos
  piezas de esta tarea con riesgo real de cambiar perceptiblemente un producto que ya está
  en manos de clientes.
- No agregar un `AUDIENCE_FRAMES` nuevo ni cambiar `resolve_audience()`/el default por tier
  — Ricardo cerró esa pregunta explícitamente, ver "Decisión de Ricardo sobre el frame de
  audiencia" arriba. Si en algún punto parece que hace falta un frame nuevo, es señal de
  volver a preguntarle, no de decidirlo en el código.
- No tocar `shared/source_intel/{scaffolder,agent,evaluator}.py`,
  `shared/research/{domain_router,relevance}.py`, `shared/pdf/audited_extractor.py`,
  `shared/narrative/numeric_guard.py`, `shared/data/bcrd_excel/interpreter.py`, ni
  `modules/social_dev/education_extract.py` — se revisaron uno por uno (ver "Cobertura
  verificada" en Contexto) y quedan fuera de alcance con motivo explícito cada uno; no son
  un olvido.
- No tocar los demás ~10 módulos de sector (construction_intel, energy_intel, esg_climate,
  free_zones_intel, macro_monitor, pension_intel, social_dev, telecom_intel, trade_intel,
  deal_scoring) más allá de lo que ya heredan automáticamente vía el ensamblador
  compartido (`shared/products/assembler.py`) — no hace falta tocarlos archivo por
  archivo, el punto de integración único ya los cubre.
- No desplegar a Railway ni hacer commit sin que Ricardo revise el diff.

## Adenda (2026-07-17, pedido de Ricardo con screenshot del catálogo) — 4º bug de la misma familia

**Hallazgo:** el selector "Entidad a analizar" del catálogo, para Seguros, listaba los slugs
internos crudos (`cuna_mutual_insurance_society_dominicana`, `mapfre_bhd`, `la_monumental`…)
en vez de nombres presentables. Causa raíz: `modules/insurance_intel/products.py::scope_options`
enviaba `label = slug` — Seguros era el ÚNICO sector con ese defecto (banca, pensiones, ESG y
macro ya enviaban nombre). Mismo patrón de la tarea: clave interna visible al cliente.

**Resuelto en el PR #550:** `label` = nombre oficial del roster SIS ("Bupa Dominicana, S.A.",
"Angloamericana de Seguros, S. A."…), con fallback honesto al slug si una entidad no calza en
el roster, y test de regresión (`test_scope_options_label_is_official_name_not_slug`).

**De paso (misma superficie, doctrina REGISTER_NEUTRO):** voseo residual user-facing corregido —
los 4 placeholders del selector en `es.json` ("Elegí…" → "Elige…") y los errores de scope de
macro/ESG ("Seleccioná…" → "Selecciona…"). El prompt interno del `numeric_guard` ("Verificá…")
no se tocó: es instrucción al modelo juez, no texto que un cliente lea.
