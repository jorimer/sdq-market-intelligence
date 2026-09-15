# Pendientes de fuentes — eje social y granularidad sub-nacional

Estado al **2026-08-10**. Un lugar para consultar antes de proponer una fuente: cada
punto dice **qué falta**, **qué ya se probó** (para no repetirlo) y **qué lo destrabaría**.

---

## 1. Cobertura educativa por provincia — la más cerca de cerrar

**Falta:** cargarla. El conector está construido y verificado contra la fuente viva —294
filas: 32 provincias y 10 regiones, años lectivos 2019-2025.

**Por qué no entró:** el tablero Power BI del MINERD (SIIE) limita por tasa y devuelve
`400 Bad Request` sin aviso. **No es bloqueo de red**: le pasó también a una máquina de
trabajo minutos después de funcionar, y producción sí alcanza ese host.

**Ya probado:** anuarios en PDF del SIIE (publican **conteos, ninguna tasa** — cero
apariciones de «tasa neta» o «tasa bruta»); planilla de la ONE (portal 403).

**Lo destraba:** que ceda el límite. Cuando ocurra, producción puede traerla **en vivo**;
la instantánea comiteada es solo respaldo. Correr
`python scripts/refresh_social_snapshots.py minerd` y luego `one-social-sync`.

## 2. Esperanza de vida sub-nacional — no existe

**Ya probado y agotado:** libro de Salud del SISDOM (**0 de 108 hojas**), portal de datos
abiertos, MSP (6 conjuntos, ninguno de mortalidad), DIGEPI/SINAVE (hosts que no
resuelven).

**Único camino conocido:** el **Anuario de Estadísticas Vitales** de la ONE. Su portal
está en 403.

## 3. Mortalidad infantil como variable VIVA

**Hoy:** publicada como serie provincial (`endesa_child_mortality`, 32 provincias) pero
**congelada en 2002 y 2007** — rondas ENDESA, no serie anual. El IDM sigue con la serie
anual del Banco Mundial, nacional.

**Lo destraba, y la cuenta es factible:** el Anuario de Estadísticas Vitales trae
**defunciones por provincia**, y los **nacimientos por provincia ya están en el portal de
datos abiertos**. Con los dos se calcula la tasa. Depende otra vez de la ONE.

**Ojo:** el SISDOM también la abre por «Región de salud» (I-VIII) — **otra geografía**, 9
regiones sanitarias que no calzan con las 10 de desarrollo.

## 4. Inclusión financiera — NO se buscó

**Hoy:** nacional (cajeros por 100 mil adultos, Banco Mundial), y además un *proxy de
acceso*, no inclusión efectiva.

**Estado honesto: nunca se buscó una fuente sub-nacional.** Es la única de las tres
constantes nacionales restantes sin búsqueda hecha.

**Dónde mirar primero:** la Superintendencia de Bancos publica puntos de acceso
(sucursales, subagentes, cajeros) y suele abrirlos por provincia — y ya tenemos conector
al ecosistema SIB.

## 5. Alfabetización — un solo corte

**Hoy:** `literacy_rate` por región, **solo 2022**, extraída con IA del PDF del
ENHOGAR-2022.

**Pista viva:** el **SINID de la ONE** (`appsinid.one.gob.do`, que **sí responde** y cuyo
`robots.txt` permite) lista «Tasa de analfabetismo… **según región**» como indicador con
serie.

**El obstáculo:** el portal expone la **ficha técnica** del indicador, pero la tabla vive
en `dwh.one.gob.do:9704` — resuelve por DNS pero el puerto no responde desde afuera, y no
hay nada en 80/443. Está publicado en el HTML y cerrado en la red.

## 6. El año 2016

Las series provinciales del SIUBEN arrancan en **2017/2018**. De los tres ciclos que
VotoSignal necesita (2016, 2020, 2024), **cubren dos**. No se encontró fuente provincial
para 2016.

## 7. SIUBEN — vive de una instantánea

Producción **no alcanza `siuben.gob.do`** (`ConnectTimeout` desde Railway; el
descubrimiento por el portal de datos abiertos sí llega, así que es ese host y no la red).
Funciona con instantánea comiteada, y su procedencia lo declara (`snapshot:FECHA`).

**Conviene revisar** si el bloqueo es permanente: una instantánea envejece, y el dato es
trimestral.

## 8. GDELT por provincia — falta correr la prueba

La operación **`gdelt-adm1-volume-test`** está registrada y agendada, pero **nunca se
corrió**. Decide si la señal de eventos provincial se publica: el geocodificado se
concentra en Santo Domingo y Santiago, y por debajo del volumen mínimo la observación
viaja con nulo y su razón.

**Es lo que falta para cerrar RF-30 de VotoSignal con un número en vez de una promesa.**

---

## Fuentes que SÍ funcionan (para no volver a buscarlas)

| fuente | qué da | acceso |
|---|---|---|
| **SISDOM (MEPyD)** | ingreso per cápita y escolaridad **por región**, mortalidad infantil por provincia | listado + descarga, ids **descubiertos** |
| **MINERD (SIIE)** | cobertura educativa por región **y provincia** | Power BI publish-to-web (limita por tasa) |
| **SIUBEN** | 5 series × 32 provincias, trimestral | datos abiertos + `siuben.gob.do` (prod no alcanza) |
| **BCRD** | informalidad (ENCFT), fuente primaria | CDN público, sin token |
| **ONE — solo el CDN** | pobreza por región 2000-2024 | `descargas.one.gob.do` (nunca se rompió) |

**Regla que salió de esta semana:** cuando una fuente de la ONE falle, **no buscar otro
host para la ONE — preguntar quién PRODUCE el dato.** La ONE republicaba cuatro de las
series que usábamos; ir al productor dejó a las cuatro mejor de lo que estaban.
