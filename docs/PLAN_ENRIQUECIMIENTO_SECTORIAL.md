# Plan — enriquecer los otros ejes con la granularidad nueva

> Escrito el **2026-08-31**. Estado de las fases al final; se actualiza al cerrar cada una.
>
> **Las cifras de este documento están FECHADAS y envejecen.** Cada tabla dice contra qué
> corte se midió y con qué llamada se vuelve a medir. No cites de acá: volvé a preguntar.
> (Un `.docx` viejo propagando estado viejo ya nos pasó.)

## Por qué existe

En agosto de 2026 entró granularidad nueva y grande: el cubo de crédito de la SIB (sector ×
provincia × entidad), la ENCFT completa (SU1–SU4, precisión estadística, dominios
regionales), el IPC por quintil, el salario mínimo y el costo de la canasta. Casi todo eso
llegó **solo a banca**. Este plan lo reparte, en orden y midiendo.

## Punto de partida (medido el 2026-08-31)

### Alcance de lo nuevo

| | capacidad de pago | holgura regional | mapa sectorial |
|---|---|---|---|
| `banking` · `banking_year_review` | sí | sí | sí |
| `insurance` · `pension` · `monetary_policy` | sí | — | — |
| los otros 11 productos | — | — | — |

Re-medir: buscar `capacidad_de_pago`, `holgura_donde_presta` y `mapa_sectorial` en
`modules/*/products*.py` y `app/products_*.py`.

### La columna vertebral que ya existía

`shared/data/sector_crosswalk.py` es *single source of truth* y puentea sobre los **17
sectores BCRD** (`shared.data.bcrd_sectors.sector_catalog`):

| fuente | granularidad | mapeada |
|---|---|---|
| ENCFT — ocupación por actividad | 10 ramas | sí |
| TSS — salario promedio cotizable | 18 actividades | sí |
| ENAE — actividad económica | por actividad | sí |
| IED — inversión extranjera | por sector | sí |
| **SIB — cubo de crédito** | **19 letras CIIU** | **NO** |

Esa última fila es el trabajo.

### Granularidad persistida y sin consumir fuera de banca

- `shared/data/bcrd_labor.py::parse_regiones` — 7 indicadores × 5 dominios × 11 años.
- `shared/data/bcrd_labor.py::PRECISION_POR_ETIQUETA` — IC y CV de 10 indicadores.
- `shared/data/tss_salary.py` — 18 actividades; solo lo usa `sector_intel` como insumo del
  `operating_cost` del IAI.

### El cubo

19 sectores × 33 provincias × 41 entidades, trimestral, con dato de 2024-03 a 2026-03
(2026-06 en adelante vacío: la SIB no publicó el cubo del Q2). Catorce campos por fila de
sector, doce por provincia.

Re-medir: `GET /api/v1/banking-score/data/mapa-sectorial?corte=YYYY-MM-DD`.

## El hecho que condiciona todo

`Y CONSUMO` y `Z VIVIENDA` **no son sectores económicos**: son destinos de crédito a hogares.
Al corte 2025-12-31 pesaban 26,72% y 18,75% — juntos, el **45,5% de la cartera del país**.
Una lectura «crédito por sector» cubre el ~54% restante.

Por la decisión del 2026-08-31 eso **no se anuncia en el texto**, pero gobierna qué se puede
afirmar: nunca «el sector X concentra el N% del crédito» sin que N esté definido sobre una
base nombrada. Ver la regla del sujeto en `CLAUDE.md`.

## Fases

### Fase 0 — La capa macro sigue al corte del documento · CERRADA (#1033)

`app/products_monetary_policy.py` computaba un `as_of` para una decisión histórica y después
llama `capacidad_de_pago(db, date.today())`, ignorándolo. `modules/pension_intel/products.py`
hacía lo mismo y su producto también lleva período. `insurance_intel` lo hacía bien.

Cerrado subiendo el helper a `shared.capacidad_de_pago.corte_del_periodo` —seguros tenía el
único cuerpo correcto y ya iba camino a la tercera copia; un módulo no puede importar de
otro, así que la única forma de no duplicarlo era que viviera junto a la lectura—. Lo vigila
`shared/tests/test_la_capa_macro_sigue_al_corte.py`, que lee la LLAMADA con `ast` en las tres
superficies.

Es la familia del #992 —la frescura envejeciendo sola dentro de un documento fechado— en dos
productos ya publicados. Va primero para no propagar el patrón al repartirlo a once ejes más.

### Fase 1 — `CarteraSectorial` a `shared/reference/`

8 archivos, todos dentro de `banking_score`. La tabla se llama `cartera_sectorial` antes y
después: **sin migración**. `shared/reference/` ya guarda datasets nacionales (registro DGII,
provincias), que es exactamente lo que el cubo es.

