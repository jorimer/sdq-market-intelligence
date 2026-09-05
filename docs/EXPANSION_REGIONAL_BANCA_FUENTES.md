# Boletín trimestral de banca — auditoría de fuentes supervisoras LATAM

**Fecha:** 2026-09-04 · **Alcance investigado:** 20 plazas (18 países + 2 organismos regionales) · **Estado:** insumo de decisión, no plan aprobado

## Premisa

Producto de **divulgación**, no comercial. Envío trimestral a lista de suscripción. Decidido el 2026-09-04:

- **Sujeto:** RD por entidad (con nombre propio, motor y calibración existentes) + resto de países **solo a nivel de sistema nacional**.
- **Contenido:** análisis con cifras de respaldo. **Sin ranking comparativo entre países.**
- **Posicionamiento:** "RD en contexto regional", no "boletín de la banca latinoamericana".

Esta premisa reemplaza la hipótesis de producto vendible con la que se inició el relevamiento. Lo que cambia se marca abajo.

---

## 0. Lo incómodo primero

**1. No hay atajo regional. Verificado hoy, contra mi propia recomendación previa.**

Recomendé usar la API de SECMCA para cargar siete plazas de un saque. **Es incorrecto y lo retiro.** Evidencia directa:

- La página del ESB de SECMCA declara textualmente: *"estos indicadores no están armonizados. Para conocer sobre indicadores financieros armonizados consultar: Estadísticas Monetarias y Financieras Armonizadas (EMFA)"*.
- Recorrí los 5 temas de EMFA vía `GET /simafir_api/ws/public/v1/emfa/tema` (200, sin auth): `PANORAMAS_FINANCIEROS`, `AGREGADOS_MONETARIOS`, `ACT_PAS_OSD_BD`, `CREDITO_OSD_BC`, `COMP_CAPT_ACT_EXTER_OSD_BC`. **Ningún cuadro prudencial.**
- Filtré los **86 temas** de `GET /public/v1/tema` por `moros|solvenc|adecuac|vencid|rentabil|ROA|ROE|patrimon|provisi|liquidez|cartera|eficienc`. Todos los aciertos son falsos positivos: "Cuenta capital" (balanza de pagos), "Inversión de cartera neta" (BdP), "Gastos de capital GC" (finanzas públicas).
- `/public/efpa/cuadros` es **GFSM 2014** — finanzas públicas. `/public/v1/esea/tema` es **deuda externa**.
- El ESB publica exactamente dos enlaces: un XLSX de **metadata** (abril 2025) y el reporte en HTML de **noviembre 2023**. **No hay feed trimestral vivo.**

**Consecuencia:** el bloque de solvencia, calidad de cartera y rentabilidad hay que construirlo supervisor por supervisor. A nivel de sistema cada conector es sustancialmente más barato que por entidad, pero siguen siendo N conectores. Esto es el argumento más fuerte a favor del alcance chico.

**2. Gratis no es permiso universal.** Panamá prohíbe "reproducción, redistribución, transmisión, circulación, adaptación" — la lista de verbos no depende del precio; la comercialización es solo un ítem más. Uruguay prohíbe "redistribución, recirculación, retrasmisión". Un boletín es literalmente eso, cueste cero o cien. En cambio Argentina y Jamaica prohíben *específicamente* el uso comercial, así que bajo esta premisa **se reabren**.

**3. El riesgo metodológico sube, no baja.** Un cliente que paga firma un contrato donde los supuestos están escritos. Un suscriptor lee un titular. Publicar solvencia de Chile al lado de la de Paraguay como si fueran la misma métrica es deshonesto, y la propia SECMCA lo confirma por escrito para su propia región. La decisión de "sin ranking" (§Premisa) es lo que protege esto; hay que sostenerla contra la tentación editorial, porque el ranking es exactamente lo que más se comparte.

**4. Deuda de casa que sigue abierta.** La SB dominicana **no tiene entrada en `shared/data/licenses.py`** y ninguno de los cinco clientes de banca hereda de `SourceClient`, así que jamás pasaron por `check_license()`. Un boletín público con atribución hace esto más urgente, no menos: vas a publicar el dato de la SB a una lista de correo.

**5. Lo que la nueva premisa elimina — buena noticia.** El boletín no puntúa entidades fuera de RD, así que **se cae la Fase 1 completa** del plan anterior: no hace falta columna `country` en los modelos, ni recalibración de umbrales por país, ni generalizar `BankType`, ni tocar `find_banking_source()`. Semanas de refactor que desaparecen. RD sigue usando el motor tal como está.

---

## 1. Qué necesita cada bloque del boletín

### Bloque RD — por entidad (usa el motor existente, sin cambios)

