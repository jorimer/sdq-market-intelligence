"""ONE social sync — persist live ONE statistics into the social store.

Pulls the real ONE data (first: poverty by development region) and upserts it into
``sd_indicators`` (idempotent by entity_key/theme/period), so the IDM runs on real
data instead of the illustrative regions. Mirrors
:mod:`modules.sector_intel.sectors_sync`.
"""
import logging
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.social_dev.models.models import SocialIndicator
from shared.data.siuben_client import DATASETS as SIUBEN_DATASETS
from shared.data.siuben_client import SOURCE as SIUBEN_SOURCE

logger = logging.getLogger("sdq.social_dev.one_sync")

# National health (WDI) → applied to every region (no by-region source yet).
WDI_HEALTH = {"SP.DYN.LE00.IN": "life_expectancy", "SP.DYN.IMRT.IN": "child_mortality"}

#: Series nacionales del WDI que NO alimentan el índice pero sí tienen consumidor propio.
#:
#: `internet_users` es «Individuals using the Internet (% of population)», el indicador
#: 3.13 de la END. Se toma del Banco Mundial y no de la UIT —que es quien lo produce—
#: porque el API de ITU DataHub dejó de ser alcanzable de forma anónima: el host viejo
#: (`api.datahub.itu.int`) responde 403 en TODAS sus rutas, incluida la raíz, y el nuevo
#: (`datahub.itu.int/api/v2`) está detrás de un desafío de CloudFront que devuelve 202 con
#: cuerpo vacío. El WDI republica la misma serie con API abierta.
#:
#: No confundir con `internet_penetration` del eje telecom, que es banda ancha MÓVIL por
#: 100 habitantes: son magnitudes distintas y la segunda puede pasar de 100.
WDI_NACIONALES_FUERA_DEL_INDICE = {
    "IT.NET.USER.ZS": ("internet_users", "% de la población"),
    # «Proportion of seats held by women in national parliaments» — el indicador 2.44 de la
    # END (Cámara de Diputados). Para sistemas bicamerales la UIP reporta la cámara BAJA, y
    # eso es exactamente lo que pide el 2.44; el Senado es otro indicador (2.43) y esta
    # serie NO lo cubre. La comprobación no es de nombre sino de valor: la ley fija la línea
    # base de Diputados en 20,8% para 2010 y la serie da 20,77 ese año, mientras la del
    # Senado era 9,4 — no hay ambigüedad posible entre las dos.
    "SG.GEN.PARL.ZS": ("women_lower_house", "% de los escaños"),
    # Mortalidad de menores de 5 años — indicador 2.22 de la END. NO es `child_mortality`,
    # que en este panel es `SP.DYN.IMRT.IN`, mortalidad INFANTIL (menores de 1). La de
    # menores de 5 incluye a la infantil más las muertes de 1 a 4 años, y ninguna
    # transformación las convierte.
    "SH.DYN.MORT": ("under5_mortality", "por 1.000 nacidos vivos"),

    # ══ LOTE 2026-08-19 · once series nacionales para el expediente de la END ══
    #
    # Cada una se comprobó ANTES de escribir este código, contra el oráculo que la propia
    # ley provee: la END declara valor y año de línea base, y una serie candidata que no
    # reproduce ese valor en ese año NO mide lo que el indicador dice medir. La sonda
    # (`modules/law_intel/sonda.py`) hace esa comprobación contra la fuente viva, en
    # segundos y sin desplegar. El Δ contra la base legal va anotado en cada una.
    #
    # SALVEDAD DE UBICACIÓN, declarada y no disimulada: `homicide_rate`, `tax_revenue_gdp`
    # y `gni_per_capita_atlas` NO son variables de desarrollo social. Viven acá porque este
    # es el eje que hoy ingiere series nacionales y las publica al registro con peso 0, que
    # es lo que el eje de leyes consume. Ninguna entra al IDM. Cuando exista un eje de
    # series nacionales de referencia, se mudan.
    "VC.IHR.PSRC.P5": ("homicide_rate", "por 100.000 habitantes"),          # 1.8  Δ 0,8%
    "SN.ITK.DEFC.ZS": ("undernourishment", "% de la población"),            # 2.27 Δ 1,4%
    # ANALFABETISMO en la ley, ALFABETIZACIÓN en la fuente: el binding declara
    # `complemento_100`. Comprobado: 100 − 89,54 = 10,46 contra una base legal de 10,5.
    # Esta serie es NACIONAL y por eso destraba el 2.19, que estaba demotado desde que se
    # descubrió que `literacy_rate` publicaba el valor de una sola región.
    "SE.ADT.LITR.ZS": ("literacy_rate_pais", "% de 15 años y más"),         # 2.19 Δ 0,4%
    # Las tres desnutriciones miden cosas DISTINTAS y ninguna transformación las convierte:
    # peso/edad (global), peso/talla (aguda) y talla/edad (crónica). Se atan por separado
    # porque la ley las fija por separado.
    "SH.STA.MALN.ZS": ("malnutrition_weight_age", "% de menores de 5"),     # 2.28 Δ 9,7%
    "SH.STA.WAST.ZS": ("malnutrition_weight_height", "% de menores de 5"),  # 2.29 Δ 4,5%
    "SH.STA.STNT.ZS": ("malnutrition_height_age", "% de menores de 5"),     # 2.30 Δ 3,1%
    # ⛔ NO se descargan `SH.STA.BASS.ZS` (2.34) ni `SH.H2O.BASW.ZS` (2.35). La sonda las
    #    dio «cerca» (Δ 2,3% y 8,8%) y el expediente YA las tenía descartadas, con un
    #    argumento que la sonda no puede ver: el JMP cambió su escala en 2015 —«mejorados»,
    #    que es lo que la ley nombra, pasó a «al menos básicos»— y la cercanía de niveles es
    #    JUSTAMENTE lo que haría pasar ese cambio de definición por un dato comparable.
    #    Queda acá escrito para que el próximo barrido no las vuelva a proponer.
    # El emisor publica 0-100 y la ley fija 0-1: el binding declara `centesimal`. NO se
    # divide acá — guardaríamos un número que ya no es el que el Banco Mundial publica.
    "SI.POV.GINI": ("gini_index", "índice 0-100"),                          # 2.7  Δ 3,5%

    # ══ LOTE 2026-08-21 · dos que el barrido con la sonda dejó en pie ══
    #
    # De catorce candidatos del Banco Mundial barridos contra el oráculo de la ley, doce se
    # cayeron por CONCEPTO y no por plomería: bruto contra neto (2.8, 3.10), incidencia
    # contra mortalidad (2.24), universos distintos (2.31, 2.32, 2.47, 2.48), área de bosque
    # contra tasa de deforestación (4.3). Quedan estas dos, y las dos van con salvedad
    # porque el año de la línea base NO está en la serie — se dice acá y se repite en el
    # binding, que es lo que llega al informe.
    #
    # `SE.XPD.TOTL.GD.ZS` es «gasto público en educación como % del PIB», literalmente el
    # indicador 2.20. La serie no trae 2009 (la base legal) y da 1,89 en 2010 contra 2,2 —
    # compatible con un año de diferencia en un indicador que se movía.
    "SE.XPD.TOTL.GD.ZS": ("public_education_spending", "% del PIB"),        # 2.20 sin 2009
    # `ER.LND.PTLD.ZS` son áreas protegidas TERRESTRES como % de la superficie. La serie
    # empieza en 2013 (22,3) contra una base legal de 24,4 en 2009. La meta de la ley es
    # PLANA —24,4 en los cuatro cortes—, así que el indicador pide sostener, no crecer.
    "ER.LND.PTLD.ZS": ("protected_areas", "% de la superficie terrestre"),  # 4.2  desde 2013
    "GC.TAX.TOTL.GD.ZS": ("tax_revenue_gdp", "% del PIB"),                  # 3.25 Δ 6,0%
    "NY.GNP.PCAP.CD": ("gni_per_capita_atlas", "US$ corrientes"),           # 3.26 Δ 5,4%
}
HEALTH_ENTITY = "nacional"
_WDI_HEALTH_YEARS = 30

