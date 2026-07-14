# SPEC — Inteligencia de Fuentes: cartera de sugerencias del ciclo de investigación Jul-2026

> v0.1 · 2026-07-14 · Documento de construcción (no de validación de mercado). Etiquetas de
> confianza: **[Certain]** verificable contra código/evidencia citada · **[Likely]** inferencia
> fuerte, no probada · **[Guessing]** supuesto a validar · **[Lock]** decisión ya tomada por el
> dueño. Complementa `docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md` (Parte B, Fuentes DGII) y usa
> el contrato de `shared/source_intel/` (`models.py`, `evaluator.py`, `scaffolder.py`,
> `service.py`) ya construido. Regla Plan First: este documento se somete antes de tocar código.

**Origen.** Sesión de investigación manual del 2026-07-14 (posterior al piloto y al fix de A.4 de
`SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md`), explorando fuentes candidatas para cerrar brechas
declaradas en el piloto: DGII (Fuente A/B, ya especificadas en el spec anterior), un dashboard de
Proindustria, un boletín de ONE (ICDV), MIVHED, y dos repositorios Power BI de ONE — DyDEF
(Directorio de Empresas Empleadoras Formales) y Dominicana en Cifras (agregador de ~20 sectores
económicos + demográficos/sociales + ambientales). Este documento NO propone código: organiza lo
encontrado en el formato del tablero de Inteligencia de Fuentes (`SourceSuggestion`: kind, title,
target_axis, target_gate, evaluation, integration_plan) para que cada ítem se dé de alta,
evalúe y andamie de manera ordenada — «el sistema propone, el dueño dispone».

## 0. Resumen ejecutivo (BLUF)

Dos categorías de hallazgo, tratamiento distinto:

1. **[Certain] No es una sugerencia de fuente — es un job sin correr.** El producto
   `economic_structure` (`modules/sector_intel/structure_product.py`) ya tiene el conector, el
   contrato `SectorProduct` y hasta datos de muestra para "PIB por sectores de origen" (BCRD) —
   incluye una línea explícita `"Turismo (Hoteles/Bares/Rest.)"`. El mensaje `_NO_DATA` del propio
   código dice: *"No hay estructura sectorial persistida: corre `bcrd-sectores-sync` para ingerir
   el PIB por sectores de origen."* Esto reemplaza la hipótesis de "fallo de ruteo" que quedó
   abierta en `SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md` §B.3 con una hipótesis más barata y más
   probable: el dato nunca se ingirió. Ver §1 — acción inmediata, fuera del tablero de sugerencias.
2. **[Certain] Ocho sugerencias nuevas con evidencia de hoy**, listas para darse de alta en el
   tablero de Inteligencia de Fuentes con `origin="manual"`, más dos ítems marcados como
   redundantes/fuera de alcance para no duplicar cobertura ya cerrada. Ver §2-§4.

---

## 1. Acción inmediata — NO pasa por el tablero de sugerencias

**No se da de alta como `SourceSuggestion`.** Si se propusiera con `target_axis="economic_structure"`,
`coverage_status()` (`shared/source_intel/coverage.py`, referenciado desde `service.py`
`reflag_covered_suggestions`) muy probablemente la auto-diferiría como «ya cubierto» — hay un
producto registrado (`register_product("economic_structure", ...)`, `registry.py:354`) con
conector declarado (fuente: *"BCRD · PIB por sectores de origen (Valor Agregado)"*,
`registry.py:58`). Cargarla al tablero desperdiciaría un ciclo de evaluación en algo que el
sistema ya sabe que tiene dueño.

**Lo que sí corresponde:**

