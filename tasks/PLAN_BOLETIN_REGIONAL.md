# PLAN FINO — Boletín trimestral de banca · RD en contexto regional

> v1 · 2026-09-04 · Desglose ejecutable, paso a paso.
> **Spec rectora:** `../docs/EXPANSION_REGIONAL_BANCA_FUENTES.md` (auditoría de 20 plazas,
> matriz de fuentes verificada en vivo, y el porqué de cada exclusión).
>
> **Cómo se ejecuta (no negociable, doctrina de casa):** UNA tarea a la vez. Antes de
> implementar cada T, Claude Code confirma su plan fino con el dueño. Antes de cerrar:
> evidencia de ejecución mostrada + `pytest modules/ shared/` en verde. Prohibido correr
> el lote de corrido.
>
> Las firmas y rutas citadas fueron leídas del código al 2026-09-04. Si un archivo cambió,
> **releerlo antes de codear** y ajustar el plan en vez de forzarlo.

---

## Qué se construye, y qué NO

**Producto:** boletín trimestral de **divulgación** (no vendible), enviado a una lista de
suscripción. Sujeto: **RD por entidad** (motor y calibración existentes, sin tocar) +
**resto de países solo a nivel de sistema nacional**. Contenido: análisis con cifras,
**sin ranking comparativo entre países**.

**Alcance edición 1:** RD + Colombia + Brasil + Chile (por sistema) + SECMCA/EMFA como capa
de crédito, depósitos y tasas armonizadas para 8 países.

**NO se construye — y esto es la mitad del valor del plan:**

- ❌ Columna `country` en `Bank`, `BankingData` o `RatingResult`. **No se tocan.**
- ❌ Recalibración de umbrales de `scoring/engine.py` por país. Los cortes 75/60/45 y los
     tramos calibrados contra el panel RD de 46 entidades se quedan como están.
- ❌ Generalización de `BankType`. Sigue siendo la taxonomía regulatoria dominicana.
- ❌ Cambios a `find_banking_source()` (`shared/settings/service.py:546-561`).
- ❌ Puntuar entidades individuales fuera de RD. **Nunca.** El motor no está calibrado para
     eso y el boletín no lo necesita.

Si una tarea de este plan te empuja a tocar algo de esa lista, **parás y replanteás**. Es
señal de que el diseño se desvió.

---

## Decisiones del dueño — **AMBAS TOMADAS (2026-09-05)**

**D-1 · RESUELTA. No se publican bandas del Perfil SDQ por entidad.** Se nombran entidades
al describir movimientos del trimestre, y las bandas quedan para agregados y para la
distribución del sistema. Distribuir juicios recurrentes sobre la solidez de bancos con
nombre propio, sin ser calificadora regulada, es el riesgo que cerró la retirada de la
escala SDQ-AAA…D: el Perfil SDQ de dos ejes es más defendible que aquella escala, pero el
CANAL cambia el perfil de exposición — un cliente firma un contrato donde los supuestos
están escritos, un suscriptor lee un titular.

**D-2 · RESUELTA, y ya implementada.** Corte declarado por país. El sync lo devuelve en
`cortes_por_pais` y hoy conviven `DOM 2026-07-31`, `SLV 2026-06-30`, `NIC 2025-06-30` y
`COL 2026-06-30`. Un corte único habría desperdiciado la frescura de las plazas rápidas
para acomodar a la más lenta.

| # | Decisión | Default recomendado si no hay respuesta al llegar a T-BR-8 |
|---|---|---|
| **D-1** | ¿El bloque RD publica **bandas del Perfil SDQ por entidad con nombre propio**? | **No publicar banda por entidad.** Nombrar entidades al describir movimientos del trimestre, y reservar las bandas para agregados y distribución del sistema. Motivo: distribución masiva y recurrente de juicios sobre solidez de bancos nombrados, sin ser calificadora regulada, es el riesgo que cerró la retirada de la escala SDQ-AAA…D |
| **D-2** | ¿Corte único para toda la edición, o corte declarado por país? | **Corte declarado por país**, visible en cada sección. Motivo: Brasil publica a ~6 meses y fijaría el techo de toda la edición; Chile va a ~28 días y Colombia a ~2 meses. Un corte único desperdicia la frescura de dos fuentes para acomodar a una |