# Informalidad nacional (ENCFT del BCRD) → aplicada a todas las regiones, como la salud
# del WDI. Es la variable exacta del IDM, no un proxy.
INFORMALITY_UNIT = "% de la población ocupada"
# Ingreso per cápita POR REGIÓN (SISDOM del MEPyD). Dejó de ser nacional: ver
# :mod:`shared.data.sisdom_income`.
INCOME_THEME = "income_per_capita"
SCHOOLING_THEME = "schooling_years"
COVERAGE_THEME = "secondary_coverage"  # ONE net secondary-coverage by region + period
COVERAGE_UNIT = "% (cobertura neta secundaria)"  # ≤40 chars: sd_indicators.unit VARCHAR(40)

# Series PROVINCIALES (SIUBEN, 32 provincias). Se derivan del catálogo del conector
# para que el resumen de la operación liste lo que realmente sincronizó.
SIUBEN_THEMES = tuple(s.theme for s in SIUBEN_DATASETS)

# National financial inclusion (World Bank Findex): ATMs per 100k adults — an annual
# access PROXY (denser than the sparse account-ownership survey). Closes the IDM's
# last rubric variable. National, applied to every region like WDI health.
WB_FINDEX = {"FB.ATM.TOTL.P5": "financial_inclusion"}
FINDEX_UNIT = "cajeros/100k (proxy acceso BM)"  # ≤40 chars: sd_indicators.unit
_WB_FINDEX_YEARS = 25  # ATMs/100k spans 2004-2023 (≤25)


def _upsert_indicator(db: Session, *, theme, entity, period, value, source, disagg, unit) -> None:
    existing = (
        db.query(SocialIndicator)
        .filter_by(entity_key=entity, theme=theme, period=period)
        .first()
    )
    row = existing or SocialIndicator(theme=theme, entity_key=entity, period=period)
    row.value = value
    row.unit = unit
    row.disaggregation = disagg
    row.source = source
    if not existing:
        db.add(row)


def _sync_wdi_health(db: Session, set_phase: Callable[[str], None]) -> int:
    """Series nacionales del WDI → ``sd_indicators`` (entidad ``nacional``).

    Dos grupos con el mismo cliente y distinta finalidad: las de SALUD alimentan el índice
    y se aplican a las diez regiones; las de `WDI_NACIONALES_FUERA_DEL_INDICE` no lo
    alimentan y existen para consumidores propios —hoy, el indicador 3.13 de la END."""
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("salud nacional (WDI)")
    synced = 0
    for code, theme in WDI_HEALTH.items():
        try:
            rows, _ = fetch_wb_indicator(code, ["DOM"], mrv=_WDI_HEALTH_YEARS)
        except Exception as e:  # noqa: BLE001 — best-effort per indicator
            logger.warning("[social] WDI %s falló: %s", code, e)
            continue
        unit = "años" if theme == "life_expectancy" else "por 1.000 nacidos vivos"
        for r in rows:
            yr, val = r.get("date"), r.get("value")
            if not yr or val is None:
                continue
            _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(yr),
                              value=float(val), source="WDI", disagg="nacional", unit=unit)
            synced += 1

    # Series nacionales que no alimentan el índice. Van en el MISMO sub-sync porque
    # comparten cliente, entidad y modo de fallo: separarlas sería una segunda ruta que
    # mantener por una diferencia que no es de ingesta sino de uso.
    for code, (theme, unit) in WDI_NACIONALES_FUERA_DEL_INDICE.items():
        try:
            rows, _ = fetch_wb_indicator(code, ["DOM"], mrv=_WDI_HEALTH_YEARS)
        except Exception as e:  # noqa: BLE001 — best-effort per indicator
            logger.warning("[social] WDI %s falló: %s", code, e)
            continue
        for r in rows:
            yr, val = r.get("date"), r.get("value")
            if not yr or val is None:
                continue
            _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(yr),
                              value=float(val), source="WDI", disagg="nacional", unit=unit)
            synced += 1
    return synced


def _sync_bcrd_informality(db: Session, set_phase: Callable[[str], None]) -> int:
    """Informalidad laboral desde la FUENTE PRIMARIA (ENCFT del BCRD, CDN público).

    Reemplaza el raspado de la landing de la ONE, que dejó de funcionar cuando el
    portal quedó tras un desafío de Cloudflare. La ONE no producía este dato: lo
    republicaba. Verificado contra la serie anterior — 55.47% contra 55.46% en 2024,
    coinciden en la centésima, así que es el mismo indicador y no uno parecido."""
    from shared.data.bcrd_labor import LICENSE, SOURCE, fetch_bcrd_informality

    set_phase("informalidad laboral (BCRD · ENCFT)")
    rows = fetch_bcrd_informality()   # la excepción sube a _best_effort
    synced = 0
    for year, value in rows:
        _upsert_indicator(db, theme="informality_rate", entity=HEALTH_ENTITY,
                          period=str(year), value=float(value), source=SOURCE,
                          disagg="nacional", unit=INFORMALITY_UNIT)
        synced += 1
    logger.info("[social] informalidad BCRD: %d años (%s)", synced, LICENSE[:40])
    return synced


#: Las tres series del mercado laboral que la END 1-12 fija y que NO alimentan el índice
#: de desarrollo. Se ingieren igual porque son dato real del emisor primario y tienen un
#: consumidor propio —el eje de evaluación de leyes—, y se exponen con peso 0.
#:
#: `unit` distingue lo que el nombre esconde: las brechas son RAZONES (adimensionales), no
#: porcentajes. Servir 2,7 con unidad «%» invitaría a leer «2,7% de brecha» cuando dice que
#: la desocupación femenina es 2,7 VECES la masculina.
_MERCADO_LABORAL = {
    "unemployment_rate": ("tasa de desocupación (BCRD · ENCFT)", "%"),
    "employment_gender_ratio": ("razón de ocupación femenina/masculina", "razón"),
    "unemployment_gender_ratio": ("razón de desocupación femenina/masculina", "razón"),
}


def _sync_bcrd_mercado_laboral(db: Session, set_phase: Callable[[str], None]) -> int:
    """Desocupación y brechas de género de la ENCFT, del CDN del BCRD.

    Baja el libro UNA vez para las tres series —y para la informalidad, que ya se ingería
    aparte— en vez de pagar cuatro descargas del mismo archivo.

    Las dos brechas son RAZONES femenina/masculina, computadas en el conector a partir del
    promedio anual de cada sexo. La cuenta se hace en código y no la deriva nadie después:
    es exactamente la clase de relación que esta plataforma computa y el modelo copia.
    """
    from shared.data.bcrd_labor import LICENSE, SOURCE, fetch_bcrd_labor_market

    set_phase("mercado laboral (BCRD · ENCFT)")
    series = fetch_bcrd_labor_market()   # la excepción sube a _best_effort
    synced = 0
    for tema, (_etiqueta, unidad) in _MERCADO_LABORAL.items():
        for year, value in series.get(tema, ()):
            _upsert_indicator(db, theme=tema, entity=HEALTH_ENTITY, period=str(year),
                              value=float(value), source=SOURCE, disagg="nacional",
                              unit=unidad)
            synced += 1
    logger.info("[social] mercado laboral BCRD: %d puntos en %d series (%s)",
                synced, len(_MERCADO_LABORAL), LICENSE[:40])
    return synced


