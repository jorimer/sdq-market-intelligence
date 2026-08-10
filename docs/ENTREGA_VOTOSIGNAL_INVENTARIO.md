# Entrega a VotoSignal — inventario contra lo pedido

**De:** SDQ Market Intelligence · **Para:** VotoSignal
**Fecha:** 2026-08-10 · **Ref.:** nota del 2026-08-09 sobre granularidad sub-nacional

---

## Resumen en tres líneas

Lo que pidieron era granularidad sub-nacional. Se entregan **cinco series por las 32
provincias** y **cuatro por las 10 regiones de desarrollo**, más el desglose de
procedencia por variable que pidieron en el punto 4. De sus prioridades, **una queda
pendiente por un límite del emisor** —cobertura educativa provincial— y **una no existe
con esa apertura** —esperanza de vida—. El IRMP sub-nacional tiene respuesta, y no es la
que ustedes suponían.

---

## 1. El 404 de `social_dev`: resuelto, y no era de la llave

No era alcance: el eje no figuraba en el registro de productos que recorren la Data API
y `/quality`. Ninguna llave, con ningún alcance, habría devuelto otra cosa.

Quedó cableado como producto. **Su llave no necesita cambios**: su acceso ya alcanza el
nivel que la Data API exige, igual que con `macro` y `esg`.

## 2. Lo que van a encontrar, por prioridad de ustedes

### Prioridad 1

| variable | apertura | cobertura | estado |
|---|---|---|---|
| `poverty_rate` · `poverty_extreme` | 10 regiones | 2000-2024 | **disponible** |
| `secondary_coverage` | 10 regiones | 2010-2024 | **disponible** |
| `secondary_coverage` **por provincia** | 32 provincias | 2019-2025 | **pendiente** (ver §4) |

### Prioridad 2 — las dos dejaron de ser constantes nacionales

| variable | antes | ahora |
|---|---|---|
| `income_per_capita` | un número para las 10 regiones, y era un *proxy* de ingreso por hora | **ingreso familiar mensual por persona, por región**, 2000-2024 |
| `informality_rate` | ONE (republicación) | BCRD, fuente primaria, 2015-2025 — sigue **nacional** |

### Prioridad 3

| variable | apertura | cobertura |
|---|---|---|
| `schooling_years` | **10 regiones** (era nacional) | 2000-2024 |
| `literacy_rate` | 10 regiones | **solo 2022** (ENHOGAR) |
| `financial_inclusion` | nacional | anual |

### Series provinciales adicionales — no las pidieron y sirven

Del padrón SIUBEN, **32 provincias, trimestral 2017-2026** (3.456 observaciones):

- `siuben_illiteracy_head_share` — analfabetismo de jefes/as de hogar
- `siuben_overcrowding_share` — hacinamiento
- `siuben_precarious_housing_share` — vivienda precaria
- `siuben_unregistered_minors_share` — **menores sin acta de nacimiento**
- `siuben_disability_icv1_share` — ICV-1 en personas con discapacidad

La cuarta puede interesarles particularmente: es **cobertura de registro civil por
provincia**, que se relaciona con el padrón electoral.

Y una más, con advertencia: `endesa_child_mortality`, mortalidad infantil por las 32
provincias, **rondas ENDESA de 2002 y 2007**. Discrimina fuerte (Bahoruco 45 por mil,
Espaillat 11) pero **no es una serie anual**: son dos cortes. Para sus ciclos no sirve;
para caracterizar una demarcación, sí.

**El caveat del SIUBEN viaja en el propio dato y les pedimos que lo respeten:** su
universo es el **padrón de focalización de hogares pobres y vulnerables**, no la
población general. «36,3% en Elías Piña» es la composición del padrón registrado allí,
**no la tasa de analfabetismo de la provincia**. Es un indicador estructural comparable
entre demarcaciones; no es una tasa poblacional.

## 3. Sus años

| | 2016 | 2020 | 2024 |
|---|:--:|:--:|:--:|
| Pobreza · ingreso · escolaridad · cobertura regional | ✅ | ✅ | ✅ |
| Series provinciales SIUBEN | ❌ | ✅ | ✅ |
| Alfabetización | ❌ | ❌ | ❌ *(solo 2022)* |

El SIUBEN arranca en 2017/2018. **De sus tres ciclos, cubre dos.**

## 4. Lo que no llega, y por qué

**Cobertura educativa por provincia — construida, verificada, no cargada.** El indicador
lo produce el MINERD y lo publica en un tablero cuya API anónima limita por tasa y
devuelve 400 sin aviso. Tenemos el conector probado contra la fuente (294 filas: 32
provincias y 10 regiones, 2019-2025) y una captura pendiente en cuanto el emisor ceda.
**No es una limitación de diseño ni de acceso: es de ritmo.** Les avisamos cuando entre.

**Esperanza de vida sub-nacional — no existe.** Se buscó y se agotó: cero apariciones en
el sistema de indicadores sociales del MEPyD, nada en el portal de datos abiertos. La
única vía sería el Anuario de Estadísticas Vitales de la ONE, cuyo portal está hoy
inaccesible.

**Mortalidad infantil — existe por provincia pero congelada en 2007** (ver §2). Se
publica como serie, no como variable viva.

## 5. Procedencia por variable — su punto 4

`GET /api/data/v1/quality/social_dev` devuelve, **por variable**: estado (real o rúbrica
declarada), fuente, cadencia, fracción real y **alcance**.

Ese último campo es el que responde a su preocupación de fondo. Declara cuáles se miden
**por demarcación** y cuáles son **nacionales aplicadas por igual a todas**. Antes de su
nota ese campo no existía para este eje, y sin él «dato real» se leía como «diferencia
entre demarcaciones» — falso para cinco de nueve variables.

Hoy quedan **tres** de alcance nacional: esperanza de vida, mortalidad infantil e
inclusión financiera. Cada una con su razón anotada.

## 6. IRMP sub-nacional — su punto 5

Su sospecha era razonable y resultó incorrecta, en una dirección útil.

No usamos GDELT DOC para la dimensión de eventos, sino BigQuery sobre el GKG. El país
sale de un campo y **la provincia sale del campo contiguo**: la granularidad siempre
estuvo en la misma tabla.

- **La dimensión `political` no puede ser sub-nacional.** Es WGI del Banco Mundial más
  proximidad electoral: país por construcción. Lo mismo macro, externa y regulatoria.
- **La de `events` sí.** Está implementada, con una **prueba de volumen** que aún no
  hemos corrido.

Esa prueba decide si se publica. El geocodificado de GDELT se concentra en Santo Domingo
y Santiago; si solo dos provincias superan el mínimo, la señal repartiría dos valores y
treinta nulos. Por debajo del umbral la observación viaja con **nulo y su razón** —nunca
un cero, que ustedes leerían como «sin tensión».

**Recomendación:** no cierren RF-30 como «no». Ciérrenlo como *la dimensión política no
es sub-nacionalizable; la de eventos está pendiente de una prueba de volumen cuyo
resultado les comunicaremos.*

---

## Nota de método

Cuatro de estas series cambiaron de fuente esta semana. En los cuatro casos la ONE no
producía el dato: lo republicaba. Ir al productor —BCRD, MINERD, MEPyD— dejó cada serie
**mejor** que antes: fuente primaria, más cobertura temporal y, en ingreso y escolaridad,
apertura por región donde había una constante nacional.

Las series con desagregación geográfica se publican; las nacionales de este eje no se
sirven como si fueran regionales. Servir una constante con etiqueta geográfica es
exactamente el problema que su nota vino a señalar.