Contrato ya satisfecho por la ingesta actual. Pesos: solidez 0.40 · calidad 0.30 · eficiencia 0.15 · liquidez 0.10 · diversificación 0.05. 19 indicadores, umbrales calibrados contra el panel dominicano de 46 entidades (`scoring/engine.py:41-58`). Sin trabajo nuevo de datos.

**Advertencia editorial:** publicar juicios sobre la solidez de bancos con nombre propio, en distribución masiva y recurrente, sin ser calificadora regulada, es el riesgo que la retirada de la escala SDQ-AAA…D buscaba cerrar. El Perfil SDQ de dos ejes es más defendible que la escala vieja, pero el canal cambia el perfil de exposición. Definir antes de la primera edición: si se publican bandas por entidad, o solo movimientos y agregados con las entidades nombradas sin banda.

### Bloque regional — por sistema nacional

Mínimo por país y por trimestre para sostener la narrativa:

| Métrica | Por qué | Disponibilidad regional |
|---|---|---|
| Adecuación de capital del sistema | Ancla de solidez | Buena — casi todos la publican |
| Morosidad / cartera vencida | El indicador que más se lee | Buena |
| Cobertura de provisiones | Contrapeso obligado de la morosidad | Media |
| ROA / ROE | Rentabilidad | Media — varios exigen derivarla |
| Crecimiento de crédito y depósitos | Ciclo | **Excelente vía SECMCA/EMFA, armonizado** |
| Tasas activa y pasiva, spread | Margen | **Excelente vía SECMCA, armonizado** |
| Liquidez | Estrés | Débil — LCR/NSFR casi siempre en PDF |

**Regla de oro:** las tres primeras filas vienen de supervisores nacionales **no armonizados** → se narran como *trayectorias dentro de cada sistema*. Las dos filas de SECMCA sí están armonizadas → son las únicas que admiten comparación directa de niveles entre países.

---

## 2. Matriz de fuentes, re-tierizada para uso no comercial a nivel de sistema

Verificado en vivo (HTTP real) salvo donde se indica. Fecha: 2026-09-04.

### Tier A — sin fricción legal ni técnica

| País | Fuente | Acceso | Licencia | Rezago | Nota |
|---|---|---|---|---|---|
| **Colombia** | SFC vía Socrata `datos.gov.co` | REST JSON/CSV **sin token**; 99 datasets | **CC BY-SA 4.0**, redistribución explícita | **~2 meses** | Verificado: `x586-r5d2` da solvencia por entidad, `max(fecha)=2026-06-30`. Agregar a sistema es trivial |
| **Brasil** | BCB IFDATA `olinda.bcb.gov.br` | **OData v4, sin key, sin rate limit** | **ODbL** | **~6 meses** ⚠️ | Verificado: R5 devuelve por `CodInst` Capital Principal, Nível I, Razão de Alavancagem, Exposição Total. Ruptura Res. CMN 4966: R8 vacío desde 202503, no empalmable con R16 |
| **Chile** | CMF APIBEST + 2.087 XLSX | API con key (10/min · 3.000/mes); catálogo CSV de 34.051 series sin credencial | **Autorización propia, no CC** — corregido 2026-09-04, ver ⚠️ abajo | **~28 días — el mejor** | Los XLSX traen la fórmula en códigos contables en la fila 2: diccionario de datos incluido |
| **SECMCA / EMFA** | `secmca-api.secmca.org` | **REST `/public/v1/` sin auth**, verificado | No localizada ⚠️ | Mensual | **8 países: CRI, SLV, GTM, HND, NIC, DOM, PAN, BLZ.** Crédito, depósitos MN/ME, tasas, encaje, agregados — **armonizados**. **No prudencial** |

El share-alike de Colombia y ODbL de Brasil **dejan de ser problema** bajo la premisa de divulgación: un boletín gratuito con atribución cumple ambas.

⚠️ **Corrección sobre Chile (2026-09-04).** Este documento afirmaba que APIBEST es CC BY 4.0 "incluso con fines comerciales", actualizado el 2026-08-06. **No se verifica.** Los únicos términos publicados de la API son `https://api.cmfchile.cl/terminos-de-uso.html`, **actualizados el 01/06/2019**, y dicen otra cosa:

> "Los derechos de autor sobre la API CMF Bancos son propiedad de esta institución. Todos los derechos reservados […] El uso y/o publicación de los contenidos entregados a través de la API CMF Bancos **está autorizado**, con la consecuente incorporación de una mención a la fuente más un enlace a la página principal del sitio web CMF Bancos (`www.sbif.cl`)."

O sea: no es una licencia CC, no dice nada sobre uso comercial, y el permiso es una autorización propia de la CMF condicionada a atribución **con enlace**. Para un boletín gratuito con atribución **alcanza y sobra** — autoriza expresamente publicar. Pero la cadena de licencia debe decir lo que la fuente dice: registrarla como CC BY 4.0 sería declarar un permiso que nadie concedió. Se buscó si APIBEST tenía términos propios: su host raíz da 404 y solo responde la ruta del catálogo CSV. No hay otro documento.

