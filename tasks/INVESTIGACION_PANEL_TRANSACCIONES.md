# Encargo de investigación · Panel de transacciones bancarias RD/Caribe

> **Sexta actualización. DOS VÍAS ABIERTAS SE CERRARON, Y EL CONTADOR NO SE MOVIÓ.**
> El panel pasó de once casos verificables a **trece**: entraron Intercommercial Bank
> (Trinidad y Tobago, 2013) y Scotiabank Belize (2021), los dos con nota auditada y con las
> dos puntas de la misma tabla. Los comparables siguen en **ocho**.
>
> **Eso no es un fracaso del relevamiento: es el gate haciendo su trabajo.** Las dos notas
> publican activos netos a VALOR RAZONABLE de la NIIF 3 y ninguna publica el patrimonio en
> libros del vendedor. Suman expediente y no suman tabla, porque la tabla es contra la que
> valúa el modelo.
>
> Y apareció una dirección que nadie fue a buscar: **cuatro operaciones relevadas se pagaron
> por debajo del valor razonable de lo que se entregaba**. Ver «El hallazgo que no se
> buscaba».
>
> Sigue valiendo lo de la actualización anterior: abrir la vista de fusiones y adquisiciones
> **no es** validar el modelo. Leer «Lo que el panel SÍ y NO demuestra».

## El hallazgo que no se buscaba: la COMPRA VENTAJOSA

Cuatro de las operaciones relevadas se pagaron **por debajo del valor razonable de los activos
netos** que el comprador reconoció. Dos están en el panel y dos en las vías abiertas:

| operación | año | múltiplo sobre valor razonable | lo que declara la nota |
|---|---|---:|---|
| JMMB / Intercommercial Bank (TT) | 2013 | **0,83×** | goodwill negativo J$361.657 miles |
| CIHL / Scotiabank Belize | 2021 | **0,71×** | ganancia por compra ventajosa US$8,5 M |
| Sagicor / RBC Royal Bank Jamaica | 2014 | — | goodwill negativo US$29.051 miles |
| NCBFG / Clarien Group (Bermuda) | 2017 | — | ganancia por compra ventajosa J$4.392.149 miles |

Cuando un comprador reconoce una ganancia por compra ventajosa está diciendo, en su propia
contabilidad auditada, que el vendedor aceptó **menos** que el valor razonable de lo que
entregaba. Cuatro casos en la misma dirección, dentro de una ola de desinversión de bancos
internacionales que se retiraban del Caribe, dicen algo sobre de qué lado estaba la urgencia.

**Qué NO es esto.** Cuatro observaciones no son una serie, y ninguna es dominicana. No se
puede concluir que el mercado dominicano pague por debajo del valor razonable — de hecho los
casos dominicanos del panel van al revés: Progreso a 2,53× y Bellbank a 1,82× sobre LIBRO.
Es una dirección relevada, no un resultado, y se publica como tal.

## Qué necesitamos, exactamente

Transacciones de **control** sobre entidades bancarias de República Dominicana y el Caribe con
**las dos puntas verificables Y sobre base CONTABLE**:

1. **PRECIO pagado** — el numerador.
2. **PATRIMONIO CONTABLE de la entidad adquirida** al momento de la operación, tal como lo
   tenía en SU balance — el denominador.

**Meta: 8 casos sobre base contable. Hoy hay 8.** Cumplida.

## Por qué importa

Alimenta el eje de valuación de entidades, que valúa contra **patrimonio contable**.

## Lo que el panel SÍ y NO demuestra

**SÍ:** a cuánto sobre valor libro se ha pagado un banco del Caribe. Ocho casos, rango
**0,77× a 2,73×**, mediana **1,73×**. Eso es evidencia de mercado y abre la vista de fusiones
y adquisiciones.

**NO:** que este modelo acierte. Contrastarlo exigiría valuar **cada adquirida** con el Excess
Return a la fecha de su operación y comparar ese valor con el precio — y para eso hace falta
la historia de ROE y patrimonio de esa entidad. La tenemos donde ingerimos el balance por
entidad, que hoy es **República Dominicana**: **3 de las 8**. Las otras cinco son de Barbados,
Caimán, Puerto Rico y Trinidad.

