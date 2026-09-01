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

**Decisión TOMADA el 2026-09-01 (#1043).** `SectorVariable` se mudó a `shared/reference/` y
habilitó **tres** lecturas, no dos —la tercera es la inversión extranjera realizada por
actividad, que nadie había listado—. Ver «Las dos decisiones» al final.

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

### Fase 5 — El resto · CERRADA (#1040)

Cableados `free_zones` (`zonas_francas`), `energy` (`energia`) y `tourism` (`turismo`), cada
uno con sus DOS mitades —el bloque en el contexto y su plantilla pidiéndolo— según lo que
enseñó la fase 4.

El bloque se GENERALIZÓ a `shared.perfil_del_sector.contexto_de_financiamiento(perfil,
sufijo)`: un solo cuerpo para los cuatro ejes, y construcción pasó a delegar. Cuatro copias
de la misma forma es como una se queda atrás.

`zonas_francas` es el primer caso REAL de agregado: sale de la letra `D`, que la SIB no
separa de la manufactura local. Su plantilla lo dice explícitamente —«si viene marcada como
AGREGADO, decí de qué agregado es y no la atribuyas solo a zonas francas»— y el aviso viaja
en el contexto.

**Un defecto que esta fase destapó y que yo había desplegado en la 4:** al renombrar una
clave del perfil no cambié el `.get()` que la lee del otro lado, así que `peso` llegó a
producción en `None` y el informe citó deuda, entidades, tasa y mora pero nunca el peso del
sector. Los tests no lo vieron porque su fixture estaba escrita a mano y arrastraba el
nombre viejo: fixture y código derivaron juntos. La cura no fue renombrar con más cuidado
sino atar las dos puntas —`test_las_DOS_PUNTAS_del_contrato_usan_las_mismas_claves` compara
las claves que el lector pide contra las que el emisor REAL produce, en los dos casos
(directo y agregado)—.

**Un año EN CURSO también lee el cubo** (#1041). Verificado en producción: los tres ejes
citan el financiamiento, pero `energy` no — su producto está en 2026, pedía un `2026-12-31`
que no existe y la capa nunca iba a viajar. El año que viene le pasa a todos.

Ahora el corte lo deriva `corte_del_cubo_para_el_anio`: el diciembre del año, o —si el año
está en curso— su último trimestre DE ESE AÑO. Nunca se sale del año, que sí contradiría el
encabezado. Es legítimo porque la capa no es del índice: es contexto agregado, viaja con su
propio corte y la plantilla exige citarlo.

**`sector_intel` quedó APARTE, y la decisión se tomó el 2026-09-01 (#1045)**: el costo del
capital entró al IAI. Ver «Las dos decisiones» al final.

### Fase 6 — `capacidad_de_pago` y holgura donde signifiquen algo · CERRADA (#1042)

Repartida SOLO donde la lectura significa algo, y **la lectura cambia por eje** — un test
exige que las cuatro sean distintas, porque cuatro plantillas con el mismo párrafo serían
relleno repartido:

| eje | su lectura |
|---|---|
| `construction` | la DEMANDA de vivienda: el piso de ingreso contra la canasta |
| `free_zones` | el COSTO LABORAL y la disponibilidad de mano de obra |
| `tourism` | la DEMANDA INTERNA que amortigua una caída de llegadas |
| `telecom` | la ASEQUIBILIDAD: lo que queda en el hogar después de comer |

**Deliberadamente NO** en `law`, `esg`, `trade` ni `macro`: ahí sería relleno, y hay un test
que lo frena si alguien la agrega sin una lectura propia.

**Dos cruces nuevos que ninguna otra fuente arma:**

- **Dónde se construye contra la holgura de ESE territorio.** Los permisos traen provincia y
  la ENCFT trae subutilización por dominio, y nadie los junta. Se pondera por m² licenciados
  y no por promedio simple de provincias, que daría la holgura de un desarrollador que
  construyera igual en las treinta y dos. Para esto hubo que EXPONER el desglose provincial
  del índice, que se computaba para el HHI y no se servía.
- **La holgura laboral de una región del IDM.** `parse_regiones` persistía 7 indicadores × 5
  dominios × 11 años y solo los leía banca. `social_dev` YA es regional: los recibe directos.
  El IDM trae pobreza, informalidad e ingreso pero NO subutilización, que es la diferencia
  entre «hay poco empleo» y «hay gente disponible que el mercado no absorbe».

`holgura_donde_presta` se GENERALIZÓ a `holgura_donde_opera(clave_peso, sujeto)` —banca
delega— porque el peso territorial de construcción son m², no saldo adeudado, y el sujeto
tiene que viajar en las claves.

**La ENCFT publica por DOMINIO (cuatro), no por región de desarrollo (diez).** La respuesta
lo dice y la plantilla obliga a decirlo: atribuirlo a la región afirmaría una precisión que
la fuente no tiene.

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
| 5 · resto de los ejes | **cerrada** 2026-09-01 (#1040 + #1041) |
| 6 · capacidad de pago y holgura | **cerrada** 2026-09-01 (#1042) |
| decisión 1 · `si_variables` a `shared/` + 3 lecturas + telecom | **tomada** 2026-09-01 (#1043) |
| decisión 2 · el costo del capital en el IAI | **tomada** 2026-09-01 (#1045) |
| lo que salió de verificar en prod | (#1044 · #1046 · #1047 · #1048) |


---

## Las DOS decisiones pendientes — TOMADAS el 2026-09-01

El dueño las desbloqueó con una razón concreta: **aún no hay reportes publicados**, así que
ningún cliente tiene en la mano una cifra que estos cambios muevan.

### 1 · `SectorVariable` → `shared/reference/` (#1043)

`si_variables` guarda cuatro registros NACIONALES —valor agregado del BCRD, ocupados de la
ENCFT, panel de la ENAE y flujos de IED por actividad— y `sector_intel` era su primer
consumidor, no su dueño. El nombre de la tabla **no cambió**: el prefijo `si_` es un contrato
con la base, y renombrarlo pediría una migración de datos para ganar estética.

De paso, las cuatro dimensiones dejaron de declararse en el sync y viven con el modelo:
`SECTOR_DIMENSION` estaba escrito **dos veces** con el mismo literal.

**Tres lecturas nuevas, no dos.** La tercera —inversión extranjera realizada por actividad—
no estaba en la anotación y es el único desenlace de inversión que el país publica abierto.

| lectura | fuente | cobertura de los 17 |
|---|---|---|
| crédito y tasa | cubo de la SIB | 16 (4 como agregado declarado) |
| costo laboral | TSS | 17 |
| actividad (peso en el VA + crecimiento) | BCRD, cuentas nacionales | 17 |
| ocupación | ONE · ENCFT | 17 (3 ramas son bundles declarados) |
| inversión extranjera | BCRD, flujos de IED | 10 |

**Telecom quedó cableado por primera vez.** `comunicaciones` es el único de los 17 slugs que
la SIB no cubre con ninguna letra CIIU: sin crédito no había bloque, y por eso el eje quedó
fuera de las fases 3-5. Las tres capas nuevas sí lo alcanzan.

**Construcción omite `actividad`, y es el único.** Ya publica el crecimiento del PIB de
construcción del BCRD con su propio nombre; servirle la misma lectura con otra clave pondría
dos cifras de crecimiento del mismo sector en el mismo contexto y el modelo elige la que le
cae más cerca. La omisión se declara en el código y en el test, y hay un test que exige las
dos.

### 2 · El costo del capital entra al IAI (#1045)

`credit_cost` = tasa promedio ponderada del cubo de la SIB, dimensión de negocios, en
`risk_increasing`. Cobertura **16/17**; `comunicaciones` la deja ausente, sin rúbrica-50 falsa.

**La tasa y no la mora, medido y no opinado.** Correlacionan a **r = +0,65** sobre el cubo de
producción: el precio del crédito ES, en buena parte, la lectura que el mercado hace del
riesgo del sector, y meter las dos sería el mismo hecho votando dos veces. La cobertura de
provisiones se descartó por medición: energía marca 4.031 % contra un rango de 124-483 % del
resto, y el min-max **crudo** de este motor (no usa `robust_bounds`) hundiría a los otros once.

**El corte es el DEL AÑO que se puntúa**, no una foto reciente aplicada hacia atrás: sobre los
21 cortes reales del cubo (2021-Q1 → 2026-Q1) el orden transversal se mueve, con rho de
Spearman de +0,69 entre el primero y el último.

**O todos, o ninguno dentro de un período.** El cubo arranca en 2021 y el IAI se puntúa desde
2007. El motor normaliza contra los pares DE ESE PERÍODO, así que una cobertura parcial por
período movería el ranking por PRESENCIA y no por dato.

**Impacto medido** con el motor y la doctrina reales contra el dataset de producción (período
2025, corte 2025-12-31): 12 de 17 cambian de posición, |Δ| medio 2,08 puntos, mayor descenso
`otros_servicios` (−5,69), mayor ascenso `energia` (+4,00), y **un cambio de banda —
`agropecuario` 42,75 → 38,80, de Medio a Bajo**. Registrado en `shared/doctrine/changelog.yaml`.

**El SGPS no se tocó:** es una mezcla directa de tres factores que suman 1,0; sumarle un
cuarto sería re-pesar la fórmula, no agregar un insumo.

### Tres defectos que salieron de VERIFICAR en producción, no de los tests

| # | qué | por qué importa |
|---|---|---|
| #1044 | una IED **negativa** servida en porcentaje invertía la dirección (+36,73 % en un año de desinversión) | la relación la computaba yo, y salió invertida |
| #1046 | el narrador del IAI **no podía citar la variable** que movió el score, y declaraba procedencia a mano (3 dimensiones dadas por rúbrica con 8/9 variables reales) | el producto se subestimaba a sí mismo en el texto que se vende |
| #1047 · #1048 | llamó «**percentil**» a una posición min-max, y después arrastró el denominador de la línea de al lado | dos afirmaciones falsas en un documento que se vende |

Ninguno lo habría encontrado la suite: el primero necesitaba una serie negativa real, y los
otros dos son propiedades del TEXTO generado.

### Lo que NO se puede afirmar

El Gate E de este eje corrió después del cambio y **no lo valida**. Pero el modo en que no lo
valida importa, y la primera redacción de este párrafo lo dijo mal: decía «el desenlace de
inversión sigue con IC negativo y significativo», que se lee como que el índice ordena la
inversión al revés. **No es eso.** El veredicto que la plataforma computa —y que se citó sin
mirar— es **EMPATE**: el mismo desenlace ordenado SOLO por el tamaño del sector alcanza un
poder estadísticamente indistinguible del índice. El signo negativo lo pone el deflactor,
porque la intensidad se divide por `sector_size`, que es una variable del propio IAI.

La lección es la de siempre en este repo, y esta vez la pagué yo: **un IC citado sin su
control es una relación inventada.** Lo que hizo fácil el error fue que el encabezado del
reporte publicaba el desenlace SECUNDARIO y el control vivía dos niveles más abajo del
payload; eso se arregló en el PR #1050.

El producto sigue declarado **descriptivo** en su `ESTADO_BACKTEST`. El estado vigente se pide
a la plataforma (`GET /api/v1/sector-intel/validation`), nunca se copia acá — y al pedirlo, se
lee `veredicto_contra_el_tamano` junto al IC, no el IC solo.
