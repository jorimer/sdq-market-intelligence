"""Ensamblador genérico de reportes de producto.

Orquesta la producción de un reporte (sector, nivel) usando SOLO el contrato
``SectorProduct`` — nunca importa un módulo de sector. El flujo es uniforme:

    manifiesto → snapshot del nivel → (sensor de anonimización si es Pulse) →
    narrativas (motor compartido vía el sector) → render (vía el sector)

El "motor" pesado (Claude/narrativa) ya es compartido (``shared/narrative``); este
ensamblador es el director de orquesta. Las cifras se generan dentro del sector con
``cifras_derivadas`` + ``numeric_guard`` (anti-alucinación), no aquí.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import json
import logging
import pathlib
from dataclasses import dataclass
from typing import Dict, Optional

from shared.products.anonymization import AnonymizationError, enforce_anonymized
from shared.products.contract import ProductSnapshot, SectorProduct
from shared.products.filenames import SUJETO_SISTEMA
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec

#: Techo de tiempo del ensamblado de UN informe, apenas por debajo del límite del proxy
#: (~300 s medidos: una descarga que lo cruzó devolvió 502 sin cuerpo). Un informe que no
#: entra acá NO es un informe lento: es uno que el cliente nunca va a recibir, y conviene
#: decirlo con un 503 que invita a reintentar en vez de morir mudo.
#:
#: **Estuvo en 240 s durante unas horas y fue una REGRESIÓN.** Lo calibré contra la Revisión
#: Anual, que narra DOS secciones, y se lo apliqué al Deep Dive de banca, que narra ONCE: a
#: 25-50 s por sección son 275-550 s, así que todo Deep Dive frío moría en 503 a los 240 s —
#: incluidos los que antes alcanzaban a terminar. Se sube a 270 s, que deja 30 s para el
#: render y la serialización sin cortar lo que sí llegaba.
#:
#: **Y esto NO resuelve el Deep Dive.** Once secciones no entran en una petición HTTP
#: síncrona: la cola alta del rango sigue por encima del proxy, y ahí ningún techo ayuda. La
#: cura es generar en segundo plano y entregar cuando esté — un cambio de forma del producto,
#: no una constante. Mientras tanto el 503 es honesto: el servicio no entregó a tiempo.
PRESUPUESTO_DE_ENSAMBLADO_S = 270

logger = logging.getLogger("sdq.products.assembler")

# Bump MANUAL para cambios de lógica que no viven en los prompts (p. ej. el ensamblado de
# secciones acá). Los cambios de PROMPT/modelo/guardrail ya NO dependen de esta constante:
# los cubre `_narrative_logic_version()`.
# "2": doctrina 2026-07-17 (TRADUCE EL TECNICISMO + registro llano de PROCEDENCIA/
# INCERTIDUMBRE) — sin el bump, los reportes cacheados seguirían sirviendo la voz vieja.
NARRATIVE_CACHE_VERSION = "2"


def _contexto_ia_version(modulo_producto: Optional[str]) -> str:
    """Huella del CONSTRUCTOR DE CONTEXTO del sector (``modules/<mod>/ai_context.py``).

    La receta cubría prompts, doctrina, modelo y guard — pero NO lo que se le PASA al modelo.
    Un arreglo de contexto quedaba invisible acá igual que un arreglo de prompt antes de que
    existiera la receta: el 2026-08-11 se corrigió `concentracion_top4_pct` —la clave que hacía
    publicar «cuatro compañías concentran el 87,1%» cuando eran cuatro RAMOS—, se desplegó, y
    el Deep Dive de MAPFRE siguió sirviendo el texto viejo desde Postgres. Esta caché no tiene
    TTL: habría quedado mal indefinidamente.

    *modulo_producto* es ``type(product).__module__`` —p. ej. ``modules.insurance_intel.products``—
    y NO el ``sector_key``. Son cosas distintas: el sector es ``"insurance"`` y el módulo es
    ``insurance_intel``. Derivarlo del objeto evita un mapa sector→carpeta que se desincroniza,
    y evita el fallo silencioso de buscar ``modules/insurance/ai_context.py``, que no existe:
    devolvería "" y la huella no invalidaría nada, con todo en verde.

    Se hashea SOLO el sector que se está rindiendo: invalidar el panel entero por tocar un
    módulo obliga a regenerar ~15-90s por informe sin motivo.
    """
    if not modulo_producto:
        return ""
    partes = modulo_producto.split(".")
    if len(partes) < 2 or partes[0] != "modules":
        # Un producto que NO vive bajo `modules/` —hoy `macro` y `monetary_policy`, en
        # `app/`— devolvía "" y quedaba SIN huella de contexto: un arreglo de lo que el
        # modelo lee no invalidaba nada, y esta caché no tiene TTL. Se hashea su propio
        # archivo, que es exactamente donde arma su contexto.
        #
        # No es tan bueno como la lista declarada —no cubre los ayudantes que importe— pero
        # es infinitamente mejor que la cadena vacía, que no cubre NADA y no avisa.
        try:
            import importlib
            propio = pathlib.Path(importlib.import_module(modulo_producto).__file__ or "")
            if propio.is_file():
                return hashlib.sha256(propio.read_bytes()).hexdigest()[:12]
        except Exception:  # noqa: BLE001 — la huella nunca debe tumbar la entrega
            pass
        return ""
    raiz = pathlib.Path(__file__).resolve().parents[2] / "modules" / partes[1]

    # Por defecto `ai_context.py`. Un módulo que arma el contexto en otro lado lo DECLARA con
    # `AI_CONTEXT_FILES`: banca lo construye en `reports/narrative.py` y en su propio
    # `products.py`, así que sin la declaración su huella quedaba vacía y un arreglo de
    # contexto de banca no invalidaba nada — el defecto que esto vino a cerrar, abierto justo
    # en el módulo más grande.
    archivos = ("ai_context.py",)
    try:
        import importlib
        archivos = tuple(getattr(importlib.import_module(modulo_producto),
                                 "AI_CONTEXT_FILES", archivos))
    except Exception:  # noqa: BLE001 — la huella nunca debe tumbar la entrega
        pass

    h = hashlib.sha256()
    visto = False
    for rel in archivos:
        try:
            h.update((raiz / rel).read_bytes())
            visto = True
        except OSError:
            continue          # archivo declarado que no existe: se ignora, no se falla
    return h.hexdigest()[:12] if visto else ""


def _narrative_logic_version() -> str:
    """Huella de la RECETA de narrativa (prompts compartidos + doctrina + modelo + guard).

    Por qué derivada y no una constante a mano: esta caché vive en Postgres y —a diferencia
    de la L2 de Redis— **no tiene TTL**; se invalida solo si cambia el dato. En un sector con
    el dato quieto, una narrativa cacheada vive indefinidamente. El bump manual estaba
    documentado ("sin el bump… seguirían sirviendo la voz vieja") y aun así no se movió desde
    que se creó: entre medio se desplegaron `NO_META_COMMENTARY` (#580), el veto de léxico
    visceral y `DIRECTION_DISCIPLINE` (#631), o sea tres arreglos de cara al cliente que
    pudieron quedar sin efecto acá. Un mecanismo correcto que depende de que alguien recuerde
    es un mecanismo roto; se deriva del contenido real de los prompts.
    """
    from shared.config.settings import settings
    from shared.narrative import cerebro
    from shared.narrative.claude_engine import TEMPLATES, THIN_TEMPLATES
    from shared.narrative.numeric_guard import GUARD_VERSION

    parts = [
        GUARD_VERSION,
        settings.ANTHROPIC_MODEL or "",
        cerebro.REGISTER_NEUTRO,
        cerebro.EPISTEMIC_STANDARD,
        cerebro.NO_META_COMMENTARY,
        cerebro.DIRECTION_DISCIPLINE,
        cerebro.BARRA_DE_INSIGHT,
        cerebro.CEREBRO_IDENTITY,
    ]
    parts += [v for _, v in sorted(cerebro.AXIS_DOCTRINE.items())]
    # Y las PLANTILLAS POR SECCIÓN, que faltaban. Esta función derivaba la receta de la
    # doctrina compartida y dejaba fuera el prompt concreto de cada sección, que es donde se
    # arregla el 90% de los defectos de redacción. Verificado en producción: se corrigió
    # `early_warning_reading` para que ubicara bien el horizonte —salía «el margen
    # desaparecería alrededor de 3.5 años ANTES DE QUE las reservas dejen de cubrir»—, se
    # desplegó, y el informe siguió sirviendo la frase rota porque ni el dato ni la doctrina
    # habían cambiado. La caché es de Postgres y NO tiene TTL: habría durado para siempre.
    #
    # Se hashean TODAS y no solo las del producto que se rinde: el ensamblador no sabe qué
    # plantillas usa cada sección, y equivocarse hacia el lado de invalidar de más cuesta una
    # regeneración; hacia el otro lado, publica texto viejo sin avisar. Los cambios de
    # plantilla son raros, así que el sobrecosto es acotado.
    parts += [f"{k}={v}" for k, v in sorted(THIN_TEMPLATES.items())]
    parts += [f"{k}={v}" for k, v in sorted(TEMPLATES.items())]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _narrative_fingerprint(payload: Optional[Dict], tier: str, lang: str,
                           modulo_producto: Optional[str] = None) -> str:
    """Hash del snapshot (dato) + tier + idioma + versión + RECETA + CONTEXTO → frescura.

    Si cambia el dato subyacente, la forma de generar el texto O lo que se le pasa al modelo,
    el fingerprint cambia → MISS → se regenera. Sin la receta, un arreglo de prompt no se veía
    nunca acá; sin el contexto, tampoco se veía un arreglo de contexto.
    """
    raw = json.dumps(payload or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(
        f"{raw}|{tier}|{lang}|{NARRATIVE_CACHE_VERSION}|"
        f"{_narrative_logic_version()}|"
        f"{_contexto_ia_version(modulo_producto)}".encode("utf-8")).hexdigest()


async def _narratives_cached(
    product: SectorProduct, tier: ProductTier, snapshot: ProductSnapshot,
    lang: str, scope: Optional[str],
) -> Dict[str, str]:
    """Narrativas del producto con caché por (sector, nivel, ámbito, período, idioma).

    HIT (fingerprint igual) → texto guardado al instante (evita ~15-90s de motor IA).
    MISS → genera y guarda en sitio. La caché NUNCA rompe la entrega: cualquier fallo de
    lectura/escritura cae a la generación directa."""
    from shared.products.models import ProductReportCache

    # Los productos guardan la sesión en `_db` (el contrato SectorProduct no expone `db`
    # público); aceptamos ambos por robustez. OJO: leer solo `db` dejaba esta caché MUERTA
    # —todo producto caía a "sin caché" y regeneraba en cada descarga (~15-90s)—. Sin sesión
    # (muestras/tests) → sin caché, correcto.
    db = getattr(product, "db", None) or getattr(product, "_db", None)
    if db is None:
        return await product.narratives(tier, snapshot, lang)

    fp = _narrative_fingerprint(snapshot.payload, tier.value, lang,
                                modulo_producto=type(product).__module__)
    key = dict(sector_key=product.sector_key, tier=tier.value,
               scope=scope or "", period=snapshot.period or "", lang=lang)
    from shared.narrative.claude_engine import is_static_fallback_text
    row = None
    try:
        row = db.query(ProductReportCache).filter_by(**key).first()
        if row is not None and row.fingerprint == fp:
            cached = dict(row.narratives or {})
            # DEFENSA / AUTO-SANADO: una fila escrita ANTES de que existiera el guard
            # anti-envenenamiento (o por cualquier regresión futura) puede contener fallback
            # estático. Vive en Postgres → sobrevive deploys y se sirve en un HIT SILENCIOSO
            # sin tocar el motor: un Deep Dive premium queda hueco de forma permanente y
            # determinista (el síntoma exacto de las filas cacheadas el 2026-07-27 durante una
            # degradación transitoria, antes del guard de escritura). Si el HIT está degradado
            # se trata como MISS: se regenera y —si el motor ya responde— se re-cachea sano,
            # sin cirugía manual de BD. El log de HIT (antes ausente) da observabilidad.
            if cached and any(is_static_fallback_text(v) for v in cached.values()):
                logger.warning(
                    "caché de narrativas HIT DEGRADADA en %s/%s (scope=%s, período=%s): "
                    "fila envenenada (fallback estático cacheado) — se ignora y regenera.",
                    product.sector_key, tier.value, scope or "", snapshot.period or "")
            else:
                logger.info(
                    "caché de narrativas HIT en %s/%s (scope=%s, período=%s).",
                    product.sector_key, tier.value, scope or "", snapshot.period or "")
                return cached  # HIT sano
    except Exception as e:  # noqa: BLE001 — la caché jamás debe tumbar la entrega
        logger.warning("caché de narrativas (lectura) no disponible: %s", e)
        return await product.narratives(tier, snapshot, lang)

    # El canal se ASEGURA acá y no se abre: si la ruta de entrega ya lo abrió, se usa el
    # suyo —abrir uno anidado descartaría los hallazgos al salir y el gate de entrega no
    # vería nada—; y si nadie lo abrió, este punto igual necesita verlos, porque lo que se
    # persiste acá vive en Postgres SIN TTL.
    # Se retiene la CAJA, no se consulta el ContextVar después: al salir del bloque el
    # ContextVar se restaura, pero el dict sigue siendo el mismo objeto que se fue llenando.
    # Consultarlo después devolvía {} y la fila marcada se cacheaba igual.
    from shared.narrative.cifras_pendientes import asegurando as asegurando_cifras
    with asegurando_cifras() as sin_respaldo:
        narratives = await product.narratives(tier, snapshot, lang)  # MISS → generar
    # NUNCA persistir texto degradado: si el motor IA cayó al fallback estático (rate-limit,
    # outage o corte de presupuesto), cachearlo serviría el mismo relleno hueco incluso
    # después de que el servicio se recupere (envenenamiento de caché). Se devuelve tal cual
    # para que el gate premium de `_content_from_snapshot` decida; la próxima descarga
    # regenerará de verdad. (``is_static_fallback_text`` ya importado arriba.)
    if any(is_static_fallback_text(v) for v in narratives.values()):
        logger.warning(
            "Narrativa degradada a fallback estático en %s/%s (scope=%s, período=%s): "
            "no se cachea; la próxima descarga reintenta.",
            product.sector_key, tier.value, scope or "", snapshot.period or "")
        return narratives
    # NI TEXTO CON CIFRAS SIN RESPALDO, por la misma razón y con más motivo: esta tabla vive
    # en Postgres y NO tiene TTL, así que una cifra que nadie puede respaldar se serviría
    # idéntica y en silencio en cada descarga posterior. Es lo que convirtió un hallazgo del
    # guard en un número citado dentro de un PDF de rating real.
    # El hallazgo lo trae el MOTOR, que juzgó contra el contexto con el que escribió el texto.
    # Antes se re-juzgaba acá con `snapshot.payload`, que no tiene las relaciones computadas
    # (`razones`, `comparaciones`): 133 números contra 55 en un Deep Dive real, y la razón
    # servida —el «132 %» de Asociación Bonao— no estaba entre esos 55. Ver
    # `shared/narrative/hallazgos_pendientes`.
    if sin_respaldo:
        logger.warning(
            "Narrativa con cifras sin respaldo en %s/%s (scope=%s, período=%s): %s — "
            "no se cachea.", product.sector_key, tier.value, scope or "",
            snapshot.period or "", sin_respaldo)
        return narratives
    try:
        if row is None:
            row = ProductReportCache(**key)
            db.add(row)
        row.fingerprint = fp
        row.narratives = narratives
        db.commit()
    except Exception as e:  # noqa: BLE001 — una carrera/constraint no debe romper la entrega
        db.rollback()
        logger.warning("caché de narrativas (escritura) omitida: %s", e)
    return narratives


@dataclass(frozen=True)
class ProductContent:
    """Contenido estructurado de un (sector, nivel), ya con el sensor de anonimización
    aplicado. Lo comparten la vista in-app (JSON) y la descarga PDF: ambas parten del
    MISMO snapshot + narrativas, sin re-implementar la doctrina de cada superficie.

    ``section_order`` es el orden canónico de secciones a renderizar: las del nivel del
    producto + las secciones ESTÁNDAR auto-generadas (metodología/fuentes) anexadas al
    final (ver docs/REPORT_STANDARD.md). Las superficies iteran este orden."""

    level: TierLevelSpec
    snapshot: ProductSnapshot
    narratives: Dict[str, str]
    section_order: tuple = ()


def _assert_system_payload(product: SectorProduct, tier: ProductTier,
                           snapshot: ProductSnapshot):
    """Doctrina: un nivel de sistema (Pulse) jamás emite identificadores. Verifica el
    snapshot ANTES de narrar y devuelve el ``level`` (para reusar la granularidad)."""
    level = product.product_manifest().require_level(tier)
    if level.granularity == Granularity.system:
        if snapshot.entity_name is not None:
            raise AnonymizationError(
                f"Un nivel de sistema de '{product.sector_key}' no debe nombrar "
                f"entidad (entity_name='{snapshot.entity_name}')."
            )
        enforce_anonymized(snapshot.payload, entity_roster=snapshot.entity_roster)
    return level


def _assert_system_narratives(level, snapshot: ProductSnapshot, narratives) -> None:
    """Defensa en profundidad: el TEXTO de un Pulse tampoco puede nombrar entidad."""
    if level.granularity == Granularity.system:
        enforce_anonymized(narratives, entity_roster=snapshot.entity_roster)


def _registrar_tiempo_de_ensamblado(product, tier, scope, snapshot, segundos: float,
                                    *, corto: bool) -> None:
    """Deja en el registro cuánto tardó ARMAR este informe. Best-effort.

    Va al mismo `llm_calls` que ya lleva el gasto —con `purpose="ensamblado"` y coste cero—
    para que el diagnóstico se lea en un solo lugar y sin migración. `corto=True` marca el
    que se pasó del techo, que es el que interesa buscar.
    """
    try:
        from shared.observability.llm_ledger import record_call
        record_call(purpose="ensamblado", model="", cost_usd=0.0,
                    module=product.sector_key, template=tier.value, cache_hit=False,
                    detail={"segundos": round(segundos, 2), "corto_por_tiempo": corto,
                            "scope": scope or "", "periodo": snapshot.period or ""})
    except Exception:  # noqa: BLE001 — medir jamás puede tumbar una entrega
        logger.exception("No se pudo registrar el tiempo de ensamblado")


def orden_de_secciones(declaradas, narrativas, extra) -> tuple:
    """El orden canónico en que se muestran las secciones de un informe.

    **Por qué es una función y no tres líneas dentro del ensamblador.** El orden es lo que
    viaja a la app como `commercial.sections`, y la app dibuja ESO: fuera del orden, una
    sección con texto no existe para el cliente. Extraerlo lo hace comprobable sin montar un
    producto entero — un test que recalcule el orden a mano pasa aunque el ensamblador haga
    otra cosa, que es exactamente lo que pasó al escribirlo la primera vez.

    Tres bloques, en este orden:

    1. las secciones que el manifiesto DECLARA para el nivel;
    2. las que el PRODUCTO produjo y el manifiesto no lista;
    3. el glosario y las estándar (metodología, fuentes), que cierran el documento.

    El bloque 2 faltaba. Le pasó al año por trimestres, cuya sección depende del PERÍODO
    pedido y no del nivel: quedaba en `narratives`, fuera del orden, y la app mostraba un
    informe con «Metodología y fuentes» y NADA en medio. El PDF salía completo porque su
    render recibe la lista de secciones por otra vía. Sin error y sin aviso, en la superficie
    que el cliente mira primero.
    """
    declaradas = tuple(declaradas or ())
    extra = extra or {}
    propias = tuple(k for k in (narrativas or {})
                    if k not in declaradas and k not in extra)
    del_final = tuple(k for k in extra if k not in declaradas)
    return declaradas + propias + del_final


async def _content_from_snapshot(
    product: SectorProduct,
    tier: ProductTier,
    snapshot: ProductSnapshot,
    lang: str,
    scope: Optional[str] = None,
) -> ProductContent:
    """Núcleo compartido: a partir de un snapshot (real o de muestra), aplica el sensor
    de anonimización Pulse y produce las narrativas vía el motor (con caché). NO renderiza."""
    level = _assert_system_payload(product, tier, snapshot)
    # El acumulador se abre ALREDEDOR de la generación: el motor deposita ahí las relaciones
    # invertidas que sobrevivieron a la reparación, y la política se decide abajo, donde se
    # conoce el nivel. Ver `shared/narrative/relaciones_pendientes`.
    from shared.narrative.cifras_pendientes import acumulando as acumulando_cifras
    from shared.narrative.relaciones_pendientes import acumulando
    _t0 = time.monotonic()
    with acumulando() as relaciones_pendientes, acumulando_cifras() as sin_respaldo:
        try:
            narratives = await asyncio.wait_for(
                _narratives_cached(product, tier, snapshot, lang, scope),
                timeout=PRESUPUESTO_DE_ENSAMBLADO_S)
        except asyncio.TimeoutError:
            # TECHO DE TIEMPO. Sin esto, una generación larga muere en el PROXY con un 502
            # sin cuerpo, y el frontend —que lee `detail`— no tiene nada que mostrar salvo
            # «No se pudo cargar el producto». El usuario ve un producto roto en vez del
            # motivo. Ocurrió con la Revisión Anual: el guard reintentaba sobre umbrales
            # prospectivos y la petición llegaba a 16 llamadas al modelo.
            #
            # Se responde el MISMO 503 de la degradación, que es lo que de verdad pasó: el
            # servicio de análisis no entregó a tiempo, y reintentar sirve.
            logger.error(
                "Ensamblado de %s/%s (scope=%s, período=%s) excedió %ds: se responde 503 "
                "en vez de morir en el proxy.", product.sector_key, tier.value, scope or "",
                snapshot.period or "", PRESUPUESTO_DE_ENSAMBLADO_S)
            # Telemetría PROPIA. Sin esto el corte por tiempo no dejaba rastro en el mismo
            # lugar donde se mira la degradación, y las dos causas se volvían la misma cosa.
            from shared.narrative.degradation_events import emit_narrative_degraded
            emit_narrative_degraded(
                surface="products", sector_key=product.sector_key, tier=tier.value,
                sections=list(level.sections), blocked=True, scope=scope,
                period=snapshot.period)
            _registrar_tiempo_de_ensamblado(product, tier, scope, snapshot,
                                            time.monotonic() - _t0, corto=True)
            from shared.narrative.claude_engine import NarrativeDegradedError
            raise NarrativeDegradedError(list(level.sections), motivo="tiempo")
    # GATE DE DEGRADACIÓN: si el motor IA cayó al fallback estático en secciones de ANÁLISIS
    # del nivel, un Deep Dive/Insight —que ES el producto pago completo— saldría hueco
    # ("El análisis ampliado se incorpora en la versión completa del producto"), engañoso y
    # dañino para la marca. Se detecta sobre el TEXTO ya ensamblado (los productos descartan
    # model_used) y se decide por tier: los premium (nombrados) FALLAN cerrado con un error de
    # reintento; el Pulse (abierto) solo se registra. Umbral = 1: una sola sección de análisis
    # degradada ya invalida un premium. La caché nunca guardó este texto (ver _narratives_cached),
    # así que al recuperarse el servicio la próxima descarga regenera de verdad.
    # El TOTAL del ensamblado, al lado de los segundos por sección. Con los dos se responde
    # «¿se pasó del techo por una sección lenta o por la suma?» sin volver a generar nada.
    _registrar_tiempo_de_ensamblado(product, tier, scope, snapshot,
                                    time.monotonic() - _t0, corto=False)

    from shared.narrative.claude_engine import NarrativeDegradedError, degraded_sections
    # Se juzgan las secciones DECLARADAS **y** las que el producto haya producido de más. Un
    # producto puede servir una sección que el manifiesto no lista —banca sirve el año por
    # dentro cuando el período es un AÑO— y el ensamblador ya las anexa al render. Mirando
    # solo `level.sections`, esa sección podía caer a texto estático y salir HUECA sin que
    # ningún gate la viera: el modo de fallo exacto que estos gates existen para cerrar.
    degraded = degraded_sections(narratives, list(dict.fromkeys(
        list(level.sections) + list(narratives or {}))))
    if degraded:
        blocked = level.granularity is not Granularity.system
        logger.warning(
            "Reporte %s/%s (scope=%s, período=%s) con %d/%d sección(es) de análisis "
            "degradada(s) a fallback estático: %s",
            product.sector_key, tier.value, scope or "", snapshot.period or "",
            len(degraded), len(level.sections), degraded)
        # Telemetría de ops (evento interno, no público). Best-effort: no rompe la entrega.
        from shared.narrative.degradation_events import emit_narrative_degraded
        emit_narrative_degraded(
            surface="products", sector_key=product.sector_key, tier=tier.value,
            sections=degraded, blocked=blocked, scope=scope, period=snapshot.period)
        if blocked:
            raise NarrativeDegradedError(degraded)

    # GATE DE CIFRA SIN RESPALDO — el gemelo del anterior, para el otro modo de entregar un
    # informe malo. La degradación deja una sección HUECA y se nota; ésta la deja LLENA con un
    # número que nadie puede respaldar, que se lee como hallazgo y viaja citado. Ya ocurrió:
    # el guard marcó la cifra, el texto sobrevivió a la regeneración y el informe salió con
    # `guard_flags=1` porque la marca no tenía ningún consumidor.
    #
    # Misma política que la degradación, por la misma razón: premium FALLA CERRADO, Pulse solo
    # se registra. Y el veto se LISTA —qué sección y qué hallazgos—: un veto silencioso se lee
    # como que el informe no existía.
    from shared.narrative.claude_engine import NarrativeSinRespaldoError
    if sin_respaldo:
        blocked = level.granularity is not Granularity.system
        logger.warning(
            "Reporte %s/%s (scope=%s, período=%s) afirma cifras sin respaldo en %d/%d "
            "sección(es): %s — %s",
            product.sector_key, tier.value, scope or "", snapshot.period or "",
            len(sin_respaldo), len(level.sections), sin_respaldo,
            "NO se entrega" if blocked else "abierto: solo se registra")
        if blocked:
            raise NarrativeSinRespaldoError(sin_respaldo)

    # GATE DE RELACIÓN INVERTIDA — el tercero, y el más acotado de los tres a propósito. Una
    # relación invertida es REPARABLE: el sistema ya computó la lectura correcta y el motor se
    # la entrega al modelo para que la copie. Por eso el remedio de primera línea es reparar,
    # no vetar — frenar quince secciones buenas por una frase corregible no protege al
    # cliente, le niega un análisis que es correcto casi entero.
    #
    # Se llega acá solo si el modelo contradijo esa lectura DOS veces seguidas. En ese punto ya
    # no es «se equivocó»: es señal de que algo más está roto —quizá el propio guard, como en
    # el falso positivo del 69%— y publicar sería apostar a que el equivocado es el detector.
    #
    # Misma política que sus hermanos: premium FALLA CERRADO, Pulse solo registra.
    if relaciones_pendientes:
        from shared.narrative.claude_engine import NarrativeRelacionInvertidaError
        blocked = level.granularity is not Granularity.system
        logger.warning(
            "Reporte %s/%s (scope=%s, período=%s) afirma relaciones que el dato contradice "
            "en %d sección(es): %s — %s",
            product.sector_key, tier.value, scope or "", snapshot.period or "",
            len(relaciones_pendientes), relaciones_pendientes,
            "NO se entrega" if blocked else "abierto: solo se registra")
        if blocked:
            raise NarrativeRelacionInvertidaError(relaciones_pendientes)
    # Glosario automático (audiencia mixta): detecta las siglas/términos técnicos que la
    # narrativa YA REDACTADA usa y anexa su definición. Va ANTES del merge de las secciones
    # estándar (metodología/fuentes no llevan jerga propia del eje). Punto único: lo
    # heredan la vista in-app (JSON) y el PDF/Word para todos los módulos de sector.
    from shared.products.report_sections import glossary_section, standard_sections
    # Solo valores str: una fila de caché con un valor no-str (columna JSON) no debe
    # tumbar la entrega — misma doctrina defensiva que las secciones estándar.
    glossary = glossary_section(
        "\n\n".join(v for v in narratives.values() if isinstance(v, str)), tier)
    if glossary:
        narratives = {**narratives, **glossary}
    # Secciones ESTÁNDAR auto-generadas (metodología/fuentes) — nuestra ventaja honesta.
    # Se anexan tras las del producto; las heredan online y PDF (docs/REPORT_STANDARD.md).
    # El corte del snapshot ancla la metodología: sin él la sección habla del estado ACTUAL
    # de la plataforma (cobertura, frescura) dentro de un informe fechado antes.
    std = standard_sections(product, tier, as_of=snapshot.period or None)
    if std:
        narratives = {**narratives, **std}
    _assert_system_narratives(level, snapshot, narratives)
    extra = {**glossary, **std}
    order = orden_de_secciones(level.sections, narratives, extra)
    return ProductContent(level=level, snapshot=snapshot, narratives=narratives,
                          section_order=order)


async def assemble_product_content(
    product: SectorProduct,
    tier: ProductTier,
    *,
    period: str,
    scope: Optional[str] = None,
    lang: str = "es",
) -> ProductContent:
    """Produce el contenido (snapshot + narrativas) de un (sector, nivel) aplicando el
    sensor de anonimización Pulse. NO renderiza — es el núcleo compartido entre la vista
    in-app y el PDF. Lanza ``ValueError`` (español) si el sector no ofrece el nivel o el
    snapshot no es resoluble, y ``AnonymizationError`` si un Pulse filtra identificadores.
    """
    snapshot = product.snapshot(tier, period, scope)
    return await _content_from_snapshot(product, tier, snapshot, lang, scope=scope)


async def assemble_product_report(
    product: SectorProduct,
    tier: ProductTier,
    *,
    period: str,
    scope: Optional[str] = None,
    sample: bool = False,
    lang: str = "es",
    output_dir: Optional[str] = None,
    fmt: str = "pdf",
    out: Optional[dict] = None,
) -> str:
    """Ensambla el reporte (sector, nivel) y devuelve el path (PDF o Word según ``fmt``).

    Sector-agnóstico: cualquier ``SectorProduct`` produce su reporte sin que el
    framework conozca su implementación. Reusa ``assemble_product_content`` (mismo
    snapshot + narrativas + sensor de anonimización que la vista in-app) y solo añade
    el render. ``fmt`` = "pdf" | "docx" — misma anatomía de marca.

    ``out`` (opcional): si se pasa un dict, se rellena con metadatos del reporte —
    ``out["period"]`` = el período REAL de los datos ensamblados (``snapshot.period``),
    que puede diferir del ``period`` PEDIDO (p.ej. el Deep Dive resuelve al último dato
    disponible: se pide "2025" y el corte real es "2026-05"); ``out["scope"]`` = la entidad
    analizada (o ``SUJETO_SISTEMA`` en un nivel de sistema). El caller los usa para nombrar
    la descarga en coherencia con la portada; sin ``out`` el comportamiento no cambia (los
    tests no lo pasan).
    """
    content = await assemble_product_content(
        product, tier, period=period, scope=scope, lang=lang)
    if out is not None:
        out["period"] = content.snapshot.period
        # SUJETO del reporte, para que la descarga lo nombre. Sin esto el nombre de archivo
        # era (sector, nivel, período) y DOS entidades del mismo corte producían el mismo
        # nombre: al bajar la segunda, pisaba a la primera. Un Pulse no tiene entidad por
        # diseño (granularidad de sistema) — ahí el sujeto es el sistema, no un hueco.
        out["scope"] = content.snapshot.entity_name or SUJETO_SISTEMA
    return await product.render(
        tier, content.snapshot, content.narratives,
        sample=sample, lang=lang, output_dir=output_dir, fmt=fmt,
    )


def supports_sample(product: SectorProduct) -> bool:
    """¿El producto ofrece una MUESTRA curada tier-1? La muestra es la pieza de conversión:
    exige el exemplar CURADO (``sample_narratives``) + los datos demo (``sample_snapshot``).
    NO basta con datos demo: no se sirve generación al vuelo como muestra. Un sector sin
    exemplar aún no ofrece muestra (botón apagado, honesto)."""
    return (callable(getattr(product, "sample_narratives", None))
            and callable(getattr(product, "sample_snapshot", None)))


async def assemble_sample_report(
    product: SectorProduct,
    tier: ProductTier,
    *,
    lang: str = "es",
    output_dir: Optional[str] = None,
) -> str:
    """Ensambla la MUESTRA (sector, nivel): datos demo sintéticos (``sample_snapshot``) +
    narrativa CURADA tier-1 (``sample_narratives``, exemplar — NO el motor IA), con la
    estampa ``sample=True`` ("MUESTRA — DATA ILUSTRATIVA"). No toca la DB ni datos reales.
    La calidad de la muestra no depende del motor en runtime. Corre el sensor de
    anonimización. Lanza ``ValueError`` (español) si el producto no ofrece exemplar."""
    snap_fn = getattr(product, "sample_snapshot", None)
    curated_fn = getattr(product, "sample_narratives", None)
    if not callable(snap_fn) or not callable(curated_fn):
        raise ValueError(f"'{product.sector_key}' no ofrece muestra curada todavía.")
    snapshot = snap_fn(tier)
    level = _assert_system_payload(product, tier, snapshot)
    narratives = curated_fn(tier)
    _assert_system_narratives(level, snapshot, narratives)
    return await product.render(
        tier, snapshot, narratives, sample=True, lang=lang, output_dir=output_dir,
    )
