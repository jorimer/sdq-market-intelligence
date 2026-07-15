# SPEC — Cobertura, ruteo y comparación regional del Motor de Research

**Estado: SPEC para revisión del dueño. NO se ha escrito código. Cada propuesta (SPEC-n) es una
unidad de trabajo que pasa por el gate humano antes de integrarse.**

Consolida el trabajo que arrancó con H10 + evaluación de fuentes de minería, más tres hallazgos que
el dueño pidió incorporar: (1) comparación regional CA/Caribe, (2) barrido sistemático de scoping,
(3) enmascaramiento de `economic_structure`. Evidencia recogida contra prod el 2026-07-15.

---

## 1. El mapa real de cobertura (barrido sistemático contra prod)

Corrí las **17 hojas** de `bcrd_sectors` (la partición completa del Valor Agregado) contra
`POST /api/v1/research` con pregunta simétrica *"¿Qué situación tiene el sector {X} en RD?"*.
Resultado real:

| Resultado | Sectores | Interpretación |
|---|---|---|
| ✅ **report, cov 1.0** (eje dedicado) | manufactura local, zonas francas, construcción, energía, turismo, comunicaciones (6) | Eje productizado + keywords → funciona |
| ❌ **scoping, cov 0.0** | agropecuario, minería, **financiero**, comercio, transporte, inmobiliario, enseñanza, salud, adm. pública, servicios profesionales, otros servicios (11) | El comprador recibe respuesta vacía |

**11 de 17 sectores devuelven cobertura 0.** No todos son bugs — hay que clasificar:

| Clase | Sectores | ¿Bug? |
|---|---|---|
| **A. Producto existe, ruteo roto** | agropecuario (eje `agribusiness`), financiero (eje `banking`) | **Sí — bug.** El motor tiene el eje pero el router no lo alcanza |
| **B/C. Dato del BCRD existe, sin eje** | minería, comercio doméstico, transporte, inmobiliario, enseñanza, salud, adm. pública, servicios profesionales, otros servicios (9) | **Cobertura 0 es DESHONESTA.** `bcrd_sectors` ya tiene tamaño+crecimiento de las 17 hojas; devolver vacío niega dato confiable que sí poseemos. Ver decisión del dueño abajo |

> **Reencuadre (decisión del dueño 2026-07-15):** la clasificación original separaba "dato sin eje"
> (B) de "sin producto ni intención" (C). Es un error: **las 17 hojas de `bcrd_sectors` tienen dato
> real del BCRD** (aporte al VAB + crecimiento). "No hay producto profundo" ≠ "no podemos comentar".
> Si tenemos fuente confiable, el motor debe dar al menos la ficha base del sector — no scoping. Por
> eso B y C se fusionan y se resuelven con UN solo eje base (SPEC-4), no con propuestas por-sector.

---

## 2. Hallazgos clasificados

### 2.1 Clase A — bugs de ruteo (producto existe, no se alcanza)

- **`agribusiness`** — único eje de los 14 con `CatalogEntry` + summarizer pero **sin keywords** en
  `AXIS_KEYWORDS`. Verificado con control simétrico: "sector agropecuario" → scoping/cov 0; "sector
  turismo" (idéntico) → report/cov 1.0. Es el modo de falla documentado para `insurance`
  (`resolve.py:45-47`).
- **`banking` a nivel sector** — las keywords de banking son de ENTIDAD (`banco`, `banca`, `mora`,
  `cartera`, `solvencia`). Una pregunta de SECTOR ("¿cómo está el sector financiero?") no matchea →
  scoping. El eje existe (banking_score, SIB) pero el vocabulario de sector no lo activa.

### 2.2 Clase B/C — 9 sectores con dato del BCRD pero sin eje (cobertura 0 deshonesta)

Las 17 hojas de `bcrd_sectors` tienen aporte al VAB + crecimiento real. De las que hoy caen a
scoping, 9 tienen ese dato y aun así devuelven vacío:

- **minería** — leaf `mineria` (trimestral, Q1-2026). Detalle en
  [`docs/EVALUACION_FUENTES_MINERIA.md`](EVALUACION_FUENTES_MINERIA.md).
- **comercio doméstico** — leaf `comercio`; el eje `trade` es comercio EXTERIOR (DGA), no cubre el
  interno.
- **transporte, inmobiliario, enseñanza, salud, adm. pública, servicios profesionales, otros
  servicios** — todas son hojas con tamaño+crecimiento reales del BCRD. Falta el eje, no el dato.

