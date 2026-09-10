"""Construction Intelligence como ``SectorProduct`` — producto dedicado del sector construcción.

Mono-módulo (patrón Free Zones/Tourism): ``construction_intel`` tiene conector real (MIVHED
licencias + BCRD PIB construcción, datos abiertos) + índice ICC (coyuntura del sector
construcción). Implementa el ``Protocol`` ``SectorProduct`` SIN tocar el framework de
productos, reusando el motor de narrativa y los getters PÚBLICOS del módulo
(``service``/``ai_context``).

Naturaleza NACIONAL: el "entity" es el sector construcción de RD; no hay firmas →
``entity_roster=()``. El Pulse es el pulso del sector; el nivel nombrado nombra al sector.

REEMPLAZA en el catálogo el corte transversal de ``sector_intel`` para ``construction``: el
producto dedicado (permisos líder MIVHED + producción BCRD) es más fiel al sector que el
slice del IAI transversal. El IAI transversal interno (peer set de 17 sectores) NO se toca
— construction sigue en el peer set vía ``bcrd_sectors``; solo cambia el producto consumible
del slot ``construction``. Se importa DESPUÉS de ``sector_intel.products`` en ``app/main``
para sobreescribir el registro.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.contract import EstadoBacktest
from shared.products import (
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
    distinct_periods,
    register_product,
    section_mode,
)
from shared.products.render import render_product_pdf
from modules.construction_intel.ai_context import construction_ai_context
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.service import get_latest

logger = logging.getLogger("sdq.products.construction")

SECTOR_KEY = "construction"
DISPLAY = "Sector Construcción · RD"
_UNSET = object()

_SECTION_TITLES = {
    "construction_pulse": "Pulso del Sector Construcción",
    "construction_assessment": "Evaluación de Coyuntura (ICC)",
    "positioning": "Posición y Trayectoria",
    "recommendation": "Lectura para Decisión",
    "delta_mensual": "Movimiento mensual de licencias (MIVHED)",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "El Índice de Construcción (ICC) se construye sobre dos fuentes abiertas y "
    "complementarias: las licencias de construcción del MIVHED (datos.gob.do), un indicador "
    "líder —el permiso precede a la obra—, y el crecimiento real del PIB de construcción del "
    "BCRD (producción efectiva). Cuatro dimensiones: producción (crecimiento real a 3 años), "
    "flujo de permisos (CAGR de m² a 3 años), diversificación tipológica y amplitud "
    "geográfica (HHI). El dato es anual y agregado nacional: los permisos del MIVHED "
    "comienzan en 2022 (historia corta para el CAGR del flujo) y la inversión licenciada es "
    "nominal (RD$), no ejecutada. El desglose por tipología incluye dos capas de fuente "
    "distinta y complementaria: los m² licenciados del MIVHED (indicador líder) y el valor "
    "tasado por tipología de la ONE (tasación oficial anual, ≈RD$15,000/m²) — que no debe "
    "confundirse con el «costo estándar» derivado del MIVHED (m² × tarifa fija ≈RD$61,600/m²). "
    "Índice preliminar, aún sin validación retrospectiva de resultados."
)
_NO_DATA = (
    "No hay ICC persistido: el producto está cableado pero su cobertura es insuficiente "
    "para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar), coherente con el dato real 2025
# (ICC 26.5 «Crítico»: producción 3y +0.39% y flujo de permisos −7.5% deprimen el
# índice pese a una diversificación tipológica/geográfica más sana; 951 licencias, 4.47M
# m², ~RD$271 mil millones licenciados; apartamentos 59.6%, Santo Domingo 22.8%).
_SAMPLE_NARRATIVES = {
    "construction_pulse": (
        "El sector construcción dominicano cierra el período con un **Índice de "
        "Construcción de 26.5/100 —banda Crítico—**, lectura consistente con una coyuntura "
        "en enfriamiento tras el auge post-pandemia. El resultado lo determinan las dos "
        "dimensiones cíclicas: la **producción efectiva** (PIB real de construcción) "
        "promedia **+0.39% anual** en los últimos tres años y cerró 2025 en **−1.8%**, "
        "mientras el **flujo de permisos** se contrae de forma marcada —los metros² "
        "licenciados caen a un **−7.5% anual** (CAGR 3 años), de 5.7M a 4.5M de m²—. El "
        "componente estructural resulta más sólido: la actividad se mantiene "
        "**razonablemente diversificada** por tipología (apartamentos lideran con 59.6% de "
        "los permisos) y **distribuida geográficamente** (Santo Domingo concentra solo "
        "22.8%). En términos de mercado, el sector de mayor peso en la economía (13.5% del "
        "VAB) atraviesa una corrección —menor obra nueva en cartera— y la señal líder de los "
        "permisos anticipa que la debilidad de producción aún no toca fondo."
    ),
    "construction_assessment": (
        "La coyuntura de la construcción se evalúa en **26.5/100 (banda Crítico)**, "
        "deprimida por sus dos motores cíclicos y sostenida principalmente por la "
        "diversificación. La **producción** real del sector se estancó (promedio 3 años "
        "+0.4%, último año −1.8%), y el **flujo de permisos** —el mejor indicador adelantado "
        "disponible— se mantiene en terreno negativo: con 951 licencias y 4.5M de m² en "
        "2025, los permisos registran una contracción aproximada de 7.5% anual. La "
        "**inversión licenciada** se ubica en torno a los RD$271 mil millones (nominal). "
        "Como contrapeso, la base de actividad no depende de un solo segmento ni región: la "
        "diversificación tipológica (apartamentos 59.6%) y la amplitud geográfica (Santo "
        "Domingo 22.8%) obtienen puntajes elevados. Desde la óptica del inversionista, el "
        "cuadro corresponde a un **sector en corrección**: existe oportunidad selectiva "
        "donde la demanda estructural persiste, pero con el ciclo de permisos aún a la baja."
    ),
    "positioning": (
        "**El ICC se ubica en banda Crítico y su posición la define el contraste entre dos "
        "dimensiones cíclicas débiles y un componente estructural sano.** Ordenadas por "
        "aporte, las dimensiones que deprimen el índice son la producción (PIB real, "
        "promedio 3 años +0.4% y último año −1.8%) y, sobre todo, el flujo de permisos "
        "(metros² licenciados a −7.5% anual), ambas en terreno cíclico negativo. En el polo "
        "opuesto, la diversificación tipológica (apartamentos 59.6%) y la amplitud "
        "geográfica (Santo Domingo 22.8%) obtienen puntajes elevados y sostienen la base de "
        "actividad. La dimensión que define la posición es el flujo de permisos: como "
        "indicador adelantado, su contracción explica por qué el índice no toca fondo pese a "
        "la solidez estructural. Cabe una nota de honestidad metodológica: los permisos "
        "MIVHED arrancan en 2022, por lo que la serie histórica es corta y no permite leer "
        "una trayectoria de varios ciclos, solo la posición relativa de las dimensiones en "
        "el período medido."
    ),
    "recommendation": (
        "Para un inversionista, desarrollador o decisor público con exposición a la "
        "construcción dominicana, la señal dominante es un **ciclo en contracción**: tanto "
        "la producción (PIB real) como el flujo líder de permisos apuntan a la baja, por "
        "lo que el momento de nueva exposición exige cautela y selectividad. La palanca de "
        "mayor valor no reside en sumar capacidad horizontal sino en la **lectura del "
        "indicador adelantado de permisos por tipología y provincia**: la diversificación "
        "sólida indica que existen segmentos y plazas donde la demanda estructural persiste "
        "(vivienda, plazas fuera del Gran Santo Domingo). Se recomienda condicionar las "
        "tesis a una reactivación del flujo de permisos —el mejor indicador adelantado— "
        "antes de asumir un giro del ciclo, y priorizar nichos diversificados sobre "
        "posiciones concentradas."
    ),
}


def construction_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Construction Intelligence", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("construction_pulse",),
                narrative_templates=("construction_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("construction_assessment", "positioning"),
                narrative_templates=("construction_outlook", "sector_positioning"),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("construction_assessment", "positioning", "recommendation", "limitations"),
                narrative_templates=("construction_outlook", "sector_positioning"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[ConstructionScore]:
    try:
        with db.begin_nested():
            row = get_latest(db, period or None)
            # Producto ANUAL: el selector de período de la UI puede ser trimestral (p.ej.
            # "2026-Q1") y nunca casa con el año del ICC → caer al último año disponible en
            # vez de quedar en blanco. Un período anual que SÍ existe se respeta.
            if row is None and period:
                row = get_latest(db, None)
            return row
    except Exception as e:  # noqa: BLE001
        logger.warning("ICC no disponible: %s", e)
        return None


def _index_dict(s: ConstructionScore) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {"icc_score": s.icc_score, "band": s.band, "coverage": s.coverage,
            "dimensions": bd.get("dimensions", {}), "production": bd.get("production", {}),
            "pipeline": bd.get("pipeline", {}), "typology": bd.get("typology", {}),
            "geography": bd.get("geography", {}), "levels": bd.get("levels", {}),
            "one_typology": bd.get("one_typology")}


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


class ConstructionProduct:

    ESTADO_BACKTEST = EstadoBacktest(
        tiene_motor=False, obstaculo="sin_corte_transversal",
        desenlace="permisos EJECUTADOS contra permisos iniciados, y producción realizada",
        dato_que_falta=("ejecución de los permisos (MIVHED publica el flujo de emisión, no "
                        "el de ejecución) y un corte por provincia con historia suficiente: "
                        "los permisos empiezan en 2022"),
        motivo=("El ICC es un índice NACIONAL con historia corta de permisos (2022+). Sin "
                "ejecución realizada no hay desenlace independiente del flujo que el índice "
                "ya mide."))
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("ConstructionProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[ConstructionScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return construction_manifest()

    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("MIVHED", "BCRD"), detail="Sin ICC persistido.")
        from datetime import date
        coverage = s.coverage if s.coverage is not None else 0.0
        freshness = None
        try:
            freshness = max(0, (date.today() - date(int(str(s.period)[:4]), 12, 31)).days)
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("MIVHED (datos.gob.do)", "BCRD", "ONE (one.gob.do)"),
                          detail=f"ICC {_fmt(s.icc_score)} ({s.band}) en {s.period} · "
                                 f"{int(s.permits) if s.permits else '—'} licencias")

    # ── El feed sub-anual: otra FUENTE del eje, con su propia cadencia ──
    #
    # NO se declara en `DataHealth.cadence`. Ese campo escala los umbrales de G1 y, medido,
    # declarar `monthly` en un índice anual cuesta 0,300 de readiness contra un umbral de
    # activación de 0,85: como el máximo es 1,0, el eje deja de publicarse en TODOS sus
    # niveles. El índice sigue siendo anual porque lo es; el feed es otra fuente.
    def senales_de_fuentes(self):
        """La señal del feed mensual del MIVHED para el sensor de fuentes congeladas."""
        from datetime import date

        from modules.construction_intel.service import CLAVE_DEL_FEED
        from shared.observations import service as obs
        from shared.operations.fuentes_congeladas import SenalDeFuente

        try:
            ultimo = obs.ultimo_periodo(self._require_db(), sector_key=SECTOR_KEY)
        except Exception as e:  # noqa: BLE001 — sin feed no hay señal, no hay error
            logger.warning("feed mensual de construcción no legible: %s", e)
            return []
        if not ultimo:
            return []
        # La antigüedad es la del PERÍODO del dato, no la de la fila: un sync que corre en
        # verde contra un archivo que ya no se actualiza no mueve el período.
        try:
            anio, mes = int(str(ultimo)[:4]), int(str(ultimo)[5:7])
            fin = date(anio + (mes == 12), 1 if mes == 12 else mes + 1, 1)
            dias = max(0, (date.today() - fin).days)
        except (ValueError, IndexError):
            dias = None
        return [SenalDeFuente(
            clave=CLAVE_DEL_FEED,
            etiqueta="MIVHED · licencias emitidas",
            cadence="monthly", freshness_days=dias,
            detalle=f"último mes con licencias observadas: {ultimo}")]

    def has_engine(self) -> bool:
        return self._latest() is not None

    def variable_signals(self) -> Dict[str, Any]:
        """Señal por-dimensión del índice para el Data Registry (motor de research).
        Reusa el ``breakdown.dimensions`` persistido (``provenance`` + peso) y la
        fuente/cadencia que el producto ya declara — sin fabricar."""
        from shared.registry.builders import pattern_b_signals

        s = self._latest()
        dims = (s.breakdown or {}).get("dimensions") if s else None
        if not dims:
            return {"period": None, "signals": []}
        dh = self.data_signals()
        signals = pattern_b_signals(breakdown=dims, source_label=", ".join(dh.sources),
                                    cadence=dh.cadence)
        return {"period": str(s.period), "signals": signals}

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), ConstructionScore.period)

    def validation_state(self) -> ValidationState:
        # Índice PRELIMINAR: 4 dimensiones sobre dato real MIVHED+BCRD, pero SIN backtest de
        # outcomes y con historia corta de permisos (2022+) → validación parcial honesta.
        return ValidationState(approved=True, score=0.55,
                               notes="ICC preliminar (sin validación retrospectiva de resultados; permisos "
                                     "MIVHED desde 2022). Producción (PIB construcción BCRD), "
                                     "flujo de permisos, diversificación tipológica y "
                                     "amplitud geográfica sobre dato real.")

    # ── Snapshot por nivel ──
    @staticmethod
    def _motivo_en_castellano(veredicto) -> str:
        """El porqué del veto, redactado para el CLIENTE.

        El `motivo` que trae el veredicto está escrito para el operador del panel y arrastra
        la clave de máquina de la cadencia ("monthly"): pegarlo tal cual publicaba «su fuente
        (monthly)» dentro de un documento en español. Es el mismo defecto que obligó a
        traducir la cadencia en la sección de metodología. Los HECHOS se copian del veredicto;
        la frase se escribe acá.
        """
        from shared.products.report_sections import CADENCIA_ES

        if veredicto is None:
            return ("el eje no declara este feed, así que no hay veredicto de frescura que "
                    "lo respalde")
        cad = CADENCIA_ES.get((veredicto.cadencia or "").lower(), veredicto.cadencia or "—")
        dias = veredicto.dias_desde_el_periodo_del_dato
        tope = veredicto.tope_de_dias_de_la_cadencia
        if dias is None or tope is None:
            return ("no se pudo determinar la antigüedad del dato de esta fuente, y una "
                    "frescura indeterminada no es una frescura verificada")
        return (f"el dato más reciente de esta fuente de cadencia {cad} tiene {dias} días, "
                f"cuando una edición nueva debía haber aparecido a los {tope}")

    def _delta_mensual(self) -> Optional[Dict[str, Any]]:
        """El movimiento del último mes observado, o ``None`` si no hay sección que publicar.

        **Con la fuente atrasada, la lectura SE PUBLICA con su mes nombrado y la declaración
        al lado** (decisión del dueño, 2026-09-10). El primer diseño vetaba la sección: temía
        describir un mes viejo con cara de actual. Pero la lectura nombra su período, así que
        no se hace pasar por el mes en curso; y que el emisor lleve semanas sin publicar es en
        sí información que el lector quiere. Callarla —o esconder la lectura— la perdía.

        La declaración viaja como DATO computado (`fuente_del_feed`) y no como prosa: la fecha
        de la última publicación sale de `published_at`, que se captura del portal al ingerir.
        Nunca se escribe a mano.

        **`indeterminada` sí veta.** Ahí no se sabe cuándo publicó la fuente, así que no hay
        declaración honesta que poner al lado: publicar la lectura sin ella sería presentarla
        como vigente sin saberlo. Vuelve con `no_publicable` y su motivo, que la sección imprime.
        """
        from modules.construction_intel.service import (
            CLAVE_DEL_FEED, ETIQUETAS_DEL_FEED)
        from shared.observations import service as obs
        from shared.observations.delta import leer_delta
        from shared.operations.fuentes_congeladas import (
            AL_DIA, CONGELADA, veredicto_de_la_fuente)

        try:
            db = self._require_db()
            ultimo = obs.ultimo_periodo(db, sector_key=SECTOR_KEY)
            if not ultimo:
                return None            # sin feed no hay sección: no aparece vacía
            veredicto = veredicto_de_la_fuente(db, sector_key=SECTOR_KEY,
                                               clave=CLAVE_DEL_FEED)
            if veredicto is None or veredicto.estado not in (AL_DIA, CONGELADA):
                return {"no_publicable": self._motivo_en_castellano(veredicto),
                        "ultimo_periodo_observado": ultimo}
            bloque = leer_delta(db, sector_key=SECTOR_KEY, period=ultimo,
                                etiquetas=ETIQUETAS_DEL_FEED)
            bloque["emisor"] = "MIVHED (datos.gob.do)"
            # La frescura de la FUENTE, como dato. Sin `dias`: una cifra calculada contra hoy
            # cambiaría el payload cada día e invalidaría la caché sin que el dato cambie, y
            # dentro de un documento envejecería sola. Lo estable es el período, la fecha de
            # publicación y el veredicto — que cambia, a lo sumo, una vez por edición.
            publicada = obs.ultima_publicacion(db, sector_key=SECTOR_KEY)
            bloque["fuente_del_feed"] = {
                "al_dia": veredicto.estado == AL_DIA,
                "ultimo_periodo": ultimo,
                "ultima_publicacion": publicada.isoformat() if publicada else None,
                "cadencia": "mensual",
            }
            bloque["provincias"] = obs.por_dimension(
                db, sector_key=SECTOR_KEY, series_code="mivhed.licencias.metros_cuadrados",
                period=ultimo, campo="provincia")[:5]
            bloque["tipologias"] = obs.por_dimension(
                db, sector_key=SECTOR_KEY, series_code="mivhed.licencias.metros_cuadrados",
                period=ultimo, campo="tipologia")[:5]
            return bloque
        except Exception:  # noqa: BLE001 — el informe anual nunca depende de esta sección
            logger.exception("Delta mensual omitido en el snapshot de construcción")
            return None

    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        s = _latest_score(self._require_db(), period or None)
        if s is None:
            entity = None if tier == ProductTier.pulse else DISPLAY
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_score": False}, entity_name=entity,
                                   entity_roster=())
        payload: Dict[str, Any] = {"has_score": True, "index": _index_dict(s)}
        # EL MOVIMIENTO DEL MES. Va al PAYLOAD y no solo al contexto del narrador: el
        # fingerprint de la caché de narrativas es del payload, así que un dato que llega
        # solo al contexto cambia sin que la caché se entere y el informe sigue sirviendo la
        # lectura vieja. Es el agujero que ya existe en energía (la serie de tendencia entra
        # al contexto de `positioning` sin estar en el payload) y no se replica acá.
        _delta = self._delta_mensual()
        if _delta:
            payload["delta_mensual"] = _delta
        # EL FINANCIAMIENTO DEL SECTOR, que este eje no tenía de ninguna forma. Mide
        # permisos, m² y concentración geográfica; cuánto crédito recibe la construcción, a
        # qué tasa y con qué mora venía del cubo de la SIB y no salía de banca.
        #
        # AL CIERRE DEL AÑO: el período de este producto es anual y el cubo es trimestral,
        # así que un año se lee con su diciembre. Con el corte de marzo el bloque
        # describiría otro trimestre que el encabezado del informe.
        #
        # Un año sin cubo —la serie arranca en 2024— simplemente no trae el bloque. No se
        # menciona: decisión del dueño del 2026-08-31.
        try:
            from datetime import date

            from shared.perfil_del_sector import (corte_del_cubo_para_el_anio,
                                                 perfil_del_sector)
            _db = self._require_db()
            _corte = corte_del_cubo_para_el_anio(_db, int(str(s.period)[:4]))
            _perfil = perfil_del_sector(_db, "construccion", _corte) if _corte else None
            if _perfil:
                payload["perfil_del_sector"] = _perfil
        except Exception:  # noqa: BLE001 — el snapshot nunca depende de esta lectura
            logger.exception("Perfil del sector omitido en el snapshot de construcción")
        # LA CAPACIDAD DE PAGO DEL HOGAR. Vive en `shared/` porque la leen varios ejes;
        # lo que cambia entre ellos es la LECTURA, no el dato, y ésa la fija la regla de
        # la plantilla. Al MISMO corte que el resto del informe.
        try:
            from shared.capacidad_de_pago import (capacidad_de_pago,
                                                  corte_del_periodo)
            _cap = capacidad_de_pago(self._require_db(),
                                     corte_del_periodo(s.period))
            if _cap:
                payload["capacidad_de_pago"] = _cap
        except Exception:  # noqa: BLE001 — el snapshot nunca depende de esta serie
            logger.exception("Capacidad de pago omitida en el snapshot de construction_intel")
        # DÓNDE SE CONSTRUYE contra la holgura laboral de ESE territorio. El cruce que
        # ninguna otra fuente del sector arma: los permisos traen provincia y la ENCFT
        # trae subutilización por dominio, y nadie los junta. Se pondera por m²
        # licenciados —lo que la fuente mide— y no por un promedio simple de
        # provincias, que daría la holgura de un desarrollador que construyera igual
        # en las treinta y dos.
        #
        # Se lee de `payload` y no de una variable: si el índice no trajo desglose,
        # acá no hay provincias que cruzar y el bloque queda sin esa lectura en vez de
        # con una vacía.
        try:
            from shared.capacidad_de_pago import (corte_del_periodo,
                                                  holgura_donde_opera)
            _provs = ((payload.get("index") or {}).get("geography") or {}).get(
                "breakdown") or []
            if _provs:
                _donde = holgura_donde_opera(
                    self._require_db(), corte_del_periodo(s.period), _provs,
                    clave_peso="sqm", sujeto="pipeline")
                if _donde:
                    payload.setdefault("capacidad_de_pago", {})[
                        "holgura_donde_construye"] = _donde
        except Exception:  # noqa: BLE001 — el snapshot nunca depende de esta serie
            logger.exception("Holgura territorial omitida en construcción")
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period=s.period, payload=payload, entity_name=DISPLAY)

    # ── Muestra sintética (datos demo ilustrativos, sin DB; fiel al dato real 2025) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        index = {"icc_score": 26.52, "band": "Crítico", "coverage": 1.0,
                 "dimensions": {
                     "production": {"score": 9.75, "weight": 0.35,
                                    "provenance": "real", "contribution": 3.41},
                     "pipeline": {"score": 0.0, "weight": 0.35,
                                  "provenance": "real", "contribution": 0.0},
                     "typology_diversification": {"score": 65.31, "weight": 0.15,
                                                  "provenance": "real", "contribution": 9.8},
                     "geographic_breadth": {"score": 88.74, "weight": 0.15,
                                            "provenance": "real", "contribution": 13.31}},
                 "production": {"latest": -1.8, "avg_growth": 0.39, "score": 9.75},
                 "pipeline": {"latest": 4473895.0, "cagr": -7.52, "score": 0.0},
                 "typology": {"hhi": 3971.1, "top": "APARTAMENTOS", "top_share": 59.6,
                              "score": 65.31,
                              # Desglose REAL MIVHED 2025 (m² por tipología, top 8 por m²) —
                              # dato verídico, no fabricado; ordenado por m² licenciados.
                              "breakdown": [
                                  {"typology": "APARTAMENTOS", "permits": 567,
                                   "sqm": 2888911.0, "sqm_share": 64.6},
                                  {"typology": "COMBINADOS", "permits": 46,
                                   "sqm": 689858.0, "sqm_share": 15.4},
                                  {"typology": "COMERCIAL Y OFICINAS", "permits": 95,
                                   "sqm": 273808.0, "sqm_share": 6.1},
                                  {"typology": "HOSPEDAJE", "permits": 14,
                                   "sqm": 202402.0, "sqm_share": 4.5},
                                  {"typology": "VIVIENDAS", "permits": 159,
                                   "sqm": 139755.0, "sqm_share": 3.1},
                                  {"typology": "CENTROS DE RECREACIÓN Y DEPORTES",
                                   "permits": 3, "sqm": 129360.0, "sqm_share": 2.9},
                                  {"typology": "ESTRUCTURAS ESPECIALES", "permits": 22,
                                   "sqm": 87097.0, "sqm_share": 1.9},
                                  {"typology": "ALMACENES", "permits": 10,
                                   "sqm": 31332.0, "sqm_share": 0.7}]},
                 "geography": {"hhi": 1443.1, "top": "SANTO DOMINGO", "top_share": 22.8,
                               "score": 88.74},
                 "levels": {"permits": 951, "sqm": 4473895.0,
                            "investment_dop": 271302161786.0, "prod_growth_latest": -1.8,
                            "prod_growth_3y": 0.39, "top_typology": "APARTAMENTOS",
                            "top_typology_share": 59.6, "top_province": "SANTO DOMINGO",
                            "top_province_share": 22.8},
                 # Capa ONE REAL 2025 (valor tasado por tipología, top 8) — dato verídico.
                 "one_typology": {"year": 2025, "by_typology": {
                     "Edificios de Apartamentos": {"licencias": 781, "construcciones": 1641,
                         "sqm": 3205538.0, "valor_tasado": 45789879594.0},
                     "Combinados": {"licencias": 71, "construcciones": 537,
                         "sqm": 719158.0, "valor_tasado": 10867091787.0},
                     "Hospedaje": {"licencias": 35, "construcciones": 117,
                         "sqm": 344187.0, "valor_tasado": 6388842600.0},
                     "Comerciales y Oficinas": {"licencias": 149, "construcciones": 113,
                         "sqm": 343086.0, "valor_tasado": 5127690355.0},
                     "Centro de Recreación y Deportes": {"licencias": 7, "construcciones": 17,
                         "sqm": 129360.0, "valor_tasado": 2380434236.0},
                     "Viviendas": {"licencias": 222, "construcciones": 408,
                         "sqm": 160579.0, "valor_tasado": 2177221397.0},
                     "Estructuras Especiales": {"licencias": 33, "construcciones": 35,
                         "sqm": 86355.0, "valor_tasado": 1299495325.0},
                     "Apartamentos y Viviendas": {"licencias": 7, "construcciones": 1259,
                         "sqm": 52310.0, "valor_tasado": 784664850.0}}}}
        payload = {"has_score": True, "index": index}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2025", payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period="2025", payload=payload, entity_name=DISPLAY)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas (sin DB) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_score"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        base_ctx = construction_ai_context(snapshot.payload["index"], snapshot.period,
                                           snapshot.payload.get("perfil_del_sector"))
        # LA CAPACIDAD DE PAGO VIAJA AL CONTEXTO, no solo al payload. Es la mitad que
        # se olvida: en la fase 4 el financiamiento llegó al payload y la prosa no lo
        # usó nunca porque el contexto no lo tenía. Servir el dato no alcanza — tiene
        # que llegar al modelo Y la plantilla tiene que pedirlo.
        _cap = (snapshot.payload or {}).get("capacidad_de_pago")
        if _cap:
            base_ctx = {**base_ctx, "capacidad_de_pago": _cap}
        audience = "inversionista"
        templates = {"recommendation": "sector_decision", "positioning": "sector_positioning"}
        out: Dict[str, str] = {}
        # Secciones con cifras → una llamada IA c/u, generadas en PARALELO (asyncio.gather):
        # antes era secuencial (~15s × N secciones). El cliente Anthropic ya libera el event
        # loop (asyncio.to_thread en claude_engine); aquí solo falta lanzar las llamadas juntas.
        pending: List = []   # (section, kwargs de generate)
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la palanca de mayor retorno sobre la "
                                  "coyuntura del sector construcción, dado el cuadro anterior.")
            pending.append((section, dict(
                context=ctx, template=templates.get(section, "construction_outlook"),
                mode=section_mode(tier, section, sections),
                axis="construction_intel", audience=audience)))

        async def _gen(section: str, kwargs: Dict) -> tuple:
            res = await narrative_engine.generate(**kwargs)
            return section, res.text

        for section, text in await asyncio.gather(*(_gen(s, k) for s, k in pending)):
            out[section] = text

        # EL MOVIMIENTO DEL MES: sección PROPIA, con contexto PROPIO.
        #
        # No entra al contexto de `positioning` ni de `construction_assessment`. Son dos
        # sujetos —el índice del año y el flujo del mes— y meterlos en un mismo prompt hace
        # que el modelo elija uno; es la razón por la que banca sirve su mapa sectorial como
        # sección aparte y no dentro del año. Y no está en el manifiesto a propósito: depende
        # del PERÍODO del feed, no del nivel, así que la anexa `orden_de_secciones`.
        delta = (snapshot.payload or {}).get("delta_mensual")
        if delta:
            out["delta_mensual"] = await self._narrar_delta(delta, snapshot)
        return out

    async def _narrar_delta(self, delta: Dict[str, Any],
                            snapshot: ProductSnapshot) -> str:
        """La lectura del movimiento del mes. Determinista cuando está vetada."""
        from modules.construction_intel.ai_context import construction_delta_context
        from shared.narrative.claude_engine import narrative_engine

        no_publicable = delta.get("no_publicable")
        if no_publicable:
            # Prosa determinista: no se le pide al modelo que redacte una ausencia. El texto
            # NOMBRA la causa — un bloque que dice «no disponible» y calla el porqué se lee
            # como un fallo nuestro, y acá el hecho es del emisor.
            return (f"No se publica la lectura del movimiento del mes: {no_publicable}. "
                    f"El índice anual de este informe no depende de este feed y no se ve "
                    f"afectado.")
        res = await narrative_engine.generate(
            context=construction_delta_context(delta, snapshot.period),
            template="construction_delta", mode="standard",
            axis="construction_intel", audience="inversionista")
        encabezado = self._encabezado_del_movimiento(delta)
        return f"{encabezado}\n\n{res.text}" if encabezado else res.text

    @staticmethod
    def _encabezado_del_movimiento(delta: Dict[str, Any]) -> str:
        """El mes nombrado y, si la fuente está atrasada, la declaración. Determinista.

        Va en CÓDIGO y no pedido al modelo: una declaración que tiene que aparecer no puede
        depender de que el narrador se acuerde, y "servir el dato no alcanza" ya se aprendió
        acá. El modelo narra el movimiento; esto garantiza que el lector sepa de qué mes es y
        si hubo ediciones después. Todo sale del bloque computado — ninguna fecha a mano.
        """
        from shared.narrative.formato import fecha_larga_es, mes_largo_es, mes_siguiente

        fuente = delta.get("fuente_del_feed") or {}
        mes = mes_largo_es(fuente.get("ultimo_periodo") or delta.get("periodo"))
        if not mes:
            return ""
        lead = f"Movimiento de {mes}."
        if fuente.get("al_dia", True):
            return lead
        publicada = fecha_larga_es(fuente.get("ultima_publicacion"))
        falta = mes_largo_es(mes_siguiente(fuente.get("ultimo_periodo")))
        if publicada and falta:
            return (f"{lead} Es la última edición que publicó el MIVHED, el {publicada}; "
                    f"la de {falta}, de cadencia mensual, no figura en la fuente a la fecha "
                    f"de este informe.")
        if falta:
            return (f"{lead} Es la última edición disponible del MIVHED; la de {falta}, de "
                    f"cadencia mensual, no figura en la fuente a la fecha de este informe.")
        return lead

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Construcción", "insight": "Insight Construcción",
                 "deep_dive": "Deep Dive Construcción"}.get(tier.value, "Construcción")
        display = ("Sector Construcción · RD" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        charts: List = []
        index = (snapshot.payload or {}).get("index") or {}
        dims = index.get("dimensions") or {}
        if dims:
            labels = {"production": "Producción (PIB)", "pipeline": "Flujo de permisos",
                      "typology_diversification": "Divers. tipológica",
                      "geographic_breadth": "Amplitud geográfica"}
            rows = [["Dimensión", "Score", "Peso"]] + [
                [labels.get(k, k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del ICC", rows))
            items = [(labels.get(k, k), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del ICC (score 0-100)", "items": items})
        # Desagregado por tipología (licencias + m² licenciados + participación en los m² del
        # año) — dato real del MIVHED; valor de profundidad, se reserva a los niveles pagos
        # (Insight/Deep Dive), no al Pulse abierto. NO se muestra "inversión" por tipología:
        # esa columna del MIVHED es un costo estándar derivado (m² × tarifa fija), redundante
        # con los m² y distinto del valor tasado de la ONE.
        typ_rows = ((index.get("typology") or {}).get("breakdown")) or []
        if typ_rows and tier != ProductTier.pulse:
            def _int(v: Optional[float]) -> str:
                return "—" if v is None else f"{int(v):,}"

            def _pct(v: Optional[float]) -> str:
                return "—" if v is None else f"{v:.1f}%"

            trows = [["Tipología", "Licencias", "m² licenciados", "% de m²"]] + [
                [str(r.get("typology") or "—").title(), _int(r.get("permits")),
                 _int(r.get("sqm")), _pct(r.get("sqm_share"))]
                for r in typ_rows[:8]]
            tables.append(("Licencias por tipología (m² licenciados, MIVHED)", trows))
        # Capa autoritativa ONE: valor tasado REAL por tipología (tasación, no costo
        # estándar) + construcciones validadas. Anual; atribuida a la ONE; niveles pagos.
        one = index.get("one_typology") or {}
        one_bt = one.get("by_typology") or {}
        if one_bt and tier != ProductTier.pulse:
            def _i(v: Optional[float]) -> str:
                return "—" if v is None else f"{int(v):,}"

            def _vmm(v: Optional[float]) -> str:
                return "—" if v is None else f"{v / 1e6:,.0f}"

            ordered = sorted(one_bt.items(),
                             key=lambda kv: (kv[1] or {}).get("valor_tasado") or 0, reverse=True)
            orows = [["Tipología", "Licencias", "Construcciones", "m²", "Valor tasado (RD$MM)"]] + [
                [str(lbl).title(), _i(d.get("licencias")), _i(d.get("construcciones")),
                 _i(d.get("sqm")), _vmm(d.get("valor_tasado"))]
                for lbl, d in ordered[:8]]
            yr = one.get("year")
            tables.append((f"Valor tasado por tipología · {yr} (ONE)", orows))
        sc = index.get("icc_score")
        headline = (f"ICC {_fmt(sc)} · {index.get('band')}" if sc is not None else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: ConstructionProduct(db))