**Confundir las dos cosas sería el error más caro del eje**, porque sería cierto en la forma y
falso en el fondo. El eje sigue declarando que sus valores **no están contrastados contra
precios pagados**, y lo computa: `panel.transacciones.contraste_del_modelo()`.

> **Esto reordena la prioridad.** El octavo caso ya no es lo que más mueve la aguja. Lo que
> más la mueve es **cobertura de balances por entidad fuera de República Dominicana** —o
> transacciones dominicanas nuevas—, porque es lo que convierte un panel de comparables en un
> contraste del modelo.

---

## La base del denominador: el hallazgo que cierra la discusión

La NIIF 3 y su equivalente US-GAAP obligan al comprador a divulgar el valor razonable de los
activos netos adquiridos. **No es patrimonio contable del vendedor**: es lo que el comprador
reconoce.

**Y la distancia entre las dos bases no tiene signo fijo.** La misma compradora —OFG Bancorp—,
en el mismo mercado, publicó las dos columnas dos veces:

| | BBVA PR (2012) | Scotiabank PR (2019) |
|---|---:|---:|
| patrimonio contable | US$650,617 M | US$381,032 M |
| activos netos a valor razonable | US$438,680 M | US$438,100 M |
| **el valor razonable está** | **32,6 % POR DEBAJO** | **15,0 % POR ENCIMA** |
| por qué | marcas de cartera (−US$118,9 M) y el goodwill heredado que desaparece | intangible de depósitos reconocido en la compra |

**Cuarenta y ocho puntos de amplitud, en las tablas de un mismo comprador.** Mientras las dos
cuñas hubieran tenido el mismo signo, se podía proponer un ajuste fijo entre bases. Con signos
opuestos, ese ajuste no existe.

Y en el caso de Scotiabank PR la base decide el signo del múltiplo: **1,13× sobre libro y
0,98× sobre valor razonable**.

**Consecuencia para el relevamiento:**

- Base **contable** → cuenta para la meta de 8.
- Base **valor razonable** → se registra con la base declarada y **NO cuenta**.
- Un caso con **las dos columnas** es el más valioso que existe. Si una tabla las trae, copiar
  ambas.
- **Toda ficha declara su base.** Sin ese campo el dato no se puede usar.

---

## Lo que YA está hecho — no repetir

### Los OCHO casos COMPARABLES (base contable)

| | comprador | país·año | % | precio | denominador | corte | **P/B** |
|---|---|---|---|---|---|---|---|
| BBVA PR | OFG Bancorp | PR·2012 | 100 % | US$500,0 M | US$650,617 M | 2012-12 | **0,77×** |
| Scotiabank PR | OFG Bancorp | PR·2019 | 100 % | US$430,437 M | US$381,032 M | 2019-12 | **1,13×** |
| Butterfield Barbados | First Citizens | BB·2012 | 100 % | US$45,0 M | US$34,995 M | 2011-12 | **1,29×** |
| Banco Río | JMMB | DO·2015 | 90 % | US$2,15 M | RD$65.568.455 | 2015-06 | **1,64×** |
| Bellbank | JMMB | DO·2022 | 100 % | ≈US$7,2 M | RD$217.851.372 | 2022-06 | **1,82×** |
| Cayman National | RFHL | KY·2019 | 74,99 % | US$198,474 M | CI$117.389.759 | 2018-09 | **1,88×** |
| Progreso | Scotiabank | DO·2018 | n/d | US$330 M | RD$6.482.978.970 | 2018-08 | **2,53×** |
| RBTT | RBC | TT·2008 | 100 % | TT$13.756,7 M | TT$5.039,3 M | 2008-03 | **2,73×** |

**Rango 0,77×–2,73×, mediana 1,73×.** Que haya casos **a los dos lados de 1,0×** importa: un
panel de puras primas estaría sesgado por selección.

Los dos más frágiles, y por qué igual entran:

- **RBTT (2008)** es la más vieja —anterior a la crisis financiera global— y el 40 % de la
  consideración se pagó en acciones de RBC. Marcada.