Todas se resuelven de una vez con el eje base de SPEC-4. Donde además haya fuentes confiables
adicionales (p.ej. salud→SISALRIL, enseñanza→MINERD/MESCyT), se pueden enriquecer después como
roadmap por-sector — pero el piso base sale ya del BCRD.

### 2.3 Enmascaramiento de `economic_structure` (falso positivo de cobertura)

`economic_structure` se activa con lenguaje de crecimiento (`motor del crecimiento`, `qué sectores
impulsan`, …). Verificado: "¿cómo está el agropecuario **y qué papel juega en el crecimiento**?" →
**report, cov 1.0** vía `economic_structure` (fuente "PIB por sectores de origen"), NO vía el eje
agribusiness. El `_structure_summary` solo expone principal motor / principal lastre / HHI — NO la
ficha del sector.

**Riesgo:** un sector de Clase A/B, si la pregunta trae marco de crecimiento, produce un informe que
*parece* completo pero corrió el motor equivocado. La cobertura 1.0 es real para "estructura", pero
engañosa como "cobertura del sector X". Esto puede ocultar los bugs de §2.1 en pruebas informales.

### 2.4 La brecha original NO era minería — era comparación regional

El gap de la pregunta que arrancó todo ("turismo/minería/construcción … **y cómo se compara con el
promedio de Centroamérica y el Caribe**") es una **capacidad que el motor no tiene**: ningún eje hace
benchmark regional. El sub-tema minería fue un desvío; la brecha citada por el comprador es el
referente CA/Caribe. Ver SPEC-6.

---

## 3. Propuestas (specs)

### SPEC-1 · `agribusiness` keywords — BUG P0
- **Cambio:** añadir `"agribusiness": ("agropecuario","agroindustria","agricola","agro","iai",...)`
  a `AXIS_KEYWORDS` (`shared/research/resolve.py`).
- **Esfuerzo:** trivial (1 línea) · **Riesgo:** mínimo.
- **Verificación:** test de no-regresión (pregunta agro → gate report) + correr en prod las 2
  preguntas del control.
- **Por qué P0:** producto vendible que hoy responde vacío a un comprador.

### SPEC-2 · Vocabulario de sector para `banking` — DECIDIDO
- **Cambio:** añadir a las keywords de `banking` términos de SECTOR (`sector financiero`,
  `financiero`, `intermediación financiera`) — cuidando no chocar con la resolución de entidad.
- **Decisión del dueño (2026-07-15): VAB agregado del sector financiero + PUENTE a banca.** Una
  pregunta de "sector financiero" da la ficha agregada (VAB financiero de `bcrd_sectors`, vía el eje
  base de SPEC-4) y tiende un puente al panorama de banca (banking_score) para quien quiera bajar al
  nivel de entidad. No es "o uno u otro": es agregado con enlace al detalle.
- **Esfuerzo:** bajo · **Riesgo:** medio (interacción con resolución de entidades bancarias).

### SPEC-3 · Guard anti-enmascaramiento de `economic_structure`
- **Cambio:** cuando `economic_structure` es el ÚNICO eje convocado pero la pregunta nombra un sector
  específico, elevar el eje del sector (que tras SPEC-4 SIEMPRE existe para las 17 hojas) en vez de
  quedarse en la vista estructural. Marca la diferencia entre "ficha del sector" y "vista estructural".
- **Esfuerzo:** medio · **Riesgo:** bajo · **Depende de:** SPEC-4 (una vez que las 17 hojas tienen eje
  base, la ambigüedad se resuelve casi sola).

### SPEC-4 · Eje base de sector desde `bcrd_sectors` — cubre las 17 hojas (reemplaza a SPEC-4/5 previos)
- **Reencuadre por decisión del dueño:** en vez de un eje por-sector (minería, comercio…), un **eje
  base genérico** que responda CUALQUIERA de las 17 hojas con el piso de inteligencia que el BCRD ya
  provee: aporte al VAB (tamaño), crecimiento real interanual, incidencia, ranking entre sectores y
  trayectoria. Fuente: `bcrd_sectors` (cuentas nacionales del BCRD). **Ningún sector con dato del BCRD
  vuelve a devolver cobertura 0.**
- **Cierra de una sola vez:** minería, comercio doméstico, transporte, inmobiliario, enseñanza, salud,
  adm. pública, servicios profesionales, otros servicios (9 sectores) — y da a la minería justo el
  "aporte al crecimiento" que el informe original decía no poder computar.
- **Escalera de valor honesta:** el eje base es nivel "Pulse" (aporte + crecimiento, sourced BCRD). Los
  sectores productizados (turismo, energía, construcción, zonas francas…) siguen enriqueciendo encima
  con sus fuentes dedicadas (MITUR, SIE, CNZFE…). La narrativa declara cuándo es solo base BCRD vs
  cuándo hay producto profundo — sin fingir profundidad que no existe.
- **Ruteo:** keywords para las 17 etiquetas → si el sector está productizado, al eje dedicado; si no,
  al eje base. (Absorbe también SPEC-1: agropecuario deja de caer a cero incluso antes de su producto.)
- **Roadmap de enriquecimiento (aparte):** donde haya fuentes confiables adicionales por sector
  (salud→SISALRIL, enseñanza→MINERD/MESCyT, etc.), se suben como propuestas independientes por tu gate.
- **Esfuerzo:** medio · **Riesgo:** bajo (sin fuente externa nueva, sin migración; el dato ya existe).

### SPEC-6 · Capacidad de comparación regional (CA/Caribe) — la brecha original
- **Qué:** un eje/servicio que, dado un sector o el agregado, compare RD contra un panel de
  Centroamérica + Caribe.
- **Fuente:** World Bank **WDI** (ya usada en la plataforma: aparece como "WGI/WDI"). Trae valor
  agregado por gran-sector (% del PIB): agricultura `NV.AGR.TOTL.ZS`, industria `NV.IND.TOTL.ZS`,
  servicios `NV.SRV.TOTL.ZS`, manufactura `NV.MNF...`, y crecimiento del PIB `NY.GDP.MKTP.KD.ZG` por
  país. El IRMP ya construye paneles de 24 países — reusar esa infraestructura.
- **⚠️ Constraint de honestidad (crítico):** WDI da granularidad GRUESA (agri/industria/servicios),
  **NO las 17 hojas del BCRD**. Minería, turismo y construcción NO están desagregados cross-country
  para la mayoría de pares. Es decir: **el benchmark regional es viable a nivel de gran-composición +
  crecimiento total, pero NO sector-por-sector fino.** El spec debe entregar la comparación gruesa y
  DECLARAR el límite (no fabricar un "minería RD vs minería CA" que la fuente no soporta). Esto es
  precisamente lo que el gate de honestidad exige.
- **Esfuerzo:** medio-alto · **Riesgo:** medio (definir el alcance honesto es la parte difícil, no el
  código).

### SPEC-7 · Guard de CI de completitud de ejes
- **Cambio:** test que falla si un eje tiene `CatalogEntry` + summarizer pero le falta `AXIS_KEYWORDS`
  (habría atrapado SPEC-1 antes de prod). Patrón "no silent gaps".
- **Esfuerzo:** bajo · **Riesgo:** nulo.

### Decisión de roadmap · Clase C — RESUELTA
Los 7 sectores de servicios (transporte, inmobiliario, enseñanza, salud, adm. pública, servicios
profesionales, otros servicios) **ya no caen a scoping**: el eje base de SPEC-4 les da la ficha del
BCRD. Enriquecerlos con fuentes propias es roadmap por-sector, no bloqueante. La regla del dueño:
"sin producto profundo ≠ no podemos comentar; si hay fuente confiable, comentamos con lo que hay".

---

## 4. Secuencia recomendada

1. **SPEC-1** (agribusiness keywords) + **SPEC-7** (guard CI) — bug/higiene, riesgo nulo. Quick win.
2. **SPEC-4** (eje base de sector, 17 hojas) — el de mayor leverage: cierra minería + comercio + los
   7 de servicios + subsuma agropecuario/financiero a nivel sector, todo con dato del BCRD que ya
   existe. Es el corazón del plan tras tus dos decisiones.
3. **SPEC-2** (puente financiero→banca) + **SPEC-3** (anti-enmascaramiento) — encima de SPEC-4, ya con
   tu criterio decidido.
4. **SPEC-6** (comparación regional CA/Caribe) — la brecha original; el trabajo real es definir el
   alcance honesto (gruesa sí, sector-fino no), no el código.

Nada se implementa sin tu OK. Todo entra por propuesta → evaluación → tu gate → integración.