#: Participación política de las mujeres en gobiernos locales (CEPAL · OIG). Los produce
#: la JCE y no hay fuente abierta nacional: se verificó contra `datos.gob.do` y no existe.
#: La CEPAL los recoge del propio organismo electoral y los publica con API abierta.
_CEPAL_POLITICA = {
    "women_mayors": ("IND_ALCALDESAS", "síndicas (alcaldesas) electas"),
    "women_councillors": ("IND_CONCEJALAS", "regidoras (concejalas) electas"),
}


def _sync_cepal_politica(db: Session, set_phase: Callable[[str], None]) -> int:
    """Síndicas y regidoras (CEPAL · Observatorio de Igualdad de Género) → indicadores
    2.45 y 2.46 de la END.

    Va en su propia sub-sync y no dentro de la del WDI: es otro emisor, con otro modo de
    fallo, y juntarlas haría que una caída de la CEPAL se leyera como un problema del
    Banco Mundial.

    La serie es ESCALONADA —un cargo electivo no cambia hasta la próxima elección— así que
    el valor se repite entre comicios. No es dato viejo: es la forma del fenómeno.
    """
    from shared.data import cepalstat_client as cep

    set_phase("participación política local (CEPAL · OIG)")
    synced = 0
    for tema, (const, etiqueta) in _CEPAL_POLITICA.items():
        try:
            filas = cep.fetch_serie(getattr(cep, const))
        except Exception as e:  # noqa: BLE001 — un indicador que falla no aborta el otro
            logger.warning("[social] CEPAL %s falló: %s", etiqueta, e)
            continue
        for anio, valor in filas:
            _upsert_indicator(db, theme=tema, entity=HEALTH_ENTITY, period=str(anio),
                              value=float(valor), source=cep.SOURCE, disagg="nacional",
                              unit="% de los cargos")
            synced += 1
    return synced


#: Umbrales que la propia ley fija en el TEXTO de los indicadores 2.2 y 2.5. No son
#: parámetros nuestros: «número de regiones con pobreza extrema mayor que 5%» y «…moderada
#: mayor que 20%». Cambiarlos sería medir otro indicador.
#: Procedencia de los conteos derivados. Va en CONSTANTE y corta: `sd_indicators.source` es
#: `varchar(40)` y la primera versión —«ONE (cómputo SDQ sobre el panel regional)»— medía 41.
#: SQLite no valida el largo y Postgres sí, así que los tests pasaron en verde y producción
#: devolvió `StringDataRightTruncation` al comitear. Es la misma lección que este repo ya
#: pagó con `mm_series`.
FUENTE_CONTEO = "ONE · cómputo SDQ"

UMBRAL_EXTREMA = 5.0
UMBRAL_MODERADA = 20.0


def _sync_exportaciones_per_capita(db: Session, set_phase: Callable[[str], None]) -> int:
    """Exportaciones per cápita (indicador 3.21 de la END) — cociente de dos series del WDI.

    Es de BIENES Y SERVICIOS, no solo mercancías, y no se adivinó: la ley fija 1.070 US$ para
    2009, la serie de bienes+servicios da 1.049 ese año (Δ 1,9%) y la de mercancías da 174.
    Comprobado con la sonda antes de escribir esta función.

    Se computa acá y no en el binding porque un binding ata UNA variable a un indicador; un
    cociente entre dos series es un dato nuevo, y como tal se ingiere con su procedencia.
    """
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("exportaciones per cápita (WDI)")
    exp, _ = fetch_wb_indicator("NE.EXP.GNFS.CD", ["DOM"], mrv=_WDI_HEALTH_YEARS)
    pob, _ = fetch_wb_indicator("SP.POP.TOTL", ["DOM"], mrv=_WDI_HEALTH_YEARS)
    e = {r["date"]: r["value"] for r in exp if r.get("value") is not None}
    p = {r["date"]: r["value"] for r in pob if r.get("value") is not None}
    synced = 0
    # Solo los años con AMBAS: un cociente con un denominador ausente no es un dato parcial,
    # es un número inventado.
    for anio in sorted(set(e) & set(p)):
        if not p[anio]:
            continue
        _upsert_indicator(db, theme="exports_per_capita", entity=HEALTH_ENTITY, period=str(anio),
                          value=float(e[anio]) / float(p[anio]), source="WDI, Banco Mundial",
                          disagg="nacional", unit="US$ corrientes por habitante")
        synced += 1
    return synced


#: Qué universo mundial usa cada indicador de participación exportadora, y con qué serie de
#: composición se recorta. El universo NO se adivinó: se probó cada candidato contra la
#: ventana que la ley promedia, que es el método que ya había resuelto el 3.21.
#:
#: El 3.18 dice «exportaciones mundiales de BIENES», no de bienes y servicios. La diferencia
#: no es de matiz: con bienes y servicios el promedio de la ventana da Δ 34,8% contra la línea
#: base legal; con mercancías, Δ 0,4%.
#: El 3.20 lleva DOS series de composición y no una, y ahí estaba el error que lo mantuvo
#: descartado. «Productos agropecuarios» no es una categoría del emisor: es la unión de dos
#: —alimentos y materias primas agrícolas— y unir cuotas NO es sumarlas. Cada cuota tiene su
#: propio denominador mundial, así que sumar 0,1183% y 0,0169% da 0,1352%, un número que no
#: significa nada. La unión se computa sobre los NIVELES: (DR_alim + DR_mat) / (mundo_alim +
#: mundo_mat). Hecho así, la ventana 2006-2007 da 0,0994% contra una base legal de 0,097.
PARTICIPACION_EXPORTADORA = {
    "3.18": ("world_export_share_goods", (),
             "% de las exportaciones mundiales de bienes"),
    "3.19": ("world_export_share_manufactures", ("TX.VAL.MANF.ZS.UN",),
             "% de las exportaciones mundiales de manufacturas"),
    "3.20": ("world_export_share_agri", ("TX.VAL.FOOD.ZS.UN", "TX.VAL.AGRI.ZS.UN"),
             "% de las exportaciones mundiales agropecuarias"),
}
FUENTE_PARTICIPACION = "WDI · cómputo SDQ"     # 18


def _sync_participacion_exportadora(db: Session,
                                    set_phase: Callable[[str], None]) -> int:
    """Indicadores 3.18, 3.19 y 3.20 de la END: participación dominicana en el comercio mundial.

    Es un cociente entre el país y el mundo, así que se ingiere como dato propio con su
    procedencia: un binding ata UNA variable y no puede llevar una división.

    **Una composición puede necesitar VARIAS series, y entonces se unen por NIVELES.** Es lo
    que destrabó el 3.20. Cada cuota que publica el emisor tiene su propio denominador
    mundial, así que sumarlas produce un número sin significado: alimentos da 0,1183% del
    mercado mundial de alimentos y materias primas agrícolas 0,0169% del suyo, y «0,1352%» no
    es la cuota de nada. La unión correcta divide la suma de los numeradores por la suma de
    los denominadores, y es lo que hace este bucle.

    Solo se publican los años con TODAS las series presentes. Un cociente al que le falta el
    denominador —o una de las series de composición— no es un dato parcial, es un número
    inventado.
    """
    from shared.data.wdi_client import fetch_wb_indicator

    def _serie(code: str, pais: str) -> Dict[str, float]:
        filas, _ = fetch_wb_indicator(code, [pais], mrv=_WDI_HEALTH_YEARS)
        return {r["date"]: float(r["value"]) for r in filas if r.get("value") is not None}

    set_phase("participación en el comercio mundial (indicadores 3.18 y 3.19)")
    pais = _serie("TX.VAL.MRCH.CD.WT", "DOM")
    mundo = _serie("TX.VAL.MRCH.CD.WT", "WLD")
    synced = 0
    for _ind, (tema, composiciones, unidad) in PARTICIPACION_EXPORTADORA.items():
        cps = [_serie(c, "DOM") for c in composiciones]
        cms = [_serie(c, "WLD") for c in composiciones]
        años = set(pais) & set(mundo)
        for d in cps + cms:
            años &= set(d)
        for anio in sorted(años):
            if composiciones:
                num = sum(pais[anio] * c[anio] / 100.0 for c in cps)
                den = sum(mundo[anio] * c[anio] / 100.0 for c in cms)
            else:
                num, den = pais[anio], mundo[anio]
            if not den:
                continue
            _upsert_indicator(db, theme=tema, entity=HEALTH_ENTITY, period=str(anio),
                              value=num / den * 100.0, source=FUENTE_PARTICIPACION,
                              disagg="nacional", unit=unidad)
            synced += 1
    return synced