**Trampa a verificar explícitamente:** hoy la tabla se registra en Alembic de forma
transitiva —vive en el mismo archivo que `Bank` y `BankingData`, y el import de `env.py`
ejecuta el módulo entero—. Al mudarla necesita su propia línea en `env.py`, o `autogenerate`
propondría **borrar la tabla**. Comprobación de salida: `autogenerate` en limpio no propone
nada.

Por qué mover y no leer desde `shared/`: los imports de `shared/` hacia `modules/` existen
hoy en 3 archivos de todo el repo. Es una excepción, no un patrón, y hacerlo patrón costaría
reescribir el mismo archivo cuando la tabla se mueva igual.

### Fase 2 — La letra CIIU en el crosswalk

Construida **contra el catálogo de la SIB**, no deducida de las etiquetas: «el catálogo de la
SIB define los campos, el portal no» costó tres backfills. `Y`/`Z` y los slugs sin letra se
marcan como no mapeables con su motivo, hacia adentro.

Lectura **preliminar, a verificar en esta fase** (pesos al corte 2025-12-31):

| slug BCRD | letra SIB | peso |
|---|---|---|
| `construccion` | F | 6,86% |
| `manufactura_local` + `zonas_francas` | D (agregado: la SIB no separa ZF) | 6,91% |
| `energia` | E | 5,07% |
| `turismo` | H | 4,94% |
| `comercio` | G | 12,20% |
| `transporte` | I | 2,39% |
| `inmobiliario` | K | 6,50% |
| `financiero` | J | 2,34% |
| `agropecuario` | A + B | 1,50% |
| `mineria` | C | 0,96% |
| `administracion_publica` | L | 0,64% |
| `ensenanza` | M | 0,32% |
| `comunicaciones` · `servicios_profesionales` | sin letra | — |

### Fase 3 — `shared/perfil_del_sector.py`

Las cuatro lecturas por slug: crédito (SIB), ocupación y subutilización (ENCFT), salario
(TSS), y donde haya provincia, la holgura del territorio donde opera. La cobertura viaja como
dato interno que acota qué se afirma, no como texto.

### Fase 4 — Un solo eje, y medir

`construction_intel`: hoy mide permisos, m², HHI por tipología y HHI por provincia, y **no
tiene ninguna dimensión de financiamiento**. Además tiene provincia, así que le aplica la
holgura laboral.

Antes de seguir se mide: ¿mejoró el texto?, ¿cuántas marcas nuevas del guard?, ¿cuánto subió
el tiempo de ensamblado? (`GET /api/v1/operations/tiempos-de-narrativa` y
`GET /api/v1/operations/marcas-del-guard`).

### Fase 5 — El resto

`free_zones`, `energy`, `tourism`, y `sector_intel` con los 19 como insumo del IAI/SGPS.

### Fase 6 — `capacidad_de_pago` y holgura donde signifiquen algo

Construcción (demanda de vivienda), telecom (asequibilidad), tourism (demanda interna),
free_zones (salario vs. mínimo), social_dev. **No** en `law`, `esg`, `trade` ni `macro`: ahí
sería relleno.

## Riesgos

1. **La caché de narrativas.** Tocar un producto en producción cambia su huella: cada informe
   ya generado se regenera (15-90 s) y el guard recibe números nuevos que juzgar. Por eso la
   fase 4 es un solo eje.
2. **El cubo arranca en 2024-03.** Un producto con período anterior simplemente no lleva la
   lectura, sin mencionarlo (decisión del 2026-08-31).
3. **La regla del sujeto.** Cada clave nueva nombra su población:
   `credito_del_sistema_al_sector_F_pct`, nunca `participacion_pct`.
4. **No invadir.** El bloque entra en el CONTEXTO del eje, no en su ruteo: `law` llegó a
   activarse en 6 de 9 preguntas cuando no debía.
5. **El techo de 270 s sigue abierto.** Agregar contexto acerca al producto al corte, y la
   caché es por producto y no por sección: al cortar se descarta todo lo generado y el
   reintento arranca de cero. Está diagnosticado y sin arreglar — ver la memoria
   `el-year-review-se-corta-a-los-270s`.

## Fuera de alcance salvo pedido explícito

- Mover `MacroSeries` (24 archivos) y `SocialIndicator` (18). No bloquea nada de esto.
- Repartir `Y`/`Z` entre sectores: sería fabricar.
- `capacidad_de_pago` en ejes donde no signifique nada.

## Estado

| fase | estado |
|---|---|
| 0 · la capa macro sigue al corte | **cerrada** 2026-08-31 (#1033) |
| 1 · `CarteraSectorial` a `shared/reference/` | pendiente |
| 2 · letra CIIU en el crosswalk | pendiente |
| 3 · `perfil_del_sector` | pendiente |
| 4 · construction + medición | pendiente |
| 5 · resto de los ejes | pendiente |
| 6 · capacidad de pago y holgura | pendiente |
