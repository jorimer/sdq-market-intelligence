# Encargo de investigación · Panel de transacciones bancarias RD/Caribe

## Qué necesitamos, exactamente

Transacciones de **control** sobre entidades bancarias de República Dominicana y el Caribe, de
la última década, con **las dos puntas verificables**:

1. **PRECIO pagado** — el numerador.
2. **VALOR LIBRO (patrimonio contable) de la entidad adquirida al momento de la operación** —
   el denominador.

**Un precio sin valor libro no sirve.** Es el hallazgo central del relevamiento hecho hasta
ahora: el mercado divulga el numerador y calla el denominador, y un múltiplo necesita las dos.
Cualquier caso que llegue con precio y sin patrimonio queda fuera del panel.

**Meta: 8 casos.** Hoy hay 1.

## Por qué importa

Alimenta el eje de valuación de entidades. Sin ocho casos, el eje publica su modelo y declara
que **no está contrastado contra precios pagados**, y la vista de fusiones y adquisiciones
queda cerrada. Con ocho, se abre y el eje puede afirmar que sus valores predicen precios.

---

## Lo que YA está hecho — no repetir

### El único caso cerrado

| | |
|---|---|
| operación | Scotiabank compra **Banco Dominicano del Progreso** |
| año | 2018 (acuerdo anunciado el 14 de agosto) |
| precio | **US$330 millones** |
| valor libro | **RD$ 6.482.978.970** (patrimonio publicado por la Superintendencia, 2018-08) |
| tipo de cambio | RD$ 49,7276/US$ (venta, promedio mensual BCRD, 2018-08) |
| **P/B** | **2,53×** (2,48×–2,58× según el mes de referencia) |

Cerró porque **el denominador salió de nuestro propio histórico de la SIB**, no de una
divulgación del comprador. Verificación cruzada: la prensa publica los activos del Progreso a
junio 2018 en RD$56.580,76 millones y nuestra serie da 56.580.760.422 — idénticos al peso.

### Descartadas, con motivo — no volver sobre ellas

- **Republic Financial Holdings / 7 filiales de Scotiabank en el Caribe (2019)** — divulga
  US$123 M, de los cuales US$98 M son *prima sobre el valor neto* de ocho países y US$25 M el
  total por Scotiabank Anguilla. **Falta el valor neto.** ← pero ver la Pista A, que puede
  resolverlo.
- **BHD + León (2014)** — fusión entre iguales: no hay comprador, no hay precio.
- **Activo Dominicana / Banaci (2018)** — sin monto. Se publicaron activos consolidados
  (RD$1.895 M), que **no son un precio**.
- **Profesional / Bancrédito (2003)** — sin monto, y operación de rescate en plena crisis.
- **Progreso / Metropolitano (2000)** — 96 % de las acciones, sin monto, y anterior a la
  reestructuración del sistema.
- **Baninter / BanComercio (1996)** — sin monto; Baninter colapsó en 2003.
- **BHD con Fiduciario (2000), Sabadell (1999), Popular de Puerto Rico (2001)** — alianzas y
  absorciones sin monto. Las alianzas además son participaciones minoritarias, que se pagan
  con otro múltiplo que una compra de control.

Fuente del barrido: <https://eldinero.com.do/72134/fusiones-y-adquisiciones-en-la-banca-dominicana/>

---

## Las pistas a perseguir, en orden de probabilidad

### Pista A — la memoria anual del COMPRADOR (la más fuerte)

**La NIIF 3 obliga al adquirente a divulgar, en sus estados auditados, el valor razonable de
los activos netos identificables adquiridos y el goodwill reconocido.** O sea que el
denominador que el comunicado de prensa calla **está en las notas de la memoria del
comprador**, por obligación contable.

Empezar por:

- **Republic Financial Holdings, memoria 2020** (cierre fiscal septiembre 2020; la operación
  cerró el 31-oct-2019, así que la nota de combinación de negocios cae en el ejercicio 2020, y
  posiblemente también en el de 2019):
  - <https://republictt.com/pdfs/annual-reports/RFHL-AR-2020.pdf>
  - <https://republictt.com/pdfs/annual-reports/RFHL-annual-report-2019.pdf>
  - índice: <https://republictt.com/publications/annual-reports>
  - **Buscar la nota titulada** «Business combination», «Acquisition of subsidiaries» o
    «Acquisitions». Transcribir: *consideration transferred*, *fair value of net assets
    acquired* (o *net identifiable assets*), *goodwill*, y el desglose por país si lo hay.
  - Si da el desglose por país, **cada país puede ser una observación distinta del panel**:
    de un solo documento podrían salir hasta siete casos, que es casi la meta entera.

