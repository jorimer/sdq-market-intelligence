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

## Decisiones abiertas del dueño

Ninguna bloquea la Fase 0 ni la Fase 1. Ambas muerden en **T-BR-8**.

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

### T-BR-3 · Registrar las licencias de las fuentes nuevas

**Hacer:** cuatro entradas en `LICENCIAS`, con el texto de atribución exacto en el campo
`atribucion`:

| Fuente | Licencia | Atención |
|---|---|---|
| SFC Colombia (Socrata) | CC BY-SA 4.0 | Exige citar fuente **y fecha de actualización**. El `-sa` lo detecta `license_restricts_redistribution` (`licenses.py:20-26`) — es correcto que lo detecte |
| BCB Brasil (IFDATA) | ODbL | `odbl` también es marca detectada. Correcto |
| CMF Chile (APIBEST) | CC BY 4.0, "incluso con fines comerciales" (act. 2026-08-06) | Citar **APIBEST**, no `datos.gob.cl`, que es CC BY-**NC** y está congelado en 2015 con recursos 404 |
| SECMCA / EMFA | **Pendiente de localizar** | No se encontró página de términos. Entra como deuda declarada (`verificado_el=None` + `nota` explicando qué se buscó), no como permiso presunto |

**Aceptación:** el gate AST verde; `deuda_de_verificacion()` lista SECMCA y **solo**
SECMCA de las cuatro.

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

**Aceptación:** ambos países con ≥8 trimestres; el test de Brasil demuestra que R8 y R16 no
se concatenan.

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
T-BR-1 → T-BR-2 → T-BR-3        (Fase 0, bloqueante)
      ↓
T-BR-4 → T-BR-5 → T-BR-6 → T-BR-7   (Fase 1; T-BR-5 primero a propósito)
      ↓
T-BR-8 (requiere D-1, D-2) → T-BR-9 → T-BR-10
```

T-BR-10 puede adelantarse: no depende de nada de la Fase 1.

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
