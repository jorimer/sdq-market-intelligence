# Respuesta a VotoSignal — granularidad sub-nacional

**De:** SDQ Market Intelligence · **Para:** VotoSignal
**Fecha:** 2026-08-09 · **Ref.:** nota del 2026-08-09 sobre alcance de la llave y granularidad

---

## Resumen

Su diagnóstico central es correcto y lo compartimos: una serie nacional no puede
reordenar candidatos dentro de una contienda, y ninguna mejora de esa serie lo cambia.
El `+0` exacto que midieron es aritmética, no ruido.

Tres precisiones sobre las causas —una de ellas los afecta más de lo que suponen— y una
corrección sobre el IRMP que reabre RF-30.

Del lado nuestro ya está construido lo que dependía de nosotros. Queda una verificación
en producción y una decisión de publicación que no son suyas.

---

## 1. El 404 de `social_dev` no era alcance de llave

`GET /api/data/v1/quality/{sector}` y el catálogo de la Data API recorren el registro de
verticales-producto de la plataforma. **`social_dev` no figuraba en ese registro.** No
era que su llave no lo alcanzara: no había nada que alcanzar, y ninguna llave con ningún
alcance habría devuelto otra cosa que 404.

Lo cerramos: el eje social quedó cableado como producto, con su contrato completo. La
consecuencia práctica para ustedes es que su pedido #4 —procedencia por variable— queda
resuelto por diseño y no como un campo agregado a mano: `/quality/social_dev` devuelve,
por variable, su estado (real o rúbrica declarada), su fuente, su cadencia y su fracción
real.

## 2. Seis de las nueve variables que pidieron ya eran constantes nacionales

Esto es lo más importante de esta respuesta y no aparecía en su nota.

De las nueve variables del IDM, solo tres tienen desagregación geográfica real. Las otras
seis son series nacionales que el índice aplica **idénticas a las diez regiones**:

| Variable | Granularidad real |
|---|---|
| `poverty_rate` / `poverty_extreme` | 10 regiones de desarrollo, 2000-2024 |
| `secondary_coverage` | 10 regiones, 2010-2024 |
| `literacy_rate` | 10 regiones, solo 2022 (ENHOGAR) |
| `life_expectancy`, `child_mortality`, `schooling_years`, `income_per_capita`, `informality_rate`, `financial_inclusion` | **nacional** |

Sus prioridades 2 y 3 —informalidad, ingreso per cápita, inclusión financiera,
escolaridad— caen todas en la segunda fila. Si se las hubiéramos servido "por región",
habrían recibido una constante con etiqueta geográfica: el mismo `+0` que ya midieron
con el IRMP, por la misma razón.

Lo dejamos declarado en la doctrina del eje, de modo que el alcance (`national` frente a
`per_subject`) viaja ahora en la señal por variable. Sin ese campo, "dato real" se leía
como "diferencia entre demarcaciones", que es falso para seis de nueve.

**Por eso la Data API publica de este eje únicamente las series con desagregación
geográfica.** Servir las nacionales sería repetir el problema que esta nota vino a
resolver.

## 3. Cobertura educativa por provincia: confirmado y hecho

Su lectura del parser era exacta. El cuadro de la ONE se titula *tasa neta de cobertura
por nivel, según región y provincia*, y nuestro parser conservaba solo las filas
`Región …` y descartaba las provinciales. Ya no: ambos niveles se persisten, distinguidos
por su nivel geográfico, sin fuente nueva.

**Con una advertencia que les corresponde conocer.** Al reverificar contra la fuente,
`www.one.gob.do` respondió **403** a nuestro cliente y también al navegador: el portal
está detrás de un desafío anti-bot. El CDN de descargas (`descargas.one.gob.do`) sigue
abierto —de ahí bajamos y parseamos sin problema el CSV de pobreza: 500 filas, 10
regiones, 2000-2024—, pero el archivo de cobertura vive en el portal. El cambio de parser
está escrito y probado contra la estructura real del cuadro; **la corrida contra el
archivo vivo queda pendiente de ejecutarse desde producción**, cuya salida a internet es
distinta de la nuestra. Lo decimos porque es también un riesgo latente para las
sincronizaciones que ya dependen de ese portal.

## 4. Pobreza provincial: no existe en esa fuente — pero encontramos otra

El CSV de pobreza de la ONE es regional por construcción: la muestra de la ENCFT está
diseñada para estimar por región de desarrollo, no por provincia. Lo verificamos
bajándolo y parseándolo: diez regiones, nada más. **La pobreza monetaria provincial no se
obtiene de ahí, y ningún cambio de nuestro lado la produce.**

Hay otra fuente, y ya está integrada. El **SIUBEN** publica en `datos.gob.do` cinco
tableros por provincia con historia trimestral. Los descargamos, parseamos y cargamos:
**3.456 observaciones, 32 provincias, 2017-2026.**