- **Butterfield Barbados** trae el denominador de las cuentas **consolidadas del vendedor**,
  no del patrimonio individual que la entidad declaraba a su regulador; incluye US$3,1 M de
  intangibles (8,8 % del denominador) de la compra original. Sobre libro individual sería
  ~1,41×. El **perímetro** sí coincide con el del precio —la entidad entera—, que es la
  condición para entrar; lo que difiere es la medición, y se declara.

### Las CUATRO fuentes de denominador que funcionaron

1. **El regulador dominicano.** SIMBAD y la serie histórica de la SIB publican el patrimonio
   por entidad. Cerró Progreso, Banco Río y Bellbank. **Para RD el denominador ya lo tenemos:
   solo falta el precio y la fecha.**
2. **Los Call Reports del FDIC** (`api.fdic.gov/banks/financials`). Todo banco de Puerto Rico
   presenta patrimonio trimestral por entidad, con su fecha de baja. Es el equivalente exacto
   de SIMBAD para PR, y sirvió de verificación cruzada del caso BBVA.
3. **Los estados auditados de la propia adquirida**, cuando cotizaba. Cerró Cayman National y
   RBTT: el denominador no depende de lo que el comprador decida contar. **Es la mejor
   estructura que puede tener un caso.**
4. **La nota de operaciones discontinuadas del VENDEDOR.** Cuando un grupo vende una filial,
   la norma le exige publicar los activos y pasivos del grupo enajenado. Cerró Butterfield
   Barbados: la resta está en la nota, no hay que despejarla de la ganancia.

Y una cuarta que da **las dos bases a la vez**: una tabla de asignación del precio de compra
de un emisor SEC que incluya la columna **«Book Value»**. Es una elección de presentación, no
una exigencia — OFG la publica, First BanCorp no.

### Verificaciones cruzadas que cerraron

- **Progreso**: la prensa publica activos por RD$56.580,76 M a junio 2018; nuestra serie da
  56.580.760.422 — idénticos al peso.
- **Bellbank**: estados auditados RD$217.294.194 a dic-2021 contra SIMBAD RD$217.294.150 —
  **44 pesos** de diferencia sobre 217 millones.
- **BBVA PR**: el 10-K da US$650,617 M para la tenedora a dic-2012; el Call Report del FDIC da
  US$616,643 M para el banco a sep-2012 — 5,5 % de diferencia, consistente con que la tenedora
  incluye la casa de valores y con los dos meses y medio de distancia.
- **Cayman National**: US$6,25 por acción contra un valor libro por acción de US$3,33 da el
  mismo 1,88× que el cálculo agregado.
- **RBTT**: el precio existe de dos formas —TT$40 por acción y US$2.200 M agregados— y
  concuerdan a TT$6,2530 por dólar, dentro del rango real de 2008. Las dos vías dan 2,73×.
- **Butterfield Barbados**: US$45 M de proceeds menos US$34,995 M de activos netos = US$10,0 M,
  contra la ganancia **neta** reportada de US$7,24 M. La diferencia de US$2,8 M son costos y
  reciclaje de conversión — el orden de magnitud esperable.
- **Banco Río**: la serie mensual de la SB corrobora la fecha por su cuenta — el patrimonio
  cae sin interrupción hasta noviembre 2015 y salta en diciembre, o sea que la capitalización
  llega después del cierre de julio 2015.

### Los TRES casos VERIFICABLES pero NO comparables (valor razonable)

| | comprador · año | precio | activos netos a VR | múltiplo |
|---|---|---:|---:|---:|
| Caribe Oriental + St. Maarten | RFHL · 2019 | TT$377.283 mil | TT$205.742 mil | 1,83× |
| Islas Vírgenes Británicas | RFHL · 2020 | TT$689.605 mil | TT$457.611 mil | 1,51× |
| Santander BanCorp | First BanCorp · 2020 | US$1.277,626 M | US$1.271,323 M | 1,005× |

Las tres aritméticas cierran exactas. El primero agrega siete territorios en una sola cifra:
es **una** observación, no siete. **La nota 34 de RFHL 2020 ya se leyó entera: no volver.**

### Descartadas, con motivo — no volver sobre ellas

- **CIBC FirstCaribbean / GNB (2019)** — US$797 M por el 66,73 % y **no se consumó**: los
  reguladores no aprobaron.
