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
    #: Qué fracción de la entidad compró el precio. NO es un detalle: un precio por el 90 %
    #: contra un patrimonio del 100 % da un múltiplo 11 % bajo, y el error no se ve —el
    #: número sale plausible—. Vive como campo y no como caveat para que el múltiplo se
    #: pueda VERIFICAR contra sus insumos.
    porcentaje: float = 1.0
    #: RD$ (o moneda del libro) por unidad de la moneda del precio, del MES del corte. Vive
    #: como campo por el mismo motivo: una conversión metida en la prosa no se puede
    #: recomputar, y ya entró mal una vez —la de prensa, a un mes que no era el del corte—.
    tipo_de_cambio: Optional[float] = None
    #: QUÉ perímetro cubren las DOS puntas. No es una etiqueta descriptiva: es la condición
    #: para que el caso exista. Un precio que compró la sociedad TENEDORA contra un
    #: patrimonio que el regulador publica del BANCO da un múltiplo plausible y equivocado —
    #: en Santander PR daría 1,26x—. Si los dos perímetros no coinciden, el caso no entra.
    alcance: str = "entidad"
    #: Lo que el caso NO permite afirmar. Se declara con el dato, no en un anexo.
    caveats: Tuple[str, ...] = ()

    @property
    def denominador_homogeneo(self) -> Optional[float]:
        """El denominador en la MONEDA y la FRACCIÓN del precio.

        Es lo que hace comparable un múltiplo con otro. Las dos correcciones que aplica ya
        entraron mal alguna vez en este mismo relevamiento: una conversión hecha a un mes que
        no era el del corte, y un precio por el 90 % puesto contra el patrimonio del 100 %.
        """
        if self.valor_libro is None:
            return None
        libro = self.valor_libro
        if self.tipo_de_cambio is not None:
            libro = libro / self.tipo_de_cambio
        return libro * self.porcentaje

    @property
    def pb_recomputado(self) -> Optional[float]:
        """El múltiplo derivado de sus insumos. Si no coincide con `pb`, uno de los dos
        miente — y el test lo cruza para todo el panel."""
        den = self.denominador_homogeneo
        if self.precio is None or not den:
            return None
        return self.precio / den

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
        pb=2.531, tipo_de_cambio=49.7276,
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
        anio=2019, comprador="OFG Bancorp",
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
        pb=1.818, tipo_de_cambio=54.9967,
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
    Transaccion(
        anio=2015, comprador="JMMB Holding Company Limited",
        adquirida="Banco de Ahorro y Crédito Río (90 % de las acciones)",
        pais="DO",
        precio=2_150_000.0, moneda_precio="USD",
        valor_libro=65_568_455.0, moneda_libro="DOP", periodo_libro="2015-06",
        pb=1.636, porcentaje=0.90, tipo_de_cambio=44.914857142857144,
        fuente_precio=("Estados financieros auditados de JMMB Group Limited al 31 de marzo "
                       "de 2016, nota de adquisición: el 1 de julio de 2015 adquirió el 90 % "
                       "del capital y el control de gestión de Banco Río de Ahorro y "
                       "Crédito por US$2.150.000 (J$252,7 millones)."),
        fuente_libro=("Patrimonio publicado por la Superintendencia de Bancos vía SIMBAD al "
                      "30 de junio de 2015 —el último cierre mensual ANTES del 1 de julio—: "
                      "RD$65.568.455. Convertido con el tipo de cambio de venta promedio del "
                      "BCRD del mismo mes (RD$44,9149/US$) y tomado al 90 %, la fracción que "
                      "compró el precio.\n\n"
                      "LA ENTIDAD ESTÁ BAJO SU NOMBRE POSTERIOR: la SB la publica como "
                      "«JMMB», banco de ahorro y crédito, hacia atrás hasta 2013 — es el "
                      "balance del Río bajo el nombre que le puso el comprador. Una búsqueda "
                      "por «Río» no la encuentra, y concluir que el dato no existe sería el "
                      "error.\n\n"
                      "LA SERIE MENSUAL CORROBORA LA FECHA, y es evidencia que ninguna de las "
                      "dos fuentes de prensa aporta: el patrimonio cae sin interrupción de "
                      "RD$87,2 M en enero 2014 a RD$60,2 M en noviembre 2015 —una entidad "
                      "que se achicaba— y salta a RD$94,3 M en diciembre 2015. La "
                      "capitalización llega DESPUÉS de julio de 2015, no de julio de 2014. "
                      "Si la compra hubiera sido en 2014 el aporte se vería en 2014, y no "
                      "hay ninguno."),
        caveats=(
            "Es el 90 %, no el 100 %. El múltiplo homogeneiza —precio del 90 % contra "
            "patrimonio del 90 %—; contra el patrimonio entero habría dado 1,47x, un 10 % "
            "bajo, y el número habría salido plausible.",
            "LA FECHA ERA EL RIESGO, no el denominador. La prensa dominicana situaba la "
            "operación en julio de 2014 y la jamaiquina en julio de 2015; los estados "
            "auditados del comprador fijan el 1 de julio de 2015, y lo de 2014 es la "
            "autorización de la Junta Monetaria (diciembre). Con el corte de junio 2014 el "
            "múltiplo habría dado 1,25x en vez de 1,64x: un 31 % de diferencia por una fecha.",
            "El 1,5x que publicó la prensa dominicana es una derivación de terceros, no la "
            "fuente del denominador. Que quede cerca del 1,64x computado es corroboración, "
            "no insumo.",
            "El 10 % restante quedó en manos de un inversionista privado, así que no hay un "
            "precio del 100 % con el que contrastar.",
        ),
    ),
    Transaccion(
        anio=2012, comprador="OFG Bancorp",
        adquirida="BBVA PR Holding Corporation y BBVA Securities of Puerto Rico",
        pais="PR",
        precio=500_000_000.0, moneda_precio="USD",
        valor_libro=650_617_000.0, moneda_libro="USD", periodo_libro="2012-12",
        pb=0.769, valor_razonable=438_680_000.0,
        fuente_precio=("Form 10-K del ejercicio 2012 (SEC) —la sociedad se llamaba entonces "
                       "Oriental Financial Group y pasó a OFG Bancorp en mayo de 2013; es la "
                       "misma, y el panel la nombra igual en los dos casos para que agrupar "
                       "por comprador no la parta en dos—, nota de combinaciones de "
                       "negocios: «Cash consideration» US$500.000 miles, en efectivo, por el "
                       "100 % de las dos sociedades. Cierre el 18 de diciembre de 2012."),
        fuente_libro=("Misma tabla, epígrafe «Book Value of Net Assets Acquired»: "
                      "«BBVAPR stockholder's equity» US$650.617 miles. El valor razonable de "
                      "los activos netos es US$438.680 miles y el goodwill US$61.320 miles; "
                      "438.680 + 61.320 = 500.000, la aritmética cierra exacta.\n\n"
                      "VERIFICACIÓN CRUZADA CONTRA EL REGULADOR: el Call Report que el banco "
                      "presentó al FDIC da un patrimonio de US$616.643 miles al 30 de "
                      "septiembre de 2012. La cifra del 10-K es de la SOCIEDAD TENEDORA y "
                      "dos meses y medio más tarde, y queda 5,5 % por encima — consistente "
                      "con que la tenedora incluye además la casa de valores. Dos fuentes "
                      "independientes, y el orden de magnitud coincide."),
        caveats=(
            "US-GAAP (ASC 805), no NIIF, y es la operación más vieja del panel: catorce años. "
            "Se publica marcada.",
            "ES EL CASO QUE MÁS ENSEÑA SOBRE LA BASE. El valor razonable queda 32,6 % POR "
            "DEBAJO del libro —marcas de cartera por US$118,9 millones y el goodwill heredado "
            "de US$116,4 millones que desaparece—, mientras que en la compra de Scotiabank PR "
            "por la MISMA compradora, en el MISMO mercado y siete años después, queda 15,0 % "
            "por ENCIMA. Cuarenta y ocho puntos de amplitud en las tablas de un mismo "
            "comprador: no existe un ajuste fijo que convierta una base en la otra.",
            "El múltiplo sobre libro es 0,77x —una compra POR DEBAJO del patrimonio— y sobre "
            "valor razonable 1,14x. La prensa publicó «3 % de prima sobre el valor tangible en "
            "libros», que es una TERCERA base: el libro de US$650,6 M incluye US$116,4 M de "
            "goodwill heredado que el tangible no tiene.",
            "El precio compró la tenedora y la casa de valores, no solo el banco. El "
            "denominador del 10-K tiene ese mismo alcance, así que las dos puntas son "
            "consistentes; el Call Report del FDIC, no —ése es solo el banco—.",
        ),
    ),
    Transaccion(
        anio=2019, comprador="Republic Financial Holdings",
        adquirida="Cayman National Corporation Ltd. (74,99 % de las acciones)",
        pais="KY",
        precio=198_474_012.50, moneda_precio="USD",
        valor_libro=117_389_759.0, moneda_libro="KYD", periodo_libro="2018-09",
        pb=1.879, porcentaje=0.7499, tipo_de_cambio=0.8333333333333334,
        fuente_precio=("Anuncio de cierre de RFHL, 13 de marzo de 2019: «the purchase of "
                       "74.99% of the issued shares in CNC at an offering price of US$6.25 "
                       "per share at an overall cost of US$198,474,012.50». Reproducido "
                       "íntegro por el propio sitio de Cayman National y por Newsday "
                       "(Trinidad)."),
        fuente_libro=("Estados financieros consolidados AUDITADOS de Cayman National "
                      "Corporation Ltd. al 30 de septiembre de 2018, dictaminados por PwC "
                      "(19 de diciembre de 2018): «TOTAL EQUITY» CI$117.389.759 sobre activos "
                      "de CI$1.463.023.918.\n\n"
                      "ES LA ESTRUCTURA IDEAL DE UN CASO: el denominador NO sale del "
                      "comprador. Sale de los estados auditados de la propia adquirida, que "
                      "cotizaba en la Bolsa de las Islas Caimán y por eso los publicaba.\n\n"
                      "Conversión al peg FIJO del dólar caimán, CI$1,00 = US$1,20 desde el 1 "
                      "de abril de 1974. No es una cotización de mercado y por eso no tiene "
                      "mes: es una paridad administrada."),
        caveats=(
            "Es el 74,99 %, no el 100 %. El múltiplo homogeneiza contra esa misma fracción "
            "del patrimonio. Comprobación independiente: US$6,25 por acción contra un valor "
            "libro por acción de CI$2,77 (US$3,33) da el mismo 1,88x.",
            "El corte del patrimonio es el 30 de septiembre de 2018 —cierre del ejercicio de "
            "CNC— y la operación cerró el 13 de marzo de 2019: cinco meses y medio de "
            "distancia. Es el último balance auditado anterior al cierre, pero la distancia "
            "es mayor que en los casos dominicanos.",
            "CNC es un GRUPO, no un banco solo: además de Cayman National Bank tiene "
            "fiduciaria, administración de fondos y casa de valores, y opera en la Isla de "
            "Man y Dubái. El balance sí es de banco —CI$747 M de préstamos y CI$1.306 M de "
            "depósitos sobre CI$1.463 M de activos—, pero el múltiplo incorpora negocios de "
            "comisiones que un banco puro no tiene.",
        ),
    ),
    Transaccion(
        anio=2020, comprador="First BanCorp (FirstBank Puerto Rico)",
        adquirida="Santander BanCorp y Banco Santander Puerto Rico",
        pais="PR",
        precio=1_277_626_000.0, moneda_precio="USD",
        valor_libro=1_271_323_000.0, moneda_libro="USD", periodo_libro="2020-09",
        pb=1.005, base=BASE_VALOR_RAZONABLE,
        fuente_precio=("Form 10-Q de First BanCorp del 3T2020 (SEC), nota de combinación de "
                       "negocios: «Total purchase price consideration (cash)» US$1.277.626 "
                       "miles. Cierre el 1 de septiembre de 2020."),
        fuente_libro=("Misma nota: «Fair value of net assets and identifiable intangible "
                      "assets» US$1.271.323 miles, con goodwill de US$6.303 miles. "
                      "1.271.323 + 6.303 = 1.277.626, cierra exacta.\n\n"
                      "LA TABLA NO PUBLICA COLUMNA DE LIBRO, a diferencia de las dos de OFG. "
                      "Por eso el caso queda sobre base valor razonable pese a venir del "
                      "mismo tipo de documento: que un 10-Q traiga el libro es una elección "
                      "de presentación del emisor, no una exigencia de la norma."),
        caveats=(
            "LA BASE NO ES VALOR LIBRO. Son activos netos identificables a valor razonable.",
            "Y no alcanza con ir al regulador: el Call Report del FDIC da un patrimonio de "
            "US$1.013.608 miles al 30 de junio de 2020, pero ése es el BANCO y el precio "
            "compró la sociedad tenedora —que además tenía la financiera de consumo—. "
            "Cruzarlos daría 1,26x, un múltiplo con el numerador y el denominador midiendo "
            "cosas distintas. Es el error de ALCANCE, y produce un número plausible.",
            "Las condiciones anunciadas hablaban de 117,5 % del «core tangible common "
            "equity» más el capital excedente a la par: una tercera base, definida por el "
            "contrato y no por un balance.",
        ),
    ),
    Transaccion(
        anio=2008, comprador="Royal Bank of Canada",
        adquirida="RBTT Financial Holdings Limited (100 % de las acciones)",
        pais="TT",
        precio=13_756_680_000.0, moneda_precio="TTD",
        valor_libro=5_039_274_000.0, moneda_libro="TTD", periodo_libro="2008-03",
        pb=2.730, alcance="grupo cotizado (las dos puntas)",
        fuente_precio=("Memoria anual 2008 de la PROPIA RBTT: «On June 16, RBC completed the "
                       "sale, paying US$2.2 billion to RBTT shareholders, 60% in cash and 40% "
                       "in RBC shares», con una consideración de TT$40 por acción y 343.917 "
                       "miles de acciones ordinarias en circulación (nota 28). "
                       "343.917.000 × TT$40 = TT$13.756.680.000.\n\n"
                       "CONTROL DE CONSISTENCIA: ese total contra los US$2.200 millones "
                       "declarados implica TT$6,2530 por dólar, dentro del rango real de "
                       "2008 (6,25-6,30). Las dos formas de expresar el precio —por acción y "
                       "agregada en dólares— concuerdan sin que haya que elegir un tipo de "
                       "cambio."),
        fuente_libro=("Balance consolidado AUDITADO de RBTT Financial Holdings al 31 de marzo "
                      "de 2008 —cierre de su ejercicio, dos meses y medio antes de la "
                      "operación—: «Total Shareholders' Equity» TT$5.039.274 miles, sobre "
                      "activos de TT$53.527.214 miles. El interés minoritario (TT$46.353 "
                      "miles) queda FUERA: el precio compró las acciones de la matriz.\n\n"
                      "Como en Cayman National, el denominador sale de la adquirida y no del "
                      "comprador: RBTT cotizaba y publicaba sus estados.\n\n"
                      "Comprobación por acción: TT$5.039.274 miles / 343.917 miles de "
                      "acciones = TT$14,653 de valor libro por acción, contra los TT$40 "
                      "pagados. Mismo múltiplo por las dos vías."),
        caveats=(
            "ES LA OPERACIÓN MÁS VIEJA DEL PANEL —2008, anterior a la crisis financiera "
            "global— y se publica marcada. Un múltiplo pagado en el pico del ciclo de "
            "fusiones caribeño no informa igual que uno de 2022.",
            "El 40 % de la consideración se pagó en ACCIONES de RBC, así que el valor "
            "efectivo dependió de la cotización de RBC al cierre. Los US$2.200 millones son "
            "el valor declarado de la operación, no un desembolso en efectivo.",
            "El número de acciones es el PROMEDIO PONDERADO del ejercicio (nota 28). Durante "
            "el año se emitieron 353.089 acciones, un 0,1 % del total, así que la diferencia "
            "contra las acciones en circulación al cierre es inmaterial — pero es una "
            "aproximación y se declara.",
            "El comparativo de 2007 fue REEXPRESADO en esta misma memoria (de TT$4.494.098 a "
            "TT$4.391.969 miles): un recordatorio de que las cifras de libro se mueven "
            "después de publicadas.",
            "RBTT era un grupo financiero de 18 países con banca, seguros y banca de "
            "inversión, no un banco solo.",
        ),
    ),
    Transaccion(
        anio=2012, comprador="First Citizens Bank Limited",
        adquirida="Butterfield Bank (Barbados) Limited (100 % de las acciones)",
        pais="BB",
        precio=45_000_000.0, moneda_precio="USD",
        valor_libro=34_995_000.0, moneda_libro="USD", periodo_libro="2011-12",
        pb=1.286, alcance="entidad, medida en las cuentas CONSOLIDADAS del vendedor",
        fuente_precio=("Memoria anual 2012 de The Bank of N.T. Butterfield & Son, nota 3 "
                       "«Discontinued Operations»: venta cerrada el 27 de agosto de 2012 con "
                       "«gross proceeds, subject to normal adjustments, of $45 million»."),
        fuente_libro=("Misma nota 3, que PUBLICA los activos y pasivos de la operación "
                      "discontinuada al 31 de diciembre de 2011: activos totales US$307.044 "
                      "miles menos pasivos totales US$272.049 miles = US$34.995 miles de "
                      "activos netos. No hay que despejarlo de la ganancia — la nota los "
                      "lista línea por línea.\n\n"
                      "CONTROL DE CONSISTENCIA: 45.000 − 34.995 = 10.005 contra la ganancia "
                      "NETA reportada de US$7.240 miles. La diferencia de US$2.765 miles son "
                      "costos de transacción y el reciclaje de conversión acumulada, que es "
                      "el orden de magnitud esperable. Las dos cifras se sostienen."),
        caveats=(
            "EL DENOMINADOR ES LA MEDICIÓN DEL GRUPO VENDEDOR, no el patrimonio que la "
            "entidad declaraba a su propio regulador. Incluye US$3.084 miles de intangibles "
            "—el 8,8 % del denominador— que vienen de la compra original de Butterfield. "
            "Sobre un libro individual sin ese intangible el múltiplo sería ~1,41x en vez de "
            "1,29x. El PERÍMETRO sí coincide con el del precio —la entidad entera—, que es "
            "la condición para entrar; lo que difiere es la medición, y se declara.",
            "El corte es diciembre 2011 y la venta cerró en agosto de 2012: ocho meses de "
            "distancia, la mayor del panel. Es la última cifra publicada, porque la columna "
            "de 2012 ya está en cero por la desconsolidación.",
            "US$45 millones son proceeds BRUTOS «sujetos a ajustes normales»: la "
            "consideración final pudo diferir, igual que pasó en OFG y en Belice.",
            "Los activos (US$308 M) y los depósitos (US$270 M) que publicó la prensa NO son "
            "el patrimonio; el denominador es la resta que hace la propia nota.",
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
    ("RBC / operaciones del Caribe Oriental a un consorcio regional (cierre abril 2021)",
     "Once SUCURSALES vendidas a cinco bancos locales, y el comunicado dice «without "
     "financial terms». Sin precio, y además el objeto no es una entidad con patrimonio "
     "publicado por un regulador sino un conjunto de sucursales: aunque apareciera el monto, "
     "no habría denominador que le corresponda. Es el descarte inverso al resto —acá falta "
     "el numerador— y no se arregla encontrándolo."),
    ("Banco Múltiple de Las Américas, Bancamérica (2022)",
     "No fue una compra: la Junta Monetaria dispuso su DISOLUCIÓN (Segunda Resolución del "
     "28-ene-2022) y la SB licitó activos y captaciones, adjudicados a Banreservas con "
     "aporte del Fondo de Contingencia. En una disolución gana quien pide MENOS aporte, que "
     "es lo contrario de un precio de control."),
    ("Banco Caribe / BID Invest (2023)",
     "Préstamo sénior de hasta US$25,15 millones. No hay inversión accionaria ni cambio de "
     "control: financiar a una entidad no es comprarla."),
    ("ANSA Merchant Bank / Bank of Baroda (Trinidad y Tobago) (2021)",
     "Compra del 100 % de las 525.597 acciones, aprobada por el Banco Central de Trinidad y "
     "Tobago el 20 de noviembre de 2020 y consumada el 1 de marzo de 2021 — y SIN PRECIO "
     "divulgado. Falta el numerador. Es de las que quedarían a un paso si el monto "
     "apareciera: la adquirida es una entidad completa con un solo regulador."),
    ("Banesco Banco Múltiple RD · Lafise · Ademi · Promérica RD y el resto del padrón",
     "Barrido del padrón de la SB sin operación de control con monto. Lo que aparece son "
     "cosas que NO son compras: entradas de novo (Lafise, autorizada en 2013), conversiones "
     "de licencia (Ademi, de ahorro y crédito a banco múltiple) y aumentos de capital por "
     "oferta pública (Promérica, 2023). Banesco sigue siendo subsidiaria de Banesco Panamá."),
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
    ("JMMB / Intercommercial Bank Ltd (Trinidad y Tobago, 2013)",
     "Precio verificado: US$8,75 millones (J$914,1 millones) por el 50 % RESTANTE, pasando "
     "de 50 % a 100 %. Falta el patrimonio contable de la entidad al corte 2013, que "
     "publicaría el Central Bank of Trinidad and Tobago. Además es una compra POR ETAPAS: el "
     "precio es solo del segundo tramo y el múltiplo hay que homogeneizarlo al 50 %."),
    ("Butterfield Barbados — el patrimonio INDIVIDUAL de la entidad",
     "El caso ya está en el panel, con el denominador que publica la nota de operaciones "
     "discontinuadas del vendedor. Lo que falta es el patrimonio que la entidad declaraba a "
     "su PROPIO regulador, el Central Bank of Barbados: sobre esa base el múltiplo sería "
     "~1,41x en vez de 1,29x, porque la medición del grupo carga US$3,1 M de intangibles de "
     "la compra original. No bloquea el caso; lo afinaría."),
    ("NCB Financial Group / Clarien Group (Bermuda, 2017)",
     "Falta aclarar QUÉ FUE la operación, antes que cualquier cifra. NCBFG SUSCRIBIÓ el "
     "50,1 % —un aporte de capital que entra a la sociedad— y no está establecido que le "
     "haya comprado las acciones a un accionista. Si fue suscripción, el monto NO es un "
     "precio de control y el caso no pertenece a este panel por más que las dos cifras "
     "existan. Lo que sí está, y vale aparte: la nota del comprador declara una GANANCIA POR "
     "COMPRA VENTAJOSA final de J$4.392.149 miles, o sea que el valor razonable de los "
     "activos netos SUPERÓ al monto pagado. Es el único caso relevado en esa dirección."),
    ("Republic Financial Holdings / desglose por país del Caribe Oriental",
     "La nota 34 agrega siete territorios en una sola cifra. Si algún estado local o el "
     "regulador de un territorio publicara su parte, esa observación se desdoblaría en "
     "varias. Hoy es una."),
    ("Sagicor Group Jamaica / RBC Royal Bank (Jamaica) (2014)",
     "Las tres cifras aparecen y CIERRAN entre sí —consideración US$84.378 miles, activos "
     "netos adquiridos US$113.429 miles, goodwill negativo US$29.051 miles— y reconcilian "
     "con los J$9.500 millones que publicó la prensa al tipo de cambio de 2014. Falta abrir "
     "el estado auditado: hasta acá vienen de un resumen y no del documento, y un caso cuya "
     "fuente no se abrió es una brecha, no un dato. Ojo además con la base: «net assets "
     "acquired» de la NIIF 3 es valor razonable, así que aun verificado NO contaría para la "
     "meta salvo que la nota publique el libro. Sería el segundo caso relevado con COMPRA "
     "VENTAJOSA: el valor razonable supera al precio."),
    ("Caribbean Investment Holdings / Scotiabank (Belize) (cierre abril 2021)",
     "Precio verificado y FINAL: US$20 millones al cierre, por debajo de los «hasta US$30,5 "
     "millones» del acuerdo de junio 2020 — un recordatorio de que el monto del anuncio no es "
     "el del cierre. El anuncio a la bolsa de Bermudas no divulga activos netos. Falta el "
     "patrimonio de la entidad: la memoria 2021 de CIHL con su asignación del precio de "
     "compra, o el Banco Central de Belice. Se conoce que SBL tenía US$389,9 millones de "
     "activos al 31-oct-2019, que NO son patrimonio."),
    ("Banco Santander Puerto Rico — el denominador sobre base CONTABLE",
     "El caso ya está en el panel sobre valor razonable. Para pasarlo a base contable hace "
     "falta el patrimonio consolidado de SANTANDER BANCORP, la sociedad tenedora, que es lo "
     "que compró el precio. El Call Report del FDIC solo cubre el banco (US$1.013.608 miles "
     "al 30-jun-2020) y usarlo cruzaría alcances. La vía es el FR Y-9C que la tenedora "
     "presenta a la Reserva Federal."),
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


#: Los países cuyo balance POR ENTIDAD esta plataforma ingiere, y por lo tanto las únicas
#: adquiridas a las que le podríamos correr nuestro propio motor. Fuera de acá tenemos el
#: precio y el libro del caso —que es lo que el gate del panel exige— pero NO la historia de
#: ROE y patrimonio que el Excess Return necesita para producir SU valuación.
PAISES_CON_MOTOR: Tuple[str, ...] = ("DO",)


@dataclass(frozen=True)
class ContrasteDelModelo:
    """Qué se puede afirmar con el panel, que NO es lo mismo que tenerlo completo."""

    #: Comparables cuya adquirida podríamos valuar con nuestro propio motor.
    n_valuables: int
    #: Comparables totales.
    n_comparables: int
    #: ¿El panel contrasta el MODELO contra precios pagados?
    contrasta_el_modelo: bool
    motivo: str


def contraste_del_modelo(panel: Sequence[Transaccion] = PANEL) -> ContrasteDelModelo:
    """¿El panel valida el modelo, o solo muestra los múltiplos que se pagaron?

    **No es la pregunta del gate, y confundirlas sería el error más caro de este eje.** El
    gate pregunta si hay ocho múltiplos sobre la misma base; contrastar el MODELO exige
    además correr el Excess Return sobre cada adquirida a la fecha de su operación y comparar
    su valor con el precio. Para eso hace falta la historia de ROE y patrimonio de ESA
    entidad, y la tenemos donde ingerimos el balance por entidad.

    Un panel de ocho comparables es evidencia de MERCADO —a cuánto se paga un banco del
    Caribe sobre libro— y no es evidencia de que este modelo acierte. Publicar lo segundo
    apoyado en lo primero sería cierto en la forma y falso en el fondo.
    """
    comp = [t for t in panel if t.comparable]
    valuables = [t for t in comp if t.pais in PAISES_CON_MOTOR]
    n_v, n_c = len(valuables), len(comp)
    faltan = sorted({t.pais for t in comp if t.pais not in PAISES_CON_MOTOR})
    return ContrasteDelModelo(
        n_v, n_c, False,
        (f"El panel tiene {n_c} múltiplo(s) comparable(s) y eso ABRE la vista de fusiones y "
         f"adquisiciones: se puede mostrar a cuánto sobre libro se pagó un banco del Caribe. "
         f"NO contrasta el modelo. Para eso habría que valuar cada adquirida con el Excess "
         f"Return a la fecha de su operación, y eso exige su historia de ROE y patrimonio: "
         f"la tenemos para {n_v} de los {n_c}, porque el balance por entidad solo lo "
         f"ingerimos de {', '.join(PAISES_CON_MOTOR)}"
         + (f" y las otras adquiridas son de {', '.join(faltan)}." if faltan else ".")
         + " El eje sigue declarando que sus valores NO están contrastados contra precios "
           "pagados."))


@dataclass(frozen=True)
class ResumenDelPanel:
    n: int
    minimo: float
    maximo: float
    mediana: float


def resumen(panel: Sequence[Transaccion] = PANEL) -> Optional[ResumenDelPanel]:
    """El rango y la mediana de los COMPARABLES, computados y no transcritos."""
    pbs = sorted(t.pb for t in panel if t.comparable and t.pb is not None)
    if not pbs:
        return None
    n = len(pbs)
    mediana = pbs[n // 2] if n % 2 else (pbs[n // 2 - 1] + pbs[n // 2]) / 2
    return ResumenDelPanel(n, pbs[0], pbs[-1], mediana)


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
        # El gate abierto TAMBIÉN lleva motivo, y no por simetría: un `abierto=True` con
        # motivo vacío se lee como «ya está validado», que es justo lo que el panel no
        # demuestra. Ver `contraste_del_modelo`.
        return EstadoDelPanel(n_ver, n_comp, MINIMO_DE_CASOS, True,
                              contraste_del_modelo(panel).motivo, len(DESCARTADAS))
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