### Tier B — viable, licencia ausente (zona gris de bajo riesgo en uso no comercial con atribución)

| País | Acceso | Nivel sistema | Nota |
|---|---|---|---|
| **Perú** | `intranet2.sbs.gob.pe`, patrón determinístico, **343 archivos dic-1998 → jul-2026** | `B-2401` trae los 6 prudenciales con fila de total | **28 años de historia — el archivo más profundo de la región.** `www.` tiene doble WAF, `intranet2.` no. Los `.XLS` modernos son XLSX disfrazados (magic `PK`) |
| **El Salvador** | `ssf.gob.sv/descargas/balances/xls/...`, sin auth ni bot-block | **Columna "Sistema Bancario" explícita** | Mensual desde ene-2003, rezago ~1 mes. **La ingesta más barata del relevamiento** |
| **Bolivia** | ASFI, **URLs construibles** `.../{subsistema}/{YYYY}/{MM}/{YYYYMM}_{PREFIJO}_{Reporte}.zip` | Fila "total sistema" | **Diccionario oficial de fórmulas publicado.** Términos → 404 en producción. Quiebre 2014 (Ley 393). Un mes inexistente da 404 con HTML: validar Content-Type |
| **Paraguay** | BCP, 1 XLSX = panel tidy 246.547 filas, 2016-2026 | Agregable | Morosidad **por actividad económica**, capital N1/N2, previsiones, ROA/ROE, liquidez. WAF bloquea no-navegadores; URL con GUID que cambia cada mes. Palanca: Ley 5282/14 |
| **Nicaragua** | **API REST viva:** `https://www.siboif.gob.ni/rest/estadisticas` (la doc la publica en `http://`, que da timeout) | Sí | Mensual, rezago ~1 mes. Drupal 7 legacy |
| **Costa Rica** | SUGEF, solo ASPX | Suficiencia patrimonial | **CC BY 4.0** — mejor licencia de CA. Pero **trimestral** y frágil: una herramienta estaba caída durante la prueba |
| **Argentina** | Anexo XLSX del BCRA (2,65 MB, 9 hojas, verificado con openpyxl) | **Por grupos homogéneos — justo esta granularidad** | **Se reabre** bajo premisa no comercial. Pero: el BCRA **no publica RPC ni exigencia de capital por entidad**; el capital adequacy solo vía FSI del FMI, trimestral y a nivel sistema |

### Tier C — bloqueados aunque el boletín sea gratuito

| Plaza | Bloqueo |
|---|---|
| **Panamá** | `aviso_legal.pdf` prohíbe "reproducción, redistribución, transmisión, circulación, adaptación" — **no depende del precio**. Técnicamente el mejor Excel de la región (~60 bancos, mensual, URLs predecibles). Tramitar autorización escrita antes de tocarlo |
| **Uruguay** | "Queda estrictamente prohibida la redistribución, recirculación, retrasmisión" — ídem. Y es **el mejor contenido del relevamiento**: LCR por moneda, NSFR, rezago 14 días. Doblemente frustrante |

### Tier D — fuente inservible o inaccesible

| Plaza | Problema |
|---|---|
| **México** | CNBV **sin API estadística** (la "API CNBV" es Open Banking regulado, art. 76 Ley Fintech). CKAN de `datos.gob.mx` **404**; licencia Libre Uso MX **404** → apertura sin respaldo verificable. Catálogos en web parts de SharePoint (JS). TLS con intermedio faltante. El aviso de retrasos por modernización de SITI WEB **sigue publicado en sep-2026** |
| **Guatemala** | `sib.gob.gt` → **403 Cloudflare**. No se pudo confirmar ni qué publica. Mayor hueco del relevamiento |
| **Ecuador** | WAF 403 contra IPs de datacenter **+ cadena TLS incompleta** (falta intermedio Sectigo) → rompe cualquier ingestor estándar. 2009-2026 detrás de `admin-ajax.php` con IDs opacos. **Cero URLs verificadas en vivo** |
| **Honduras** | Dataset CKAN "Estados Financieros" **sin actualizar desde 2023-11-30**. CDD es SPA. Auditados solo PDF |
| **Jamaica** | Se reabre legalmente (prohibición es de uso comercial), pero **Prudential Indicators congelados en dic-2019**. Inservible por contenido |
| **Trinidad y Tobago** | Data Centre es widget JS sin descargas. **FSI cortado en mar-2024** por cambio de metodología. `data.gov.tt` en mantenimiento |
| **CCSBSO** | No publica estadísticas propias. Es un directorio de enlaces a cada superintendencia. Valor: mapa de fuentes |

