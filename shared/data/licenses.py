"""Registro de las licencias DECLARADAS por los conectores — con quién las verificó y contra qué.

**El defecto que lo motiva, y que apareció dos veces.** Un conector declara su licencia en
una cadena de texto. La cadena describe al emisor en prosa amable —«uso público con cita»—
y omite las cláusulas que restringen. Dos casos comprobados el 2026-08-22:

  · **UIP / Parline** (indicador 2.43 de la END): decía «uso público con cita»; la licencia
    real es **CC BY-NC-SA 4.0**, o sea Atribución + NoComercial + CompartirIgual. Los
    informes del eje `law_intel` que usan ese indicador se entregan en base comercial.
  · **OWID / EM-DAT**: decía «CC-BY-4.0 (Our World in Data; EM-DAT/CRED)» — la licencia del
    REDISTRIBUIDOR con el nombre del PRODUCTOR pegado al lado. EM-DAT es de uso no
    comercial y el uso comercial exige un acuerdo aparte con CRED/UCLouvain.

**Por qué un registro y no dos correcciones.** Las dos cadenas eran plausibles leídas de
costado, y ninguna de las dos las había contrastado nadie contra la página de términos del
emisor. Corregir las dos deja intacto lo que las produjo: que escribir una licencia no
obliga a haberla leído. Acá cada cadena declarada tiene que existir con su ``terminos_url``
y la fecha en que alguien la leyó — o decir explícitamente que no se leyó, y entonces
figura en la lista de deuda en vez de pasar por verificada.

**La cadena es una ENTRADA DE MÁQUINA.** ``shared.data_api.manifest`` decide si un activo se
puede reexportar buscando marcas (``nc-``, ``-sa``, ``odbl``, «no comercial») en este mismo
texto: `license_restricts_redistribution`. Una restricción escrita en prosa es una
restricción que el detector no ve, y el activo sale publicable. Por eso una licencia
restrictiva tiene que NOMBRAR su cláusula, no describirla.

Lo vigila ``shared/data/tests/test_regla_licencia_declarada.py``, que lee el código con
``ast`` y exige que toda licencia declarada esté acá.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Licencia:
    """Qué se sabe de una licencia declarada, y cómo se sabe.

    ``verificado_el`` es la fecha en que alguien ABRIÓ la página de términos y leyó lo que
    dice. ``None`` significa que nadie lo hizo: la cadena se heredó de quien escribió el
    conector. No es lo mismo que «no hay términos» —eso se dice en ``nota`` y va con
    ``terminos_url=None``—, y confundir las dos cosas es exactamente el error que este
    registro existe para impedir.
    """

    #: Dónde publica el emisor sus términos. ``None`` solo cuando NO los publica.
    terminos_url: Optional[str]
    #: ISO date de la lectura de esa página. ``None`` = deuda, no ausencia de restricción.
    verificado_el: Optional[str]
    #: Qué se leyó ahí, o por qué no se pudo leer.
    nota: str
    #: ¿Es la licencia de un EMISOR? Tres cadenas del repo no lo son: son valores por
    #: defecto de un contrato (`SourceClient.license`, `Evidence.license`) o dato declarado
    #: a mano. Contarlas como deuda de verificación inflaría la deuda con trabajo que no
    #: existe — no hay página de términos que abrir.
    es_fuente: bool = True
    #: El texto EXACTO que hay que publicar cuando se usa esta fuente, cuando nombrarla es
    #: CONDICIÓN de la licencia y no cortesía editorial. Vacío = la licencia no la exige.
    #:
    #: Vive acá y no en cada módulo por la misma razón que el resto del registro: la
    #: obligación es de la LICENCIA y alcanza a todo eje que use la fuente, incluido el que
    #: alguien cablee mañana. Una atribución que depende de que el redactor se acuerde es
    #: una atribución que se pierde en la primera reescritura — y en el eje telecom se
    #: perdió antes de existir: su contexto de IA nombraba a INDOTEL, que dejó de ser la
    #: fuente en 2022, mientras el dato venía de la UIT.
    atribucion: str = ""

    @property
    def verificada(self) -> bool:
        return bool(self.verificado_el)


#: Marca para las cadenas que NO son la licencia de una fuente: valores por defecto de un
#: contrato o de un modelo. Se declaran igual —el detector las encuentra— pero no se les
#: pide URL ni fecha, porque no hay emisor detrás.
_NO_ES_UNA_FUENTE = "no es la licencia de una fuente: valor por defecto del contrato."


#: Texto declarado → qué se sabe de él. La clave es la cadena EXACTA que aparece en el
#: código: si alguien la reescribe, la entrada deja de resolver y el test lo dice.
LICENCIAS: Dict[str, Licencia] = {
    # ── Verificadas contra la página de términos del emisor ──────────────────────────
    ("Unión Interparlamentaria (Parline) — CC BY-NC-SA 4.0: Atribución + "
     "NoComercial + CompartirIgual "
     "(https://creativecommons.org/licenses/by-nc-sa/4.0/)"): Licencia(
        terminos_url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
        verificado_el="2026-08-22",
        atribucion=("Fuente: Unión Interparlamentaria (Parline), entidad DO-UC01, bajo "
                    "licencia CC BY-NC-SA 4.0."),
        nota=("Pie de `data.ipu.org` (snapshot de Wayback del 2025-12-07): `by-nc-sa.svg` "
              "y el enlace a la 4.0. Antes decía «uso público con cita», que omitía las "
              "DOS cláusulas que restringen. NC pesa: el indicador 2.43 de la END viaja "
              "en informes que se venden. "
              "LA CLÁUSULA NC YA SE LE PREGUNTÓ AL EMISOR: correo a postbox@ipu.org el "
              "2026-08-23 (punto 3 del pedido de acceso), planteando que la evaluación se "
              "entrega en base comercial y pidiendo guía escrita sobre si el uso está "
              "permitido con atribución. SIN RESPUESTA al 2026-08-23. No confundir a la "
              "UIP con la UIT: son dos organismos distintos y a la UIT no se le escribió."),
    ),
    ("OWID CC-BY-4.0 sobre su procesamiento; el dato base es de EM-DAT/CRED "
     "(UCLouvain) y NO es CC: uso NO COMERCIAL, el comercial exige acuerdo "
     "aparte con CRED — https://doc.emdat.be/docs/legal/terms-of-use/"): Licencia(
        terminos_url="https://doc.emdat.be/docs/legal/terms-of-use/",
        verificado_el="2026-08-22",
        atribucion=("Fuente: EM-DAT, CRED / UCLouvain — con procesamiento de Our World "
                    "in Data."),
        nota=("EM-DAT: acceso libre para uso no comercial; el comercial exige un acuerdo "
              "aparte con CRED/UCLouvain y cuota anual, y prohíbe construir bases "
              "sustitutas o derivadas. OWID declara que el dato de terceros queda sujeto "
              "a los términos del proveedor original — su CC-BY cubre su procesamiento, "
              "no el dato de abajo."),
    ),
    "cita con atribución · decidido 2026-08-22": Licencia(
        terminos_url=None,
        verificado_el="2026-08-22",
        atribucion=("Fuente: Latinobarómetro. Cifra computada por SDQ sobre la "
                    "tabulación que publica el emisor."),
        nota=("Latinobarómetro NO publica términos: ni los permite ni los prohíbe. Es el "
              "único caso del registro donde `terminos_url` es None por el emisor y no "
              "por deuda nuestra. La decisión de publicar con atribución explícita es del "
              "dueño y está registrada en `fuentes_admitidas` del expediente END 2030 "
              "(entrada `encuesta_regional`), con su razonamiento."),
    ),
    ("Observatorio de Igualdad de Género de la CEPAL (CEPALSTAT) — NO es CC: los "
     "términos del emisor conceden uso PERSONAL y NO COMERCIAL, sin derecho a "
     "revender, redistribuir ni crear obras derivadas — "
     "https://www.cepal.org/es/terminos-y-condiciones-sobre-el-uso-del-sitio-web-"
     "entre-la-cepal-y-el-usuario"): Licencia(
        terminos_url=("https://www.cepal.org/es/terminos-y-condiciones-sobre-el-uso-del-"
                      "sitio-web-entre-la-cepal-y-el-usuario"),
        verificado_el="2026-08-23",
        nota=("La TERCERA instancia de la misma forma, y la más estrecha de las tres. "
              "Decía «uso público con cita». Los términos que el propio servicio declara "
              "en su `termsOfService` (apispec_1.json de api-cepalstat.cepal.org, que es "
              "el endpoint que leemos) conceden bajar y copiar «para su uso personal, sin "
              "fines comerciales, sin ningún derecho a revender, redistribuir, o crear "
              "otros trabajos a partir de los mismos». No hay CC de por medio. Alimenta "
              "los indicadores 2.45 y 2.46 de la END, que se venden. "
              "`atribucion` queda VACÍA a propósito: acá nombrar la fuente no habilita "
              "nada —no hay cláusula BY que satisfacer— y ponerle un texto daría a "
              "entender que citándola el asunto queda resuelto. Lo que restringe es el "
              "uso comercial, la redistribución y la obra derivada."),
    ),
    ("World Bank Open Data CC-BY 4.0 (por defecto; el catálogo tiene datasets con "
     "otras licencias) + UN Comtrade, que NO es libre: propiedad de Naciones "
     "Unidas, uso interno, PROHIBIDA LA REDISTRIBUCIÓN del dato original sin "
     "permiso escrito de la UNSD (el dato transformado no lo alcanza) — "
     "https://comtrade.un.org/licenseagreement.html"): Licencia(
        terminos_url="https://comtrade.un.org/licenseagreement.html",
        verificado_el="2026-08-23",
        atribucion=("Fuente: UN Comtrade (Naciones Unidas) y World Bank Open Data. "
                    "Cifras derivadas por SDQ."),
        nota=("CUARTA instancia, y la que el repo ya sabía a medias: decía «free, "
              "attribution» para DOS emisores, y solo describía a uno. Comtrade es "
              "propiedad intelectual de la ONU, cedida para uso interno; re-diseminar el "
              "dato ORIGINAL exige permiso escrito de la UNSD, y por encima de 100.000 "
              "registros una «license to distribute» paga sobre suscripción premium. El "
              "dato TRANSFORMADO no lo alcanza — la ONU no lo reclama— y ahí está la vía. "
              "`modules/trade_intel/partner_chapters_sync.LICENCIA` ya apuntaba al lado "
              "correcto: cuando dos declaraciones de una fuente discrepan, gobierna la "
              "que alguien lee."),
    ),

    # ── Deuda: heredadas de quien escribió el conector, sin contrastar ────────────────
    # No están «bien»: están SIN LEER. Van listadas y no escondidas, que es la diferencia
    # entre una cola de trabajo y un basurero. El test cuenta cuántas son y no deja que
    # crezcan.
    ("ITU DataHub — la plataforma publica CC BY-NC-SA 3.0 IGO, pero la UIT "
     "autorizó POR ESCRITO (2026-08-18) el uso como insumo de productos "
     "analíticos comerciales citándola como fuente; el permiso NO cubre "
     "redistribuir las series en bruto, y la UIT está actualizando sus términos"): Licencia(
        terminos_url="https://datahub.itu.int/",
        verificado_el="2026-08-18",
        atribucion=("Fuente: Unión Internacional de Telecomunicaciones (UIT · ITU "
                    "DataHub). Cifras procesadas por SDQ."),
        nota=("VERIFICADA CONTRA EL EMISOR, y en la dirección contraria a las otras cuatro: "
              "acá lo declarado era MÁS restrictivo que lo permitido. Respuesta de la "
              "División de Datos y Analítica de las TIC (Indicators@itu.int) del "
              "2026-08-18: el uso «como insumo para productos analíticos comerciales» está "
              "permitido «siempre que la UIT (ITU) sea citada adecuadamente como fuente», y "
              "están actualizando sus términos para permitir el uso comercial de forma "
              "explícita — la licencia que figura en la plataforma «aún no refleja este "
              "cambio». El permiso se concedió sobre el uso que la consulta describió, que "
              "excluía redistribuir las series en bruto; por eso la cadena conserva las "
              "marcas NC/SA y el manifiesto sigue reteniendo lo verbatim. "
              "CONDICIÓN PENDIENTE DE MECANIZAR: la atribución es requisito del permiso y "
              "el eje telecom no tiene el `exige_atribucion` computado que sí tiene leyes. "
              "En el mismo correo la UIT explica el corte del API: rehicieron el back-end "
              "y publicaron una API nueva el 30-jul-2026, y además sufrieron ciberataques "
              "contra sus API, así que restringieron el acceso externo sin fecha de "
              "restablecimiento. Ofrecen enviar datos puntuales a pedido — hay canal "
              "humano abierto. "
              "RESPONDIDO el 2026-08-23 15:09 UTC. La respuesta confirma la fórmula de "
              "atribución que quedó cableada, toma el ofrecimiento de datos puntuales "
              "(los cinco códigos de RD: 260, 178, 11632, 19303, 12047) y deja DOS "
              "puntos de alcance preguntados y todavía sin contestar: (a) si mostrar "
              "cifras individuales de la UIT dentro de un informe queda cubierto —es "
              "ilustración del análisis, no redistribución del conjunto—, y (b) si el "
              "permiso alcanza a los informes YA entregados o solo a los futuros. "
              "Mientras no contesten, esos dos puntos son NO CONFIRMADOS: no son una "
              "negativa, pero tampoco se pueden dar por concedidos."),
    ),
    "CC-BY-3.0 (University of Notre Dame)": Licencia(
        terminos_url=None, verificado_el=None,
        nota=("ND-GAIN se anuncia como «free and open-access» y da una cita sugerida; en "
              "sus páginas de índice y de descarga no aparece la licencia. La 3.0 la "
              "escribió quien hizo el conector.")),
    "CC-BY-4.0 (Ember)": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar contra Ember."),
    "Datos Abiertos RD (INDOTEL)": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "Datos Abiertos RD (datos.gob.do)": Licencia(
        terminos_url=None, verificado_el=None,
        nota=("El portal declara licencia por dataset; esta cadena la comparten cinco "
              "conectores, así que puede no ser la misma para los cinco.")),
    "Datos abiertos ONE (one.gob.do)": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "Datos públicos DGA — estadísticas de comercio exterior": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "GDELT Project (open data)": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "GDELT Project (open data) · BigQuery public dataset": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "IMF WEO (terms of use)": Licencia(
        terminos_url=None, verificado_el=None,
        nota="Nombra que hay términos sin decir cuáles: es la forma pura de la deuda."),
    "NOAA NHC — dominio público": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "SISDOM (VAES/MEPyD) — indicadores sociales oficiales, uso público con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "World Bank Open Data (CC-BY 4.0)": Licencia(
        terminos_url="https://datacatalog.worldbank.org/public-licenses",
        verificado_el="2026-08-23",
        atribucion="Fuente: World Bank Open Data (CC-BY 4.0).",
        nota=("CONFIRMADA como estaba escrita: CC-BY 4.0 es la licencia por defecto de los "
              "datasets que produce el Banco Mundial. Con una salvedad que el propio "
              "catálogo declara y que la cadena no dice: «Many datasets are available "
              "under other licenses» — hay ODbL cuando lo exige el proveedor original, "
              "licencias de microdatos y términos de terceros. Vale para WDI y WGI, que es "
              "lo que hoy se lee; no vale como salvoconducto para cualquier serie del "
              "Banco Mundial que se agregue mañana."),
    ),
    "datos abiertos del Estado dominicano (datos.gob.do) — uso público con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos oficiales BCRD — uso público con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos oficiales ONE — uso público con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos públicos DGA/Aduanas RD — uso con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos públicos DGII (Estadísticas de Contribuyentes) — uso con cita; CIIU rev.3": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos públicos DGII (Informe de Recaudación) — uso con cita; ODbL en datos.gob.do": Licencia(
        terminos_url=None, verificado_el=None,
        nota="Nombra ODbL (share-alike), así que el manifiesto sí la retiene. Sin leer."),
    "datos públicos Ministerio de Hacienda (Estadísticas Fiscales) — uso con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos públicos SIPEN — sistema dominicano de pensiones (uso con cita)": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "datos públicos TSS/SDSS — uso con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "estadísticas públicas del Banco Central de la República Dominicana — uso con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "estadísticas públicas del Ministerio de Educación (SIIE) — uso con cita": Licencia(
        terminos_url=None, verificado_el=None, nota="Sin contrastar."),
    "https://comtrade.un.org/db/help/licenseagreement.aspx": Licencia(
        terminos_url="https://comtrade.un.org/db/help/licenseagreement.aspx",
        verificado_el=None,
        nota=("La cadena ES la URL de los términos, que es más honesto que una glosa — "
              "pero nadie registró qué dicen, y contradice a `comtrade_client`.")),
    "https://opendatacommons.org/licenses/odbl/": Licencia(
        terminos_url="https://opendatacommons.org/licenses/odbl/", verificado_el=None,
        nota=("ODbL: share-alike sobre bases derivadas. La cadena la nombra y el "
              "manifiesto la retiene. Falta confirmar que el SIS la declare hoy.")),
    "https://sis.gob.do (público)": Licencia(
        terminos_url=None, verificado_el=None,
        nota="«público» no es una licencia: es dónde está el archivo. Sin contrastar."),
    "open-data": Licencia(
        terminos_url=None, verificado_el=None,
        nota=("Dos palabras sin emisor ni cláusula, en el conector de IED del BCRD. La "
              "declaración más pobre del repo.")),

    # ── No son licencias de fuente ───────────────────────────────────────────────────
    "unknown": Licencia(
        terminos_url=None, verificado_el=None, es_fuente=False,
        nota=f"`SourceClient.license` por defecto — {_NO_ES_UNA_FUENTE}"),
    "": Licencia(
        terminos_url=None, verificado_el=None, es_fuente=False,
        nota=f"`Evidence.license` por defecto — {_NO_ES_UNA_FUENTE}"),
    "declarado (store soberano)": Licencia(
        terminos_url=None, verificado_el=None, es_fuente=False,
        nota=("Dato declarado a mano en el store soberano, no traído de un emisor: "
              f"{_NO_ES_UNA_FUENTE}")),
}


def atribucion_exigida(licencia_texto: Optional[str]) -> str:
    """El texto que hay que publicar al usar esa licencia, o ``""`` si no lo exige.

    Se consulta; no se transcribe. Un eje que copie la frase a su propio módulo vuelve a
    crear el problema que el registro cierra: la copia sobrevive a la corrección.
    """
    lic = LICENCIAS.get((licencia_texto or "").strip())
    return lic.atribucion if lic else ""


def fuentes_que_exigen_atribucion() -> Dict[str, str]:
    """``{licencia: texto de atribución}`` de las que condicionan el uso a nombrarlas.

    Se COMPUTA del registro. Una lista escrita a mano envejece en cuanto se verifica la
    siguiente, y la que falte es justo la que se publicaría sin atribuir.
    """
    return {texto: lic.atribucion for texto, lic in LICENCIAS.items() if lic.atribucion}


def deuda_de_verificacion() -> Dict[str, Licencia]:
    """Las licencias que nadie contrastó contra la página del emisor.

    Se COMPUTA del registro y no se escribe a mano: una lista escrita envejece en cuanto
    alguien verifica una, y la que quede de más se lee como deuda que ya no existe.
    """
    return {texto: lic for texto, lic in LICENCIAS.items()
            if lic.es_fuente and not lic.verificada}
