# Hallazgo 7 — el corpus de "rúbrica declarada" es 89% documentación interna, no doctrina citable

> **CERRADO.** Documento histórico: se conserva por el diagnóstico de §1-2, no como trabajo
> pendiente. El §3-4 (código) y el §5 (contenido) se implementaron y mergearon el 2026-07-15 en
> `24e15c0` — `CORPUS_MANIFEST` quedó con los 5 YAML de doctrina, `_passages_from_source` extrae
> solo el campo `rationale` con parseo YAML real, y hay gate de CI
> (`shared/knowledge/corpus/tests/test_citability_gate.py`).
>
> **Las 3 preguntas del §6 quedaron resueltas así (2026-07-22):**
> 1. Las 4 notas entre paréntesis del §5 se verificaron contra el código, no de memoria. Tres de
>    las cuatro seguían siendo válidas (IRC transición en rúbrica; IRMP con rúbrica cero; IDM
>    entero en dato real). **La del IAI había quedado obsoleta**: el texto publicado declaraba
>    como rúbrica cuatro variables que ya son dato real (`operating_cost` TSS,
>    `labor_availability` ENCFT, `regulatory_quality` y `regulatory_volatility` WGI,
>    `skills_index` WB HCI). De 9 variables, 8 son reales; la única rúbrica viva es
>    `ease_of_business`. Los `dimension_rationales` de `sectoral.yaml` se corrigieron.
> 2. Luz verde dada y ejecutada.
> 3. **Sí** — la advertencia explícita se adoptó, y en ambas direcciones: donde una dimensión es
>    rúbrica se declara ("supuesto neutral de casa"), y donde es dato real pero de alcance
>    NACIONAL se declara también, porque un cliente podría leer "dato real" como "diferencia
>    entre sectores" y no lo hace.
>
> Lección que deja: un texto citable que describe el estado de los datos **envejece con cada
> conector nuevo**. Vale la pena una verificación periódica del rationale contra la procedencia
> real, no solo del formato — el gate de CI atrapa tablas y código, no afirmaciones vencidas.

**Estado original del documento (2026-07-15): diagnóstico confirmado por auditoría de código
sobre los 14 documentos del manifest. Sección 5 era BORRADOR de contenido.**

## 1. Magnitud del problema (no son 2 archivos sueltos)

Repliqué `_split_blocks()` (la función real de troceo, `shared/knowledge/corpus/__init__.py`)
y la corrí contra los 14 documentos del `CORPUS_MANIFEST` completo — no solo contra los 2 que
viste en pantalla. Resultado: **215 chunks totales, 192 marcados como no aptos para cita directa
a cliente (89%)**. Los criterios de marca: tabla markdown cruda, fence de código, comentario YAML
tipo prosa dirigido a desarrolladores, dump de `key: value` sin campo de prosa, densidad de
identificadores/rutas de código, o corte a los 280 caracteres en mitad de frase (el límite que usa
`_evidence_lines` al citar).

Desglose:

| Fuente | Chunks | Sospechosos | Naturaleza real del documento |
|---|---|---|---|
| `shared/doctrine/sectoral.yaml` | 7 | 7 | config YAML (pesos/variables) + comentarios de dev |
| `shared/doctrine/esg.yaml` | 5 | 5 | ídem |
| `shared/doctrine/regulatory.yaml` | 11 | 10 | ídem |
| `shared/doctrine/social.yaml` | 5 | 5 | ídem |
| `shared/doctrine/macro_sector.yaml` | 9 | 9 | ídem (aunque SÍ tiene prosa citable, ver §3) |
| `docs/REPORT_STANDARD.md` | 16 | 14 | spec de producto interno |
| `docs/DEEP_DIVE_FITCH_PARITY.md` | 44 | 39 | bitácora de workstream de ingeniería (PRs, fixes) |
| `docs/RUBRIC_AUDIT_AND_REMEDIATION.md` | 21 | 16 | auditoría interna de deuda técnica |
| `docs/IRMP_SOURCE_UPGRADE_RESEARCH.md` | 16 | 15 | investigación de fuentes de datos (interno) |
| `docs/SPEC_PLATFORM_PRODUCTIZATION.md` | 25 | 20 | spec de arquitectura de software |
| `docs/SPEC_TIER_PRODUCTIZATION_BANKING.md` | 20 | 18 | spec de arquitectura de software |
| `docs/RECETA_ONBOARDING_SECTOR.md` | 9 | 9 | guía de onboarding para ingenieros |
| `docs/SERIES_CANONICAS_BCRD.md` | 14 | 14 | catálogo técnico de series (tablas) |
| `docs/bcrd_estadisticas_catalog.md` | 5 | 3 | inventario de archivos Excel |
| **Total** | **215** | **192 (89%)** | |

