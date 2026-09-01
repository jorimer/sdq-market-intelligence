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
llamaba `capacidad_de_pago(db, date.today())`, ignorándolo. `modules/pension_intel/products.py`
hacía lo mismo y su producto también lleva período. `insurance_intel` lo hacía bien.

Cerrado subiendo el helper a `shared.capacidad_de_pago.corte_del_periodo` —seguros tenía el
único cuerpo correcto y ya iba camino a la tercera copia; un módulo no puede importar de
otro, así que la única forma de no duplicarlo era que viviera junto a la lectura—. Lo vigila
`shared/tests/test_la_capa_macro_sigue_al_corte.py`, que lee la LLAMADA con `ast` en las tres
superficies.

Era la familia del #992 —la frescura envejeciendo sola dentro de un documento fechado— en dos
productos ya publicados. Fue primero para no propagar el patrón al repartirlo a once ejes más.

### Fase 1 — `CarteraSectorial` a `shared/reference/` · CERRADA (#1034)

8 archivos, todos dentro de `banking_score`. La tabla se llama `cartera_sectorial` antes y
después: **sin migración**. `shared/reference/` ya guarda datasets nacionales (registro DGII,
provincias), que es exactamente lo que el cubo es.

**La trampa era real y se comprobó por mutación:** sin su línea en `env.py`,
`autogenerate` emite `op.drop_table('cartera_sectorial')` — no falla nada, sale una
migración plausible que destruye datos. Con la línea, lo único que queda sobre la tabla es
la nulabilidad de `created_at`/`updated_at`, que es deriva preexistente y afecta a varias.

Lo vigila `shared/tests/test_alembic_ve_todas_las_tablas.py`, que compara en un subproceso
lo que registra `env.py` contra lo que registra la app. Al escribirlo encontró **tres
instancias preexistentes** de lo mismo —`const_scores`, `tour_scores` y
`source_suggestions`—, ya corregidas.

**Lo que NO era como yo lo había medido.** El cubo tiene `bank_id` con FK a `banks` y una
relación a `Bank`: no es dato nacional puro, está a grano de entidad. La relación no la usaba
nadie y se quitó; el FK queda, y es la primera FK de `shared/` hacia una tabla de módulo en
este repo. Se hizo igual porque la alternativa —materializar un agregado de sistema en otra
tabla— crea dos caminos que tienen que coincidir, que es el defecto que costó la tasa de 38
entidades ese mismo día. **Deuda anotada:** `banks` es tan nacional como este cubo y debería
acompañarlo; se referencia en 53 archivos y es otra tarea.

Por qué mover y no leer desde `shared/`: los imports de `shared/` hacia `modules/` existen
hoy en 3 archivos de todo el repo. Es una excepción, no un patrón, y hacerlo patrón costaría
reescribir el mismo archivo cuando la tabla se mueva igual.

### Fase 2 — La letra CIIU en el crosswalk · CERRADA (#1035)

Construida **contra el catálogo de la SIB**, no deducida de las etiquetas: «el catálogo de la
SIB define los campos, el portal no» costó tres backfills. `Y`/`Z` y los slugs sin letra se
marcan como no mapeables con su motivo, hacia adentro.

Verificado. El catálogo se leyó de los valores DISTINTOS que la fuente emitió en los **nueve
cortes** persistidos, no de un informe: las 19 etiquetas aparecen en los nueve, así que es
estable. El mapa vive en `shared/data/sector_crosswalk.py` (`SIB_SECTORS`, `map_sib_label`,
`sib_members`, `sib_coverage`), con guard fail-closed al importar como el de ENCFT/ENAE/IED.

**Cobertura: 16 de los 17 slugs.** Diez letras son 1:1; `D` agrupa manufactura local con
zonas francas y `K` agrupa inmobiliario con servicios profesionales; `A` y `B` comparten
`agropecuario` y `E` cubre solo la parte eléctrica de «Energía y Agua». Todos los agregados
declaran su motivo, y el test exige que los directos NO lleven nota — sin ese contra-caso,
exigir nota a todos no significaría nada.

**La única brecha es `comunicaciones`:** la `J` de la SIB es financiera, no «información y
comunicaciones» — su marco no sigue la revisión 4 en ese punto.

**Cuatro letras no son sectores** y no alimentan ningún slug: `Y` y `Z` son destinos de
crédito a hogares (26,72% y 18,75% de la cartera al 2025-12-31) y `P` y `Q` son hogares como
empleadores y organismos extraterritoriales.

**Lo que el test NO puede detectar,** dicho para que no se le suponga alcance: que la SIB
renombre un sector mañana. Eso se descubre en producción, y por eso `map_sib_label` cae a la
letra inicial — una etiqueta reescrita sigue resolviendo, que es lo que evita que media
cartera desaparezca del agregado por un cambio cosmético. Lo que sí vigila es que la tabla
declarada no se separe de lo medido.

### Fase 3 — `shared/perfil_del_sector.py` · CERRADA (#1036)