#: Mes que representa el año para la cobertura del Seguro Familiar de Salud. Es un STOCK
#: —personas protegidas a una fecha— y por eso el año se representa por su CIERRE, no por el
#: promedio de sus doce meses, que es la convención de un flujo.
#:
#: La decisión se tomó POR PRINCIPIO y antes de mirar el resultado, y conviene que quede
#: escrito: los doce valores de 2010 van de 36,2% a 44,9% de la población, así que existe un
#: mes que reproduce la línea base legal casi exacto. Elegirlo habría sido ajustar el método
#: al oráculo, que es la forma más limpia de fabricar una verificación.
MES_DE_CIERRE = "12"

FUENTE_SFS = "CNSS · cómputo SDQ"        # 22


def _sync_cobertura_salud(db: Session, set_phase: Callable[[str], None]) -> int:
    """Indicador 2.36 de la END: porcentaje de población protegida por el Seguro de Salud.

    El emisor publica el CONTEO de afiliados, mensual desde 2007, y no el porcentaje: se
    comprobó contra su portal y contra el catálogo nacional de datos abiertos. El denominador
    es decisión nuestra y por eso viaja declarado.

    **Población del WDI y no el censo.** El censo de 2010 es un punto y el indicador necesita
    una serie anual completa. La elección mueve la cifra —con el censo, la cobertura de 2010
    sube de 44,9% a 46,6%— y por eso se declara en vez de resolverse en silencio.

    Contra el oráculo: diciembre de 2010 da 44,86% frente a los 42,4% que fija la ley, Δ 5,8%.
    """
    import json
    import urllib.request

    from shared.data.sisalril_client import SISALRILClient

    set_phase("cobertura del Seguro Familiar de Salud (indicador 2.36 de la END)")
    recs = SISALRILClient(mode="live").fetch(series="sfs.afiliacion.total")
    afiliados = {r.period[:4]: float(r.value) for r in recs
                 if r.value is not None and r.period[5:7] == MES_DE_CIERRE}

    u = ("https://api.worldbank.org/v2/country/DOM/indicator/SP.POP.TOTL"
         "?format=json&per_page=100")
    req = urllib.request.Request(u, headers={"User-Agent": "SDQ-MarketIntelligence/1.0"})
    with urllib.request.urlopen(req, timeout=60) as fh:
        datos = json.load(fh)
    poblacion = {x["date"]: x["value"] for x in (datos[1] or []) if x.get("value")}

    synced = 0
    # Solo los años con AMBAS. Un cociente con el denominador ausente no es un dato parcial.
    for anio in sorted(set(afiliados) & set(poblacion)):
        _upsert_indicator(db, theme="health_insurance_coverage", entity=HEALTH_ENTITY,
                          period=anio, value=afiliados[anio] / poblacion[anio] * 100.0,
                          source=FUENTE_SFS, disagg="nacional",
                          unit="% de la población, a diciembre")
        synced += 1
    return synced


#: Cómo nombra el emisor cada línea y qué indicador de la END alimenta. El SUJETO viaja en el
#: tema: son cifras de la ZONA RURAL, no del país.
POBREZA_RURAL = {
    "indigencia": ("rural_poverty_extreme", "% de la población rural"),   # 2.3
    "pobreza": ("rural_poverty_total", "% de la población rural"),        # 2.6
}
FUENTE_SISDOM_ZONA = "SISDOM · MEPyD"          # 17


def _sync_pobreza_rural(db: Session, set_phase: Callable[[str], None]) -> int:
    """Indicadores 2.3 y 2.6 de la END: pobreza rural extrema y general.

    El panel abierto que ya se ingiere está por REGIÓN y no por zona, así que ninguna
    combinación de sus filas produce la cifra rural. El corte por zona vive en el cuadro
    03 3 003a del SISDOM.

    El emisor llama «indigencia» a la pobreza extrema. La correspondencia no se supuso: la
    indigencia rural de 2010 da 16,76 contra los 16,9 que la ley fija para el 2.3, Δ 0,8%.

    **La serie tiene un quiebre de metodología en 2016** y el emisor lo declara publicando ese
    año dos veces. El cliente sirve la metodología vigente y expone el salto medido; el binding
    lo lleva escrito. Encadenar los tramos sin declararlo sería repetir lo de la informalidad.
    """
    from shared.data.sisdom_pobreza_zona import fetch_zona_rural

    set_phase("pobreza rural por zona (SISDOM · indicadores 2.3 y 2.6)")
    series, quiebre = fetch_zona_rural()
    if quiebre.get("anio_de_solape"):
        logger.info("SISDOM pobreza rural: quiebre en %s, salto %s",
                    quiebre["anio_de_solape"], quiebre.get("salto_pct"))
    synced = 0
    for linea, (tema, unidad) in POBREZA_RURAL.items():
        for periodo, valor in series.get(linea, []):
            _upsert_indicator(db, theme=tema, entity=HEALTH_ENTITY, period=str(periodo),
                              value=float(valor), source=FUENTE_SISDOM_ZONA,
                              disagg="nacional", unit=unidad)
            synced += 1
    return synced


def _sync_razon_exportaciones_importaciones(db: Session,
                                            set_phase: Callable[[str], None]) -> int:
    """Indicador 3.22 de la END: razón exportaciones sobre importaciones de bienes y servicios.

    Se computa acá y no en el binding por la misma razón que las exportaciones per cápita: un
    binding ata UNA variable a un indicador y no puede llevar una división. Un cociente entre
    dos series es un dato nuevo y como tal se ingiere, con su procedencia.

    **La ventana promediada fue lo que lo destrabó.** La ley fecha la línea base como
    «2005-2010», sin un año, así que la sonda no tenía contra qué contrastar. Promediando la
    ventana completa da 0,7429 contra los 0,75 que fija la ley —Δ 0,9%— y ningún año suelto
    cae dentro de la tolerancia: la razón se mueve de 0,639 a 0,850 dentro de esos seis años.
    La coincidencia discrimina porque la serie NO es plana.

    Solo se publican los años con AMBAS series: un cociente con un denominador ausente no es
    un dato parcial, es un número inventado.
    """
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("razón exportaciones/importaciones (indicador 3.22 de la END)")
    exp, _ = fetch_wb_indicator("NE.EXP.GNFS.CD", ["DOM"], mrv=_WDI_HEALTH_YEARS)
    imp, _ = fetch_wb_indicator("NE.IMP.GNFS.CD", ["DOM"], mrv=_WDI_HEALTH_YEARS)
    e = {r["date"]: r["value"] for r in exp if r.get("value") is not None}
    i = {r["date"]: r["value"] for r in imp if r.get("value") is not None}
    synced = 0
    for anio in sorted(set(e) & set(i)):
        if not i[anio]:
            continue
        _upsert_indicator(db, theme="exports_imports_ratio", entity=HEALTH_ENTITY,
                          period=str(anio), value=float(e[anio]) / float(i[anio]),
                          source="WDI, Banco Mundial", disagg="nacional",
                          unit="razón (1,0 = equilibrio)")
        synced += 1
    return synced