- **Bancamérica (2022)** — **disolución**, no compra. En una licitación de rescate gana quien
  pide *menos* aporte del fondo de contingencia.
- **RBC / Caribe Oriental (2021)** — once **sucursales** sin precio; no hay entidad con
  patrimonio publicado que le corresponda.
- **Sagicor / Alignvest (2019)** — tiene las dos puntas y queda fuera igual: no es banco.
- **Banco Caribe / BID Invest (2023)** — préstamo, no adquisición.
- **BHD + León (2014)** — fusión entre iguales: no hay comprador.
- **Activo / Banaci (2018)** — sin monto; se publicaron activos consolidados, que no son un
  precio.
- **Profesional / Bancrédito (2003)**, **Progreso / Metropolitano (2000)**, **Baninter /
  BanComercio (1996)**, **alianzas de BHD (1999-2001)** — sin monto, y anteriores a la
  reestructuración del sistema.
- **Banesco RD · Lafise · Ademi · Promérica y el resto del padrón** — entradas de novo,
  conversiones de licencia y aumentos de capital. No son compras.
- **ANSA Merchant Bank / Bank of Baroda (Trinidad) (2021)** — compra del **100 %** de las
  acciones, aprobada por el banco central y consumada, y **sin precio divulgado**. Falta el
  numerador: si apareciera, el caso quedaría a un paso.

---

## Lo que sigue, por lo que MUEVE la aguja

### 1. Cobertura de balances fuera de RD — lo que convierte comparables en contraste

Es la prioridad nueva, y no está en el conteo del panel. Con el balance por entidad de un
país más, sus adquiridas se vuelven valuables con nuestro propio motor y el contraste del
modelo deja de ser imposible. En orden de rendimiento:

- **Puerto Rico: ya está resuelto y no lo estamos usando.** Los Call Reports del FDIC dan
  patrimonio, activos y resultados trimestrales por entidad, con API pública y sin
  credencial. Cubre las dos adquiridas de PR del panel.
- **Trinidad (CBTT), Barbados (CBB), Bermudas (BMA), Caimán (CIMA)**: verificar si publican
  estados por entidad y con qué histórico.

### 2. Transacciones dominicanas nuevas — suman al panel Y al contraste

**Resoluciones de la Junta Monetaria, año por año, 2016→2026.** De cada una que autorice
venta o traspaso de acciones hace falta **la entidad, la fecha de cierre, el porcentaje y el
monto**. El denominador ya lo tenemos.

### 3. Casos con el precio verificado y el denominador pendiente

| operación | precio verificado | qué falta |
|---|---|---|
| **JMMB / Intercommercial Bank** (Trinidad, 2013) | US$8,75 M por el 50 % restante | patrimonio al corte 2013 (CBTT). Es compra **por etapas** |
| **CIHL / Scotiabank Belize** (abr-2021) | **US$20 M** (final, no los US$30,5 M del anuncio) | patrimonio (memoria 2021 de CIHL, o Banco Central de Belice) |
| **NCB / Clarien** (Bermuda, 2017) | J$4,15 mm ≈ US$33,04 M por el 50,1 % | primero, **qué fue la operación**: NCBFG *suscribió* el 50,1 %, y un aporte de capital que entra a la sociedad no es un precio pagado a un vendedor |

### 4. Afinamientos de casos que ya están

- **Butterfield Barbados** — el patrimonio **individual** ante el Central Bank of Barbados.
  Movería el múltiplo de 1,29× a ~1,41×. No bloquea; afina.
- **Bellbank** — el segundo denominador: el PPA estaba «not yet finalized» a dic-2022, y la
  memoria de JMMB Group a marzo 2023 debería traerlo.
- **Sagicor / RBC Jamaica (2014)** — las tres cifras aparecen y **cierran entre sí**
  (consideración US$84,378 M, activos netos US$113,429 M, goodwill negativo US$29,051 M) y
  reconcilian con los J$9.500 M de la prensa, pero vienen de un resumen y no del estado
  auditado. **Hay que abrir la nota.** Aun abierta es valor razonable: solo contaría si la
  nota publica además el libro.