- **Scotiabank (Bank of Nova Scotia), memoria 2018 y 2019** — como vendedor no divulga el
  libro del Progreso, pero sus notas de *divestitures* pueden dar la ganancia por venta y los
  activos netos dados de baja, que permiten despejarlo.

### Pista B — reguladores y bolsa

- **Junta Monetaria / Superintendencia de Bancos de RD**: toda fusión o adquisición bancaria
  requiere autorización, y las resoluciones a veces incluyen el monto y el patrimonio de las
  entidades. Buscar en <https://www.sb.gob.do> y en las resoluciones de la Junta Monetaria del
  Banco Central.
- **SIMV (Superintendencia del Mercado de Valores de RD)**: prospectos de emisión y hechos
  relevantes de bancos con deuda pública listada. Nota: `simv.gob.do` devuelve 403 a peticiones
  automatizadas — hay que entrar con navegador.
- **Otras bolsas del Caribe**: Trinidad (TTSE), Jamaica (JSE), Barbados (BSE). Los emisores
  listados publican hechos relevantes con montos.

### Pista C — el resto del Caribe

Operaciones que no entraron al barrido dominicano y conviene mirar:

- **CIBC FirstCaribbean** — venta de participación mayoritaria a GNB Financial (Colombia),
  anunciada 2019: se anunció con precio y con múltiplo implícito.
- **JMMB Group** (Jamaica) — adquisiciones de bancos en RD y Trinidad.
- **Sagicor Financial** — adquisición por Alignvest (2019), con precio público.
- **Banco Múltiple Caribe / Banesco / Bancamérica / Bellbank** — cambios de control recientes
  en RD; verificar si hubo operación con monto.
- **NCB Financial Group** (Jamaica) — compra de Clarien Bank (Bermuda) y de Guardian Holdings.

---

## Formato de entrega

Por cada caso encontrado, **una ficha con las dos puntas y su fuente por separado**:

```
operación:      <comprador> compra <adquirida>
país:           <ISO>
año:            <AAAA>  ·  fecha del acuerdo/cierre: <AAAA-MM-DD>
PRECIO:         <monto> <moneda>
  fuente:       <URL o documento + página/nota>
  ¿qué % de las acciones compró?  <si no está claro, decirlo>
VALOR LIBRO:    <monto> <moneda>  ·  al corte <AAAA-MM>
  fuente:       <URL o documento + página/nota>
tipo de cambio (si las monedas difieren): <valor> · fuente
CAVEATS:        <lo que el caso NO permite afirmar>
```

**Reglas que no se negocian:**

1. **Las dos fuentes van por separado.** Un múltiplo con el precio público y el libro estimado
   no es verificable, y una nota de procedencia única lo escondería.
2. **No se estima el denominador.** Si el valor libro no está publicado, el caso se descarta y
   se anota el motivo. Despejarlo desde los activos totales, desde el goodwill sin el precio, o
   desde un supuesto de capitalización **no cuenta**.
3. **Activos totales ≠ precio ≠ patrimonio.** Confundir tamaño con precio es el error que este
   panel existe para no cometer.
4. **Fusiones entre iguales quedan fuera.** No hay comprador, así que no hay precio de control.
5. **Participaciones minoritarias quedan fuera**, o se marcan como tales: se pagan con otro
   múltiplo que una compra de control.
6. **Operaciones de rescate en crisis quedan marcadas**: un múltiplo pagado por una entidad
   intervenida no informa sobre una compra en marcha normal.
7. **Anterior a 2010, marcar.** El sistema dominicano se reestructuró tras la crisis de 2003.

## Lo que también sirve, aunque no cierre un caso

Un **«no está publicado» verificado** vale: si se revisó la memoria del comprador y la nota de
combinación de negocios no desglosa el país, eso se anota y se cierra esa vía. El panel corto
con motivos es un resultado; el panel corto sin motivos se lee como falta de trabajo.
