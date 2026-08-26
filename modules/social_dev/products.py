"""Desarrollo Social (IDM) como ``SectorProduct`` — el eje social entra al catálogo.

Hasta ahora ``social_dev`` era un eje del sistema pero NO un producto: no figuraba en
``PRODUCT_CATALOG``, y por eso ni la Data API ni ``/quality/{sector}`` podían verlo —
ambos recorren ese catálogo. Un consumidor externo recibía 404 y lo leía como un
problema de alcance de su llave; en realidad no había nada que alcanzar. Este módulo
cierra esa brecha implementando el contrato, sin tocar el framework.

Naturaleza de PANEL SUB-NACIONAL, y ahí está su razón de ser: el sujeto es la
demarcación (10 regiones de desarrollo · 32 provincias), no el país. Es el único eje de
la plataforma cuyo dato varía DENTRO de la República Dominicana, que es exactamente lo
que necesita quien ordena territorios y no países.

Qué se publica y qué no:

* **Series**: solo las que tienen desagregación geográfica real (ver
  ``service.subnational_series``). Las seis variables nacionales del IDM se aplican
  idénticas a las 10 regiones; servirlas "por región" sería entregar una constante con
  etiqueta geográfica.
* **Score**: el IDM por región, con su desglose dimensional. Cálculo de casa.
* **Procedencia**: ``variable_signals`` declara por variable si es real o rúbrica **y si
  su alcance es nacional o por sujeto** — la distinción que evita leer "dato real" como
  "diferencia entre demarcaciones".

La muestra de conversión (``sample_snapshot`` + ``sample_narratives``) es un exemplar
CURADO con cifras ilustrativas y declaradas como tales: nunca sale por la Data API ni
entra a un informe de cliente, y el framework la entrega marcada al agua.

Eje doctrinal ÚNICO: ``social_dev`` + ``social_outlook`` → numeric_guard.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.social_dev.social_sync import HEALTH_ENTITY
from shared.data.minerd_coverage import COUNTRY_SLUG as MINERD_COUNTRY
from shared.data.sisdom_schooling import COUNTRY_SLUG as SISDOM_COUNTRY
from shared.registry.builders import axis_variable_scopes
from shared.registry.signals import NATIONAL, PER_SUBJECT
from shared.products.contract import EstadoBacktest
from shared.products import (
    CanonicalScore,
    CanonicalSeries,
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    ScoreObservation,
    SectorProductManifest,
    SeriesObservation,
    TierLevelSpec,
    ValidationState,
    distinct_periods,
    register_product,
    section_mode,
)
from shared.products.render import render_product_pdf
from modules.social_dev.models.models import DevelopmentScore
from modules.social_dev.service import (
    assemble_idm_dataset,
    get_latest,
    get_scores,
    subnational_observations,
    subnational_series,
)

logger = logging.getLogger("sdq.products.social_dev")

SECTOR_KEY = "social_dev"
DISPLAY = "Desarrollo Social · Demarcaciones de RD"
DOCTRINE_AXIS = "social"
_UNSET = object()

_SECTION_TITLES = {
    "social_pulse": "Pulso del Desarrollo Social",
    "social_assessment": "Evaluación del Desarrollo (IDM)",
    "inequality": "Distribución entre Demarcaciones",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "El Índice de Desarrollo Multidimensional (IDM) se computa sobre las 10 regiones de "
    "desarrollo. De sus nueve variables, tres se miden por demarcación —pobreza monetaria "
    "y cobertura neta secundaria (ONE, por región; la cobertura también por provincia) y "
    "alfabetización (ENHOGAR-2022, por región)— y seis son de alcance NACIONAL: esperanza "
    "de vida y mortalidad infantil (WDI), escolaridad, ingreso e informalidad (ONE) e "
    "inclusión financiera (Banco Mundial). Esas seis sostienen el nivel del índice pero no "
    "diferencian entre demarcaciones, y así se declaran variable por variable. Las series "
    "provinciales del SIUBEN describen la composición de su padrón de focalización —hogares "
    "registrados— y no la población general de la provincia. El IDM es una lectura de "
    "desarrollo relativo dentro del país, no una medición de bienestar individual ni un "
    "pronóstico."
)
_NO_DATA = (
    "No hay IDM persistido para el período: el producto está cableado pero su cobertura "
    "(G1) es insuficiente para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar). Coherente con los datos demo de
# ``sample_snapshot``: IDM 38.4 «Bajo» en Enriquillo, puesto 10 de 10, media del panel
# 55.3, máximo 78.9, amplitud 40.5; dimensiones salud 62.0, educación 41.2, nivel de
# vida 22.8, inclusión 27.6.
_SAMPLE_NARRATIVES = {
    "social_pulse": (
        "El panel de desarrollo social de la República Dominicana cierra el período con un "
        "**IDM medio de 55.3/100 sobre las 10 regiones de desarrollo**, pero el promedio es "
        "el dato menos informativo del conjunto: la **amplitud entre la región más y la "
        "menos desarrollada alcanza 40.5 puntos** —de 38.4 a 78.9—, es decir, más de dos "
        "tercios de la escala. Un país con esa dispersión no tiene un nivel de desarrollo; "
        "tiene varios conviviendo bajo una misma bandera fiscal y regulatoria. La lectura "
        "relevante para política pública no es si el promedio sube, sino si la brecha se "
        "cierra: un avance nacional impulsado por las regiones que ya lideran mejora la "
        "media y empeora la desigualdad territorial al mismo tiempo. El índice se computa "
        "sobre nueve variables en cuatro dimensiones de peso igual —salud, educación, nivel "
        "de vida e inclusión—, de las cuales tres se miden por demarcación y seis son de "
        "alcance nacional; estas últimas sostienen el nivel del índice pero no explican por "
        "qué unas regiones quedan atrás de otras."
    ),
    "social_assessment": (
        "La región **Enriquillo registra un IDM de 38.4/100 —banda Baja—, el más bajo del "
        "panel (puesto 10 de 10)**, a 16.9 puntos de la media nacional de 55.3 y a 40.5 del "
        "máximo. El desglose dimensional ubica el problema con precisión: **nivel de vida "
        "(22.8) e inclusión (27.6) concentran el rezago**, mientras salud (62.0) es la "
        "dimensión más sólida y educación (41.2) queda en un terreno intermedio. La lectura "
        "es que la carencia dominante de Enriquillo no es sanitaria sino económica —pobreza "
        "monetaria y exclusión del sistema financiero formal—, y que la política de salud, "
        "de alcance mayormente nacional, ya rinde ahí sus frutos. Conviene subrayar una "
        "limitación estructural del diagnóstico: la dimensión de salud y buena parte de "
        "inclusión se alimentan de variables nacionales idénticas para las diez regiones, de "
        "modo que la distancia real entre Enriquillo y el resto se explica sobre todo por "
        "pobreza y acceso educativo, que sí se miden por demarcación."
    ),
    "inequality": (
        "**Enriquillo no está por debajo del promedio: está en el extremo de una "
        "distribución muy abierta.** Con 38.4 puntos frente a una media de 55.3 y un máximo "
        "de 78.9, la región ocupa el último lugar de un panel cuya amplitud (40.5 puntos) y "
        "coeficiente de variación (0.24) describen un país territorialmente desigual más que "
        "un país de desarrollo medio. La distinción importa para decidir: si la dispersión "
        "fuera estrecha, una política nacional uniforme bastaría para mover a todas las "
        "regiones a la vez; con esta amplitud, el instrumento uniforme reproduce la brecha, "
        "porque el punto de partida no es comparable. La consecuencia práctica es que las "
        "regiones del extremo inferior requieren intensidad diferencial —no solo cobertura— "
        "y que el indicador de éxito de una intervención territorial debe ser la reducción "
        "de la amplitud del panel, no el aumento de su media."
    ),
    "recommendation": (
        "Para un formulador de política o un multilateral con exposición a Enriquillo, el "
        "orden de las palancas se desprende del desglose y no del juicio. La **dimensión de "
        "nivel de vida (22.8) es la de mayor rezago y la que más responde a instrumentos de "
        "ingreso**: es donde una transferencia condicionada, un programa de empleo formal o "
        "una intervención productiva rinde el mayor movimiento por peso invertido. La "
        "segunda palanca es la **inclusión (27.6)**, donde el acceso al sistema financiero "
        "formal —corresponsalías, pagos digitales, bancarización de las transferencias— "
        "opera con costo marginal bajo una vez que existe el flujo de ingreso. La educación "
        "(41.2) es la palanca de horizonte largo y no debe competir con las anteriores por "
        "el presupuesto de corto plazo. Salud (62.0) no requiere intensificación "
        "diferencial en esta región. La recomendación es concentrar el esfuerzo "
        "territorial en ingreso e inclusión, y medir el resultado por la reducción de la "
        "distancia de Enriquillo a la media del panel, no por su nivel absoluto."
    ),
}


def social_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Desarrollo Social", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("social_pulse",), narrative_templates=("social_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("social_assessment", "inequality"),
                narrative_templates=("social_outlook",),
                audience="formulador de política / multilateral", cadence="recurring",
                price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("social_assessment", "inequality", "recommendation", "limitations"),
                narrative_templates=("social_outlook",),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


def _safe(db: Optional[Session], fn, default):
    """Lectura en SAVEPOINT: el recompute de readiness itera TODOS los sectores en una
    sola sesión, así que un eje que falla no puede envenenar la transacción del que
    sigue (parity dev↔prod: en Postgres eso aborta todo lo demás)."""
    if db is None:
        return default
    try:
        with db.begin_nested():
            return fn()
    except Exception as e:  # noqa: BLE001 — degradación honesta, nunca tumbar el monitor
        logger.warning("[social_dev] lectura no disponible: %s", e)
        return default


class SocialDevProduct:

    ESTADO_BACKTEST = EstadoBacktest(
        tiene_motor=True, eje_motor="social_dev",
        desenlace="IDH regional del PNUD (validez CONVERGENTE, no backtest temporal)",
        motivo=("Corte transversal de las 10 regiones de desarrollo. Un Gate E temporal no "
                "aplica: el IDM es un índice relativo cuyas variables nacionales normalizan "
                "plano, así que se valida contra una medida independiente del mismo período."))
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._scores: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("SocialDevProduct requiere una sesión de DB para esta operación.")
        return self._db

    # ── Lecturas base ──
    def _latest_panel(self) -> List[DevelopmentScore]:
        """Los scores del último período con IDM computado (el panel de regiones)."""
        if self._scores is _UNSET:
            self._scores = _safe(self._db, self._read_latest_panel, [])
        return self._scores

    def _read_latest_panel(self) -> List[DevelopmentScore]:
        from modules.social_dev.service import _period_key

        rows = get_scores(self._require_db())
        if not rows:
            return []
        # ``str(...)`` en la frontera: estos modelos usan el estilo legacy de SQLAlchemy,
        # cuyo tipo estático es ``Column[str]`` y no ``str``.
        latest = max((str(r.period) for r in rows), key=_period_key)
        return [r for r in rows if str(r.period) == latest]

    def product_manifest(self) -> SectorProductManifest:
        return social_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        from datetime import date

        panel = self._latest_panel()
        if not panel:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("ONE",), detail="Sin IDM persistido.")
        period = str(panel[0].period)
        asm = _safe(self._db, lambda: assemble_idm_dataset(self._require_db(), period=period),
                    {"sources": {}})
        smap: Dict[str, Dict[str, str]] = asm.get("sources") or {}
        # Cobertura REAL: fracción de pares (región, variable) con dato vivo. Es la misma
        # cifra que la UI marca real-vs-rúbrica; no se declara aparte.
        cells = [state for vars_ in smap.values() for state in vars_.values()]
        coverage = (sum(1 for s in cells if s == "live") / len(cells)) if cells else 0.0
        freshness = None
        try:
            freshness = (date.today() - date(int(str(period)[:4]), 12, 31)).days
        except (ValueError, TypeError):
            pass
        sources = ("ONE", "WDI", "Banco Mundial", "SIUBEN")
        return DataHealth(
            coverage=coverage, freshness_days=freshness, cadence="annual", sources=sources,
            detail=(f"IDM {period} sobre {len(panel)} regiones · cobertura real "
                    f"{coverage:.0%} · series provinciales SIUBEN + ONE"))

    def has_engine(self) -> bool:
        return bool(self._latest_panel())

    def validation_state(self) -> ValidationState:
        """G5 desde el informe de validez convergente persistido (IDM vs IDH regional
        del PNUD). Sin informe: aprobado con score BAJO — el índice corre sobre dato
        real, pero una validación que no se corrió no se declara como si se hubiera
        corrido."""
        report = _safe(self._db, self._read_validation, None)
        if not report:
            return ValidationState(
                approved=True, score=0.40,
                notes=("IDM sobre dato real (ONE/WDI/BM); validez convergente contra el "
                       "IDH regional del PNUD aún no computada para este corte."))
        rho = report.get("spearman") or report.get("rho")
        score = 0.75 if isinstance(rho, (int, float)) and abs(rho) >= 0.6 else 0.55
        return ValidationState(
            approved=True, score=score,
            notes=f"Validez convergente contra el IDH regional del PNUD (ρ={rho}).")

    def _read_validation(self) -> Optional[Dict[str, Any]]:
        import json

        from shared.settings.models import AppSetting

        row = (self._require_db().query(AppSetting)
               .filter(AppSetting.key == "idm_convergent_validity").first())
        return json.loads(str(row.value)) if row else None

    def variable_signals(self) -> Dict[str, Any]:
        """Procedencia POR VARIABLE del IDM para el Data Registry — y con ella el
        ALCANCE (nacional vs por sujeto), que la doctrina social ahora declara.

        Es la mitad que faltaba: sin el alcance, seis variables nacionales aplicadas por
        igual a las 10 regiones se reportaban como si midieran cada región, y "dato real"
        se leía como "diferencia entre demarcaciones"."""
        from shared.registry.builders import pattern_a_signals

        panel = self._latest_panel()
        if not panel:
            return {"period": None, "signals": []}
        period = str(panel[0].period)
        asm = _safe(self._db, lambda: assemble_idm_dataset(self._require_db(), period=period),
                    None)
        if not asm or not asm.get("sources"):
            return {"period": None, "signals": []}
        dh = self.data_signals()
        signals = pattern_a_signals(
            axis=DOCTRINE_AXIS, dataset=asm.get("dataset") or {}, sources=asm["sources"],
            source_label=", ".join(dh.sources), cadence=dh.cadence)
        signals = list(signals) + self._senales_fuera_del_indice(period, dh)
        return {"period": str(period), "signals": signals}

    # Temas que el panel INGIERE y que el índice de desarrollo no usa. Se publican en el
    # registro porque son dato real del Estado y hay consumidores fuera del IDM —el eje de
    # evaluación de leyes mide la meta de pobreza extrema de la END contra este tema—, pero
    # NO forman parte del índice y por eso van con peso 0: la cobertura ponderada del eje se
    # computa sobre el peso, así que un peso 0 no mueve ni el numerador ni el denominador.
    # Sin esta lista, un dato que el Estado publica y nosotros ingerimos queda invisible para
    # todo el que no sea el IDM.
    #: clave → (etiqueta, dimensión, nota). El ALCANCE se declara en la doctrina del eje
    #: (`variable_scopes`), no acá. No es decorativo: sin él
    #: todas caían al default `per_subject` y un consumidor que lee `value` recibía el
    #: valor de UNA región creyendo que era el del país. Pasó: el eje de evaluación de
    #: leyes publicó la pobreza extrema de cibao_norte como cifra nacional.
    _FUERA_DEL_INDICE = {
        # entidad None = «la que haya»: sólo es legítimo cuando el tema tiene UNA sola
        # fila por período (las nacionales del BCRD). Para un tema con diez regiones hay
        # que nombrar la entidad o la señal miente.
        "poverty_extreme": ("poverty_extreme", None, "Pobreza monetaria extrema",
                            "living_standards",
                            "No alimenta el índice de desarrollo (el IDM usa la pobreza "
                            "general). Se publica porque es dato real y tiene consumidores "
                            "propios."),
        "unemployment_rate": ("unemployment_rate", HEALTH_ENTITY,
                              "Tasa de desocupación (SU1)", "inclusion",
                              "ENCFT del BCRD, promedio de cuatro trimestres publicado por "
                              "el emisor. No alimenta el índice de desarrollo. ATENCIÓN al "
                              "comparar con series anteriores a 2015: la ENFT y la ENCFT dan "
                              "niveles que difieren casi al doble."),
        # Las dos brechas son RAZONES, no porcentajes. La etiqueta lo dice porque la
        # cifra sola (2,7) se lee como un porcentaje y significa «2,7 VECES».
        "employment_gender_ratio": (
            "employment_gender_ratio", HEALTH_ENTITY,
            "Razón de ocupación femenina/masculina", "inclusion",
            "Tasa de ocupación de mujeres dividida por la de hombres (1,0 = paridad). "
            "Computada sobre el promedio anual de cada sexo de la ENCFT; el BCRD publica "
            "los trimestres, no el promedio. No alimenta el índice de desarrollo."),
        "unemployment_gender_ratio": (
            "unemployment_gender_ratio", HEALTH_ENTITY,
            "Razón de desocupación femenina/masculina", "inclusion",
            "Desocupación de mujeres dividida por la de hombres (1,0 = paridad; más alto "
            "es peor). Computada sobre el promedio anual de cada sexo de la ENCFT. Una "
            "RAZÓN sobrevive al cambio de encuesta que vuelve incomparable al nivel: el "
            "cambio de metodología se cancela en numerador y denominador."),
        # El TOTAL PAÍS del tablero del SIIE, que el parser descartaba. Son las únicas
        # cifras nacionales de cobertura educativa que existen en el panel: el IDM usa la
        # serie por región, y promediar diez regiones sin ponderar por matrícula no da la
        # cobertura del país. Habilitan los indicadores 2.9 y 2.10 de la END.
        # Indicadores 2.20 y 4.2 de la END. Las dos llevan su salvedad en la nota: el año
        # de la línea base legal NO está en la serie del emisor, así que el contraste con
        # la ley se hace contra el año más cercano y eso se declara antes de medir.
        # Registro Único de trámites (Ley 167-21). Alcance NACIONAL y período MENSUAL: es
        # un catálogo vivo, no una estadística anual, y el mes es lo que deja ver si la
        # cifra se mueve. La clave del porcentaje nombra su denominador porque acá conviven
        # dos poblaciones —los catalogados y los que declaran— y `pct_con_tiempo` a secas se
        # reatribuye al que quede más cerca.
        "tramites_catalogados": (
            "tramites_catalogados", HEALTH_ENTITY,
            "Trámites publicados en el catálogo del Estado", "institutional",
            "Portal Único de Servicios (gob.do). Cuántos procedimientos administrativos "
            "publica el Estado. La Ley 167-21 (art. 39) obliga a publicarlos TODOS, y su "
            "art. 40 le pone consecuencia: solo se puede exigir lo registrado. No alimenta "
            "el índice de desarrollo."),
        "tramites_con_tiempo_declarado": (
            "tramites_con_tiempo_declarado", HEALTH_ENTITY,
            "Trámites que declaran su tiempo de respuesta", "institutional",
            "Cuántas fichas del catálogo dicen cuánto tarda el trámite. Lo exige la "
            "Resolución 142-2024 del MAP —NO la Ley 167-21, que no nombra el tiempo de "
            "respuesta—; la resolución se dicta al amparo del art. 42, que manda al "
            "ministerio emitir los lineamientos. El dato se extrae de la PROSA de la ficha "
            "con una gramática anclada: la API no tiene campo para esto."),
        "tramites_pct_con_tiempo_sobre_los_catalogados": (
            "tramites_pct_con_tiempo_sobre_los_catalogados", HEALTH_ENTITY,
            "Trámites que declaran su tiempo, sobre los catalogados (%)", "institutional",
            "La razón, servida y no derivada. Una cifra baja acá NO dice que los trámites "
            "sean lentos — dice que no se sabe cuánto tardan, que es otra afirmación y es "
            "la que el dato sostiene. El valor vigente lo sirve la serie: escribirlo acá lo "
            "vuelve falso en la próxima corrida sin que nadie se entere."),
        "tramites_mencionan_cifra_de_tiempo_sin_anclar": (
            "tramites_mencionan_cifra_de_tiempo_sin_anclar", HEALTH_ENTITY,
            "Fichas con alguna cifra de tiempo sin anclar al plazo del trámite",
            "institutional",
            "El CONTRAFACTUAL del criterio de extracción, y no una medición del plazo de los "
            "trámites: son multas, vigencias de documentos y condiciones de agenda. Se "
            "publica para poder decir cuánto más grande sería la cifra que sí se publica si "
            "se aceptara cualquier número de tiempo de la prosa, computando la razón en vez "
            "de afirmarla. No alimenta el índice de desarrollo."),
        "public_education_spending": (
            "public_education_spending", HEALTH_ENTITY,
            "Gasto público en educación (% del PIB)", "education",
            "Banco Mundial (SE.XPD.TOTL.GD.ZS). La serie no trae 2009, que es el año de la "
            "línea base de la ley. No alimenta el índice de desarrollo."),
        "protected_areas": (
            "protected_areas", HEALTH_ENTITY,
            "Áreas protegidas terrestres (% de la superficie)", "living_standards",
            "Banco Mundial (ER.LND.PTLD.ZS). Superficie TERRESTRE: la serie marina es otra "
            "y da la mitad. La serie empieza en 2013 y la línea base de la ley es de 2009."),
        # Indicadores 3.18 y 3.19. La etiqueta nombra el UNIVERSO porque es lo que
        # distingue una cifra de la otra: bienes y manufacturas dan participaciones
        # distintas y las dos se llaman «participación exportadora».
        "world_export_share_goods": (
            "world_export_share_goods", HEALTH_ENTITY,
            "Participación en exportaciones mundiales de bienes (%)", "living_standards",
            "Mercancías dominicanas sobre mercancías mundiales, del Banco Mundial; el "
            "cociente es cómputo SDQ. NO es bienes y servicios: con ese universo la cifra "
            "sube un tercio."),
        "world_export_share_manufactures": (
            "world_export_share_manufactures", HEALTH_ENTITY,
            "Participación en exportaciones mundiales de manufacturas (%)",
            "living_standards",
            "Mercancías recortadas por la composición de manufacturas que publica el mismo "
            "emisor, para el país y para el mundo. Cómputo SDQ."),
        # Indicador 2.36 de la END. La unidad dice «a diciembre» porque la convención
        # de anualización es parte del dato: con el promedio anual la cifra de 2010 baja
        # cinco puntos.
        "health_insurance_coverage": (
            "health_insurance_coverage", HEALTH_ENTITY,
            "Población protegida por el Seguro de Salud (% a diciembre)", "health",
            "Afiliación al Seguro Familiar de Salud publicada por el CNSS sobre población "
            "del Banco Mundial; el cociente es cómputo SDQ. El emisor no publica el "
            "porcentaje: el denominador es elección nuestra y está declarada."),
        # Indicadores 2.3 y 2.6 de la END. El sujeto va en la etiqueta: son cifras de la
        # ZONA RURAL, y sin decirlo un lector las toma por nacionales.
        "rural_poverty_extreme": (
            "rural_poverty_extreme", HEALTH_ENTITY,
            "Pobreza extrema — zona rural (% de la población rural)", "living_standards",
            "SISDOM, cuadro 03 3 003a. El emisor la llama «indigencia monetaria». La serie "
            "tiene un quiebre de metodología en 2016 declarado por el emisor."),
        "rural_poverty_total": (
            "rural_poverty_total", HEALTH_ENTITY,
            "Pobreza general — zona rural (% de la población rural)", "living_standards",
            "SISDOM, cuadro 03 3 003a. Línea de pobreza TOTAL, que incluye la indigencia. "
            "Mismo quiebre de metodología en 2016."),
        # Indicadores 2.1 y 2.4 de la END. El sufijo `_national` no es decorativo: las
        # series homónimas sin él son REGIONALES, y confundirlas fue lo que hizo publicar el
        # valor de una sola región contra una meta nacional.
        "poverty_extreme_national": (
            "poverty_extreme_national", HEALTH_ENTITY,
            "Pobreza extrema — país (% de la población)", "living_standards",
            "SISDOM, cuadro 03 3 003a, columna nacional. El emisor la llama «indigencia "
            "monetaria». Quiebre de metodología declarado en 2016."),
        "poverty_rate_national": (
            "poverty_rate_national", HEALTH_ENTITY,
            "Pobreza general — país (% de la población)", "living_standards",
            "SISDOM, cuadro 03 3 003a, columna nacional. Línea de pobreza TOTAL, que incluye "
            "la indigencia. Mismo quiebre de 2016, con un salto mucho mayor que el de la "
            "línea de indigencia."),
        # Indicador 3.22 de la END. Es una RAZÓN, no un porcentaje: la etiqueta lo dice
        # porque «0,78» a secas se lee como 78% y significa otra cosa.
        "exports_imports_ratio": (
            "exports_imports_ratio", HEALTH_ENTITY,
            "Razón exportaciones/importaciones de bienes y servicios", "living_standards",
            "Cociente de dos series del Banco Mundial, computado por SDQ. 1,0 es equilibrio "
            "comercial. No alimenta el índice de desarrollo."),
        # Indicador 1.1 de la END. La etiqueta dice PERCEPCIÓN porque eso es lo que mide:
        # cuánta confianza declara la gente, no cuán confiables son los partidos. Sin decirlo,
        # un lector toma la cifra por una medición del fenómeno.
        "trust_political_parties": (
            "trust_political_parties", HEALTH_ENTITY,
            "Confianza declarada en los partidos políticos (%)", "living_standards",
            "Encuesta regional de opinión (Latinobarómetro): porcentaje que declara mucha o "
            "algo de confianza, sobre la base sin no-respuesta; la suma es cómputo SDQ. Es "
            "una medición de PERCEPCIÓN. No alimenta el índice de desarrollo."),
        # Indicador 3.23 de la END. El sufijo `_total` distingue esta serie NACIONAL de la
        # que el eje sectorial ingiere por actividad: son el mismo dato con alcances
        # distintos, y confundirlos publicaría la inversión de un rubro contra la meta del
        # país.
        # Indicador 2.33 de la END. El SUJETO viaja en la etiqueta: es el gasto del Gobierno
        # CENTRAL, no el del gobierno general que republica el organismo internacional —ese
        # incluye la seguridad social y da un 66% más. La razón se computa contra UNA sola
        # serie de PIB para los trece años; el emisor publica la suya en cuatro de ellos y
        # queda 6-8% por encima, porque dividió por el PIB de su añada.
        "health_spending_central_gov_pct_gdp": (
            "health_spending_central_gov_pct_gdp", HEALTH_ENTITY,
            "Gasto en salud del Gobierno Central (% del PIB)", "living_standards",
            "Línea de Salud del cuadro de clasificación funcional de DIGEPRES, monto "
            "devengado, sobre el PIB nominal. No alimenta el índice de desarrollo."),
        # Indicador 2.40 de la END. El SUJETO va en la etiqueta: es INGRESO, no ocupación
        # —`employment_gender_ratio` mide otra cosa y las dos son razones F/M—. Y la etiqueta
        # dice «razón» porque un 0,91 a secas se lee como un porcentaje.
        # Indicador 3.30 de la END. La etiqueta nombra a las DISTRIBUIDORAS porque el dato
        # es el aporte a ellas: llamarlo «subsidio eléctrico» a secas lo haría leer como el
        # subsidio del Gobierno a todo el sector, que es un universo mayor.
        "electricity_subsidy_usd_mm": (
            "electricity_subsidy_usd_mm", HEALTH_ENTITY,
            "Aporte del Gobierno a las distribuidoras eléctricas (millones de US$)",
            "living_standards",
            "Anexo del Informe de Desempeño del MEM, edición de diciembre, acumulado del "
            "año. No alimenta el índice de desarrollo."),
        # Indicador 2.34 de la END, hoja «END 2.34» de SISDOM.
        "improved_sanitation_access": (
            "improved_sanitation_access", HEALTH_ENTITY,
            "Acceso a servicios sanitarios mejorados (%)", "inclusion",
            "Término idéntico al de la ley. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 2.35 de la END, hoja «END 2.35» de SISDOM.
        "public_network_water_access": (
            "public_network_water_access", HEALTH_ENTITY,
            "Acceso a agua de la red pública (%)", "inclusion",
            "RED PÚBLICA dentro o fuera de la vivienda — no «al menos básica», que incluye pozos. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 2.37 de la END, hoja «END 2.37a» de SISDOM.
        "broad_unemployment_rate": (
            "broad_unemployment_rate", HEALTH_ENTITY,
            "Tasa de desocupación ampliada (%)", "inclusion",
            "AMPLIADA, no abierta: es la que reproduce la línea base de la ley. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 2.47 de la END, hoja «END 2.47» de SISDOM.
        "child_labour_6_14": (
            "child_labour_6_14", HEALTH_ENTITY,
            "Niños de 6 a 14 años que trabajan (%)", "inclusion",
            "Término y tramo etario idénticos a los de la ley. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 2.48 de la END, hoja «END 2.48» de SISDOM.
        "neet_unemployed_15_19": (
            "neet_unemployed_15_19", HEALTH_ENTITY,
            "Jóvenes de 15 a 19 que no estudian y están desempleados (%)", "inclusion",
            "Término idéntico al de la ley. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 2.8 de la END, hoja «END 2.8a» de SISDOM.
        "preschool_net_coverage": (
            "preschool_net_coverage", HEALTH_ENTITY,
            "Cobertura neta de nivel inicial (%)", "inclusion",
            "Tasa neta de cobertura de nivel inicial, de encuestas de hogares. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 3.10 de la END, hoja «END 3.10» de SISDOM.
        "tertiary_net_enrollment": (
            "tertiary_net_enrollment", HEALTH_ENTITY,
            "Matrícula neta de nivel superior, 18-24 años (%)", "inclusion",
            "Término idéntico al de la ley. Serie del propio Estado para su ley; el instrumento "
            "(ENFT/ENCFT) viaja en la desagregación. No alimenta el índice."),
        # Indicador 2.24 de la END, hoja «END 2.24» de SISDOM.
        "malaria_mortality_rate": (
            "malaria_mortality_rate", HEALTH_ENTITY,
            "Mortalidad asociada a malaria (por 100.000 hab.)", "inclusion",
            "Registro del CENCET. Serie del propio Estado para su ley. No alimenta el índice."),
        # Indicador 2.28 de la END, hoja «END 2.28» de SISDOM.
        "child_underweight_rate": (
            "child_underweight_rate", HEALTH_ENTITY,
            "Desnutrición global en menores de 5 años (%)", "inclusion",
            "ENDESA. La serie TERMINA en 2013. Serie del propio Estado para su ley. No alimenta el índice."),
        # Indicador 2.29 de la END, hoja «END 2.29» de SISDOM.
        "child_wasting_rate": (
            "child_wasting_rate", HEALTH_ENTITY,
            "Desnutrición aguda en menores de 5 años (%)", "inclusion",
            "ENDESA. La serie TERMINA en 2013. Serie del propio Estado para su ley. No alimenta el índice."),
        # Indicador 2.30 de la END, hoja «END 2.30» de SISDOM.
        "child_stunting_rate": (
            "child_stunting_rate", HEALTH_ENTITY,
            "Desnutrición crónica en menores de 5 años (%)", "inclusion",
            "ENDESA. La serie TERMINA en 2013. Serie del propio Estado para su ley. No alimenta el índice."),
        # Indicador 2.31 de la END, hoja «END 2.31» de SISDOM.
        "vertical_hiv_transmission": (
            "vertical_hiv_transmission", HEALTH_ENTITY,
            "Transmisión vertical del VIH (%)", "inclusion",
            "Hijos de madres VIH positivas que resultan seropositivos. Serie del propio Estado para su ley. No alimenta el índice."),
        # Indicador 2.32 de la END, hoja «END 2.32» de SISDOM.
        "advanced_hiv_on_art": (
            "advanced_hiv_on_art", HEALTH_ENTITY,
            "Portadores de VIH avanzado con antirretrovirales (%)", "inclusion",
            "Cobertura de tratamiento. Serie del propio Estado para su ley. No alimenta el índice."),
        # Indicador 4.2 de la END. La etiqueta dice TERRESTRE porque el denominador lo es:
        # llamarlo «área protegida» a secas se leería como sobre todo el territorio.
        "protected_area_pct_land": (
            "protected_area_pct_land", HEALTH_ENTITY,
            "Superficie protegida (% del área terrestre)", "living_standards",
            "Suma de los seis grupos de categoría del cuadro de la ONE sobre el área "
            "terrestre del país. No alimenta el índice de desarrollo."),
        "income_gender_ratio": (
            "income_gender_ratio", HEALTH_ENTITY,
            "Razón de ingreso laboral femenino/masculino", "inclusion",
            "SISDOM, hoja de la END. La serie cruza un cambio de encuesta en 2016 (ENFT → "
            "ENCFT) y el instrumento viaja en la desagregación de cada año. No alimenta el "
            "índice de desarrollo."),
        "fdi_total_usd_mm": (
            "fdi_total_usd_mm", HEALTH_ENTITY,
            "Inversión extranjera directa — país (millones de US$)", "living_standards",
            "Suma de las nueve actividades del cuadro del BCRD, cuya coincidencia con la "
            "fila de total la comprueba el conector. No alimenta el índice de desarrollo."),
        # Indicador 2.38 de la END. Es una dispersión ENTRE regiones, así que el sujeto es
        # el país y no una demarcación — y la etiqueta lo dice, porque «brecha regional» a
        # secas se lee como si fuera el dato de una región.
        "regional_unemployment_gap": (
            "regional_unemployment_gap", HEALTH_ENTITY,
            "Brecha de desocupación ampliada entre regiones (puntos)", "living_standards",
            "Distancia entre la región con mayor y con menor desocupación ampliada (SU2) de "
            "la ENCFT del BCRD; la resta es cómputo SDQ. En PUNTOS porcentuales, no en por "
            "ciento. No alimenta el índice de desarrollo."),
        # Indicador 3.20 de la END. La etiqueta nombra las DOS categorías que se unen,
        # porque «agropecuarias» no es una categoría del emisor y un lector que lo tome por
        # una sola busca una serie que no existe.
        "world_export_share_agri": (
            "world_export_share_agri", HEALTH_ENTITY,
            "Cuota mundial de exportaciones agropecuarias de RD (%)", "living_standards",
            "Alimentos MÁS materias primas agrícolas, unidos por niveles y no por cuotas: "
            "cada categoría tiene su propio denominador mundial. Cómputo SDQ sobre series "
            "del Banco Mundial. No alimenta el índice de desarrollo."),
        # Indicador 4.1 de la END. La etiqueta dice TODOS los gases y dice que incluye el
        # uso de la tierra, porque la ley titula el indicador «dióxido de carbono» y no es
        # eso: el CO2 solo da 2,13 contra una base legal de 3,6. Callar el alcance dejaría al
        # lector con el nombre de la ley, que es justamente el que confunde.
        "ghg_per_capita": (
            "ghg_per_capita", HEALTH_ENTITY,
            "Emisiones de GEI per cápita, con uso de la tierra (t CO2e)", "living_standards",
            "Total de gases de efecto invernadero INCLUYENDO uso de la tierra (AR5), del "
            "Banco Mundial, sobre población del mismo emisor; el cociente es cómputo SDQ. Es "
            "la magnitud que reproduce la línea base de la ley — el CO2 solo no. No alimenta "
            "el índice de desarrollo."),
        # Los tres índices comerciales del sector eléctrico (indicadores 3.27, 3.28 y 3.29
        # de la END). El SUJETO viaja en la etiqueta: son las tres distribuidoras estatales
        # agregadas, no el sector entero — que es exactamente el universo que la ley mide, y
        # el que un lector reatribuiría al «sector eléctrico» si la etiqueta callara.
        "electric_cri_ede": (
            "electric_cri_ede", HEALTH_ENTITY,
            "Índice de recuperación de efectivo (CRI) — EDE agregadas", "inclusion",
            "Anexo del Informe de Desempeño del MEM, año completo (enero-diciembre). No "
            "alimenta el índice de desarrollo."),
        "electric_perdidas_ede": (
            "electric_perdidas_ede", HEALTH_ENTITY,
            "Pérdidas de energía — EDE agregadas (% de la comprada)", "inclusion",
            "Pérdidas TOTALES (técnicas y no técnicas). No confundir con las «pérdidas "
            "comerciales» de los informes anteriores a 2020, que son un subconjunto y "
            "corren unos quince puntos por debajo."),
        "electric_cobranzas_ede": (
            "electric_cobranzas_ede", HEALTH_ENTITY,
            "Cobranzas — EDE agregadas (% de lo facturado)", "inclusion",
            "Cobro sobre facturación, que es la definición que el propio indicador de la "
            "ley trae entre paréntesis. No alimenta el índice de desarrollo."),
        "secondary_coverage_pais": (
            "secondary_coverage", MINERD_COUNTRY,
            "Cobertura neta secundaria — total país", "education",
            "Total nacional publicado por el MINERD (SIIE). Distinto de la serie por "
            "región que alimenta el índice de desarrollo."),
        "primary_coverage_pais": (
            "primary_coverage", MINERD_COUNTRY,
            "Cobertura neta básica — total país", "education",
            "Total nacional publicado por el MINERD (SIIE)."),
        # «Individuals using the Internet (% of population)» del WDI — el indicador 3.13
        # de la END. NO es `internet_penetration` del eje telecom, que es banda ancha
        # MÓVIL por 100 habitantes y puede pasar de 100: son magnitudes distintas y la
        # confusión entre ellas es la que hay que impedir con la etiqueta.
        "internet_users": (
            "internet_users", HEALTH_ENTITY,
            "Usuarios de internet (% de la población)", "inclusion",
            "Serie del Banco Mundial (republica a la UIT, que es quien la produce). Se "
            "toma de ahí porque el API de ITU DataHub dejó de ser alcanzable de forma "
            "anónima. No confundir con la penetración de banda ancha móvil del eje "
            "telecom, que es otra magnitud."),
        # Senado — indicador 2.43. Es el cuarto cargo electivo y el único que ninguna
        # otra fuente cubre: el WDI da la cámara BAJA y la CEPAL solo trae oradores.
        "women_senate": (
            "women_senate", HEALTH_ENTITY,
            "Mujeres en el Senado (% de los escaños)", "inclusion",
            "Unión Interparlamentaria (Parline), entidad DO-UC01. Cámara ALTA: no "
            "confundir con `women_lower_house`, que es la Cámara de Diputados."),
        # Síndicas y regidoras — indicadores 2.45 y 2.46. Las etiquetas llevan los DOS
        # nombres porque la fuente regional usa «alcaldesas» y «concejalas», y sin eso
        # nadie relaciona la señal con lo que la ley pide.
        "women_mayors": (
            "women_mayors", HEALTH_ENTITY,
            "Síndicas (alcaldesas) electas (% de los cargos)", "inclusion",
            "Observatorio de Igualdad de Género de la CEPAL, que recoge el dato del "
            "organismo electoral. Serie ESCALONADA: un cargo electivo no cambia de "
            "composición hasta la próxima elección."),
        "women_councillors": (
            "women_councillors", HEALTH_ENTITY,
            "Regidoras (concejalas) electas (% de los cargos)", "inclusion",
            "Observatorio de Igualdad de Género de la CEPAL. Serie ESCALONADA entre "
            "elecciones, igual que la de síndicas."),
        # Mortalidad de menores de 5 — indicador 2.22. La etiqueta dice el tramo de edad
        # porque es lo único que la distingue de `child_mortality` (menores de 1), y los
        # dos valores son plausibles el uno por el otro.
        "under5_mortality": (
            "under5_mortality", HEALTH_ENTITY,
            "Mortalidad de menores de 5 años (por 1.000 nacidos vivos)", "health",
            "Estimación modelada del grupo interagencial de la ONU, vía Banco Mundial. "
            "Distinta de `child_mortality`, que es mortalidad INFANTIL (menores de 1)."),
        # Escaños de mujeres en la cámara BAJA — indicador 2.44 de la END. La etiqueta
        # dice «Diputados» y no «parlamento» a propósito: la serie no cubre el Senado, que
        # es el indicador 2.43 y va por otro camino.
        "women_lower_house": (
            "women_lower_house", HEALTH_ENTITY,
            "Mujeres en la Cámara de Diputados (% de escaños)", "inclusion",
            "Serie del Banco Mundial sobre el reporte de la Unión Interparlamentaria. Para "
            "sistemas bicamerales la UIP reporta la cámara BAJA: esta serie NO cubre el "
            "Senado."),
        # La fila «Total» del cuadro 05 3 007 del SISDOM, que el parser salteaba por no
        # resolver a ninguna región. Habilita el indicador 2.18 de la END.
        "schooling_years_pais": (
            "schooling_years", SISDOM_COUNTRY,
            "Escolaridad promedio (15+) — total país", "education",
            "Fila «Total» del cuadro 05 3 007 del SISDOM (MEPyD). Distinta de la serie "
            "por región que alimenta el índice de desarrollo."),
        # ══ LOTE 2026-08-19 · las once del expediente de la END ══
        # Entidad `HEALTH_ENTITY` («nacional») en TODAS: son series de país con una fila por
        # período. Dejar la entidad en None acá sería legítimo solo para temas de una sola
        # fila, y no hay razón para arriesgarse — nombrarla es lo que impidió que la
        # pobreza extrema de una región se publicara como cifra nacional.
        "homicide_rate": ("homicide_rate", HEALTH_ENTITY, "Tasa de homicidios",
                          "inclusion",
                          "Homicidios intencionales por 100.000 habitantes (Banco Mundial, "
                          "a partir de UNODC). No alimenta el índice de desarrollo."),
        "undernourishment": ("undernourishment", HEALTH_ENTITY,
                             "Prevalencia de subalimentación", "living_standards",
                             "FAO vía Banco Mundial. No alimenta el índice de desarrollo."),
        "literacy_rate_pais": ("literacy_rate_pais", HEALTH_ENTITY,
                               "Tasa de alfabetización (15 años y más)", "education",
                               "Serie NACIONAL del Banco Mundial. Distinta de "
                               "`literacy_rate`, que este panel mide por región: el eje de "
                               "leyes fija metas de país y necesita el agregado."),
        "malnutrition_weight_age": ("malnutrition_weight_age", HEALTH_ENTITY,
                                    "Desnutrición global (peso/edad)", "health",
                                    "Menores de 5 años. Es una de TRES desnutriciones que "
                                    "la ley fija por separado y que no se convierten entre "
                                    "sí. No alimenta el índice de desarrollo."),
        "malnutrition_weight_height": ("malnutrition_weight_height", HEALTH_ENTITY,
                                       "Desnutrición aguda (peso/talla)", "health",
                                       "Menores de 5 años. No alimenta el índice."),
        "malnutrition_height_age": ("malnutrition_height_age", HEALTH_ENTITY,
                                    "Desnutrición crónica (talla/edad)", "health",
                                    "Menores de 5 años. No alimenta el índice."),
        "gini_index": ("gini_index", HEALTH_ENTITY, "Índice de GINI", "inclusion",
                       "Se publica en la escala del emisor (0-100). La END lo fija en 0-1 "
                       "y esa conversión la declara el binding, no esta ingesta."),
        "tax_revenue_gdp": ("tax_revenue_gdp", HEALTH_ENTITY,
                            "Presión tributaria (% del PIB)", "inclusion",
                            "No es una variable de desarrollo social: vive acá porque este "
                            "es el eje que ingiere series nacionales. No alimenta el índice."),
        "gni_per_capita_atlas": ("gni_per_capita_atlas", HEALTH_ENTITY,
                                 "INB per cápita (método Atlas)", "living_standards",
                                 "Tampoco es una variable de desarrollo social. No alimenta "
                                 "el índice."),
        # ══ LOTE 2026-08-19 (b) · los tres DERIVADOS ══
        # No vienen de un emisor: los computamos nosotros sobre datos que ya ingerimos. Por
        # eso su `source` lo dice — un consumidor tiene que poder distinguir «lo publica la
        # ONE» de «lo calculamos con el panel de la ONE».
        "exports_per_capita": ("exports_per_capita", HEALTH_ENTITY,
                               "Exportaciones per cápita", "living_standards",
                               "Exportaciones de bienes Y servicios sobre población (WDI). "
                               "No alimenta el índice de desarrollo."),
        "regiones_pobreza_extrema_sobre_umbral": (
            "regiones_pobreza_extrema_sobre_umbral", HEALTH_ENTITY,
            "Regiones con pobreza extrema sobre 5%", "living_standards",
            "CÓMPUTO SDQ sobre el panel regional de la ONE. Solo se publica el año con las "
            "diez regiones presentes: con nueve, el conteo bajaría por un dato faltante y "
            "se leería como progreso."),
        "regiones_pobreza_moderada_sobre_umbral": (
            "regiones_pobreza_moderada_sobre_umbral", HEALTH_ENTITY,
            "Regiones con pobreza moderada sobre 20%", "living_standards",
            "CÓMPUTO SDQ sobre el panel regional de la ONE. Mismo guard de completitud."),
        # ══ Indicador 2.17 de la END ══
        "llece_math6_bajo_nivel_ii": (
            "llece_math6_bajo_nivel_ii", HEALTH_ENTITY,
            "Alumnos en o por debajo del nivel II · matemáticas 6º", "education",
            "Pruebas regionales del LLECE (TERCE 2013, ERCE 2019). Se publica el NIVEL y "
            "nunca el puntaje: la ley fija sus metas en la escala de SERCE 2006 (media 500) "
            "y el emisor publica desde 2013 con media 700. Los niveles sí son comparables."),
    }

    def _senales_fuera_del_indice(self, period: str, dh) -> List[Any]:
        """Señales de temas ingeridos que el índice no usa. Solo si HAY dato.

        Se comprueba contra la base en vez de declararlas siempre: publicar una señal de un
        tema sin filas afirmaría que el eje mide algo que no mide, que es exactamente lo que
        el registro existe para impedir.
        """
        from shared.registry.signals import REAL, VariableSignal

        from modules.social_dev.models.models import SocialIndicator
        out: List[Any] = []
        # El ALCANCE sale de la doctrina, que es donde se declara el de todas las
        # variables del eje. Repetirlo acá sería una segunda verdad, y el día que
        # divergieran ganaría la que el consumidor mire primero.
        alcances = axis_variable_scopes(DOCTRINE_AXIS)
        for clave, (tema, entidad, label, dimension, nota) in self._FUERA_DEL_INDICE.items():
            alcance = alcances.get(clave, PER_SUBJECT)

            def _leer(t=tema, e=entidad):
                q = (self._require_db().query(SocialIndicator.value, SocialIndicator.period)
                     .filter(SocialIndicator.theme == t, SocialIndicator.value.isnot(None)))
                # Filtrar por ENTIDAD cuando la señal afirma una: sin esto la consulta
                # devolvía una fila cualquiera del período más reciente, y en un tema con
                # diez regiones eso es el valor de una demarcación al azar servido como si
                # fuera del eje. Es el mismo defecto que hizo publicar la pobreza extrema
                # de cibao_norte como cifra nacional.
                if e is not None:
                    q = q.filter(SocialIndicator.entity_key == e)
                # La serie ENTERA, ascendente. Servir solo el último punto costaba el
                # veredicto más valioso del eje de leyes: con una sola observación el
                # semáforo se niega —bien— a emitir tendencia, así que «retrocede» y «no
                # alcanzará» eran inalcanzables para el producto aunque el dato estuviera
                # en esta misma tabla. La ley pide juzgar AVANCE y solo sabíamos decir nivel.
                return q.order_by(SocialIndicator.period.asc()).all()

            filas = _safe(self._db, _leer, []) or []
            if not filas:
                continue
            # Solo las nacionales llevan historia: la de una variable por-sujeto sería la de
            # UN sujeto, y una trayectoria falsa afirma una DIRECCIÓN, no solo un nivel.
            historia = tuple((str(p), float(v)) for v, p in filas)
            valor, periodo_tema = filas[-1][0], filas[-1][1]
            out.append(VariableSignal(
                key=clave, label=label, state=REAL, dimension=dimension,
                weight=0.0,                      # fuera del índice: no pondera
                source=", ".join(dh.sources), cadence=dh.cadence,
                value=float(valor), real_fraction=1.0, scope=alcance,
                history=historia if alcance == NATIONAL else (),
                # El período va en la SEÑAL y no solo en la nota: un consumidor no puede
                # parsear prosa para saber a qué año corresponde la cifra que le sirven.
                period=str(periodo_tema),
                note=f"{nota} Último período con dato: {periodo_tema}."))
        return out

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), DevelopmentScore.period)

    # ── Sujetos elegibles de los niveles nombrados ──
    def scope_kind(self) -> str:
        return "entity"

    def scope_options(self) -> List[Dict[str, str]]:
        """Las regiones con IDM computado — los sujetos que un nivel nombrado acepta.

        Se ofrece SOLO lo que tiene score: un selector que lista una región sin dato
        manda al usuario a un error evitable."""
        from shared.data.one_client import region_catalog

        scored = {r.entity_key for r in self._latest_panel()}
        return [{"value": slug, "label": label, "group": "Regiones de desarrollo"}
                for slug, label in region_catalog() if slug in scored]

    # ── Series canónicas (Data API) ──
    def canonical_series(self) -> List[CanonicalSeries]:
        """Solo las series con desagregación geográfica real. El descriptor se deriva
        del contenido de ``sd_indicators``, así que una fuente nueva aparece sola."""
        rows = _safe(self._db, lambda: subnational_series(self._require_db()), [])
        return [
            CanonicalSeries(
                code=d["code"], label=d["label"], unit=d.get("unit"),
                frequency=d.get("frequency") or "unknown", source=d.get("source") or "",
                license=d.get("license"), period_first=d.get("period_first"),
                period_latest=d.get("period_latest"), n_obs=int(d.get("n_obs") or 0),
                curated=bool(d.get("curated")), nature=str(d.get("nature") or "unknown"),
                note=d.get("note", "") or "",
            )
            for d in rows
        ]

    def series_observations(
        self, code: str, *, start: Optional[str] = None, end: Optional[str] = None,
        as_of: Optional[str] = None, limit: Optional[int] = None,
    ) -> List[SeriesObservation]:
        if as_of:
            raise ValueError(
                "El eje social no conserva revisiones point-in-time: no se puede servir "
                "'as_of'. Pedir la serie sin ese parámetro.")
        rows = _safe(self._db,
                     lambda: subnational_observations(self._require_db(), code, start=start,
                                                      end=end, limit=limit), [])
        return [
            SeriesObservation(period=o["period"], value=o["value"], unit=o.get("unit"),
                              source=o.get("source"), published_at=o.get("published_at"),
                              reason=o.get("reason"))
            for o in rows
        ]

    # ── Score canónico (Data API) ──
    def canonical_scores(self) -> List[CanonicalScore]:
        rows = _safe(self._db, lambda: get_scores(self._require_db()), [])
        if not rows:
            return []
        from modules.social_dev.service import _period_key

        periods = tuple(sorted({r.period for r in rows if r.period}, key=_period_key))
        return [CanonicalScore(
            code="idm", label="Índice de Desarrollo Multidimensional",
            subject_kind="entity", direction="mayor score = mayor desarrollo",
            scale="0-100", method_version="1.0",
            subjects=tuple(sorted({r.entity_key for r in rows})),
            period_latest=periods[-1] if periods else None, periods=periods, n_obs=len(rows),
            note=("Panel de las 10 regiones de desarrollo. Seis de sus nueve variables son "
                  "de alcance nacional y sostienen el nivel sin diferenciar demarcaciones; "
                  "el desglose dimensional y la procedencia por variable viajan aparte."))]

    def score_observations(
        self, code: str, *, subject: Optional[str] = None, start: Optional[str] = None,
        end: Optional[str] = None, limit: Optional[int] = None,
    ) -> List[ScoreObservation]:
        if code != "idm":
            return []
        from modules.social_dev.service import _period_key

        rows = _safe(self._db, lambda: get_scores(self._require_db()), [])
        rows = [r for r in rows if subject is None or r.entity_key == subject]
        rows.sort(key=lambda r: (_period_key(r.period), r.entity_key))
        if start:
            rows = [r for r in rows if _period_key(r.period) >= _period_key(start)]
        if end:
            rows = [r for r in rows if _period_key(r.period) <= _period_key(end)]
        if limit:
            rows = rows[-int(limit):]
        return [
            ScoreObservation(
                subject=r.entity_key, period=r.period, score=r.development_score,
                band=r.band, dimensions=r.breakdown, model_version=r.model_version,
                reason=None if r.development_score is not None else "IDM no computado")
            for r in rows
        ]

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        from shared.data.one_client import region_catalog
        from modules.social_dev.scoring.development import distribution_stats

        db = self._require_db()
        rows = _safe(db, lambda: get_scores(db, period or None), [])
        if period:
            panel = rows
        else:
            panel = self._latest_panel()
        panel = [r for r in panel if r.development_score is not None]
        if not panel:
            entity = None if tier == ProductTier.pulse else DISPLAY
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_score": False}, entity_name=entity,
                                   entity_roster=())

        dist = distribution_stats([r.development_score for r in panel])
        resolved_period = panel[0].period
        if tier == ProductTier.pulse:
            # Agregado de sistema: sin nombres de demarcación (el sensor de anonimización
            # del ensamblador lo verifica contra el roster).
            return ProductSnapshot(
                tier=tier, period=resolved_period,
                payload={"has_score": True, "distribution": dist, "n_entities": len(panel)},
                entity_name=None, entity_roster=())

        if not scope:
            raise ValueError(
                "Se requiere 'scope' con la región de desarrollo (p. ej. 'enriquillo'). "
                f"Opciones: {', '.join(sorted(r.entity_key for r in panel))}.")
        row = next((r for r in panel if r.entity_key == scope), None)
        if row is None:
            raise ValueError(
                f"La región '{scope}' no tiene IDM computado en {resolved_period}.")

        ordered = sorted(panel, key=lambda r: r.development_score, reverse=True)
        rank = next(i + 1 for i, r in enumerate(ordered) if r.entity_key == scope)
        sources = (_safe(db, lambda: assemble_idm_dataset(db, period=resolved_period), {})
                   .get("sources") or {}).get(scope)
        name = dict(region_catalog()).get(scope, scope)
        return ProductSnapshot(
            tier=tier, period=resolved_period, entity_name=name,
            payload={"has_score": True, "entity_key": scope, "region_name": name,
                     "score": {"development_score": row.development_score, "band": row.band,
                               "period": row.period, "breakdown": row.breakdown},
                     "rank": rank, "n_entities": len(panel), "distribution": dist,
                     "sources": sources})

    # ── Muestra de conversión (datos demo SINTÉTICOS, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        """Exemplar de muestra: cifras ILUSTRATIVAS, no una lectura de la base.

        El framework las entrega siempre marcadas al agua y por la ruta de muestra; no
        se sirven por la Data API ni entran a un informe de cliente. Las dimensiones
        suman al score con los pesos de la doctrina (0.25 cada una), para que la muestra
        no enseñe una aritmética que el índice real no hace."""
        dist = {"n": 10, "mean": 55.3, "min": 38.4, "max": 78.9, "spread": 40.5, "cv": 0.2413}
        if tier == ProductTier.pulse:
            return ProductSnapshot(
                tier=tier, period="2024",
                payload={"has_score": True, "distribution": dist, "n_entities": 10},
                entity_name=None, entity_roster=())
        breakdown = {
            "health": {"score": 62.0, "weight": 0.25, "contribution": 15.5},
            "education": {"score": 41.2, "weight": 0.25, "contribution": 10.3},
            "living_standards": {"score": 22.8, "weight": 0.25, "contribution": 5.7},
            "inclusion": {"score": 27.6, "weight": 0.25, "contribution": 6.9},
        }
        return ProductSnapshot(
            tier=tier, period="2024", entity_name="Enriquillo",
            payload={"has_score": True, "entity_key": "enriquillo",
                     "region_name": "Enriquillo",
                     "score": {"development_score": 38.4, "band": "Bajo", "period": "2024",
                               "breakdown": breakdown},
                     "rank": 10, "n_entities": 10, "distribution": dist,
                     "sources": {"poverty_rate": "live", "secondary_coverage": "live",
                                 "literacy_rate": "live", "life_expectancy": "live",
                                 "child_mortality": "live", "schooling_years": "live",
                                 "income_per_capita": "live", "informality_rate": "live",
                                 "financial_inclusion": "live"}})

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA tier-1 de la muestra (exemplar). NO usa el motor IA."""
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_score"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        from modules.social_dev.ai_context import social_ai_context

        payload = snapshot.payload
        if tier == ProductTier.pulse:
            base_ctx = {"periodo": snapshot.period, "distribucion": payload.get("distribution"),
                        "n_demarcaciones": payload.get("n_entities")}
            audience = "formulador_politica"
        else:
            base_ctx = social_ai_context(
                payload["entity_key"], payload["score"], region_name=payload.get("region_name"),
                sources=payload.get("sources"), rank=payload.get("rank"),
                n_regions=payload.get("n_entities"), distribution=payload.get("distribution"))
            audience = "formulador_politica"

        out: Dict[str, str] = {}
        pending: List = []
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: qué dimensión del IDM concentra el "
                                  "rezago de esta demarcación y qué palanca la mueve, dado "
                                  "el cuadro anterior.")
            elif section == "inequality":
                ctx["enfoque"] = ("La DISTRIBUCIÓN entre demarcaciones, no el promedio: "
                                  "dónde cae esta región en la dispersión del panel.")
            pending.append((section, dict(
                context=ctx, template="social_outlook",
                mode=section_mode(tier, section, sections),
                axis="social_dev", audience=audience)))

        async def _gen(section: str, kwargs: Dict) -> tuple:
            res = await narrative_engine.generate(**kwargs)
            return section, res.text

        for section, text in await asyncio.gather(*(_gen(s, k) for s, k in pending)):
            out[section] = text
        return out

    # ── Render ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None,
                     fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Desarrollo Social", "insight": "Insight Desarrollo Social",
                 "deep_dive": "Deep Dive Desarrollo Social"}.get(tier.value, "Desarrollo Social")
        display = ("Panel de Demarcaciones · RD" if tier == ProductTier.pulse
                   else (snapshot.entity_name or DISPLAY))
        payload = snapshot.payload or {}
        tables: List = []
        charts: List = []
        headline = None

        score = payload.get("score") or {}
        breakdown = score.get("breakdown") or {}
        if breakdown:
            rows = [["Dimensión", "Score", "Peso"]] + [
                [k, _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in breakdown.items()]
            tables.append(("Dimensiones del IDM", rows))
            charts.append({"title": "Dimensiones del IDM (score 0-100)",
                           "items": [(k, (d or {}).get("score")) for k, d in breakdown.items()]})
            headline = f"IDM {_fmt(score.get('development_score'))} · {score.get('band')}"

        dist = payload.get("distribution") or {}
        if dist.get("n"):
            tables.append(("Distribución del panel", [
                ["Métrica", "Valor"],
                ["Demarcaciones", str(dist.get("n"))],
                ["Media", _fmt(dist.get("mean"))],
                ["Mínimo", _fmt(dist.get("min"))],
                ["Máximo", _fmt(dist.get("max"))],
                ["Amplitud", _fmt(dist.get("spread"))],
            ]))
        if tier == ProductTier.pulse and not headline and dist.get("mean") is not None:
            headline = f"IDM medio {_fmt(dist.get('mean'))} · {dist.get('n')} demarcaciones"

        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: SocialDevProduct(db))