def _sync_gei_per_capita(db: Session, set_phase: Callable[[str], None]) -> int:
    """Indicador 4.1 de la END: emisiones per cápita, en toneladas de CO2 equivalente.

    **El oráculo identificó el CONCEPTO, que es lo que estaba mal.** La ley titula el
    indicador «Emisiones de dióxido de carbono» y fija 3,6 para 2010, y ese nombre mandó a
    atarlo al CO2 solo — que da 2,131 y se descartó por un 41% de diferencia. El nombre
    miente: contrastando las tres magnitudes candidatas contra la línea base, sólo una cierra.

        CO2 solo, per cápita                          2,131   Δ 40,8%   descartar
        todos los GEI sin uso de la tierra            3,415   Δ  5,1%   con salvedad
        todos los GEI INCLUYENDO uso de la tierra     3,639   Δ  1,1%   ← la que la ley usó

    Es el mismo método con el que la ventana promediada identificó el universo del 3.18: se
    prueban los candidatos contra la cifra que el legislador escribió y la que la reproduce
    dice qué quiso medir. Lo que discrimina acá es el CONCEPTO y no el año — la serie es casi
    plana entre 2010 y 2014, así que 2013 y 2014 también rondan 3,6. La ley fija 2010 y 2010
    cierra; el resto es coincidencia de una meseta y así queda dicho.

    Se computa acá y no en el binding por lo mismo que el 3.22: un binding ata UNA variable y
    no puede llevar una división. El emisor publica el total en megatoneladas y la ley fija la
    meta per cápita, así que el cociente es un dato nuevo y se ingiere con su procedencia.

    Solo se publican los años con AMBAS series.
    """
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("emisiones per cápita (indicador 4.1 de la END)")
    # Todos los GEI INCLUYENDO uso de la tierra (LULUCF), en Mt de CO2 equivalente, AR5.
    gei, _ = fetch_wb_indicator("EN.GHG.ALL.LU.MT.CE.AR5", ["DOM"], mrv=_WDI_HEALTH_YEARS)
    pob, _ = fetch_wb_indicator("SP.POP.TOTL", ["DOM"], mrv=_WDI_HEALTH_YEARS)
    g = {r["date"]: r["value"] for r in gei if r.get("value") is not None}
    p = {r["date"]: r["value"] for r in pob if r.get("value") is not None}
    synced = 0
    for anio in sorted(set(g) & set(p)):
        if not p[anio]:
            continue
        _upsert_indicator(db, theme="ghg_per_capita", entity=HEALTH_ENTITY,
                          period=str(anio), value=float(g[anio]) * 1e6 / float(p[anio]),
                          source="WDI, Banco Mundial", disagg="nacional",
                          unit="t CO2e per cápita")
        synced += 1
    return synced


#: Fuente de los niveles LLECE. Corta a propósito: `sd_indicators.source` es varchar(40).
FUENTE_LLECE = "LLECE/UNESCO"
#: Materia y grado del indicador 2.17 de la END: matemáticas de 6to grado.
LLECE_2_17 = ("Matematicas", "6")


def _sync_llece_niveles(db: Session, set_phase: Callable[[str], None]) -> int:
    """Indicador 2.17 de la END: % de alumnos en o por debajo del nivel II, matemáticas 6º.

    Es el ÚNICO de los seis indicadores LLECE de la ley que sobrevive al cambio de escala,
    porque es el único que el legislador escribió en PORCENTAJE DE ALUMNOS POR NIVEL. Los
    otros cinco fijan puntajes en la escala de SERCE 2006 (media 500) y el LLECE publica desde
    2013 con media 700: no hay puente y construirlo sería inventar la conversión.

    El cliente sirve NIVELES y nunca puntajes, a propósito — ver su docstring.
    """
    from shared.data.llece_client import fetch_bajo_nivel_ii

    set_phase("niveles LLECE (indicador 2.17 de la END)")
    materia, grado = LLECE_2_17
    synced = 0
    for periodo, valor in fetch_bajo_nivel_ii(materia, grado):
        _upsert_indicator(db, theme="llece_math6_bajo_nivel_ii", entity=HEALTH_ENTITY,
                          period=periodo, value=float(valor), source=FUENTE_LLECE,
                          disagg="nacional", unit="% de alumnos")
        synced += 1
    return synced


#: Procedencia del anexo del MEM. Corta a propósito: `sd_indicators.source` es varchar(40) y
#: una fuente de 41 caracteres tumba el commit entero en Postgres sin que SQLite lo note.
FUENTE_MEM = "MEM · anexo Informe de Desempeño"   # 32

#: Qué serie del anexo alimenta qué indicador de la END, y en qué unidad.
#:
#: **Las unidades entran en `varchar(40)` y eso NO es un detalle de estilo.** La primera
#: versión decía «% (índice de recuperación de efectivo, EDE agregadas)» —52 caracteres— y
#: producción devolvió `StringDataRightTruncation` al comitear, tumbando la sync entera. Es
#: la tercera vez que este repo paga el mismo peaje, y esta vez con el comentario sobre el
#: largo escrito tres líneas más arriba: lo puse en `source` y lo rompí en `unit`.
#:
#: El SUJETO viaja igual, en la etiqueta de la señal —«EDE agregadas»—, que no tiene tope.
MEM_TEMAS = {
    "cri": ("electric_cri_ede", "% de recuperación de efectivo"),
    "perdidas": ("electric_perdidas_ede", "% de la energía comprada"),
    "cobranzas": ("electric_cobranzas_ede", "% de lo facturado"),
}

#: Años de informe cuyo anexo de DICIEMBRE se pide. Cada uno trae tres años, así que la lista
#: se solapa a propósito: el solapamiento es lo que deja ver si el emisor revisó una cifra.
MEM_INFORMES = [2021, 2022, 2023, 2024, 2025]


def _sync_mem_electrico(db: Session, set_phase: Callable[[str], None]) -> int:
    """Indicadores 3.27, 3.28 y 3.29 de la END, del anexo del Informe de Desempeño del MEM.

    El emisor publica las tres magnitudes con los nombres que usa el legislador —el CRI viene
    literalmente como «Índice de Recuperación de Efectivo»— y agregadas para las tres
    distribuidoras estatales. Ese ES el universo del indicador: la ley mide el desempeño
    comercial de las EDE, no el del sector completo.

    Solo se leen los anexos de DICIEMBRE. Las columnas de los otros meses son acumuladas del
    año en curso, y publicar cuatro meses con el rótulo de doce no es una aproximación en un
    indicador estacional: es otro número. El cliente lo hace cumplir y rechaza el anexo que no
    declara un año completo.
    """
    from shared.data.mem_client import series_anuales

    set_phase("sector eléctrico (MEM · anexo del Informe de Desempeño)")
    series = series_anuales(MEM_INFORMES)
    synced = 0
    for clave, (tema, unidad) in MEM_TEMAS.items():
        for periodo, valor in series.get(clave, []):
            _upsert_indicator(db, theme=tema, entity=HEALTH_ENTITY, period=periodo,
                              value=float(valor), source=FUENTE_MEM,
                              disagg="nacional", unit=unidad)
            synced += 1
    return synced