| Ítem | Detalle |
|---|---|
| Verificar | ¿Existe y corre el job `bcrd-sectores-sync` mencionado en `_NO_DATA` (structure_product.py:61-63)? ¿Cuándo corrió por última vez? |
| Si existe pero no ha corrido | Correrlo. Es la ruta más barata de todo este documento — cero código nuevo. |
| Si no existe | Es un ticket de build (conector `bcrd-sectores-sync` pendiente), no una sugerencia de fuente nueva — la fuente y el producto ya están decididos y andamiados en código, falta el job de ingesta. |
| Prueba de aceptación | Con datos persistidos, re-correr la Pregunta 1 del piloto (compuesta QSR) y confirmar que "participación de Hoteles-Bares-Restaurantes en el PIB" ancla REAL vía `economic_structure`, no vía brecha declarada. |
| Dato de referencia externo para QA | ONE "Dominicana en Cifras" → Cuentas Nacionales confirma la serie pública: Hoteles-Bares-Restaurantes RD$613,377.5MM (2024, nominal), +9.5% en tasa de crecimiento real — el sector de mayor crecimiento de los 10 mostrados en ese tablero. Útil para validar que el número que persista `bcrd-sectores-sync` cuadra con la fuente pública (mismo origen, BCRD). |

---

## 2. Sugerencias nuevas — listas para el tablero (`kind="source"` salvo donde se indique)

Formato de evaluación preliminar: mismos cuatro criterios que `evaluator.py` (`_CRITERIA`) —
coverage, cadence, format, license — puntuados 0-1 por mí como punto de partida humano, **no
sustituye la evaluación IA/heurística del sistema** (`evaluate_suggestion`, `method="ai"` o
`"heuristic"`). Recomendación en el vocabulario del sistema (`_RECS`): approve · investigate ·
reject · defer.

### 2.1 — DyDEF: Directorio de Empresas Empleadoras Formales (ONE + Hacienda)

> **[Certain] CORREGIDA en el cruce pre-carga del 2026-07-14.** El repo ya cubre dos de las
> tres dimensiones de esta fuente con granularidad igual o superior: (a) el conteo de unidades
> por actividad económica ya existe a nivel **subclase CIIU (6 dígitos)** vía el conector DGII
> (`shared/data/dgii_rnc_client.py`, Parte B del spec DGII, en `main`) — DyDEF solo llega a
> división (2 dígitos); (b) el **salario promedio por actividad** ya está integrado y en prod
> vía `shared/data/tss_salary.py` (18 actividades, Power BI querydata, sync
> `tss_salario_sync`). El valor incremental REAL de DyDEF queda acotado a los **cruces por
> tamaño de empresa (micro/pequeña/mediana/grande), sexo y masa salarial**, que ninguna fuente
> integrada expone — la cifra ancla de "solo 72 empresas de 151+ empleados en servicio de
> comidas y bebidas" sale exactamente de ese cruce y no es reproducible con DGII ni TSS.
> La sugerencia se carga con la descripción acotada a ese valor incremental. En el tablero hay
> dos sugerencias TSS diferidas (`pension/g5`, empleadores/empleos cotizantes) que solapan
> tema pero no variable.

- **target_axis:** ninguno de los 14 del catálogo calza limpio — alimenta `shared/knowledge`
  (corpus de research libre) como `kind="info_type"`, no un producto sectorial existente.
- **Descripción:** Empresas empleadoras formales (fuente: registros DGII + TSS, validados por
  ONE), con cruces por tamaño de empresa (micro ≤10 / pequeña 11-50 / mediana 51-150 / grande
  151+), sexo, salario promedio y masa salarial trimestral, geografía. Filtro de actividad
  económica solo llega a División CIIU (2 dígitos) — no aísla comida rápida de servicio de
  comidas y bebidas en general.
- **Cifra ancla verificada hoy:** división "Servicio de comidas y bebidas" = 7,182 empresas
  empleadoras, 80,385 empleados (2025). 78% de esas empresas tienen 1-10 empleados; solo 72
  (1%) tienen 151+ — el proxy más cercano a "operación tipo cadena grande" disponible hoy.
- **Evaluación preliminar:** coverage 0.6 (división, no subclase; cruces ricos que DGII no
  tiene) · cadence 0.85 (mensual confirmada, T1 2026 con datos de marzo) · format 0.3 (solo
  Power BI embebido — no se encontró descarga xlsx/csv durante la revisión) · license 0.7
  (público, sin términos de reventa revisados).
