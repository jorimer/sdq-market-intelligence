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
