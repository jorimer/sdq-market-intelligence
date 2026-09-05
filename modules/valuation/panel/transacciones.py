"""Panel de transacciones bancarias RD/Caribe. Investigación de campo, no ingesta.

**Por qué existe.** Una valuación se valida contra lo que alguien PAGÓ. Sin este panel, el eje
publica un modelo con sus supuestos y su sensibilidad, y declara que el contraste no existe.
Con ocho casos verificables, la vista de M&A se abre y `ESTADO_BACKTEST` deja de decir
`dato_pendiente`.

**El relevamiento, y lo que midió.** La banca dominicana registra **nueve** fusiones y
adquisiciones documentadas desde 1996, y **una sola divulgó precio en su momento**: Scotiabank
por Banco Dominicano del Progreso, US$330 millones (2018). Las otras ocho —BHD con León,
Profesional con Bancrédito, Progreso con Metropolitano, Activo con Banaci, y las alianzas de
BHD con Sabadell, Popular de Puerto Rico y Fiduciario— se anunciaron sin monto.

**Ése es el hallazgo del relevamiento**: no es que las transacciones no existan, es que el
mercado casi nunca divulga el denominador. Un múltiplo necesita las dos puntas.

**Y el camino que sí funciona: el denominador es NUESTRO.** El patrimonio de cualquier banco
dominicano está en el histórico de la Superintendencia que esta plataforma ya ingiere, y en
SIMBAD, su Superset público. No depende de que el comprador lo publique. Con el tipo de
cambio del BCRD del mismo mes, el múltiplo sale auditable de punta a punta — así cerraron el
Progreso (2018) y Bellbank (2022). Para una operación dominicana, **lo único que falta buscar
es el precio**.

**La NIIF 3 también devuelve un denominador, y no es el mismo.** Obliga al comprador a
publicar los activos netos identificables a VALOR RAZONABLE, que es lo que él reconoce y no
lo que el vendedor tenía en libros. Los dos casos de Republic Financial Holdings entran así.
Cuánto se separan las dos bases dejó de ser un argumento: la tabla del 10-Q de OFG Bancorp
publica las dos columnas sobre el mismo balance, y el valor razonable está **15,0 % por
encima** del libro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

#: Casos con precio sobre valor libro verificable que el gate exige para abrir la vista M&A.
MINIMO_DE_CASOS = 8

#: La BASE del denominador. No es un matiz: decide si dos múltiplos se pueden poner en la
#: misma tabla.
#:
#: * `contable` — patrimonio del balance del vendedor, tal como lo publicó su regulador. Es
#:   la base del modelo de Excess Return, que valúa contra patrimonio contable.
#: * `valor_razonable` — activos netos identificables a valor razonable de la NIIF 3, que es
#:   lo que el COMPRADOR reconoce. Puede incluir intangibles que **no existían** en el
#:   balance del vendedor: en la compra del Caribe Oriental, el intangible de depósitos es el
#:   62 % del denominador publicado. Un múltiplo sobre esa base NO es un P/B y ponerlo al
#:   lado de uno contable ordena lo que no es comparable.
BASE_CONTABLE = "contable"
BASE_VALOR_RAZONABLE = "valor_razonable"


@dataclass(frozen=True)
class Transaccion:
    """Una operación con su múltiplo y, sobre todo, con de dónde salió cada punta."""

    anio: int
    comprador: str
    adquirida: str
    pais: str
    #: Precio en la moneda en que se anunció, y su moneda.
    precio: Optional[float]
    moneda_precio: str
    #: Valor libro en RD$ (o la moneda declarada) al corte de referencia.
    valor_libro: Optional[float]
    moneda_libro: str
    periodo_libro: Optional[str]
    pb: Optional[float]
    #: Procedencia de CADA punta, por separado: un múltiplo con el precio público y el libro
    #: inventado no es verificable, y agregarlas en una sola nota lo escondería.
    fuente_precio: str
    fuente_libro: str
    #: Sobre qué base se computó el múltiplo. Ver `BASE_CONTABLE` / `BASE_VALOR_RAZONABLE`.
    base: str = BASE_CONTABLE
    #: El SEGUNDO denominador, cuando la misma tabla auditada publica los dos. Es raro y es
    #: lo más valioso que puede traer un caso: con las dos cifras del mismo balance, la
    #: distancia entre bases se MIDE en vez de suponerse.
    valor_razonable: Optional[float] = None
    #: Lo que el caso NO permite afirmar. Se declara con el dato, no en un anexo.
    caveats: Tuple[str, ...] = ()

    @property
    def cuna_de_base_pct(self) -> Optional[float]:
        """Cuánto se separa el valor razonable del libro, EN ESTE caso, en porcentaje.

        Se computa, no se transcribe. Es la magnitud que decide si mezclar las dos bases en
        una tabla sería un matiz o un error: mientras solo se pueda argumentar, cualquiera
        puede suponerla chica.
        """
        if self.valor_razonable is None or not self.valor_libro:
            return None
        return (self.valor_razonable / self.valor_libro - 1.0) * 100.0

    @property
    def verificable(self) -> bool:
        """Las DOS puntas presentes. Un precio sin libro no es un múltiplo."""
        return self.pb is not None and self.precio is not None and self.valor_libro is not None

    @property
    def comparable(self) -> bool:
        """¿Entra a la misma tabla que el resto?

        Solo la base CONTABLE, porque es contra la que valúa el modelo de Excess Return.
        Un múltiplo sobre valor razonable de la NIIF 3 es verificable y NO es un P/B: mide
        el precio contra lo que el comprador reconoce, no contra lo que el vendedor tenía en
        libros. Los dos son datos; mezclarlos es el error.
        """
        return self.verificable and self.base == BASE_CONTABLE


#: Lo relevado. Cada entrada se agrega con sus dos fuentes o no se agrega.
PANEL: Tuple[Transaccion, ...] = (
    Transaccion(
        anio=2018, comprador="Scotiabank", adquirida="Banco Dominicano del Progreso",
        pais="DO",
        precio=330_000_000.0, moneda_precio="USD",
        valor_libro=6_482_978_970.0, moneda_libro="DOP", periodo_libro="2018-08",
        pb=2.531,
        fuente_precio=("Anuncio del acuerdo, agosto 2018 — US$330 millones. Reportado por "
                       "prensa dominicana (Hoy, El Dinero). Es el monto del ACUERDO: la "
                       "consideración final podría haber diferido."),
        fuente_libro=("Patrimonio publicado por la Superintendencia de Bancos, serie "
                      "histórica que esta plataforma ingiere (Banco Dominicano del Progreso, "
                      "1984-12 → 2020-05). Convertido con el tipo de cambio de venta promedio "
                      "del BCRD de 2018-08 (RD$ 49,7276/US$). Las dos puntas son auditables "
                      "sin depender de que el comprador publique el denominador.\n\n"
                      "VERIFICACIÓN CRUZADA: el artículo de El Dinero que documenta la "
                      "operación publica los activos del Progreso a junio 2018 en "
                      "RD$ 56.580,76 millones. Nuestra serie histórica de la SIB da "
                      "56.580.760.422 para ese mismo mes — idénticos al peso. La fuente del "
                      "denominador no es la misma que la del artículo, y coinciden."),
        caveats=(
            "No está confirmado públicamente si los US$330 M corresponden al 100 % de las "
            "acciones; si fue una participación menor, el múltiplo implícito sería MAYOR.",
            "El múltiplo es sensible al mes de referencia del patrimonio: 2,58× con el cierre "
            "de junio, 2,53× con agosto, 2,48× con diciembre. Se publica el del mes del "
            "acuerdo y se muestra el rango.",
            "El patrimonio de la SIB es contable, que es la base correcta para un P/B — no "
            "el patrimonio técnico regulatorio.",
        ),
    ),

    Transaccion(
        anio=2019, comprador="Republic Financial Holdings",
        adquirida=("Operaciones de Scotiabank en el Caribe Oriental y St. Maarten "
                   "(St. Maarten, Anguila, Dominica, Granada, San Cristóbal y Nieves, "
                   "Santa Lucía, San Vicente y las Granadinas)"),
        pais="LCA/VCT/KNA/DMA/GRD/AIA/SXM",
        precio=377_283_000.0, moneda_precio="TTD",
        valor_libro=205_742_000.0, moneda_libro="TTD", periodo_libro="2019-11",
        pb=1.834, base=BASE_VALOR_RAZONABLE,
        fuente_precio=("Memoria anual 2020 de Republic Financial Holdings, nota 34 "
                       "«Business combinations», apartado (a). Purchase consideration "
                       "transferred: TT$377.283 miles, liquidado en efectivo."),
        fuente_libro=("Misma nota: «Total identifiable net assets at fair value» TT$205.742 "
                      "miles, con goodwill de TT$171.541 miles. La aritmética CIERRA exacta "
                      "—205.742 + 171.541 = 377.283—, que es la validación interna de que "
                      "las tres cifras son consistentes.\n\n"
                      "Es el hallazgo del camino de la NIIF 3: el comunicado de prensa daba "
                      "el precio y la prima sobre el valor neto, pero NO el valor neto. La "
                      "norma obliga al comprador a publicarlo en sus estados auditados, y "
                      "ahí estaba."),
        caveats=(
            "LA BASE NO ES VALOR LIBRO. Son activos netos identificables a VALOR RAZONABLE, "
            "que incluyen TT$127.166 miles de intangible de depósitos reconocido EN la "
            "adquisición —no existía en el balance del vendedor— y TT$8.600 miles de revalúo "
            "de inmuebles sobre un valor en libros de TT$30.000 miles.",
            "El intangible solo es el 62 % del denominador publicado. Quitándolo junto con el "
            "revalúo, el libro aproximado del vendedor sería TT$69.976 miles y el múltiplo "
            "sobre esa base ~5,4x. Es una DERIVACIÓN, no un dato: la nota no publica el libro "
            "del vendedor y puede haber otras marcas no desglosadas. Por eso no se publica "
            "como P/B.",
            "Es UNA observación, no siete: la nota agrega los siete territorios en una sola "
            "cifra y no los desglosa por país.",
        ),
    ),
    Transaccion(
        anio=2020, comprador="Republic Financial Holdings",
        adquirida="Scotiabank British Virgin Islands Limited (100 % de las acciones)",
        pais="VGB",
        precio=689_605_000.0, moneda_precio="TTD",
        valor_libro=457_611_000.0, moneda_libro="TTD", periodo_libro="2020-06",
        pb=1.507, base=BASE_VALOR_RAZONABLE,
        fuente_precio=("Memoria anual 2020 de Republic Financial Holdings, nota 34, apartado "
                       "(b). Purchase consideration transferred: TT$689.605 miles, en "
                       "efectivo, por el 100 % de las acciones."),
        fuente_libro=("Misma nota: «Total identifiable net assets at fair value» TT$457.611 "
                      "miles, goodwill provisional TT$231.994 miles. La aritmética cierra "
                      "exacta.\n\n"
                      "A diferencia del caso del Caribe Oriental, su desglose de activos NO "
                      "tiene línea de intangibles —caja, préstamos y otros—, así que acá el "
                      "valor razonable está MUCHO más cerca del libro."),
        caveats=(
            "La base sigue siendo valor razonable de la NIIF 3, no valor libro del vendedor, "
            "aunque sin intangible reconocido la distancia entre las dos bases es menor.",
            "El goodwill es PROVISIONAL: la propia nota dice que el valor razonable estaba "
            "pendiente de valuación final y sujeto a ajuste hasta junio de 2021.",
            "Es la única de las tres con el porcentaje de acciones CONFIRMADO (100 %).",
        ),
    ),

    Transaccion(
        anio=2019, comprador="OFG Bancorp (Oriental Bank)",
        adquirida="Scotiabank de Puerto Rico (100 % de las acciones)",
        pais="PR",
        precio=430_437_000.0, moneda_precio="USD",
        valor_libro=381_032_000.0, moneda_libro="USD", periodo_libro="2019-12",
        pb=1.130, valor_razonable=438_100_000.0,
        fuente_precio=("Form 10-Q de OFG Bancorp, 3T2020 (SEC), tabla de Business "
                       "Combinations: consideración remedida US$430.437 miles. El precio de "
                       "TITULAR fue US$550 millones (comunicado del 26-jun-2019 y Form 10-K "
                       "2019, nota 2); la consideración registrada bajó tras el dividendo "
                       "pre-cierre de US$500 millones que Scotiabank giró a su matriz. Se "
                       "publica la registrada, que es la que se pagó por lo que quedó."),
        fuente_libro=("Misma tabla del 10-Q, columna «Book Value»: activos identificables "
                      "US$3.512.724 miles menos pasivos asumidos US$3.131.692 miles = "
                      "US$381.032 miles de patrimonio contable.\n\n"
                      "ES EL CASO MÁS VALIOSO DEL PANEL, y no por el múltiplo. La misma "
                      "tabla auditada publica los DOS denominadores en columnas contiguas "
                      "—«Book Value» y «Fair Value As Remeasured»— sobre el mismo balance y "
                      "a la misma fecha. Es la única medición directa que tenemos de cuánto "
                      "se separan las dos bases: el valor razonable está 15,0 % por encima "
                      "del libro. Hasta acá la distancia se argumentaba; con este caso se "
                      "mide.\n\n"
                      "Las dos puntas salen de documentos SEC distintos: el precio del "
                      "comunicado y el 10-K, el denominador de la tabla PPA del 10-Q."),
        caveats=(
            "US-GAAP (ASC 805), no NIIF: Puerto Rico es territorio de EE.UU. La lógica de la "
            "asignación del precio de compra es equivalente y el marco NO lo es, así que al "
            "lado de un caso dominicano bajo normas de la SB hay que decirlo.",
            "Sobre valor razonable el múltiplo es 0,98x — una compra en condiciones "
            "ventajosas, con una ganancia por compra ventajosa de US$7,65 millones "
            "reconocida por OFG. El mismo precio da 1,13x sobre libro y 0,98x sobre valor "
            "razonable: cruzar el umbral de 1,0x depende ENTERAMENTE de qué base se use.",
            "El 1,15x que publicó la prensa es sobre valor tangible AJUSTADO, una tercera "
            "base distinta de las dos de la tabla. No es la cifra que se publica acá.",
            "La operación de las Islas Vírgenes de EE.UU. fue por separado (prima de "
            "depósitos de US$10 millones) y no entra en estas cifras.",
        ),
    ),
    Transaccion(
        anio=2022, comprador="JMMB Holding Company Limited",
        adquirida="Banco Múltiple Bellbank (100 % del capital suscrito y pagado)",
        pais="DO",
        precio=7_200_000.0, moneda_precio="USD",
        valor_libro=217_851_372.0, moneda_libro="DOP", periodo_libro="2022-06",
        pb=1.818,
        fuente_precio=("Estados financieros de JMMB Group Limited al 31-dic-2022, nota de "
                       "combinación de negocios: la operación dominicana «was acquired at a "
                       "cost of approximately US$7.2 million». El 100 % del capital suscrito "
                       "y pagado, según la Tercera Resolución de la Junta Monetaria del "
                       "23-jun-2022 que autorizó la venta y traspaso."),
        fuente_libro=("Patrimonio publicado por la Superintendencia de Bancos vía SIMBAD, su "
                      "Superset público, para BELLBANK a junio 2022: RD$217.851.372. "
                      "Convertido con el tipo de cambio de venta promedio del BCRD del MISMO "
                      "mes (RD$54,9967/US$), de la serie que esta plataforma ingiere.\n\n"
                      "VERIFICACIÓN CRUZADA: los estados auditados de la propia adquirida "
                      "dan RD$217.294.194 de patrimonio a diciembre 2021, y SIMBAD da "
                      "RD$217.294.150 para ese mismo corte — 44 pesos de diferencia sobre "
                      "217 millones, razón 1,0000002. Dos fuentes independientes sobre el "
                      "mismo balance, y el denominador no depende de que el comprador lo "
                      "publique.\n\n"
                      "Se publica el corte de JUNIO 2022, el mes de la autorización, y no el "
                      "de diciembre 2021 que reportó la prensa: el precio y el denominador "
                      "quedan a la misma fecha, y el tipo de cambio también."),
        caveats=(
            "El precio es «aproximadamente» US$7,2 millones en la propia nota del comprador: "
            "tiene dos cifras significativas y el múltiplo hereda esa precisión.",
            "El múltiplo es sensible al corte: 1,89x con diciembre 2021, 1,84x con marzo "
            "2022, 1,82x con junio 2022. Se publica el del mes de la autorización y se "
            "muestra el rango.",
            "La prensa convirtió el patrimonio de diciembre 2021 a US$3,99 millones, lo que "
            "implica RD$54,46/US$. El tipo de cambio de venta del BCRD de ese mes fue "
            "RD$57,16 — la conversión de prensa NO es la del corte, y sobre el dato del "
            "BCRD el múltiplo de diciembre es 1,89x y no 1,80x.",
            "El valor razonable de los activos netos identificables (PPA) todavía estaba «not "
            "yet finalized» al trimestre de diciembre 2022, así que este caso NO aporta el "
            "segundo denominador.",
            "Bellbank era una entidad chica —RD$1.660 millones de activos—, y en una entidad "
            "chica cualquier ajuste de valor razonable mueve mucho el múltiplo.",
        ),
    ),
)

#: Operaciones RELEVADAS y descartadas del panel, con el motivo. Se listan porque un panel
#: chico sin explicación se lee como falta de trabajo, y esto es lo contrario: es el
#: resultado del trabajo.
DESCARTADAS: Tuple[Tuple[str, str], ...] = (
    ("CIBC FirstCaribbean / GNB Financial, participación mayoritaria (anuncio nov-2019)",
     "US$797 millones por el 66,73 %, y la operación NO SE CONSUMÓ: los reguladores no la "
     "aprobaron. Un precio anunciado que nunca se pagó no es una transacción — no hubo "
     "transferencia de control, así que no hay nada que el panel pueda observar."),
    ("Sagicor Financial / Alignvest (2019)",
     "US$536 millones a ~1,0x libro, con el patrimonio en el propio filing. Las dos puntas "
     "están y el caso NO entra igual: Sagicor es aseguradora y conglomerado financiero, no "
     "banco, y la operación fue una cotización por SPAC más que una compra de control "
     "bancaria. Se anota su múltiplo como referencia regional y no como caso del panel."),
    ("NCB Financial Group / Clarien Group, Bermuda (2017)",
     "Adquisición del 50,1 % —control— completada, y SIN PRECIO divulgado: las partes "
     "evitaron toda cifra. Es el descarte inverso al resto: acá falta el numerador, no el "
     "denominador. El patrimonio de Clarien a junio 2017 (US$107 millones) sí es público, "
     "así que si el precio apareciera el caso cerraría de inmediato."),
    ("Centro Financiero BHD y Grupo Financiero León (diciembre 2014)",
     "Fusión ENTRE IGUALES, no una compra: no hay precio porque no hubo comprador. Aunque se "
     "hubiera publicado una relación de canje, un múltiplo de fusión no informa sobre lo que "
     "un tercero pagaría — que es la pregunta que este panel existe para responder."),
    ("Banco Múltiple Activo Dominicana / Banco de Ahorro y Crédito Banaci (2018)",
     "Adquisición anunciada sin monto. Se publicaron los activos consolidados resultantes "
     "—RD$1.895 millones—, que no son un precio: confundir tamaño con precio es exactamente "
     "el error que un panel de múltiplos existe para no cometer."),
    ("Banco Profesional / Banco Nacional de Crédito, Bancrédito (2003)",
     "Anunciada sin monto, y en un contexto de crisis: aun con precio, un múltiplo de una "
     "operación de rescate no informa sobre una compra en marcha normal."),
    ("Banco Dominicano del Progreso / Banco Metropolitano (2000)",
     "Fusión por absorción del 96 % de las acciones, anunciada sin monto. Y aun con precio, "
     "un múltiplo de hace veinticinco años, anterior a la crisis de 2003 y a la "
     "reestructuración del sistema, no informa sobre el mercado de hoy."),
    ("Banco Intercontinental, Baninter / Banco del Comercio (1996)",
     "Anunciada sin monto. Además, Baninter colapsó en 2003 en la mayor crisis bancaria del "
     "país: un múltiplo pagado por una entidad que después resultó no ser lo que declaraba "
     "no informa sobre el valor de nada."),
    ("BHD / Banco Fiduciario (2000) · BHD con Banco Sabadell (1999) · BHD con Popular "
     "International Bank de Puerto Rico (2001)",
     "Alianzas estratégicas y una fusión por absorción, todas anunciadas sin monto. Las "
     "alianzas además no son transacciones de control: una participación minoritaria se "
     "paga con otro múltiplo que una compra, y mezclarlas contaminaría el panel."),
)


#: Operaciones donde falta UNA cosa concreta y se sabe cuál. No son descartes —un descarte
#: es una vía cerrada— y no son casos: entran al panel el día que se cierre lo que falta.
#: Se listan porque nombrar el obstáculo exacto es lo que hace accionable un relevamiento.
VIAS_ABIERTAS: Tuple[Tuple[str, str], ...] = (
    ("JMMB / Banco de Ahorro y Crédito Río (RD)",
     "Falta LA FECHA, no el denominador. El precio está verificado en los estados auditados "
     "de JMMB Group —US$2,15 millones (J$252,7 millones) por el 90 %— y el patrimonio de la "
     "entidad está en SIMBAD en todos los cortes, porque la SB la publica bajo su nombre "
     "POSTERIOR («JMMB», banco de ahorro y crédito) hacia atrás hasta 2013. Lo que bloquea "
     "es que las fuentes discrepan entre julio de 2014 y julio de 2015, y el múltiplo es "
     "muy sensible: ~1,25x con el corte de junio 2014 y ~1,64x con el de junio 2015. "
     "Fijar la fecha con la resolución de la Junta Monetaria la convierte en caso."),
    ("Republic Financial Holdings / desglose por país del Caribe Oriental",
     "La nota 34 agrega siete territorios en una sola cifra. Si algún estado local o el "
     "regulador de un territorio publicara su parte, esa observación se desdoblaría en "
     "varias. Hoy es una."),
    ("JMMB / Bellbank — segundo denominador",
     "El PPA estaba «not yet finalized» al trimestre de diciembre 2022. La memoria auditada "
     "de JMMB Group del año fiscal a marzo 2023 debería traerlo, y con él este caso pasaría "
     "a medir la cuña entre bases como hace el de OFG."),
)

#: Discrepancia RELEVADA y no resuelta, que se declara en vez de elegir un lado. El paquete
#: original de Scotiabank en el Caribe se anunció en US$123 millones —US$98 millones de PRIMA
#: sobre el valor neto de ocho países más US$25 millones por Scotiabank Anguilla—, pero los
#: goodwill que publica la nota 34 de RFHL para las dos operaciones que sí cerraron no suman
#: esa prima. Lo más probable es que el paquete se haya recortado entre el anuncio y el
#: cierre —varios reguladores no aprobaron—, con lo cual el anuncio y la nota no describen el
#: mismo perímetro. Mientras no se confirme, el panel usa SOLO las cifras de la nota
#: auditada y no las del comunicado.
DISCREPANCIA_RFHL = (
    "El comunicado del paquete (US$123 M, US$98 M de prima) y la nota 34 auditada no "
    "describen el mismo perímetro: el paquete original cubría nueve países y solo cerró "
    "parte. No se mezclan las dos fuentes."
)


@dataclass(frozen=True)
class EstadoDelPanel:
    #: Con las dos puntas publicadas, en cualquier base.
    n_verificables: int
    #: Sobre base CONTABLE, que es la única que entra a la misma tabla. El gate cuenta ésta.
    n_comparables: int
    minimo: int
    abierto: bool
    motivo: str
    descartadas: int = 0


def estado(panel: Sequence[Transaccion] = PANEL) -> EstadoDelPanel:
    """¿Se puede abrir la vista de M&A? El gate se consulta antes, no después.

    Cuenta los COMPARABLES, no los verificables. Un múltiplo sobre valor razonable de la
    NIIF 3 es un dato bueno y no es un P/B: sumarlo al conteo abriría la vista con una tabla
    que mezcla dos bases, que es peor que tenerla cerrada.
    """
    n_ver = sum(1 for t in panel if t.verificable)
    n_comp = sum(1 for t in panel if t.comparable)
    if n_comp >= MINIMO_DE_CASOS:
        return EstadoDelPanel(n_ver, n_comp, MINIMO_DE_CASOS, True, "", len(DESCARTADAS))
    otras_bases = n_ver - n_comp
    extra = ""
    if otras_bases:
        extra = (f" Hay {otras_bases} caso(s) más con las dos puntas publicadas pero sobre "
                 "activos netos a VALOR RAZONABLE de la NIIF 3, que no es valor libro: mide "
                 "el precio contra lo que el comprador reconoce, no contra lo que el vendedor "
                 "tenía en libros. Se conservan con su base declarada y NO entran al conteo.")
    return EstadoDelPanel(
        n_ver, n_comp, MINIMO_DE_CASOS, False,
        (f"El panel tiene {n_comp} transacción(es) con precio sobre valor libro CONTABLE y el "
         f"gate exige {MINIMO_DE_CASOS}. No es falta de relevamiento: se revisaron las nueve "
         "operaciones de la banca dominicana desde 1996, las notas de combinaciones de "
         "negocios del mayor comprador del Caribe y los filings ante la SEC de los "
         "compradores cotizados. El mercado divulga el precio y casi nunca el denominador; "
         "cuando lo divulga, suele ser sobre otra base. Un múltiplo necesita las dos puntas Y "
         f"la misma base.{extra} La vista de M&A queda cerrada y el eje lo declara."),
        len(DESCARTADAS))