def _sync_conteos_regionales(db: Session, set_phase: Callable[[str], None]) -> int:
    """Indicadores 2.2 y 2.5: cuántas REGIONES superan el umbral que la ley fija.

    El dato de entrada es el panel por región que ya ingerimos — el mismo que NO sirve para
    las metas nacionales de pobreza (2.1 y 2.4), porque el registro publicaría el valor de
    una sola demarcación. Acá es exactamente lo que hace falta: un conteo entre regiones ES
    una cifra del país.

    **El guard que importa: solo se cuenta un año con las DIEZ regiones presentes.** Con
    nueve, el conteo baja porque falta un dato, no porque una región haya cruzado el umbral —
    y baja en la dirección de la meta, así que se leería como progreso. Es la forma más
    silenciosa de fabricar una mejora, y el único aviso sería que nadie la note.

    Se valida contra el oráculo de la propia ley: en 2010 las diez regiones superaban el 20%
    de pobreza moderada, y la línea base legal del 2.5 es exactamente 10.
    """
    from modules.social_dev.models.models import SocialIndicator
    from shared.data.one_client import region_catalog

    set_phase("conteos regionales de pobreza (2.2 y 2.5 de la END)")
    regiones = {slug for slug, _ in region_catalog()}
    synced = 0
    for tema, umbral, destino in (
        ("poverty_extreme", UMBRAL_EXTREMA, "regiones_pobreza_extrema_sobre_umbral"),
        ("poverty_rate", UMBRAL_MODERADA, "regiones_pobreza_moderada_sobre_umbral"),
    ):
        filas = (db.query(SocialIndicator.period, SocialIndicator.entity_key,
                          SocialIndicator.value)
                 .filter(SocialIndicator.theme == tema,
                         SocialIndicator.value.isnot(None),
                         SocialIndicator.entity_key.in_(regiones))
                 .all())
        por_anio: Dict[str, Dict[str, float]] = {}
        for periodo, entidad, valor in filas:
            por_anio.setdefault(str(periodo), {})[entidad] = float(valor)
        completos = incompletos = 0
        for periodo, vals in sorted(por_anio.items()):
            if len(vals) < len(regiones):
                incompletos += 1
                continue
            completos += 1
            _upsert_indicator(
                db, theme=destino, entity=HEALTH_ENTITY, period=periodo,
                value=float(sum(1 for v in vals.values() if v > umbral)),
                source=FUENTE_CONTEO, disagg="nacional",
                unit="número de regiones")
            synced += 1
        if incompletos:
            # Se registra: un año descartado por panel incompleto es una brecha declarada,
            # no un año sin dato del Estado.
            logger.info("social: %s — %d años completos, %d descartados por panel incompleto",
                        destino, completos, incompletos)
    return synced


def _sync_ipu_senado(db: Session, set_phase: Callable[[str], None]) -> int:
    """Mujeres en el Senado (UIP · Parline) → indicador 2.43 de la END.

    Sub-sync propia: es el cuarto emisor distinto de los cuatro cargos electivos, y juntarla
    con otra haría que su caída se leyera como problema del vecino.
    """
    from shared.data.ipu_parline_client import SOURCE, fetch_senado

    set_phase("mujeres en el Senado (UIP · Parline)")
    filas = fetch_senado()   # la excepción sube a _best_effort
    synced = 0
    for anio, valor in filas:
        _upsert_indicator(db, theme="women_senate", entity=HEALTH_ENTITY, period=str(anio),
                          value=float(valor), source=SOURCE, disagg="nacional",
                          unit="% de los escaños")
        synced += 1
    return synced


def _sync_sisdom_income(db: Session, set_phase: Callable[[str], None]) -> int:
    """Ingreso per cápita POR REGIÓN (SISDOM del MEPyD) → ``sd_indicators``.

    Reemplaza el ingreso laboral por hora de la ONE, que era un PROXY declarado, nacional
    y —desde Cloudflare— inalcanzable. El cuadro ``03 3 021`` es la variable exacta del
    IDM (ingreso familiar mensual por persona), anual 2000-2024 y abierta por las 10
    regiones de desarrollo. La variable deja de ser una constante con etiqueta geográfica.

    **A diferencia de las demás sub-syncs, esta BORRA algo**: las filas nacionales que
    dejó el proxy de la ONE. No es limpieza cosmética. Conviven bajo el mismo tema una
    cifra en RD$/hora (~167) y otra en RD$/mes por persona (~18.000): dos órdenes de
    magnitud y dos unidades. Cualquier lectura futura que caiga en la vieja —un fallback
    a ``nacional``, un promedio, una serie de la Data API— devolvería un disparate sin
    que nada avise. El upsert normal no las alcanza porque cambió la entidad, así que
    quedarían ahí para siempre. Se borra solo lo que este cambio deja obsoleto: tema
    ingreso + entidad nacional + fuente ONE."""
    from shared.data.sisdom_income import SOURCE as SISDOM_SOURCE
    from shared.data.sisdom_income import UNIT, fetch_sisdom_income_per_capita

    set_phase("ingreso per cápita por región (SISDOM · MEPyD)")
    rows = fetch_sisdom_income_per_capita()   # la excepción sube a _best_effort
    if not rows:
        return 0

    synced = 0
    for slug, year, value in rows:
        _upsert_indicator(db, theme=INCOME_THEME, entity=slug, period=str(year),
                          value=float(value), source=SISDOM_SOURCE,
                          disagg="region", unit=UNIT)
        synced += 1

    # Solo después de que la fuente nueva TRAJO dato: si fallara, el borrado dejaría la
    # variable sin nada. El orden importa.
    stale = (
        db.query(SocialIndicator)
        .filter(SocialIndicator.theme == INCOME_THEME,
                SocialIndicator.entity_key == HEALTH_ENTITY,
                SocialIndicator.source == "ONE")
        .delete(synchronize_session=False)
    )
    if stale:
        logger.info("[social] ingreso: %d filas nacionales del proxy ONE dadas de baja "
                    "(reemplazadas por %d regionales del SISDOM)", stale, synced)
    return synced


def _sync_sisdom_schooling(db: Session, set_phase: Callable[[str], None]) -> int:
    """Escolaridad promedio por región Y TOTAL PAÍS (SISDOM del MEPyD, cuadro 05 3 007).

    Reemplaza la serie NACIONAL de la ONE, que quedó tras Cloudflare y que —aun cuando
    llegaba— era la MISMA cifra para las diez regiones. Por región discrimina: en 2024
    Ozama promedia 10,29 años y Enriquillo 7,98, una brecha de 2,3 años que el número
    nacional escondía. Segunda constante nacional del IDM en caer, después del ingreso.

    Da de baja la fila nacional del proxy anterior: bajo el mismo tema convivirían el
    valor país y los diez regionales, y el upsert no la alcanza porque cambió la entidad.
    Corre DESPUÉS de que la fuente nueva trajo dato, así que una caída del MEPyD no
    destruye lo que hay."""
    from shared.data.sisdom_schooling import (COUNTRY_SLUG, SOURCE, UNIT,
                                              fetch_sisdom_schooling)

    set_phase("escolaridad por región y total país (SISDOM · MEPyD)")
    rows = fetch_sisdom_schooling()   # la excepción sube a _best_effort
    synced = 0
    for slug, year, value in rows:
        # El slug `pais` es la fila «Total» del cuadro y NO es una región. Va con su
        # propio `disaggregation` para que nada lo cuente como una demarcación más.
        #
        # Y va bajo la entidad `pais`, no `nacional`: esta última es la del proxy viejo
        # que este mismo sync da de baja unas líneas más abajo, y escribir ahí sería
        # borrar en el mismo paso lo que se acaba de traer. La distinción además dice
        # algo real — `nacional` marca series que sólo existen a nivel país (BCRD, WDI) y
        # `pais` la fila de total extraída de un cuadro sub-nacional.
        geo = "pais" if slug == COUNTRY_SLUG else "region"
        _upsert_indicator(db, theme=SCHOOLING_THEME, entity=slug, period=str(year),
                          value=float(value), source=SOURCE, disagg=geo, unit=UNIT)
        synced += 1
    if synced:
        borradas = (db.query(SocialIndicator)
                    .filter(SocialIndicator.theme == SCHOOLING_THEME,
                            SocialIndicator.entity_key == HEALTH_ENTITY)
                    .delete(synchronize_session=False))
        if borradas:
            logger.info("[social] escolaridad: %d filas nacionales dadas de baja "
                        "(ahora es por región)", borradas)
    return synced