---

## FASE 0 — Deuda de licencias (bloqueante)

Bloqueante de verdad: la Fase 2 publica dato de la SB a una lista de correo, y hoy la SB
no está declarada en ningún lado.

### T-BR-1 · Registrar la SB dominicana en el registro de licencias

**Hallazgo que la motiva:** ninguno de los cinco clientes de banca
(`modules/banking_score/external/sib_data_client.py`, `sib_historical_client.py`,
`simbad_client.py`, `fiduciaria_pdf_client.py`, `shared/data/sib_client.py`) declara
atributo `license` ni hereda de `SourceClient`, así que el gate AST de
`shared/data/tests/test_regla_licencia_declarada.py` nunca los alcanzó y **jamás pasaron
por `check_license()`**. Es el eje con más dato real y el único sin licencia declarada.

**Hacer:**
1. Añadir a `LICENCIAS` (`shared/data/licenses.py:109`) las entradas de la SB, SIMBAD y el
   histórico de la SB, con el formato exacto del dict: `terminos_url`, `verificado_el`
   (fecha en que alguien **abrió y leyó** la página), `atribucion`, `nota`.
2. Aplicar la doctrina de emisores públicos dominicanos ya escrita en
   `shared/data/licenses.py:31-56` (Ley 200-04, Decreto 103-22, NORTIC A3, Ley 65-00
   art. 41). Esa doctrina **ya existe y es RD-específica** — se aplica, no se reescribe.
3. Declarar el atributo `license` en los cinco clientes con la cadena EXACTA registrada.

**No hacer en esta tarea:** refactorizar los cinco clientes para que hereden de
`SourceClient`. Es T-BR-2 y tiene riesgo propio.

**Aceptación:** `pytest shared/data/tests/test_regla_licencia_declarada.py` verde; las
cadenas nuevas aparecen en `LICENCIAS` y **no** en `deuda_de_verificacion()`.

---

### T-BR-2 · Hacer que los clientes de banca pasen por el gate

**Hacer:** que los cinco clientes hereden de `SourceClient`
(`shared/data/base_client.py:50`) y llamen a `check_license()` antes del primer fetch,
como hace `FixtureBackedClient.fetch()` (`base_client.py:131`).

**Riesgo real:** `SIBDataClient` tiene ~2200 líneas y su `fetch` no tiene la firma
`fetch(series, period) -> List[Record]` del ABC. **No forzar la firma.** Opciones a
proponer al dueño antes de codear: (a) heredar y sobreescribir con firma propia
documentando la divergencia, (b) un mixin de licencia sin el ABC completo.

**Aceptación:** un cliente con `license_ok=False` levanta `LicenseError` antes de tocar la
red, demostrado con un test. Todos los tests de `modules/banking_score/` siguen verdes.

---

### T-BR-3 · Registrar las licencias de las fuentes nuevas — **DISUELTA (2026-09-04)**

**Por qué no es un paso propio.** El gate exige que registro y declaración entren JUNTOS:
`test_el_registro_no_tiene_entradas_muertas` falla si una clave de `LICENCIAS` no la
declara ningún código vivo. Los conectores son T-BR-5/6/7, así que registrar las cuatro
licencias antes deja cuatro entradas muertas y CI en rojo. Comprobado registrando una
entrada ficticia: el gate la nombra y falla. Las alternativas eran conectores vacíos con
la cadena colgada —código muerto— o adelantar la Fase 1 entera.

**Dónde vive ahora:** el registro de cada licencia viaja con su conector. Lo que sí se
hizo el 2026-09-04, y es el trabajo real de esta tarea, fue **leer los términos en vivo**:
el resultado está abajo, en la tarea de cada fuente, para que el día del conector sea
copiar y pegar en vez de volver a investigar.

**Lo que aplica a las cuatro:**

- `license_restricts_redistribution` vive en `shared/data_api/manifest.py:97`, **no** en
  `licenses.py`. Detecta `-sa` y `odbl` por substring — en Colombia y Brasil no son falsos
  positivos, son las cláusulas reales, y es correcto que las marque.