## 2. Causa raíz real

`CORPUS_MANIFEST` (`shared/knowledge/corpus/__init__.py:46-59`) es un allowlist explícito — buena
intención de diseño ("agregar una fuente es una decisión revisada, no un accidente", dice el propio
comentario del archivo) — pero en la práctica nunca se revisó a nivel de PÁRRAFO, solo a nivel de
ARCHIVO. Los 9 documentos de `docs/*.md` en el manifest **nunca fueron escritos para que un
cliente los lea** — son specs de arquitectura de software, bitácoras de PRs, auditorías internas de
deuda técnica. Los 5 YAML de `shared/doctrine/` sí contienen doctrina legítima (pesos, bandas,
lógica de inversión de variables) pero estructurada como config para el motor de scoring, con
comentarios `#` dirigidos a quien mantiene el código — no como prosa para citar.

`_is_code_dump()` (`shared/research/decompose.py:148-152`) existe precisamente para evitar esta
fuga, pero su regex busca sintaxis de código (backticks, rutas `.py`, `identificador_con_dos_guiones`,
rutas `/con/slash`) — no detecta prosa fluida en español que resulta ser, por contenido, una nota de
ingeniería ("el código viejo ya no existe en prod") o una tabla markdown aplanada. El filtro está
calibrado para la forma, no para la audiencia.