def _sync_endesa_child_mortality(db: Session, set_phase: Callable[[str], None]) -> int:
    """Mortalidad infantil POR PROVINCIA (SISDOM `04 3 035b`, rondas ENDESA 2002 y 2007).

    Serie PUBLICADA, no variable del índice: el IDM sigue usando la serie anual viva de
    WDI. Entrarla al cálculo ganaría territorio y perdería vigencia — todo período
    posterior a 2007 quedaría con el mismo número, otra constante con etiqueta
    provincial. El tema lleva el nombre de la encuesta para que nadie la confunda con la
    serie del Banco Mundial: comparten concepto, no metodología.

    Que no toque el índice no depende de la buena voluntad: `assemble_idm_dataset` lee
    `child_mortality` de la entidad `nacional`, y esto escribe otro tema en entidades
    provinciales."""
    from shared.data.sisdom_child_mortality import (
        SOURCE, THEME, UNIT, fetch_endesa_child_mortality,
    )

    set_phase("mortalidad infantil por provincia (SISDOM · ENDESA)")
    rows = fetch_endesa_child_mortality()   # la excepción sube a _best_effort
    synced = 0
    for slug, year, value in rows:
        _upsert_indicator(db, theme=THEME, entity=slug, period=str(year),
                          value=float(value), source=SOURCE, disagg="provincia", unit=UNIT)
        synced += 1
    return synced


def _sync_minerd_coverage(db: Session, set_phase: Callable[[str], None],
                          provenance: Dict[str, str]) -> int:
    """Cobertura neta de secundaria por región Y por provincia → ``sd_indicators``.

    La fuente pasó de la planilla de la ONE al tablero del MINERD, que es quien produce
    el indicador: la ONE lo republicaba y su portal quedó tras un desafío de Cloudflare.
    El cambio también trae el desglose PROVINCIAL, que la planilla tenía y el parser
    anterior descartaba.

    Trae los DOS niveles educativos —básica (indicador 2.9 de la END) y secundaria
    (2.10)— y las TRES resoluciones geográficas, incluido el **total de país**, que el
    parser descartaba: sin él, un consumidor que compare contra una meta nacional termina
    usando la cifra de una región.

    Cada nivel educativo va a su propio tema; las resoluciones geográficas comparten tema
    y se distinguen por ``disaggregation``; los slugs provinciales nunca chocan con los regionales (fijado en
    ``shared/reference/tests/test_provinces.py``). Solo las filas regionales llegan al
    IDM: :func:`assemble_idm_dataset` itera el catálogo de regiones, así que agregar
    provincias no puede mover un score."""
    from shared.data.minerd_coverage import SOURCE as MINERD_SOURCE
    from shared.data.minerd_coverage import TEMA_POR_NIVEL, fetch_minerd_coverage_levels
    from shared.data.snapshots import live_or_snapshot

    set_phase("cobertura educativa básica y secundaria (MINERD · SIIE)")
    # El tablero Power BI limita por tasa y devuelve 400 sin aviso — le pasó también a
    # una máquina de trabajo minutos después de funcionar. La instantánea comiteada es el
    # camino offline que el propio shared/data/powerbi ya prescribe para esta API.
    rows, prov = live_or_snapshot("minerd_coverage_levels", fetch_minerd_coverage_levels,
                                  source=MINERD_SOURCE)
    for tema in TEMA_POR_NIVEL.values():
        provenance[tema] = prov
    synced = 0
    for nivel, geo, slug, year, value in rows:
        _upsert_indicator(db, theme=TEMA_POR_NIVEL[nivel], entity=slug, period=str(year),
                          value=float(value), source=MINERD_SOURCE, disagg=geo,
                          unit=COVERAGE_UNIT)
        synced += 1
    return synced


def _sync_siuben_provincial(db: Session, set_phase: Callable[[str], None],
                            provenance: Dict[str, str]) -> int:
    """Fetch the five SIUBEN provincial boards (32 provinces, quarterly since 2017) →
    ``sd_indicators`` with ``disaggregation='provincia'``.

    This is the first SUB-NATIONAL source of the axis. It does NOT feed the IDM: the
    index is assembled strictly over the 10 development regions
    (:func:`assemble_idm_dataset` iterates ``region_catalog()``), so these rows are
    additive and cannot shift a regional score. They exist to be served on their own —
    a consumer that ranks demarcations needs values that differ BETWEEN demarcations,
    which a national constant can never provide.

    The universe (the SIUBEN targeting registry, not the general population) travels in
    the series code and unit; see :mod:`shared.data.siuben_client`. Best-effort."""
    from shared.data.siuben_client import fetch_siuben_provincial, theme_spec
    from shared.data.snapshots import live_or_snapshot

    set_phase("indicadores provinciales (SIUBEN: 32 provincias)")
    # Producción NO alcanza siuben.gob.do (ConnectTimeout desde Railway) aunque el
    # descubrimiento por datos.gob.do sí llegue: es ese host, no la red. El respaldo se
    # captura donde la fuente responde (scripts/refresh_social_snapshots.py).
    rows, prov = live_or_snapshot("siuben_provincial", fetch_siuben_provincial,
                                  source=SIUBEN_SOURCE)
    provenance["siuben_provincial"] = prov
    if not rows:
        return 0

    # Prefetch instead of one SELECT per row: five boards × 32 provinces × ~38 quarters
    # is a few thousand upserts, and a round-trip each would make a background sync
    # needlessly slow against a remote Postgres.
    existing = {
        # ``str(...)`` en la frontera: estos modelos usan el estilo legacy de SQLAlchemy,
        # cuyo tipo estático es ``Column[str]`` y no ``str``.
        (str(r.entity_key), str(r.theme), str(r.period)): r
        for r in db.query(SocialIndicator).filter(SocialIndicator.source == SIUBEN_SOURCE).all()
    }
    synced = 0
    for theme, slug, period, value in rows:
        spec = theme_spec(theme)
        key = (slug, theme, period)
        row = existing.get(key)
        if row is None:
            row = SocialIndicator(theme=theme, entity_key=slug, period=period)
            db.add(row)
            existing[key] = row
        _apply_siuben_fields(row, value=value, unit=spec.unit if spec else None)
        synced += 1
    return synced


def _apply_siuben_fields(row, *, value: float, unit) -> None:
    """Asigna los campos de una observación del SIUBEN (frontera con el modelo legacy)."""
    row.value = float(value)
    row.unit = unit
    row.disaggregation = "provincia"
    row.source = SIUBEN_SOURCE


def _sync_wb_findex(db: Session, set_phase: Callable[[str], None]) -> int:
    """Fetch World Bank Findex financial-access (ATMs/100k adults) → sd_indicators
    (entity ``nacional``, applied to every region). Best-effort."""
    from shared.data.wdi_client import fetch_wb_indicator

    set_phase("inclusión financiera nacional (BM Findex: cajeros/100k)")
    synced = 0
    for code, theme in WB_FINDEX.items():
        try:
            rows, _ = fetch_wb_indicator(code, ["DOM"], mrv=_WB_FINDEX_YEARS)
        except Exception as e:  # noqa: BLE001 — best-effort per indicator
            logger.warning("[social] BM Findex %s falló: %s", code, e)
            continue
        for r in rows:
            yr, val = r.get("date"), r.get("value")
            if not yr or val is None:
                continue
            _upsert_indicator(db, theme=theme, entity=HEALTH_ENTITY, period=str(yr),
                              value=float(val), source="WB", disagg="nacional", unit=FINDEX_UNIT)
            synced += 1
    return synced