- Esa cuarentena **no toca al boletín**: solo aplica a `DERIVATION_VERBATIM` («servir el
  valor del emisor tal cual ES redistribuir; servir un cálculo propio, no») y vive en la
  API de datos, que es otro producto. Queda una decisión para T-BR-6: agregar entidades
  para obtener el sistema es cálculo propio, pero republicar el agregado tal como lo
  publica el supervisor sería verbatim.
- El techo del ratchet (`DEUDA_AL_2026_08_23 = 23`) está exactamente al límite. SECMCA
  entra con `verificado_el=None` y **lo rompe a propósito**: hay que subirlo a 24 en el
  mismo commit del conector, con el motivo escrito.

---

## FASE 1 — Almacén regional a nivel sistema

### T-BR-4 · Modelo `country_banking_aggregate`

**Módulo nuevo:** `modules/regional_banking/` con `models/`, `api/`, `tests/`,
`__init__.py`, siguiendo el patrón de "Adding a New Module" del `CLAUDE.md`.

**Por qué tabla separada y no una columna en `BankingData`:** distinto sujeto (sistema vs
entidad), distinta semántica, y así el motor de RD queda literalmente intacto — el test de
no-regresión se vuelve trivial porque no hay nada que regresar.

**Referencia de diseño:** `CountryVariable` en
`modules/macro_political_risk/models/models.py` — es el único store multi-país del repo y
ya resolvió esta forma. Copiar su estructura:

```python
iso_code   = Column(String(3),  nullable=False)   # "COL", "BRA", "CHL", "DOM"
period_end = Column(Date,       nullable=False)
metric     = Column(String(60), nullable=False)
value      = Column(Float,      nullable=True)    # None = missing, nunca interpolado
source     = Column(String(30), nullable=False)
meta       = Column(JSON,       nullable=True)
__table_args__ = (UniqueConstraint("iso_code","period_end","metric", name="uq_rb_pais_periodo_metrica"),
                  Index("ix_rb_pais_periodo", "iso_code", "period_end"))
```

**Campo que NO está en `CountryVariable` y acá es obligatorio:** `norma_contable`
(String, nullable=False). Registra bajo qué norma se computó la métrica en su país de
origen. **Es lo que impide que alguien construya un ranking por accidente tres ediciones
después.** Sin ese campo el guard de T-BR-9 no tiene sobre qué operar.

**Migración:** `alembic -c infrastructure/alembic.ini revision --autogenerate -m "regional
banking aggregate"`, luego `upgrade head`. Las versions viven en
`infrastructure/alembic/versions/`.

**Aceptación:** migración aplica y revierte limpio; test de round-trip que confirma que
`value=None` persiste como `None` y no como `0.0`.

---

### T-BR-5 · Conector SECMCA / EMFA (el primero, y el más barato)

**Va primero a propósito:** es REST público sin autenticación, ya verificado en vivo, y
carga 8 países con un solo conector. Si algo del diseño de T-BR-4 está mal, se descubre
acá y barato.

**Plantilla:** `shared/data/dga_client.py` (123 líneas) es el conector más corto que
hereda del contrato. Copiar su forma: módulo con funciones puras de parseo + una clase que
declara `source`/`license`/`license_ok`.

**Endpoints verificados en vivo el 2026-09-04 (200, sin auth):**
- `GET https://secmca-api.secmca.org/simafir_api/ws/public/v1/tema` → 86 temas
- `GET .../public/v1/emfa/tema` → 5 temas, cuadros y variables
- `GET .../public/v1/obtenerDatos/porCriterio/{pais}/{variable}/{unidad}/{frecuencia}`
- Países: `CRI SLV GTM HND NIC DOM PAN BLZ` (con `codigoSDMX` ISO3 ya provisto)

**Qué extraer:** crédito por sector, depósitos MN/ME, tasas activa y pasiva, encaje,
agregados monetarios. **Todo armonizado** — es la única fuente del boletín que admite
comparación directa de niveles entre países.

**Qué NO extraer, y por qué:** SECMCA **no publica prudenciales**. Verificado: los 5 temas
de EMFA son monetarios; el filtro de los 86 temas por
`moros|solvenc|adecuac|vencid|rentabil|ROA|ROE|provisi` solo da falsos positivos de
balanza de pagos y finanzas públicas; EFPA es GFSM 2014 y ESEA es deuda externa. **Si
encontrás un endpoint prudencial, es un hallazgo nuevo: paralo y reportalo, no lo asumas.**