Entrega **dos** de las cuatro lecturas: crédito (SIB, agregado y sin ninguna entidad
nombrada) y costo laboral (salario promedio cotizable de la TSS, con su año).

**Por qué dos y no cuatro.** Se midió el estado de las fuentes en producción antes de
escribir: `tss-salario-sync` está en verde con los 17 slugs del año 2025, pero la ocupación
ENCFT y el tamaño/crecimiento del BCRD viven los dos en `SectorVariable`, tabla de
`sector_intel`. Traerlas exigiría que `shared/` importe el modelo de un módulo — el patrón
que la fase 1 evitó mudando la tabla en vez de leerla desde afuera. Además
`encft-empleo-sync` lleva desde junio de 2026 fallando con 403 contra one.gob.do.

Cada respuesta trae `cobertura.lecturas_pendientes` con las dos, como dato interno del
contexto y no como texto del informe.

**Lo que este módulo protege es el SUJETO.** Varias letras de la SIB alimentan a más de un
slug: la `D` no separa manufactura local de zonas francas y la `K` agrupa inmobiliario con
servicios profesionales. Para esos slugs la cifra NO es del sector pedido sino del agregado
que publica la fuente, y la respuesta lo dice en `es_agregado`, `el_agregado_incluye` y
`por_que_es_agregado`. Repartir un agregado entre sus miembros sería fabricar.

**Las primitivas de agregación se MUDARON, no se copiaron**, a
`shared/reference/cartera_agregacion.py`: el mapa sectorial de banca y este perfil comparten
un solo cuerpo, y hay un test que exige que los dos importen del mismo lugar. Copiarlas
habría repetido el defecto que ese mismo día borró la tasa de 38 entidades.

**Decisión pendiente para el dueño:** mover `SectorVariable` a `shared/` (o exponerla)
habilitaría las otras dos lecturas. No se hizo por cuenta propia porque es la misma decisión
de arquitectura que se tomó explícitamente en la fase 1.

### Fase 4 — Un solo eje, y medir · CERRADA (#1037)

`construction_intel`: hoy mide permisos, m², HHI por tipología y HHI por provincia, y **no
tiene ninguna dimensión de financiamiento**. Además tiene provincia, así que le aplica la
holgura laboral.

El perfil entra al payload AL CIERRE del año —el producto es anual y el cubo trimestral—
y viaja al contexto con el sujeto en cada clave y las relaciones ya computadas.

**Línea base medida antes de desplegar** (nivel `pulse`, 2026-08-31): 26 s, cero menciones de
financiamiento, y `n=0` ensamblados de este eje en la ventana de siete días.

Una clave se RENOMBRÓ por precisión, no para pasar un test: el guard del sujeto marcó
`peso_..._en_el_credito_del_pais_pct` y tenía razón en el fondo — el denominador es la
cartera clasificada del sistema (el cubo de la SIB), no la economía del país. Quedó
`peso_de_la_construccion_en_la_cartera_del_sistema_pct`.

#### La medición, que es el punto de esta fase

| | antes | después |
|---|---|---|
| tiempo de ensamblado (`pulse`) | 26 s | **24-29 s** (mediana 24,16 s sobre 5 corridas) |
| cortados por tiempo | 0 | **0** |
| marcas nuevas del guard | — | **0** |
| menciona el financiamiento | no | **sí** |

**El hallazgo que justifica haber hecho un solo eje.** Con el bloque ya viajando en el
contexto, la primera generación en producción NO lo usó: la prosa siguió hablando solo de
permisos, m², tipología y geografía. El modelo hacía lo correcto — la plantilla enumera
taxativamente qué cifras usar y el financiamiento no estaba en esa lista. **Servir el dato no
alcanza: hay que pedirlo** (#1038).

Es la familia de «el cómputo existe y la superficie no lo pide», que en esta misma sesión ya
apareció con el mapa sectorial en 1 de 4 tipos de informe. Acá la superficie es el prompt.

**Con la plantilla corregida, el texto cambia de conclusión:** «El financiamiento del sistema
al sector (corte: 31 de diciembre de 2025) no amplifica la señal de alarma… Un ciclo de
permisos a la baja con financiamiento sano es distinto a uno con crédito deteriorado: el
riesgo aquí es de demanda nueva, no de cartera existente.» Esa lectura era imposible antes, y
el modelo citó la fecha de la capa como se le pidió.

**Consecuencia para las fases 5 y 6:** cada eje necesita DOS trabajos, no uno — el cableado y
su plantilla. Presupuestar los dos.

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
| 1 · `CarteraSectorial` a `shared/reference/` | **cerrada** 2026-08-31 (#1034) |
| 2 · letra CIIU en el crosswalk | **cerrada** 2026-08-31 (#1035) |
| 3 · `perfil_del_sector` | **cerrada** 2026-08-31 (#1036) |
| 4 · construction + medición | **cerrada** 2026-08-31 (#1037 + #1038) |
| 5 · resto de los ejes | pendiente |
| 6 · capacidad de pago y holgura | pendiente |