El fix de Hallazgo 5 (round-robin por fuente, PR #542) no introdujo el problema — lo hizo visible.
Antes, estos pasajes perdían la lotería de truncación por posición; ahora, cualquier fuente
presente en `sq.evidence` garantiza su línea. El bug real es anterior y más profundo: nada en el
pipeline distingue "esto es material propio con licencia clara" (el criterio que sí aplica
`CORPUS_MANIFEST` hoy) de "esto fue escrito para que un cliente lo lea" (el criterio que falta).

## 3. Arquitectura propuesta — separación dura, no un filtro más

**Principio: lo que se CITA a un cliente y lo que ALIMENTA el cálculo del score son dos cosas
distintas, y hoy comparten el mismo archivo YAML sin frontera.**

1. **`CORPUS_MANIFEST` deja de apuntar a `docs/*.md`.** Los 9 documentos de metodología/spec de
   ingeniería salen del manifest por completo. No necesitan reescritura — nunca debieron ser
   fuente de cita, siguen existiendo como documentación interna del repo, solo dejan de ser
   indexados para retrieval.

2. **Los 5 YAML de doctrina se dividen en dos planos:**
   - **Config** (pesos, bandas, `dimension_variables`, `rubric_defaults`, `inflation_targets`,
     `sovereign_ratings`, etc.) — se sigue leyendo directo por el motor de scoring, como hoy.
     **Deja de indexarse para retrieval.** No es prosa, nunca debió serlo.
   - **Citable** — un campo `rationale` de texto libre, uno por dimensión (o por variable donde
     amerite), escrito deliberadamente para ser leído por un cliente. Ya existe este patrón en
     `macro_sector.yaml` (7 reglas, 7 `rationale:`, prosa limpia) — es el único de los 5 que lo
     tiene. Los otros 4 (`sectoral`, `esg`, `regulatory`, `social`) no tienen ningún campo
     `rationale` hoy — cero prosa citable existe para esas 4 doctrinas. Esto es un hallazgo en sí
     mismo: no es que el corpus cite mal el IAI/IRC/IRMP/IDM — es que nunca hubo nada citable que
     extraer. Ver §5, borrador para cerrar esa brecha.

3. **Ingesta**: `load_corpus_passages()` deja de trocear archivos completos con `_split_blocks()`
   para las fuentes de doctrina. En su lugar, extrae SOLO los valores de `rationale:` (cuando
   existen) como un `Passage` por regla/dimensión — texto ya limpio, ya en español, ya del
   tamaño correcto, sin necesidad de trocear nada. Si una dimensión no tiene `rationale`, no
   genera `Passage` — esa dimensión simplemente no es citable como rúbrica hasta que alguien la
   escriba (comportamiento seguro por diseño: ausencia de prosa curada = sin cita, nunca dump
   crudo).

4. **Gate de construcción, no de runtime.** Se reemplaza la lógica de `_is_code_dump()` (que
   corre en cada research query, después del hecho) por un test que corre en CI sobre
   `load_corpus_passages()` completo: **ningún** `Passage` puede contener fence de código, ≥2
   filas de tabla markdown, ≥4 líneas `key:` sin acompañarse de una frase de cierre, o terminar
   fuera de límite de oración. Si alguien agrega una fuente nueva al manifest o un `rationale`
   mal escrito, el build falla — no lo descubre un cliente en un PDF. Esto es la generalización
   permanente del script de auditoría que usé para la tabla de §1: en vez de un one-off mío, se
   convierte en el gate real del repo.

Con esto, Hallazgo 5 (round-robin por fuente) vuelve a ser seguro por construcción: cualquier
fuente que llegue a `sq.evidence` ya pasó el gate de citabilidad en el momento de la ingesta, no
depende de que la suerte de truncación la esconda.

## 4. Qué es código (listo para especificar ya) y qué es contenido (necesita tu revisión)

**Código — alcance cerrado, sin ambigüedad, listo para Claude Code:**
- Purgar los 9 `docs/*.md` de `CORPUS_MANIFEST`.
- Reescribir `_passages_from_source()` para las 5 fuentes de doctrina: extraer `rationale`
  (parseo YAML real, no regex sobre texto) en vez de trocear el archivo con `_split_blocks()`.
- Test de gate en CI sobre el corpus completo (generalización del script de auditoría).
- Mantener acceso directo a los YAML completos para el motor de scoring (nada cambia ahí — solo
  cambia qué se indexa para *retrieval*).

**Contenido — necesita tu palabra final, no la mía:**
Los `rationale` de `sectoral.yaml`, `esg.yaml`, `regulatory.yaml`, `social.yaml` (18 dimensiones
en total) no existen todavía. Te escribí un borrador completo en §5, fundamentado estrictamente en
lo que ya está codificado en cada YAML (pesos, variables, estado real-vs-rúbrica declarado en los
propios comentarios) — no inventé metodología, narré la que ya existe. Pero esto se vuelve la voz
institucional de SDQ citada a clientes, así que no debe salir a producción sin que lo leas. Marco
explícitamente donde el propio YAML deja ambigüedad (p.ej. qué tan "real" es cada dimensión hoy)
para que la corrijas si mi lectura del código no coincide con el estado real de producción que tú
conoces.

## 5. BORRADOR — rationale por dimensión (18), para pegar en los 4 YAML tras tu revisión

### `shared/doctrine/sectoral.yaml` — IAI (Índice de Atractivo de Inversión)

- **macro** (0.25): "Mide cómo las condiciones macroeconómicas del país golpean específicamente a
  este sector — no el macro genérico, sino su exposición particular (ver Doctrina · Contrato
  macro→sectorial). Es la dimensión de mayor peso porque ningún sector opera aislado del ciclo
  nacional, y es dato real derivado del contrato macro-sectorial, no juicio de casa."
- **business** (0.25): "Clima de negocios: facilidad de operar, costo operativo y rentabilidad
  real del sector. La rentabilidad usa dato real de la Encuesta Nacional de Actividad Económica
  (ENAE) donde el sector está cubierto (8 de 17 sectores); donde no, la variable queda ausente
  en vez de rellenarse — evita distorsionar el índice con un valor inventado. Facilidad de
  negocio y costo operativo son hoy rúbrica uniforme (neutral, no discrimina entre sectores)
  mientras no haya dato real per-sector."
- **talent** (0.20): "Disponibilidad y nivel de competencias de la fuerza laboral relevante para
  el sector. Es hoy rúbrica uniforme (neutral 50 para los 17 sectores) — un limitante estructural
  de mediano plazo que SDQ aún no discrimina con dato real por sector."
- **regulation** (0.15): "Calidad y estabilidad del marco regulatorio que enmarca al sector. Pesa
  menos que negocios o talento porque, a diferencia de estos, hoy también es rúbrica uniforme
  (neutral) en tanto no se conecte el dato real del WGI que ya alimenta el eje de riesgo
  regulatorio nacional (IRMP)."
- **sector** (0.15): "Crecimiento y tamaño relativo del sector dentro del valor agregado nacional
  — dato real del BCRD para los 17 sectores. Es la dimensión que, junto con el entorno macro,
  mueve el ranking entre sectores hoy, porque negocios/talento/regulación siguen en rúbrica
  uniforme."

*(Nota para tu revisión: 3 de las 5 dimensiones del IAI —business en 2 de sus 3 variables, talent
completa, regulation completa— corren hoy sobre rúbrica neutral uniforme, no dato real
diferenciado por sector. Esto ya estaba declarado en `rubric_defaults` del YAML; el rationale de
arriba solo lo hace explícito en prosa. Si esto cambió en producción desde que se escribió el
comentario del YAML, dímelo y lo ajusto.)*

### `shared/doctrine/esg.yaml` — IRC (Índice de Resiliencia Climática, nacional desde v2.0)

- **physical_risk** (0.30): "Exposición física al riesgo climático: huracanes (HURDAT2/NOAA) y
  sensibilidad climática general (ND-GAIN). Es la dimensión de mayor peso porque el Caribe
  enfrenta el riesgo físico climático más alto y menos discrecional del conjunto — no es una
  variable de política, es geografía. Dato real."
- **transition_risk** (0.25): "Dependencia de combustibles fósiles e intensidad de carbono de la
  matriz energética — la exposición del país al costo de una transición energética global, no al
  clima físico en sí. Hoy corre sobre rúbrica uniforme (0.5) mientras se conecta el balance
  energético/PEN como fuente real."
- **adaptive_capacity** (0.25): "Preparación física y económica del país para responder a
  impactos climáticos ya en curso (ND-GAIN readiness). Compensa parcialmente el riesgo físico: dos
  países con igual exposición a huracanes no enfrentan el mismo riesgo neto si uno tiene mayor
  capacidad de respuesta. Dato real."
- **governance** (0.20): "Calidad de gobernanza y preparación social para gestionar el riesgo
  climático (ND-GAIN). Dato real."

*(Nota: el YAML marca "físico/adaptativa/gobernanza = ND-GAIN real; transición = rúbrica uniforme"
explícitamente en su comentario — el rationale de transition_risk lo refleja. Confírmame si
`fossil_dependence`/`carbon_intensity` ya se conectaron a una fuente real, porque el comentario del
YAML sugiere que estaba en plan, no necesariamente cerrado.)*

### `shared/doctrine/regulatory.yaml` — IRMP (Índice de Riesgo Macro-Político)

- **macro** (0.30): "Estabilidad macroeconómica: crecimiento, brecha de inflación frente a la meta
  del banco central, balance fiscal, deuda pública y cobertura de reservas en meses de
  importación. Es la dimensión de mayor peso del IRMP porque la estabilidad macro condiciona
  directamente el costo de financiamiento soberano. Dato real."
- **external** (0.20): "Solidez de la posición externa: cuenta corriente, inversión extranjera
  directa, volatilidad cambiaria y rating soberano (S&P, con Fitch/Moody's como contexto —
  política de 'S&P manda' para evitar doble conteo). Dato real."
- **political** (0.25): "Estabilidad político-institucional, medida con los 5 indicadores
  absolutos del World Governance Indicators (estado de derecho, efectividad de gobierno, control
  de corrupción, estabilidad política, voz y rendición de cuentas) más la proximidad al próximo
  ciclo electoral, calculada desde el calendario electoral verificado de cada país — no una
  encuesta de percepción tecleada. Dato real; es la dimensión con más peso individual después de
  macro porque la inestabilidad institucional es, históricamente, el mejor predictor de deterioro
  fiscal no forzado por choques externos."
- **regulatory** (0.15): "Calidad regulatoria y su volatilidad histórica, ambas del WGI nacional.
  Pesa menos que las otras dimensiones institucionales porque se solapa parcialmente con
  'political' — el IRMP retiró en 2026 las rúbricas tecleadas (`policy_continuity`,
  `discretion`, `contract_enforcement`) precisamente por doble conteo con estas dimensiones WGI.
  Dato real."
- **events** (0.10): "Tensión de corto plazo: tono de la cobertura noticiosa, intensidad de
  disturbios y exposición a sanciones, las tres vía GDELT. Es la dimensión de menor peso porque
  captura choques transitorios, no la condición estructural del país — pero es la que más rápido
  reacciona a un evento nuevo. Dato real."

*(Nota: este es el eje más maduro de los 4 — el propio YAML declara "YA NO HAY RÚBRICA DURA en el
IRMP" tras la racionalización de 2026-07. Los 5 rationale de arriba pueden citarse con más
confianza que los de IAI/IRC/IDM, que sí tienen dimensiones todavía en rúbrica uniforme.)*

### `shared/doctrine/social.yaml` — IDM (Índice de Desarrollo Multidimensional)

- **health** (0.25): "Esperanza de vida y mortalidad infantil, ambas del WDI nacional. Dato
  real."
- **education** (0.25): "Alfabetización y cobertura secundaria neta por región (ONE/ENHOGAR), más
  años promedio de escolaridad a nivel nacional (ONE no publica esta última por región). Dato
  real."
- **living_standards** (0.25): "Ingreso per cápita — proxy declarado de ingreso laboral por hora
  (ONE), no ingreso per cápita del hogar — y tasa de pobreza por región (ONE). Dato real."
- **inclusion** (0.25): "Inclusión financiera (cajeros por 100 mil adultos, Banco Mundial Findex,
  proxy de acceso) e informalidad laboral (ONE/BCRD, Encuesta Continua de Fuerza de Trabajo).
  Dato real."