**Licencia (verificado en vivo el 2026-09-04):** SECMCA **no publica términos de uso ni
copyright** — se recorrió `www.secmca.org` buscando aviso legal, términos, privacidad y
pie de copyright, y no hay ninguno. Entra como **deuda declarada**: `verificado_el=None`
con la `nota` diciendo qué se buscó y dónde, nunca como permiso presunto. Es la única de
las cuatro que sube el techo del ratchet, de 23 a 24.

**Aceptación:** trae ≥1 serie real para los 8 países; `norma_contable` = `"EMFA
armonizado"`; fixture grabado para test offline.

---

### T-BR-6 · Conector Colombia (SFC vía Socrata)

**Verificado en vivo el 2026-09-04:** `GET
https://www.datos.gov.co/resource/x586-r5d2.json?$limit=3` → 200, solvencia por entidad,
Banco de Bogotá, valores absolutos. `$select=max(fecha)` → `2026-06-30`.

**Datasets:** `x586-r5d2` (Solvencia Individual, 2021-01→), `mxk5-ce6w` (CUIF por entidad
y cuenta, 20,1 M filas, 2016-01→), `rvii-eis8` (cartera por producto con buckets de mora).
**`snsm-7ynr` está muerto desde dic-2021 pese a declararse mensual — no usarlo.**

**Trampas conocidas:** join por `tipo_entidad`+`codigo_entidad`, **nunca por nombre**
(`"BANCO DE BOGOTA S.A."` vs `"Banco De Bogotá S.A."`). Agregados sobre la tabla completa
timeoutean a 120 s → paginar con `$limit`/`$offset` o filtrar por `fecha` primero.
`www.superfinanciera.gov.co` tiene Cloudflare; `datos.gov.co` no.

**Agregación a sistema:** sumar entidades de `tipo_entidad` bancos. Los ratios se computan
sobre los agregados, **no se promedian los ratios de las entidades** — es la trampa
clásica y da un número distinto.

**Licencia (verificado en vivo el 2026-09-04):** el propio dataset la declara vía la API
de Socrata — `GET https://www.datos.gov.co/api/views/x586-r5d2.json` devuelve
`licenseId: "CC_40_BY_SA"`, «Creative Commons Attribution | Share Alike 4.0 International»,
`termsLink` a `creativecommons.org/licenses/by-sa/4.0/legalcode`. Y trae el texto de
atribución del emisor, que va literal al campo `atribucion`: **«Superintendencia Financiera
de Colombia - SUPERFINANCIERA, Bogotá D.C.»**. El share-alike es real y la cuarentena de
verbatim es correcta.

**Aceptación:** solvencia, morosidad y cartera del sistema colombiano para ≥8 trimestres;
`norma_contable` = `"CUIF Colombia (SFC)"`.

---

### T-BR-7 · Conectores Brasil y Chile

**Brasil — verificado en vivo el 2026-09-04:** OData v4 sin key.
`GET .../IFDATA/versao/v1/odata/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes=202603&@TipoInstituicao=1&@Relatorio='5'&$format=json`
devuelve por `CodInst`: `Índice de Capital Principal`, `Índice de Capital Nível I`,
`Razão de Alavancagem`, `Exposição Total`.

Dos advertencias que **hay que codificar, no solo saber**:
- **Rezago ~6 meses.** Al 2026-09-04 la última data-base es `202603`; junio devuelve
  `value:[]`. El conector debe descubrir el último `AnoMes` disponible, no asumirlo.
- **Ruptura Res. CMN 4966.** El Relatório 8 (calidad AA–H) tiene datos hasta `202412` y
  está **vacío desde `202503`**, reemplazado por R16 con staging C1–C5. **No son
  empalmables.** El conector debe rechazar la concatenación y registrar dos series
  distintas, o el boletín va a mostrar un salto que no ocurrió en la realidad.