- **Santander BanCorp** — para pasarlo a base contable hace falta el patrimonio consolidado de
  la **tenedora** (FR Y-9C ante la Reserva Federal). El Call Report solo cubre el banco.
- **RFHL Caribe Oriental** — el desglose por país convertiría una observación en varias.

## Formato de entrega

```
operación:      <comprador> compra <adquirida>
país:           <ISO>
año:            <AAAA>  ·  fecha del acuerdo/cierre: <AAAA-MM-DD>
% de acciones:  <si no está claro, decirlo>

PRECIO:         <monto> <moneda>   ← el REGISTRADO al cierre, no el del titular
  fuente:       <URL o documento + página/nota>

DENOMINADOR:    <monto> <moneda>  ·  al corte <AAAA-MM>
  BASE:         contable  |  valor_razonable                ← OBLIGATORIO
  ALCANCE:      banco  |  sociedad tenedora  |  grupo        ← OBLIGATORIO
  fuente:       <URL o documento + página/nota>

SEGUNDO DENOMINADOR (solo si la MISMA tabla publica las dos columnas):
  <monto> <moneda>  ·  BASE: <la otra>  ·  fuente: <la misma tabla>

tipo de cambio (si difieren las monedas): <valor> · fuente · MES del corte
CAVEATS:        <lo que el caso NO permite afirmar>
```

**Reglas que no se negocian:**

1. **La BASE es obligatoria.** Sin ella el caso no se puede usar.
2. **El ALCANCE es obligatorio.** El precio suele comprar la tenedora y el regulador suele
   publicar el banco. Cruzarlos da un número plausible y equivocado: en Santander PR daría
   1,26×.
3. **Las dos fuentes van por separado.** Un múltiplo con el precio público y el denominador
   estimado no es verificable.
4. **No se estima el denominador.** Ni desde los activos, ni desde el goodwill, ni desde un
   múltiplo implícito de prensa, ni despejándolo de la ganancia del vendedor. Si la nota
   permite derivarlo, se anota como **derivación** y no como dato.
5. **El PORCENTAJE comprado es obligatorio**, y el múltiplo se homogeneiza. Un precio por el
   90 % contra un patrimonio del 100 % da ~10 % bajo, y sale plausible.
6. **El tipo de cambio es el del MES DEL CORTE**, y se nombra. Una conversión de prensa puede
   estar hecha a otra fecha: pasó con Bellbank. Si es una **paridad fija** —el dólar caimán—,
   decirlo: no tiene mes.
7. **El precio que vale es el REGISTRADO al cierre.** En OFG el titular era US$550 M y la
   consideración US$430 M, por un dividendo pre-cierre. En Belize el anuncio decía hasta
   US$30,5 M y se pagaron US$20 M.
8. **Un aporte de capital NO es un precio.** Si el dinero entró a la sociedad en vez de ir a
   un vendedor, no es una transacción de control.
9. **Activos totales ≠ precio ≠ patrimonio.**
10. **Una operación que no se consumó no es una transacción.** Verificar que cerró.
11. **Una disolución o liquidación no es una compra.**
12. **Fusiones entre iguales quedan fuera**; **minoritarias**, fuera o marcadas.
13. **Rescates en crisis se marcan**, y **anterior a 2010 también**.
14. **Una cifra agregada de varios países es UNA observación.**
15. **Una compra POR ETAPAS** trae el precio de un tramo: homogeneizar contra ese tramo.
16. **Ojo con los nombres.** La SB publica las entidades bajo su nombre ACTUAL hacia atrás en
    el tiempo: Banco Río aparece como «JMMB» desde 2013. No concluir «no está» sin buscar
    también por el nombre posterior.
17. **Un mismo comprador, un mismo nombre.** OFG Bancorp se llamaba Oriental Financial Group
    antes de 2013; si se lo nombra distinto en dos fichas, agrupar por comprador lo parte en
    dos.

## Lo que también sirve, aunque no cierre un caso

Un **«no está publicado» verificado** vale: si se revisó la memoria del comprador y la nota no
desglosa, se anota y se cierra esa vía. El panel corto con motivos es un resultado; el panel
corto sin motivos se lee como falta de trabajo.