- **Recomendación:** `investigate` — el bloqueador real es formato (¿existe API o descarga
  detrás del embed?), no valor del dato.
- **Caveat obligatorio para el `note`:** la diferencia entre esta cifra y la de DGII (universo
  de contribuyentes, no solo empleadores) NO se etiqueta como "informalidad" — es cobertura de
  nómina formal (TSS) vs. registro fiscal (DGII); confirmado con datos de BCRD de que la
  informalidad laboral nacional sigue sobre 46% (mayo 2025), así que ninguna de las dos fuentes
  agota el universo real de negocios operando.

### 2.2 — ONE Dominicana en Cifras: Energía por tipo de usuario

- **target_axis:** `energy`.
- **Descripción:** Clientes, energía (GWh) y potencia (MW) por tipo de usuario (Comercial,
  Industrial, Residencial, Gobierno, Ayuntamiento), serie 2019-2024. Fuente: SIE + Organismo
  Coordinador (OC-SENI), elaborado por ONE.
- **Cifra ancla verificada hoy:** segmento Comercial 2024 — 279,236 clientes, 2,385.6 GWh,
  5,450.4 MW.
- **Evaluación preliminar:** coverage 0.5 (consumo/clientes por tipo de usuario — NO es tarifa
  DOP/kWh, que sigue siendo la brecha declarada original) · cadence 0.8 (anual, consistente con
  el resto de series de este portal) · format 0.6 (tabla dentro de Power BI, sin confirmar
  descarga estructurada) · license 0.7 (público).
- **Recomendación:** `investigate` — cierra una dimensión nueva (consumo por segmento) que el
  motor de energía actual no expone, pero no cierra el gap de tarifa que motivó la búsqueda.

### 2.3 — ONE Dominicana en Cifras: Construcción por tipología (incl. "Comercial y oficinas")