**Chile:** APIBEST necesita `x-api-key` (cuota 10/min · 100/día · 3.000/mes, rango máx.
12 meses por request) — pedirle la credencial al dueño, **no** crear cuenta. Vía sin
credencial para el catálogo: `https://best-sbif-api.azurewebsites.net/public/descargar/archivo-publico/catalogo-csv`
(10,9 MB, 34.051 series, **leer como latin-1**). Los XLSX del canal `/626/` traen la
fórmula en códigos contables en la **fila 2**: es un diccionario de datos, aprovecharlo
para el mapeo en vez de adivinar. El canal `/617/` está obsoleto (404).

**Licencias (verificado en vivo el 2026-09-04):**

- **Brasil:** el dataset IFDATA en `dadosabertos.bcb.gov.br` declara `odc-odbl` — Open
  Database License, con `license_url`. Confirmado por su API de catálogo.
- **Chile — OJO, la spec estaba equivocada y se corrigió.** No es CC BY 4.0 ni menciona
  uso comercial. Los únicos términos publicados son `https://api.cmfchile.cl/terminos-de-uso.html`,
  **actualizados el 01/06/2019**: «Todos los derechos reservados […] El uso y/o publicación
  de los contenidos […] **está autorizado**, con la consecuente incorporación de una
  mención a la fuente más un enlace a la página principal del sitio web CMF Bancos
  (`www.sbif.cl`)». Alcanza de sobra para el boletín, pero la cadena debe decir eso y no
  CC BY 4.0 — y la atribución **exige el enlace**, no solo el nombre. APIBEST no tiene
  términos propios: su host raíz da 404.

**Aceptación:** ambos países con ≥8 trimestres; el test de Brasil demuestra que R8 y R16 no
se concatenan.

---

## FASE 1 — CERRADA el 2026-09-05, con nueve países y dos diferidos

Decisión del dueño: se cierra con lo que hay y se pasa a la Fase 2. **La edición 1 cubre
RD por entidad + las siete plazas de SECMCA/EMFA + Colombia por sistema.** Nueve países ya
son un boletín; esperar a once con dos fuentes que no dependen de nosotros no lo era.

| Tarea | Estado |
|---|---|
| T-BR-4 · almacén `rb_country_aggregates` | hecha (`69bda04a`) |
| T-BR-5 · SECMCA/EMFA, 7 plazas | hecha (`0f3fe306`) — 46.649 observaciones |
| T-BR-6 · Colombia (SFC) | hecha (`c731ddc6`) — solvencia y morosidad del sistema |
| T-BR-7 · Brasil y Chile | **diferida a la edición 2**, ver abajo |

**Brasil — la API de valores del BCB está caída (2026-09-05).** Su OData responde 200 en la
raíz, en `$metadata` y en `ListaDeRelatorio()`, pero **`IfDataValores(...)` devuelve 500
«Erro desconhecido»** en todas las combinaciones probadas: cuatro años (2021, 2023, 2024,
2025), dos tipos de institución, cuatro relatórios, JSON y CSV, y las dos sintaxis de
parámetros. `IfDataCadastro` también. NO es un cambio de contrato — el `$metadata` declara
la firma exacta que usábamos—, así que muy probablemente sea transitorio: **reintentar antes
de la edición 2**.

Lo que sí quedó confirmado es la ruptura de la Res. CMN 4966, y está en el catálogo oficial
del propio BCB: **R8** «Carteira de crédito ativa - por nível de risco da operação» y
**R16** «Carteira de crédito ativa - por carteiras de instrumentos financeiros» son dos
relatórios DISTINTOS con nombre distinto, no dos versiones del mismo. El conector rechaza la
concatenación, no la resuelve.

**Chile — falta la credencial.** `api.cmfchile.cl` responde HTTP 422 «API key no ha sido
suministrada»; no hay vía sin registro. El catálogo CSV público (10,9 MB, 34.051 series,
latin-1) sí baja pero es solo un DICCIONARIO, sin datos. Aprovechado igual: **26.201 series
son de entidades bancarias y 1.319 traen vocabulario prudencial** —cartera deteriorada,
morosidad de 90 días o más, provisiones por riesgo de crédito—, así que el día que llegue la
credencial no hay que investigar qué pedir. **Acción del dueño: solicitar la API key.**

---

## FASE 2 — Generador del boletín

### T-BR-8 · Plantilla de edición