| Serie | Provincias | Cobertura |
|---|---|---|
| Analfabetismo de jefes/as de hogar | 32 | 2018-Q1 … 2026-Q2 |
| Hacinamiento (extremo + moderado) | 32 | 2017-Q1 … 2026-Q2 |
| Vivienda precaria (cuartería, barracón, otra) | 32 | 2017-Q1 … 2026-Q2 |
| Menores sin acta de nacimiento | 32 | 2017-Q1 … 2026-Q2 |
| ICV-1 en personas con discapacidad | 32 | 2022-Q2 … 2026-Q2 |

Discrimina, y con holgura: en 2024-Q4 el analfabetismo de jefes/as va de **36,3% en Elías
Piña a 7,5% en el Distrito Nacional**. Esa es la varianza transversal que su modelo
necesita y que diez valores para 210 escaños no podían dar.

**Tres advertencias que deben viajar con el dato, y viajan en el propio código:**

1. **El universo no es la población general.** El SIUBEN levanta el padrón de
   focalización de hogares pobres y vulnerables. "36,3% en Elías Piña" es la composición
   del padrón registrado en esa provincia, **no la tasa de analfabetismo de la
   provincia**. Es un indicador estructural legítimo y comparable entre demarcaciones;
   no es una tasa poblacional. Por eso los códigos llevan el prefijo `siuben_` y el
   sufijo `_share`: el caveat está en el nombre, no en una nota al pie.
2. **El tablero de ICV cubre solo a las personas con discapacidad del padrón** —un
   subconjunto del subconjunto—. Su código lo dice.
3. **2016 no existe.** Las series arrancan en 2017 y 2018. De sus tres ciclos, cubrimos
   2020 y 2024; el de 2016 no lo tenemos y no vemos de dónde sacarlo con esta fuente.

## 5. IRMP sub-nacional: su sospecha es incorrecta, y en una dirección útil

Asumieron que la dimensión `events` se alimenta de GDELT DOC, cuyas consultas son por
país. No es así: usamos **BigQuery sobre el GKG particionado**, y el código de país sale
del *offset 2* del campo `V2Locations`. **El offset 3 de ese mismo campo es el código
ADM1 — la provincia.** La granularidad siempre estuvo en la misma tabla; la consulta la
descartaba.

De modo que la respuesta se parte en dos:

- **La dimensión `political` no puede ser sub-nacional.** Se compone de los indicadores
  WGI del Banco Mundial más la proximidad electoral: país por construcción. Lo mismo vale
  para macro, externa y regulatoria (cuentas nacionales, rating soberano, WGI).
- **La dimensión `events` sí puede.** Está escrita: consulta por ADM1, mapeo de código a
  provincia derivado del nombre de lugar dominante —no de una tabla FIPS de memoria— y
  control de costo por partición.

**Pero no la publicamos todavía, y la razón les importa.** El geocodificado de GDELT se
concentra en Santo Domingo y Santiago; las provincias pequeñas devuelven muestras
diminutas donde una sola nota mueve el promedio de tono. Una señal así reparte dos
valores útiles y treinta cifras de ruido. Por eso la implementación incluye una **prueba
de volumen** que informa cuántas provincias superan un mínimo de registros, y por debajo
de ese mínimo la observación viaja con valor nulo y su razón —nunca un cero, que ustedes
leerían como "sin tensión". Esa prueba se corre contra BigQuery, cuyas credenciales están
en producción; **el veredicto de publicar o no depende de su resultado.**

Nuestra recomendación: **no cierren RF-30 como "no".** Ciérrenlo como *la dimensión
política no es sub-nacionalizable; la de eventos está pendiente de una prueba de volumen
cuyo resultado les comunicaremos.*

---

## Estado y qué falta

**Hecho y verificado:**

- Padrón canónico de las 32 provincias, con su mapeo a las 10 regiones de desarrollo.
- Conector SIUBEN: 3.456 observaciones descargadas, parseadas y validadas contra la
  fuente viva.
- Parser de la ONE conservando el desglose provincial.
- `social_dev` cableado como producto: series, score IDM y procedencia por variable con
  alcance declarado.
- Consulta GDELT por ADM1 con regla de volumen y nulo honesto.

**Pendiente, y no depende de ustedes:**

1. Correr la sincronización de cobertura educativa desde producción, para confirmar el
   desglose provincial contra el archivo vivo (bloqueado desde nuestra red por el desafío
   anti-bot del portal de la ONE).
2. Correr la prueba de volumen de GDELT por ADM1 y decidir si esa señal se publica.
3. Activar el eje social en la Data API. La exposición está condicionada, por diseño, a
   que el sector esté publicado y su readiness supere el umbral; es una decisión del
   dueño de la plataforma, no un cambio de código.

**Una nota sobre lo que no les vamos a mandar:** las seis variables nacionales del IDM no
se publicarán como series por demarcación. Si en algún momento les resultan útiles como
control temporal a nivel país, se sirven como lo que son —series nacionales— y así se
etiquetan.

---

**Contacto técnico:** el detalle de cada medición citada vive en el repositorio de la
plataforma; las cifras de este documento son reproducibles contra las fuentes públicas
citadas.