> **[Certain] RECLASIFICADA COMO REDUNDANTE en el cruce pre-carga del 2026-07-14 — NO se
> carga al tablero.** El conector `shared/data/mivhed_client.py` (fuente "Licencias emitidas
> por MIVHED, 2022-2026", datos.gob.do CKAN — CSV/XLSX estructurado, formato SUPERIOR al
> embed Power BI de ONE) ya ingiere el mismo dato de origen (MIVHED, Depto. Tramitación de
> Planos) **a nivel de licencia individual con columna Tipología incluida**, y su parser ya
> emite `by_typology` (mix de permisos por tipología) además de los totales
> permits/sqm/investment. Esa fuente figura en el tablero con estado **integrated**
> (dimensión PIPELINE del ICC, PR #384). El único residuo de esta entrada — desagregar m² y
> valor tasado POR tipología, no solo el conteo — es una **extensión menor del parser
> existente** (los campos ya vienen en el dataset crudo), es decir un ticket de build, no una
> fuente nueva. Cargarla como sugerencia repetiría el patrón del §1 ("no es una fuente — es
> un job/ticket pendiente"). La cifra ancla de ONE (Comercial y oficinas 2025: 149 licencias,
> 343,086 m², RD$5,127.7MM) queda como dato de QA para validar esa extensión.

> **[Certain] RESULTADO DE LA EXTENSIÓN + QA — implementado y verificado 2026-07-14.**
> `parse_licenses` ahora emite `by_typology_detail` (`{tipología: {permits, sqm, investment}}`)
> y el producto de construcción expone, en Insight/Deep Dive, una tabla **Licencias por
> tipología (m² licenciados)** con licencias, m² y participación en los m² del año. **La parte
> de m² por tipología quedó cerrada y es dato real y valioso** (p.ej. 2025: Apartamentos 567
> lic. / 2,888,911 m² / 64.6 %; Comercial y oficinas 95 lic. / 273,808 m² / 6.1 %).
>
> **La cifra ancla de la ONE NO reconcilió — y la premisa de "valor tasado por tipología" era
> incorrecta.** Dos hallazgos materiales del cruce contra el dataset crudo del MIVHED:
> 1. **La columna "Inversión Total" del MIVHED NO es valor tasado — es un costo estándar
>    derivado** = m² × una tarifa fija por año (94 % de las filas es exactamente m² × RD$61,600
>    y el resto m² × RD$57,200). Por eso su desglose por tipología es **redundante con los m²**
>    y da ≈RD$61,600/m² en casi todas las tipologías, ~4× el valor tasado de la ONE
>    (≈RD$14,946/m²). Son cantidades distintas: la ONE tasa; el MIVHED estandariza. El producto
>    **deliberadamente NO expone "inversión/valor tasado" por tipología** para no vender un
>    costo derivado como valuación (la señal monetaria agregada sigue viva en
>    `levels.investment_dop` con su caveat de nominalidad).
> 2. **La taxonomía tampoco calza:** el MIVHED trae para "Comercial y oficinas" 2025 **95
>    licencias / 273,808 m²**, no las 149 licencias / 343,086 m² de la ONE. La ONE además
>    distingue "licencias" (149) de "construcciones" (113), un conteo que el archivo
>    transaccional del MIVHED no reproduce fila a fila. La ONE agrega el uso comercial de otra
>    forma; no es el mismo bucket.
>
> **Conclusión:** el archivo del MIVHED (datos.gob.do) y el tablero de la ONE **no son la misma
> medición** — no basta con "los campos ya vienen en el crudo". El valor real capturado son los
> **m² licenciados por tipología** (cerrado). Si el dueño quiere el **valor tasado** real por
> tipología (RD$/m² de tasación) o el conteo de "construcciones" de la ONE, eso **sí** requiere
> la fuente de la ONE (no es una extensión del parser del MIVHED) — decisión abierta para el
> dueño, ya no un ticket de build sobre `mivhed_client.py`.

> **[Certain] EVALUACIÓN DE LA FUENTE ONE — verificada con descarga real 2026-07-14. La
> premisa "solo Power BI (format 0.6)" era FALSA: la ONE publica el dato como Excel
> estructurado descargable.** En
> `one.gob.do/.../estadisticas-sectoriales/construccion-y-actividades-inmobiliarias/` hay
> **cuatro .xlsx por tipo de construcción, mensuales, 2013-2025** (actualizados 2026-02-24):
> 4.7 Licencias otorgadas · 4.8 Construcciones · 4.9 Área construida (m²) · **4.10 Valor
> tasado (RD$)**. URLs directas `www.one.gob.do/media/<hash>/…xlsx` (el `<hash>` es opaco y
> puede cambiar al republicar → resolver por título desde la página, patrón CDN-rename del
> BCRD [[bcrd-publications-connector]], no hardcodear).
>
> **Reconciliación EXACTA (descargué y parseé 4.10):** hoja por año; "Comerciales y Oficinas"
> 2025 = **RD$5,127,690,356** (idéntico a la cifra ancla), Total 2024 =
> **RD$81,496,658,121** (= los RD$81,496.7MM que reporta la ONE). Confirma que el valor
> tasado de la ONE (≈RD$15,214/m² en 2024) es real, distinto y ~4× menor que el costo
> derivado del MIVHED (RD$61,600/m²). Taxonomía jerárquica y más fina que el MIVHED (grupos
> "Edificios de Apartamentos" → sub-líneas; buckets como "Comerciales y Oficinas", "Combinados
> / Comercio y Vivienda", etc.).
>
> **Complejidades reales del conector** (no bloqueantes, molde = ETL Excel BCRD
> [[bcrd-excel-historico-etl]]): (a) la orientación de las hojas CAMBIA entre años (2013:
> filas=mes, columnas=tipo; 2024+: filas=tipo, columnas=mes) → el parser detecta la
> orientación; (b) filas de grupo vs sub-línea → tomar solo los totales de grupo para no
> doblar; (c) **falta el año 2015** (hueco honesto, no fabricar); (d) mapear la tipología
> ONE↔MIVHED para poder cruzar. **Recomendación revisada: `approve`** — fuente estructurada,
> autoritativa y ya reconciliada; el esfuerzo es un conector Excel de dificultad media, no una
> extracción Power BI frágil.

- **target_axis:** `construction`.
- **Descripción:** Licencias, construcciones, m² y valor tasado por tipología de construcción
  (Comercial y oficinas, Edificios de apartamentos, Combinados, Centros de salud, etc.), serie
  anual 2020-2025. Fuente: MIVIED (Departamento Tramitación de Planos), elaborado por ONE.
- **Cifra ancla verificada hoy:** tipología "Comercial y oficinas" 2025 — 149 licencias, 113
  construcciones, 343,086 m², valor tasado RD$5,127,690,356 (≈RD$14,946/m²).
- **Evaluación preliminar:** coverage 0.65 (desagrega por tipología de uso, algo que el
  agregado actual del motor de construcción — Permits/Sqm/Investment DOP total — no tiene; sigue
  siendo valor de construcción nueva, no precio de arrendamiento de espacio existente, que es el
  gap literal declarado) · cadence 0.75 (anual) · format 0.6 (tabla en Power BI) · license 0.7.
- **Recomendación:** `investigate` → probable `approve` si se confirma acceso a datos crudos —
  es la fuente más fuerte encontrada hoy para "costo de construcción comercial", aunque sigue
  sin ser "precio de alquiler".

### 2.4 — ONE: Índice de Costos Directos de Construcción de Vivienda (ICDV)

- **target_axis:** `construction`.
- **Descripción:** Costo de construcción por m² para 4 tipologías de vivienda, base oct-2009,
  boletín mensual (PDF de una página), serie continua desde ~2012 ("Año 15" en 2026).
- **Cadencia confirmada hoy:** mayo 2026 publicado 23-jun-2026 (rezago ~6-7 semanas). Cobertura
  geográfica limitada a Distrito Nacional + Santo Domingo.
- **Evaluación preliminar:** coverage 0.4 (solo vivienda, no espacio comercial; cobertura
  geográfica limitada) · cadence 0.9 (mensual, ininterrumpida, rezago corto y predecible) ·
  format 0.5 (PDF de una página — Ricardo señaló que esto no es un obstáculo dado el pipeline
  actual de ingestión de fuentes PDF) · license 0.7.
- **Recomendación:** `investigate` — cadencia y trazabilidad fuertes; valor limitado porque mide
  vivienda, no espacio comercial (el gap declarado). Útil como proxy de presión de costos del
  sector, no como respuesta directa a la pregunta del comprador.

### 2.5 — Proindustria: Registro Industrial (xlsx trimestral)

- **target_axis:** ninguno de los 14 calza limpio (más cercano: `agribusiness`, pero ese eje es
  producción agrícola, no manufactura de alimentos) — candidato a `kind="info_type"` sin eje, o
  a diferirse hasta que exista un caso de uso de cadena de suministro.
- **Descripción:** Empresas registradas/calificadas por Proindustria bajo la Ley 392-07.
  Confirmado con archivo real (449 registros, Q1 2026): 0 coincidencias de
  restaurante/comida rápida/cadena; 61.5% (276/449) son elaboración/procesamiento de alimentos
  (insumos, no food service). Sin columna CIIU — actividad en texto libre, 206 valores únicos.
  Calidad de dato: 35/449 (7.8%) códigos RI sin formato estándar; campo "Provincia" con 95
  valores únicos (RD tiene 32 provincias formales — mezcla provincia/municipio sin normalizar).
- **Evaluación preliminar:** coverage 0.25 para el caso de uso QSR/restaurantes (no aplica) ·
  cadence 0.6 (trimestral, sin confirmar si el criterio de inclusión es "activo a la fecha" o
  "evento registral del trimestre" — **[Guessing]**, no confirmado) · format 0.8 (xlsx real,
  ya en mano) · license 0.7.
- **Recomendación:** `defer` para el caso de uso actual (QSR/restaurantes). Reabrir solo si
  surge un mandato de cadena de suministro de insumos alimenticios o manufactura.

### 2.6 — DGA: aranceles de insumos alimenticios congelados (kind="info_type", fuente aún sin URL confirmada)

- **target_axis:** `trade`.
- **Descripción:** Tasas arancelarias por partida arancelaria para proteínas/aceites/papas
  procesadas congeladas, y beneficios aplicables bajo DR-CAFTA. Sigue siendo la brecha declarada
  original del informe QSR — no se identificó la fuente concreta durante esta sesión.
- **Evaluación preliminar:** sin evaluar (no hay fuente candidata todavía, solo la necesidad).
- **Recomendación:** `investigate` — el siguiente paso es identificar si el Arancel de Aduanas
  dominicano tiene versión consultable/descargable por partida en el portal de DGA.

### 2.7 — SIE: pliego tarifario eléctrico comercial/industrial (DOP/kWh) — CORREGIDO tras cruce con `docs/sectorial-gate-e-fuentes-hallazgos.md`

> **[Certain] Esta entrada estaba mal calificada en la v0.1 de este documento** ("fuente aún sin
> URL confirmada"). Al colocar el archivo en `docs/` encontré que ya existe una investigación
> previa del propio repo (`sectorial-gate-e-fuentes-hallazgos.md`, 2026-06-19, §2.4) que YA
> localizó esta fuente: categorías tarifarias **MTD-2 = "Zonas Francas e Industrial"** vs.
> **MTD-1 (comercio)** vs. BTD/BTS (residencial), publicadas por la SIE. No es un gap de
> descubrimiento — es un gap de extracción: el archivo de origen es un **PDF escaneado de la
> resolución tarifaria vigente**, que requiere OCR.
- **target_axis:** `energy`.
- **Descripción:** Tarifa en DOP/kWh por categoría de usuario (comercial, industrial). No es lo
  mismo que el consumo/clientes de §2.2 — es el precio, no el volumen.
- **Evaluación preliminar (revisada):** coverage 0.85 (categoría tarifaria específica para
  comercial e industrial, ya identificada) · cadence 0.5 (depende de cuándo la SIE emite
  resolución nueva, no es un boletín periódico fijo) · format 0.3 (PDF escaneado — el
  bloqueador real es OCR, no localización) · license 0.7.
- **Recomendación:** `investigate` con alcance acotado — no es "encontrar la fuente" (ya está
  encontrada), es "construir el OCR de la resolución vigente". Mucho más barato que lo que yo
  había estimado en la v0.1 de este documento.
- **Detalle adicional recuperado en el cruce pre-carga del 2026-07-14** (estaba en
  `sectorial-gate-e-fuentes-hallazgos.md` §2.4 y la corrección anterior no lo arrastró): la
  tarifa SIE diferencia **4 sectores de uso** (zonas francas / manufactura / comercio /
  turismo), no solo "comercial e industrial"; URL de la fuente: `https://sie.gob.do/`
  (bibliografía del doc, línea 158); el hallazgo original la ubicaba como insumo de
  `operating_cost` para el Gate E sectorial. Verificado en código: NO existe ningún conector
  de tarifa eléctrica en `shared/data/` (solo capacidad, generación y reclamaciones). Nota de
  tablero: existe una sugerencia diferida "Boletín Estadístico Mensual SIE – Generación,
  Transmisión y Tarifas 2024-2026" (`energy/g1`, auto-diferida por cobertura del eje) — es un
  artefacto distinto (boletín estadístico vs. resolución/pliego tarifario), no un duplicado.

### 2.8 — TSS: salario e informalidad por actividad económica — REEMPLAZA la entrada original (BCRD Boletín Trimestral)

> **[Certain] Corrección material a la v0.1.** La entrada original de este ítem citaba el
> Boletín Trimestral del Mercado Laboral de BCRD (informalidad nacional, 53.4% en mayo 2025) como
> la mejor fuente disponible para el Canal 2 (presión salarial) del motor macro. Es una fuente
> real y sigue citada abajo, pero `sectorial-gate-e-fuentes-hallazgos.md` (§2.4, investigación del
> 2026-06-19, previa a esta sesión) ya encontró algo mejor: la **TSS (Tesorería de la Seguridad
> Social)** publica salario promedio cotizable **por actividad económica**, con valores 2025 YA
> VERIFICADOS: minería RD$74,788 · financiero 61,414 · energía 51,034 · comunicaciones 47,781 ·
> enseñanza 42,365 · admin. pública 41,774 · construcción 39,368 · salud 38,863 · transporte
> 38,819. El mismo corte trae además **tasas de informalidad POR SECTOR** (no solo nacional):
> agropecuario 80-85% · construcción 70-75% · comercio 55-60% · industria 30-35% · financiero
> ~20%. Sector-específico supera a nacional-agregado para el caso de uso de este motor.
>
> **Bonus no capturado en el hallazgo original:** el mismo documento identifica el **salario
> mínimo legal diferenciado por sector** (Comité Nacional de Salarios), y trae una cifra
> específica para **restaurantes: RD$21,000** — junto con hoteles/casinos RD$21,840 y zonas
> francas RD$20,875. Esta es la cifra de costo laboral más directamente aplicable a la pregunta
> QSR original de todo lo revisado hoy, y no la encontré yo — ya estaba en el repo.
- **target_axis:** `macro` (o transversal vía `shared/knowledge`).
- **Fuentes:** TSS salario por actividad (extracción: boletines trimestrales PDF, sin CSV
  sectorial abierto confirmado — `datos.gob.do/es/dataset/trabajadores-activos-en-tss` solo trae
  el total, no el desglose) · Comité Nacional de Salarios / Min. Trabajo (salario mínimo
  sectorial, resoluciones en `transparencia.mt.gob.do`) · BCRD Boletín Trimestral (informalidad
  nacional, como contexto agregado — sigue siendo válido, solo ya no es la primera opción).
- **Evaluación preliminar:** coverage 0.85 (por sector, no nacional-agregado; incluye el mínimo
  legal específico de restaurantes) · cadence 0.8 (trimestral) · format 0.4 (boletín TSS en PDF,
  sin CSV sectorial — mismo patrón de esfuerzo que §2.7) · license 0.75.
- ~~**Recomendación:** `approve` — mejor que mi propuesta original (BCRD nacional), y la
  investigación de descubrimiento ya está hecha por el propio equipo hace tres semanas. El
  esfuerzo que queda es extracción (parsear boletines TSS PDF), no búsqueda.~~

> **[Certain] SEGUNDA CORRECCIÓN MATERIAL — cruce pre-carga del 2026-07-14.** La premisa de
> esfuerzo de esta entrada estaba equivocada: el **salario promedio TSS por actividad
> económica YA ESTÁ CONSTRUIDO Y EN PROD** — `shared/data/tss_salary.py` (`TSSSalaryClient`)
> extrae salario promedio cotizable por 18 actividades (campo `ACT_ECO2_BC` del reporte
> Power BI "Cotizaciones" de TSS, vía querydata — sin OCR de PDF), y
> `modules/sector_intel/sectors_sync.py` (`tss_salario_sync`) lo mapea a los 17 slugs BCRD y
> lo persiste como `sector_operating_cost` (Gate E sectorial, PRs #207-#212). No hay nada que
> "parsear de boletines TSS PDF": esa parte NO es una sugerencia de fuente, ya es un conector
> en producción. La entrada se **acota a los dos componentes genuinamente faltantes**:
> 1. **Salario mínimo legal sectorial** (Comité Nacional de Salarios / Min. Trabajo) — sin
>    conector. Incluye el dato QSR clave (restaurantes RD$21,000) y los sectores que la
>    corrección anterior omitió del hallazgo original: **vigilancia RD$24,633** (el mínimo
>    sectorial más alto), **campo RD$714.60/jornada**, construcción (escala a destajo).
>    URL exacta: `transparencia.mt.gob.do/index.php/base-legal/category/2025`.
> 2. **Informalidad POR SECTOR** — hoy solo existe la tasa nacional (`shared/data/one_client.py`,
>    `informality_rate`); las cifras sectoriales del hallazgo (agropecuario 80-85% …
>    financiero ~20%) no tienen fuente estructurada identificada todavía.
> Caveats del hallazgo original que la corrección anterior tampoco arrastró: el empleo TSS se
> revisa al alza por morosidad de empleadores (rezagar ≥1 trimestre) y el quiebre
> metodológico laboral es **Q3-2014 (ENFT→ENCFT)** — ojo: `SERIES_CANONICAS_BCRD.md:71` dice
> "2021", discrepancia interna del repo sin resolver. **Recomendación revisada:**
> `investigate` (el `approve` original descansaba en un esfuerzo de extracción que ya no
> existe; lo que queda es un conector nuevo chico + identificar la fuente de informalidad
> sectorial).

---

## 3. Fuera de alcance / redundante — no cargar al tablero sin verificar primero

| Fuente | Razón |
|---|---|
| MIVHED — boletín trimestral de licencias de construcción (residencial) | **[Likely]** ya es la fuente detrás de "MIVHED · BCRD" que el motor de construcción ya cita (Permits 951, Sqm 4,473,895 en los informes revisados). Confirmar contra el conector existente antes de proponerla como nueva — si coincide, no hay nada que agregar. |
| DGII Fuente A y Fuente B (ITBIS) | Ya especificadas en `SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md` §B.1-B.2. No duplicar aquí — Fuente A recomendada "aprobar", Fuente B "investigar, no aprobar todavía" (granularidad de subclase sin confirmar; los zips no se pudieron leer por bloqueo de permisos de fetch de binarios en esta sesión). |

---

## 4. Próximos pasos

1. **Antes que nada:** verificar `bcrd-sectores-sync` (§1). Es gratis comparado con cualquier
   otra línea de este documento y probablemente cierra el hallazgo más viejo de todo este ciclo
   de trabajo (Pregunta 1 del piloto original).
2. Dar de alta en el tablero de Inteligencia de Fuentes (`create_suggestion`, `origin="manual"`)
   las sugerencias de §2 **que sobrevivieron el cruce pre-carga del 2026-07-14**: 2.1
   (corregida/acotada), 2.2, 2.4, 2.5, 2.6, 2.7 (enriquecida) y 2.8 (corregida/acotada).
   **2.3 NO se carga** — reclasificada redundante (ver su bloque de corrección: es una
   extensión del parser `mivhed_client.py`, no una fuente nueva).
3. Correr `evaluate()` sobre cada una para obtener el veredicto real del sistema (IA o
   heurística) — mis puntuaciones de arriba son un punto de partida humano, no la sustituyen.
4. Para las que salgan `approved`, correr `scaffold()` para el plan de integración antes de
   escribir ningún conector.
5. Verificar §3 contra el código real de conectores (`shared/data/`) antes de decidir si se
   proponen o se descartan por redundancia — esta sesión no tuvo acceso a ese directorio del
   repo para confirmarlo directamente.

## Riesgos / decisiones abiertas

- **[Guessing]** No se confirmó si DyDEF (§2.1) o los tableros de Dominicana en Cifras (§2.2,
  §2.3) tienen una vía de descarga estructurada fuera del embed de Power BI. Si no la tienen, el
  conector requeriría automatización de navegador o la API de Power BI — un patrón de ingesta
  más frágil que la descarga de archivo publicado que ya usan las fuentes DGII.
- **[Guessing]** El criterio de inclusión del archivo de Proindustria (activos a la fecha vs.
  eventos del trimestre) no se confirmó — afecta si 2.5 es una serie de stock o de flujo.
- **[Certain, pero sin verificar en este repo]** Este documento asume que `coverage_status()` en
  `shared/source_intel/coverage.py` existe y funciona como lo describe `service.py` — ese
  archivo no estaba disponible en la copia del repo usada durante esta sesión.