---

## 3. Alcance recomendado para la edición 1

**RD (por entidad) + Colombia, Brasil, Chile (por sistema) + SECMCA/EMFA como capa de crédito, depósitos y tasas armonizadas para 8 países.**

Justificación: los tres países son los únicos con licencia abierta *y* acceso programático *y* rezago compatible con cadencia trimestral. SECMCA agrega ocho plazas de contexto monetario armonizado con un solo conector y sin autenticación, cubriendo Centroamérica sin necesidad de tocar supervisores bloqueados. RD aporta el diferenciador: nadie más lo mira con esta profundidad.

Expansión posterior por costo marginal creciente: El Salvador y Perú (Excel determinístico, sin bot-block en la ruta correcta) → Bolivia y Nicaragua → Paraguay (exige navegador headless, pero es la mejor cobertura analítica) → Costa Rica y Argentina.

**No perseguir:** Panamá y Uruguay sin autorización escrita previa; Guatemala, Ecuador, México y Honduras hasta que cambie la fuente.

---

## 4. Ruta de implementación

**Fase 0 — Deuda de casa (1-2 semanas). Bloqueante: se publica dato de la SB a una lista de correo.**

1. Registrar la SB dominicana en `shared/data/licenses.py` con `terminos_url` y `verificado_el` reales; hacer que los cinco clientes de banca hereden de `SourceClient` para que el gate AST los alcance.
2. Registrar las licencias de las fuentes nuevas: Colombia (CC BY-SA 4.0), Brasil (ODbL), Chile (autorización propia con atribución y enlace — **no** CC), SECMCA (pendiente de localizar). **El registro de cada una viaja con su conector**, no antes: el gate exige que la cadena esté declarada por código vivo, y una entrada sin conector queda muerta y rompe CI (comprobado 2026-09-04). Cargar el texto exacto de atribución en el campo `atribucion` — Colombia exige citar fuente **y fecha de actualización**.
3. Implementar `variable_signals()` en `banking_score`, que hoy degrada a `_product_level_fallback`. Sin desglose por variable no hay forma honesta de reportar cobertura, y el boletín es precisamente donde eso se vuelve público.

**Fase 1 — Almacén regional a nivel sistema (2-3 semanas)**

4. Tabla nueva `country_banking_aggregate` — `(iso3, period_end, metric, value, source, license, fetched_at)`. Deliberadamente **separada** de `BankingData`: distinto sujeto, distinta semántica, y así el motor de RD queda intacto y el test de no-regresión es trivial.
5. Cuatro conectores: Colombia (Socrata), Brasil (OData), Chile (XLSX + catálogo), SECMCA (REST público). Cada uno declara licencia antes del primer fetch.
6. Registrar en cada métrica la **norma contable de origen**, no solo el valor. Es lo que impide que alguien construya después un ranking por accidente.

**Fase 2 — Generador del boletín (2-3 semanas)**

7. Plantilla de edición: §1 RD en profundidad · §2 sistemas nacionales por trayectoria · §3 crédito/tasas armonizados vía EMFA · §4 nota metodológica fija.
8. **Guard de no-comparabilidad:** un test que falle si una misma visualización mezcla métricas no armonizadas de más de un país. La disciplina editorial no sobrevive a la edición número doce; el test sí.
9. Nota metodológica permanente al pie, generada desde el registro de procedencia (`shared/registry/provenance.py`), nunca escrita a mano.

**Fase 3 — Distribución**

10. Decidir plataforma de envío y cumplimiento de datos de suscriptores (si hay suscriptores en la UE, aplica GDPR: base legal, opt-in verificable, baja en un clic).
11. Cadencia: publicar con el rezago de la fuente más lenta del bloque, o declarar por país el corte usado. **No mezclar cortes sin decirlo.** Brasil a 6 meses es el que fija el techo si se quiere un corte único.

---

## 5. Lo que este documento NO verificó

- Guatemala: nada, por el 403 de Cloudflare. Hueco mayor.
- Ecuador: ninguna URL en vivo; todo proviene de snapshots de Wayback 2026.
- CNBV México: ninguna URL de descarga directa mapeada.
- Términos de uso de SECMCA — **pendiente y necesario antes de la Fase 1**, ya que es el conector que más plazas carga.
- Contenido del XLSX de metadata del ESB de SECMCA (se confirmó que el enlace existe, no se abrió).
- Si el Data Centre de T&T expone JSON reutilizable.
- Contenido del reporte CAMELS de SUGEF y del bucket "Indicadores Financieros" de SIBOIF.
- Si Panamá publica ROA/ROE desagregados (solo se vieron agregados) — irrelevante mientras siga bloqueado.
- **Ninguna licencia fue revisada por abogado.** Las lecturas de §0.2 y §2 son inferencia sobre el texto publicado.