def _best_effort(label: str, fn: Callable[[], int], errors: List[str]) -> int:
    """Corre una sub-sincronización y DEJA RASTRO de por qué no trajo nada.

    Antes cada sub-sync se tragaba su excepción y devolvía 0, así que la operación
    terminaba con cuatro fuentes en cero y ``errors: []`` — un éxito aparente. Pasó de
    verdad: el 2026-08-09 el portal de la ONE y el SIUBEN devolvieron cero desde
    producción y la consola no lo dijo. Un guard que no reporta no protege: esconde.

    Las dos causas se distinguen a propósito, porque se actúan distinto:

    * **no se pudo llegar** (excepción) → problema nuestro o de red: hay que investigar;
    * **la fuente no devolvió nada** (cero sin excepción) → puede ser legítimo (el emisor
      no publicó todavía) y no amerita alarma, pero tiene que constar.
    """
    try:
        n = fn()
    except Exception as e:  # noqa: BLE001 — best-effort, pero NUNCA silencioso
        logger.warning("[social] %s falló: %s", label, e)
        errors.append(f"{label}: no se pudo obtener el dato ({type(e).__name__}: {e})")
        return 0
    if n == 0:
        errors.append(f"{label}: la fuente respondió sin observaciones")
    return n


def one_social_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Pull live social data (ONE poverty by region + WDI national health) and
    upsert into ``sd_indicators``. Best-effort; never raises on an upstream failure.
    """
    set_phase = set_phase or (lambda _m: None)
    from shared.data.one_client import ONEClient

    set_phase("descargando pobreza por regiones (ONE)")
    client = ONEClient(mode="live")
    try:
        records = list(client.fetch())
    except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
        logger.warning("ONE social sync falló: %s", e)
        return {"error": f"ONE no disponible: {e}", "synced": 0, "errors": [str(e)]}

    set_phase(f"persistiendo {len(records)} valores")
    synced = 0
    periods = set()
    errors: List[str] = []
    # Procedencia por fuente: 'live' o 'snapshot:AAAA-MM-DD'. Viaja SIEMPRE al resultado —
    # un respaldo usado en silencio es exactamente cómo un fallback se vuelve permanente.
    provenance: Dict[str, str] = {}
    for r in records:
        region, theme, period = r.dimension, r.series, r.period
        if not region or not period:
            errors.append(f"registro sin región/período: {theme}")
            continue
        periods.add(period)
        _upsert_indicator(db, theme=theme, entity=region, period=period,
                          value=r.value, source="ONE", disagg="region", unit=r.unit)
        synced += 1

    # ── DERIVADO, y TEMPRANO a propósito ────────────────────────────────────────────────
    # Los conteos de los indicadores 2.2 y 2.5 solo necesitan el panel regional que se acaba
    # de persistir arriba. Nada de lo que viene después los alimenta.
    #
    # Estuvieron al final, que parecía lo natural —«que lean todo lo escrito»— y era el peor
    # lugar posible: Railway REINICIA las tareas largas de este servicio, la sync muere
    # durante SIUBEN (3.456 filas provinciales) y todo lo no comiteado se pierde. Tres
    # corridas seguidas terminaron en «interrumpido por reinicio» sin llegar nunca acá.
    #
    # Con su propio commit, los conteos sobreviven a que el resto de la corrida se caiga. Es
    # la diferencia entre depender de que la sync entera termine y depender solo de su
    # primera fase.
    conteos_synced = _best_effort(
        "conteos regionales de pobreza (2.2 y 2.5)",
        lambda: _sync_conteos_regionales(db, set_phase), errors)
    # También temprano y con el mismo commit: no depende de nada posterior y así sobrevive a
    # que la corrida se caiga en una fase larga.
    llece_synced = _best_effort(
        "niveles LLECE (2.17)", lambda: _sync_llece_niveles(db, set_phase), errors)
    razon_synced = _best_effort(
        "razón exportaciones/importaciones (3.22)",
        lambda: _sync_razon_exportaciones_importaciones(db, set_phase), errors)
    rural_synced = _best_effort(
        "pobreza rural por zona (2.3 y 2.6)",
        lambda: _sync_pobreza_rural(db, set_phase), errors)
    gei_synced = _best_effort(
        "emisiones per cápita (4.1)",
        lambda: _sync_gei_per_capita(db, set_phase), errors)
    salud_synced = _best_effort(
        "cobertura del Seguro Familiar de Salud (2.36)",
        lambda: _sync_cobertura_salud(db, set_phase), errors)
    export_synced = _best_effort(
        "participación en el comercio mundial (3.18 y 3.19)",
        lambda: _sync_participacion_exportadora(db, set_phase), errors)
    # Mismo criterio: no depende de nada de esta corrida y entra antes del commit temprano.
    mem_synced = _best_effort(
        "sector eléctrico (MEM · 3.27, 3.28 y 3.29)",
        lambda: _sync_mem_electrico(db, set_phase), errors)
    db.commit()

    health_synced = _best_effort(
        "salud nacional (WDI)", lambda: _sync_wdi_health(db, set_phase), errors)
    informality_synced = _best_effort(
        "informalidad laboral (BCRD · ENCFT)",
        lambda: _sync_bcrd_informality(db, set_phase), errors)
    # El rótulo nombra al EMISOR, porque es lo que se lee en la consola cuando algo
    # falla: decir "(ONE)" de un dato que ahora produce otro organismo mandaría a mirar
    # el portal equivocado.
    mercado_laboral_synced = _best_effort(
        "mercado laboral (BCRD · ENCFT)",
        lambda: _sync_bcrd_mercado_laboral(db, set_phase), errors)
    cepal_synced = _best_effort(
        "participación política local (CEPAL · OIG)",
        lambda: _sync_cepal_politica(db, set_phase), errors)
    senado_synced = _best_effort(
        "mujeres en el Senado (UIP · Parline)",
        lambda: _sync_ipu_senado(db, set_phase), errors)
    exportaciones_synced = _best_effort(
        "exportaciones per cápita (WDI)",
        lambda: _sync_exportaciones_per_capita(db, set_phase), errors)
    income_synced = _best_effort(
        "ingreso per cápita (SISDOM · MEPyD)",
        lambda: _sync_sisdom_income(db, set_phase), errors)
    coverage_synced = _best_effort(
        "cobertura educativa (MINERD · SIIE)",
        lambda: _sync_minerd_coverage(db, set_phase, provenance), errors)
    schooling_synced = _best_effort(
        "escolaridad por región (SISDOM · MEPyD)",
        lambda: _sync_sisdom_schooling(db, set_phase), errors)
    findex_synced = _best_effort(
        "inclusión financiera (BM Findex)", lambda: _sync_wb_findex(db, set_phase), errors)
    mortality_synced = _best_effort(
        "mortalidad infantil provincial (SISDOM · ENDESA)",
        lambda: _sync_endesa_child_mortality(db, set_phase), errors)
    provincial_synced = _best_effort(
        "indicadores provinciales (SIUBEN)",
        lambda: _sync_siuben_provincial(db, set_phase, provenance), errors)
    db.commit()

    return {
        "synced": synced,
        "health_synced": health_synced,
        "informality_synced": informality_synced,
        "mercado_laboral_synced": mercado_laboral_synced,
        "cepal_politica_synced": cepal_synced,
        "senado_synced": senado_synced,
        "exportaciones_synced": exportaciones_synced,
        "conteos_regionales_synced": conteos_synced,
        "llece_synced": llece_synced,
        "razon_exp_imp_synced": razon_synced,
        "pobreza_rural_synced": rural_synced,
        "gei_per_capita_synced": gei_synced,
        "cobertura_salud_synced": salud_synced,
        "participacion_export_synced": export_synced,
        "mem_electrico_synced": mem_synced,
        "income_synced": income_synced,
        "coverage_synced": coverage_synced,
        "schooling_synced": schooling_synced,
        "findex_synced": findex_synced,
        "provincial_synced": provincial_synced,
        "mortality_synced": mortality_synced,
        "provenance": provenance,
        "periods": sorted(periods),
        "regions": len({r.dimension for r in records if r.dimension}),
        "themes": (sorted({r.series for r in records})
                   + sorted(set(WDI_HEALTH.values()))
                   + ["informality_rate", INCOME_THEME]
                   + [COVERAGE_THEME, "schooling_years"]
                   + sorted(WB_FINDEX.values())
                   + sorted(SIUBEN_THEMES)),
        "errors": errors,
    }