*(Nota: el IDM es el segundo eje más limpio — el YAML declara las 9 variables en dato real, sin
rúbrica activa salvo como fallback ante un período sin dato. Los 4 rationale de arriba son
directos; avísame si el proxy de ingreso per cápita (ingreso laboral/hora, no ingreso del hogar)
necesita una advertencia más visible en el reporte final, más allá de la cita de rúbrica —
me parece un matiz que un cliente debería ver siempre, no solo cuando se cita esta dimensión.)*

## 6. Qué necesito de ti

1. Confirmar o corregir las 4 notas entre paréntesis arriba (estado real-vs-rúbrica de IAI/IRC —
   son lecturas mías del código, no verificación en producción).
2. Luz verde para que el prompt de Claude Code (abajo, en el chat) implemente §3-4 usando el texto
   de §5 tal como está, o con tus correcciones.
3. Decidir si quieres que `governance` (IRC) y las dimensiones aún en rúbrica uniforme (business/
   talent/regulation del IAI, transition_risk del IRC) lleven una advertencia explícita en el
   texto citado ("esta dimensión aún no discrimina entre sectores/países — rúbrica neutral") en
   vez de leerse como si fuera dato diferenciado. Yo recomendaría que sí — es coherente con el
   principio de honestidad que motivó todo Hallazgo 1-6, y es barato de agregar ahora que ya
   estamos escribiendo el texto.
