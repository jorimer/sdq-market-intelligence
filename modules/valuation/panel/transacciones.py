"""Panel de transacciones bancarias RD/Caribe. Investigación de campo, no ingesta.

**Por qué existe.** Una valuación se valida contra lo que alguien PAGÓ. Sin este panel, el eje
publica un modelo con sus supuestos y su sensibilidad, y declara que el contraste no existe.
Con ocho casos verificables, la vista de M&A se abre y `ESTADO_BACKTEST` deja de decir
`dato_pendiente`.

**El relevamiento, y lo que midió.** La banca dominicana registra **nueve** fusiones y
adquisiciones documentadas desde 1996, y **una sola divulga precio**: Scotiabank por Banco
Dominicano del Progreso, US$330 millones (2018). Las otras ocho —BHD con León, Profesional
con Bancrédito, Progreso con Metropolitano, Activo con Banaci, y las alianzas de BHD con
Sabadell, Popular de Puerto Rico y Fiduciario— se anunciaron sin monto.

En el Caribe la mejor documentada es Republic Financial Holdings por siete operaciones de
Scotiabank (2019): divulga **US$123 millones**, de los cuales US$98 millones son *prima sobre
el valor neto* de ocho países y US$25 millones el total por Scotiabank Anguilla. El precio
está, **el valor neto no** — así que el múltiplo no se puede derivar sin inventar el
denominador.

**Ése es el hallazgo del relevamiento**: no es que las transacciones no existan, es que el
mercado no divulga el denominador. Un múltiplo necesita las dos puntas.

**Y una que sí cierra, porque el denominador es NUESTRO.** El patrimonio del Progreso está en
el histórico de la Superintendencia que esta plataforma ya ingiere (1984-12 → 2020-05), así
que el valor libro no depende de que el comprador lo publique. Con el tipo de cambio del BCRD
del mismo mes, el múltiplo sale auditable de punta a punta.
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
    #: Lo que el caso NO permite afirmar. Se declara con el dato, no en un anexo.
    caveats: Tuple[str, ...] = ()

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
)

#: Operaciones RELEVADAS y descartadas del panel, con el motivo. Se listan porque un panel
#: chico sin explicación se lee como falta de trabajo, y esto es lo contrario: es el
#: resultado del trabajo.
DESCARTADAS: Tuple[Tuple[str, str], ...] = (
    ("Republic Financial Holdings / siete operaciones de Scotiabank en el Caribe (2019)",
     "Divulga US$123 M —US$98 M de PRIMA sobre el valor neto de ocho países más US$25 M por "
     "el total de Scotiabank Anguilla— pero NO el valor neto. Sin denominador no hay "
     "múltiplo, y estimarlo desde los US$1.500 M de activos que suma la operación sería "
     "inventarlo."),
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
         f"gate exige {MINIMO_DE_CASOS}. No es falta de relevamiento: se revisaron nueve "
         "operaciones de la banca dominicana desde 1996 y las notas de combinaciones de "
         "negocios del mayor comprador del Caribe. El mercado divulga el precio y casi nunca "
         "el denominador; cuando lo divulga, es sobre otra base. Un múltiplo necesita las dos "
         f"puntas Y la misma base.{extra} La vista de M&A queda cerrada y el eje lo declara."),
        len(DESCARTADAS))