**Bloqueada por D-1 y D-2.** Confirmar ambas con el dueño antes de empezar.

Estructura: §1 RD en profundidad (motor existente) · §2 sistemas nacionales por
**trayectoria** · §3 crédito y tasas armonizados vía EMFA (la **única** sección donde se
comparan niveles entre países) · §4 nota metodológica.

La nota metodológica se genera desde `shared/registry/provenance.py`, **nunca se escribe a
mano** — ya hay gate de CI sobre eso.

---

### T-BR-9 · Guard de no-comparabilidad

**La tarea más importante del plan.** La disciplina editorial de no hacer rankings no
sobrevive a la edición doce; un test sí.

**Hacer:** `modules/regional_banking/tests/test_regla_sin_comparacion_no_armonizada.py`,
en la forma de los ~40 guards estructurales que ya tiene el repo (ver
`shared/data/tests/test_regla_licencia_declarada.py` como modelo de docstring: explica el
caso que lo motivó, no solo la regla).

**Qué debe fallar:** que una misma visualización o tabla del boletín ponga lado a lado la
misma métrica de más de un país cuando los `norma_contable` difieren. La excepción
explícita y única: métricas cuyo `source` es EMFA, que sí están armonizadas.

**Evidencia para el docstring:** la propia SECMCA declara por escrito en su página del ESB
que sus indicadores bancarios *"no están armonizados"* y remite a EMFA. Si el organismo
regional lo dice de su propia región, nosotros no podemos afirmar lo contrario.

**Aceptación:** el test falla contra un caso construido a propósito, y pasa contra el
boletín real.

---

### T-BR-10 · Implementar `variable_signals()` en `banking_score`

Hoy degrada a `_product_level_fallback` (`shared/registry/service.py:33-58`) y sirve una
sola señal `_axis` con `degraded=True`. El boletín es exactamente donde eso se vuelve
público: vas a declarar cobertura ante una lista de correo.

**Firma:** devolver `Tuple[VariableSignal, ...]` (`shared/registry/signals.py:65`). Estados
`REAL | RUBRIC | GAP`; `normalize_state()` mapea desconocido → `GAP`, conservador por
regla. Usar `scope="national"` en las variables de alcance país y `per_subject` en las que
diferencian entre entidades — la distinción existe para no decirle a alguien que algo
explica su posición cuando no la explica.

**Aceptación:** `banking_score` deja de aparecer con `degraded=True` en el registro.

---

## Orden de ejecución

```
T-BR-1 → T-BR-2                 (Fase 0, bloqueante — CERRADAS 2026-09-04)
      ↓                         T-BR-3 disuelta: cada licencia viaja con su conector
T-BR-4 → T-BR-5 → T-BR-6 → T-BR-7   (Fase 1; T-BR-5 primero a propósito)
      ↓
T-BR-8 (requiere D-1, D-2) → T-BR-9 → T-BR-10
```

T-BR-10 podría adelantarse —no depende de nada de la Fase 1—, pero **no se adelanta**:
decisión del dueño (2026-09-04) de avanzar en orden sin dejar huecos entre fases.

## Gates que todo cambio debe pasar

```bash
pytest modules/ shared/ -v
```

El repo tiene ~40 tests estructurales (guards de AST y de regla). Los que este trabajo
toca de cerca:

- `shared/data/tests/test_regla_licencia_declarada.py` — ratchet: **una fuente nueva entra
  verificada o se rechaza.** Escanea los nombres `{LICENSE, _LICENSE, LICENCIA, license}`
  por AST sobre `shared/`, `modules/` y `app/`.
- `shared/narrative/tests/test_sin_notacion_heredada.py` — la escala SDQ-AAA…D está
  retirada. **El guard lee `ast` sobre `modules/` y `shared/`, y NO cubre los `.md`**: en
  la prosa del boletín la disciplina es tuya.
- `shared/validation/tests/test_disclaimer_sin_cifras_a_mano.py`
- `shared/data/tests/test_regla_total_nacional_declarado.py`

## Al cerrar

Agregar entrada a `tasks/lessons.md` con el formato del archivo (`### YYYY-MM-DD — título`
+ **Síntoma** / **Causa raíz** / **Regla** / **Disparador**) por cada corrección del dueño.
