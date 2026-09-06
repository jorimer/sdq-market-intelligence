"""SDQ Proyecciones Macro — el eje que vende el pronóstico y su track record.

**Por qué es un eje propio y no una sección del eje macro.** Decisión del dueño: se vende
aparte. Medido antes de construir, la familia `special:` no servía para eso —
`is_subscription_sku` no la incluye, así que solo admite intervalo `once`, y `sku_grants`
devuelve `[]`, así que no concede acceso—. Un `special:` es, por diseño, una compra puntual
cotizada a medida cuya entrega media un analista. Un eje del catálogo, en cambio, gana
`insight:macro_forecast` con intervalos mensual/anual y grants reales **sin tocar
`shared/billing`**, que es código de cobro en vivo.

**La cadencia.** Trimestral es la PUBLICACIÓN; el cobro es anual. El informe sale cuando la
operación `macro-forecast-emit` emite, ~45 días tras cerrar el trimestre — el rezago del
IMAE, que es cuando el nowcast tiene algo que decir y ~15 días antes de que el BCRD publique
el PIB. Esa ventana ES el producto.

**Todo el texto de este eje se COMPUTA.** No pasa por el motor de IA, y no es una omisión: un
informe cuyo contenido son cifras de error, coberturas empíricas de intervalos y una
reconciliación exacta no tiene nada que redactar — tiene que reportar. Un modelo escribiendo
esta prosa inventaría justo los números que el producto existe para probar.

**El precio no vive acá.** Se publica con `create_tariff` cuando el dueño lo fije; sin tarifa
vigente el nivel queda inactivo, que es el comportamiento correcto y no un error.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products import (
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
    register_product,
)
from shared.data import medida_de_pronostico as med
from shared.data.periodos import fin_del_periodo, periodo_anterior
from shared.products.contract import EstadoBacktest
from shared.products.render import render_product_pdf
from shared.registry.signals import COVERAGE_PROJECTION

logger = logging.getLogger("sdq.products.macro_forecast")

#: Los archivos que entran en la HUELLA de la caché de narrativas. Este producto redacta con
#: CÓDIGO (`prosa_computada`), así que su «contexto» no es solo `ai_context.py`: es también
#: el archivo que arma el texto. Sin declararlo, cambiar la prosa dejaba el fingerprint
#: IDÉNTICO —medido— y la caché, que no tiene TTL, seguía sirviendo el texto viejo
#: indefinidamente. Lo vigila
#: `shared/products/tests/test_ningun_producto_sin_huella_de_contexto.py`.
AI_CONTEXT_FILES = ("ai_context.py", "products_forecast.py")

SECTOR_KEY = "macro_forecast"
#: La variable objetivo dentro del bloque del BVAR. Es el nombre del MODELO, no un
#: `series_code`: `bloque.codigo_de_variable` lo resuelve a la serie observable.
OBJETIVO_DEL_BLOQUE = "pib_real"
DISPLAY = "SDQ Proyecciones Macro"

SECCION_NOWCAST = "nowcast"
SECCION_TRAYECTORIA = "trajectory"
SECCION_SECTORIAL = "sectoral"
SECCION_DESEMPENO = "forecast_track_record"
SECCION_ESCENARIOS = "scenarios"
SECCION_RESUMEN = "resumen_ejecutivo"
SECCION_PROPOSITO = "proposito_y_alcance"
SECCION_METODOLOGIA = "methodology"

_SECTION_TITLES = {
    SECCION_RESUMEN: "Resumen ejecutivo",
    SECCION_PROPOSITO: "Propósito y alcance",
    SECCION_NOWCAST: "Nowcast del trimestre en curso",
    SECCION_TRAYECTORIA: "Trayectoria proyectada",
    SECCION_SECTORIAL: "Lectura sectorial",
    # En el CUERPO y no en anexo: es el argumento de venta, no la letra chica (§5 del spec).
    SECCION_DESEMPENO: "Desempeño de nuestras proyecciones anteriores",
    SECCION_ESCENARIOS: "Escenarios a 3-8 trimestres (sin track record)",
    # NO empieza con «Metodología»: el framework agrega su propia «Metodología y fuentes»
    # —corte, frescura, cobertura, validación, procedencia— y dos secciones que empiezan
    # igual en el mismo índice se leen como una repetida. Ésta dice de qué están hechos los
    # números; aquélla, de dónde salen y qué los limita como dato.
    SECCION_METODOLOGIA: "Cómo se construye cada cifra",
}

_METODOLOGIA = (
    "**Nowcast.** Ecuación puente IMAE→PIB: se completa el trimestre con un AR sobre el "
    "índice mensual, se agrega a trimestral y se regresa contra el crecimiento del PIB. Se "
    "publica solo porque le gana a un random walk fuera de muestra (+62,9 % con un mes "
    "publicado, +77,9 % con dos). Con los TRES meses publicados no se estima: el índice del "
    "PIB queda determinado por identidad aritmética y se sirve como cifra determinada, sin "
    "banda de error.\n\n"
    "**Trayectoria.** BVAR con prior Minnesota por observaciones artificiales, sobre cinco "
    "variables (PIB, inflación, TPM, tipo de cambio y tasa activa). λ₂ = 1 lo impone el prior "
    "conjugado y se declara en vez de esconderse; λ₁ se elige por verosimilitud marginal en "
    "la ventana de entrenamiento, nunca mirando el error fuera de muestra.\n\n"
    "**El horizonte se corta en dos trimestres, y el corte es estructural.** El modelo le gana "
    "al random walk en los ocho horizontes sobre la muestra completa, pero al excluir la "
    "pandemia esa ventaja no sobrevive más allá del corto plazo. De tres trimestres en "
    "adelante lo que se muestra es un ESCENARIO: lleva su banda y no lleva track record.\n\n"
    "**Sectorial.** Las 17 actividades más los impuestos, con los pesos del cuadro nominal "
    "del BCRD —el único donde la identidad cierra exacta— y reconciliación proporcional al "
    "peso contra el agregado. Con índices encadenados la agregación exacta contra el PIB "
    "publicado es imposible: nuestro agregador queda a 0,149 pp de media, más ajustado que el "
    "propio cuadro de incidencias del BCRD. La profundidad es de 33 trimestres, porque el "
    "cuadro por actividad arranca en 2018.\n\n"
    "**Qué NO es.** Ninguna cifra de este informe es consejo de inversión. Un pronóstico con "
    "banda es una afirmación sobre la incertidumbre, no una promesa sobre el resultado."
)


def macro_forecast_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name=DISPLAY, levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=(SECCION_NOWCAST,), narrative_templates=(), prosa_computada=True,
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            # `insight` es el nivel de SUSCRIPCIÓN: es el que da `insight:macro_forecast`,
            # con intervalos mensual y anual. La decisión fue cobro ANUAL, publicación
            # trimestral.
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.system,
                sections=(SECCION_RESUMEN, SECCION_PROPOSITO,
                          SECCION_NOWCAST, SECCION_TRAYECTORIA, SECCION_SECTORIAL,
                          SECCION_DESEMPENO, SECCION_METODOLOGIA),
                narrative_templates=(), prosa_computada=True,
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            # El tercer nivel no es relleno para cumplir el contrato del framework: es donde
            # viven los ESCENARIOS, que el BVAR produce a 3-8 trimestres y que
            # deliberadamente NO llevan track record. Separarlos por nivel es coherente con
            # separarlos por tipo: `Escenario` no tiene `backtest_id`, así que no puede
            # anclar nada aunque alguien lo intente.
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.system,
                sections=(SECCION_RESUMEN, SECCION_PROPOSITO,
                          SECCION_NOWCAST, SECCION_TRAYECTORIA, SECCION_ESCENARIOS,
                          SECCION_SECTORIAL, SECCION_DESEMPENO, SECCION_METODOLOGIA),
                narrative_templates=(), prosa_computada=True,
                audience="comité / tesorería", cadence="on_demand", price_band="on-demand"),
        })


# ── Lecturas, cada una en SAVEPOINT para no envenenar la transacción externa ──


def _seguro(db: Optional[Session], fn, defecto):
    if db is None:
        return defecto
    try:
        with db.begin_nested():
            return fn(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("lectura de proyecciones no disponible: %s", e)
        return defecto


class MacroForecastProduct:

    ESTADO_BACKTEST = EstadoBacktest(
        tiene_motor=False, obstaculo="sin_corte_transversal",
        desenlace="el valor observado de la serie proyectada cuando el BCRD lo publica",
        motivo=("Tiene backtest —ventana expansiva, point-in-time, contra un random walk— pero "
                "NO es un Gate E de discriminación transversal: el sujeto es UNO (el país), y "
                "un Gini o un IC de rango necesitan un panel que ordenar. Se lee por RMSE "
                "contra el random walk y por la COBERTURA EMPÍRICA de los intervalos, que "
                "viaja al lado del error: un intervalo del 80 % que acierta el 45 % de las "
                "veces está mal calibrado aunque su error medio sea bajo."))
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("MacroForecastProduct requiere una sesión de DB.")
        return self._db

    def product_manifest(self) -> SectorProductManifest:
        return macro_forecast_manifest()

    # ── Readiness ──

    def _vigentes(self) -> List:
        from modules.macro_monitor.forecasting.procedencia import vigentes
        return _seguro(self._db, lambda d: vigentes(d), [])

    def _puntuados(self) -> List:
        from modules.macro_monitor.forecasting.desempeno import filas
        return _seguro(self._db, lambda d: filas(d), [])

    def _sin_poder_puntuarse(self) -> List:
        """Los pendientes que no van a cerrar NUNCA. Se cuentan en readiness porque es la
        superficie que mira un operador sin generar un informe: un `pending` roto y un
        `pending` esperando el trimestre se ven igual desde afuera, y son cosas distintas."""
        from modules.macro_monitor.forecasting.ledger import no_puntuables
        return _seguro(self._db, lambda d: no_puntuables(d), [])

    def _determinadas(self) -> int:
        """Cuántas cifras determinadas hay hoy: 0 o 1.

        No es un pronóstico. Con los tres meses del IMAE publicados, el promedio trimestral
        del índice ES el índice de volumen del PIB por identidad de construcción del BCRD.
        Cuenta como anclada porque lo está: es dato publicado, verificado en cada lectura.
        """
        from modules.macro_monitor.forecasting import nowcast
        c = _seguro(self._db, lambda d: nowcast.cifra_determinada(d, date.today()), None)
        return 1 if c is not None else 0

    def data_signals(self) -> DataHealth:
        """La cobertura de este eje mide ADMISIBILIDAD, no dato medido.

        Devolvía `1.0 if vig else 0.0`, que contesta «¿hay alguna proyección vigente?».
        `DataHealth.coverage` declara contestar otra —«¿qué fracción del peso de mi índice
        está anclada a dato real?»— y la prosa la publicaba con esa lectura: el informe del
        2026-09-05 dijo «100% del índice se construye sobre dato real medido en la fuente»
        cuatro líneas antes de declarar, computado, que el 0% se sostiene en dato real. Y la
        única proyección que sostenía ese 100% ni siquiera pasaba el gate: la tabla del
        propio informe la publica con «¿ancla una afirmación? no».

        Acá el índice ES la proyección, así que la pregunta honesta es qué fracción de lo que
        se publica está sostenida por un pronóstico ADMISIBLE o por una cifra determinada por
        identidad. Va bajo `COVERAGE_PROJECTION` para que ninguna superficie la lea como peso
        anclado a dato medido.
        """
        from modules.macro_monitor.forecasting.procedencia import es_publicable

        vig = self._vigentes()
        determinadas = self._determinadas()
        frescura = None
        if vig:
            cortes = sorted(str(f.as_of) for f in vig)
            try:
                frescura = (date.today() - date.fromisoformat(cortes[-1])).days
            except ValueError:
                frescura = None
        admisibles = sum(1 for m in vig if es_publicable(m)[0])
        publicado = len(vig) + determinadas
        cobertura = (admisibles + determinadas) / publicado if publicado else 0.0
        if vig or determinadas:
            detalle = (f"{admisibles} de {len(vig)} proyección(es) vigente(s) pasan el gate; "
                       f"{determinadas} cifra(s) determinada(s) por identidad; "
                       f"{len(self._puntuados())} conjunto(s) con backtest puntuado"
                       # Lo que no va a cerrar NUNCA se cuenta acá también: es la superficie
                       # que mira un operador sin generar un informe, y ahí un `pending`
                       # roto y uno esperando el trimestre se ven igual.
                       f"{_rotas_en_detalle(self._sin_poder_puntuarse())}")
        else:
            detalle = "sin proyecciones emitidas todavía"
        return DataHealth(
            coverage=cobertura, coverage_kind=COVERAGE_PROJECTION,
            freshness_days=frescura, cadence="quarterly",
            sources=("BCRD — IMAE, PIB por sectores de origen, TPM, tipo de cambio, tasas",
                     "SDQ — ledger de pronósticos (mm_forecast_log)"),
            detail=detalle)

    def has_engine(self) -> bool:
        return bool(self._vigentes())

    def validation_state(self) -> ValidationState:
        """El veredicto se LEE del ledger, nunca se transcribe.

        Sin conjuntos puntuados el score es 0.0 y se dice por qué: en el día uno de un
        producto de pronóstico no hay track record, y fingir uno es exactamente lo que el
        ledger existe para impedir.
        """
        fs = self._puntuados()
        if not fs:
            return ValidationState(
                approved=True, score=0.0,
                notes=("Sin pronósticos puntuados todavía: el track record se acumula a "
                       "medida que los trimestres cierran. Los modelos SÍ tienen backtest "
                       "fuera de muestra (ver Metodología); lo que falta es historial en "
                       "vivo, que es otra cosa y no se sustituye con el backtest."))
        n = sum(f.n_oos for f in fs)
        return ValidationState(
            approved=True, score=min(1.0, n / 12.0),
            notes=(f"{n} pronóstico(s) puntuado(s) en {len(fs)} conjunto(s); el error y la "
                   "cobertura empírica de los intervalos se computan del ledger en cada "
                   "lectura."))

    def available_periods(self) -> List[str]:
        return sorted({str(f.as_of) for f in self._vigentes()}, reverse=True)

    def scope_kind(self) -> str:
        return "system"

    # ── Snapshot ──

    def _payload(self, db: Session) -> Dict[str, Any]:
        from modules.macro_monitor.forecasting import (
            desempeno, nowcast, procedencia, sectoral,
        )
        from modules.macro_monitor.forecasting import panel as panel_mod
        from modules.macro_monitor.forecasting.desempeno import filas

        hoy = date.today()
        proyecciones: List[Dict[str, Any]] = []
        for f in procedencia.vigentes(db, hoy=hoy):
            meta = procedencia.meta_de(db, f)
            ok, motivo = procedencia.es_publicable(meta)
            proyecciones.append({
                "serie": meta.target_series, "horizonte": meta.horizon,
                # La MEDIDA viaja con el punto. Sin ella, la tabla escribía «%» por su
                # cuenta: acertaba mientras la única medida fuera `dlog_pct`, y el día que
                # entre una proyección en nivel publicaría un índice de 133 como «133 %».
                "punto": meta.point, "medida": meta.measure,
                "intervalos": [list(t) for t in meta.intervals],
                "modelo": meta.model_id, "as_of": meta.as_of,
                # La DISTANCIA relativa. Es lo único que faltaba para reconstruir, desde el
                # propio ledger, qué horizonte no se emitió y por qué — ver
                # `_horizontes_ausentes`.
                "h": None if f.h is None else int(f.h),
                "ancla": ok, "motivo": motivo, "n_oos": meta.n_oos,
            })
        cifra = None
        try:
            c = nowcast.cifra_determinada(db, hoy)
            if c is not None:
                cifra = {"trimestre": c.horizon, "indice": c.indice, "dlog_pct": c.dlog_pct,
                         "es_identidad": True,
                         "diferencia_maxima_historica": c.diferencia_maxima_historica}
        except Exception:  # noqa: BLE001
            cifra = None
        sect = None
        sect_motivo = ""
        try:
            panel = sectoral.construir_panel(db)
            if not (panel.trimestres and proyecciones):
                sect_motivo = _SIN_AGREGADO_QUE_DESAGREGAR
            else:
                primera = proyecciones[0]
                # La medida se le pregunta a la FILA, no a la variable del bloque. Dos
                # motores emiten sobre la misma serie con medidas distintas —el nowcast una
                # variación trimestral, el BVAR una interanual—, así que la clase depende de
                # QUÉ FILA es la vigente. Y preguntarle al bloque por el `series_code`
                # lanzaba `KeyError`: ese helper espera el nombre de la variable, y el
                # `except` de abajo se lo tragaba haciendo desaparecer la sección entera.
                clase = panel_mod.clase_de_crecimiento(primera.get("medida"))
                if clase != sectoral.MEDIDA_DEL_PANEL:
                    sect_motivo = _MEDIDAS_QUE_NO_SE_RESTAN.format(
                        agregado=primera.get("medida") or "sin declarar",
                        panel=sectoral.MEDIDA_DEL_PANEL,
                        modelo=primera.get("modelo", "?"))
                    raise _NoSeDesagrega(sect_motivo)
                pr = sectoral.proyectar(
                    panel, g_pib=float(primera["punto"]),
                    horizonte=str(primera["horizonte"]),
                    origen_del_agregado=str(primera["modelo"]),
                    medida_del_agregado=clase)
                sect = {
                    "horizonte": pr.horizonte, "brecha_pp": pr.brecha_pp,
                    "ajuste_pp": pr.ajuste_pp, "brechas": pr.brechas,
                    "sectores": [{"etiqueta": s.etiqueta, "crecimiento": s.crecimiento,
                                  "crecimiento_sin_reconciliar":
                                      s.crecimiento_sin_reconciliar,
                                  "peso": s.peso, "incidencia": s.incidencia}
                                 for s in pr.sectores],
                }
        except _NoSeDesagrega:
            pass          # el motivo ya está escrito, y viaja en el payload
        except Exception as e:  # noqa: BLE001
            logger.warning("lectura sectorial no disponible: %s", e)
            sect_motivo = f"{_FALLO_SECTORIAL} {e}"
        return {
            "proyecciones": proyecciones,
            "escenarios": _escenarios_vigentes(db),
            "cifra_determinada": cifra,
            "sectorial": sect,
            # La sección se ENTERA de por qué no salió. Sin esto, una lectura sectorial
            # ausente y una imposible se leen igual —«no está disponible»— y el informe
            # promete diecisiete secciones y entrega dieciséis sin decir nada.
            "sectorial_motivo": sect_motivo,
            "desempeno": [{"modelo": f.model_id, "serie": f.target_series,
                           "horizonte": f.horizonte, "n_oos": f.n_oos, "rmse": f.rmse,
                           "mae": f.mae,
                           "interval_coverage": [list(t) for t in f.interval_coverage],
                           "solapan": f.solapan}
                          for f in filas(db)],
            # Lo que NO va a cerrar nunca. Viaja en el snapshot porque esta superficie
            # renderiza sin base: si tuviera que consultarla, o se enteraría de otra cosa o
            # —lo que pasó— escribiría su propia copia del texto y el arreglo del otro lado
            # no la tocaría. La superficie no re-juzga: se entera.
            "no_puntuables": desempeno.no_puntuables(db),
        }

    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        payload = self._payload(db)
        if not payload["proyecciones"] and not payload["cifra_determinada"]:
            raise ValueError(
                "No hay proyecciones emitidas todavía. La operación «macro-forecast-emit» "
                "las emite tras cada ingesta canónica, ~45 días después de cerrar el "
                "trimestre.")
        periodo = period or (payload["proyecciones"][0]["as_of"]
                             if payload["proyecciones"] else date.today().isoformat())
        return ProductSnapshot(tier=tier, period=periodo, payload=payload, entity_name=None)

    # ── Narrativas: TODAS deterministas ──

    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        secciones = self.product_manifest().require_level(tier).sections
        p = snapshot.payload
        out: Dict[str, str] = {}
        for sec in secciones:
            if sec == SECCION_RESUMEN:
                out[sec] = _md_resumen_ejecutivo(p)
            elif sec == SECCION_PROPOSITO:
                out[sec] = _PROPOSITO
            elif sec == SECCION_NOWCAST:
                out[sec] = _md_nowcast(p)
            elif sec == SECCION_TRAYECTORIA:
                out[sec] = _md_trayectoria(p)
            elif sec == SECCION_SECTORIAL:
                out[sec] = _md_sectorial(p)
            elif sec == SECCION_DESEMPENO:
                out[sec] = _md_desempeno(p)
            elif sec == SECCION_ESCENARIOS:
                out[sec] = _md_escenarios(p)
            elif sec == SECCION_METODOLOGIA:
                out[sec] = _METODOLOGIA
        return out

    # ── Procedencia por variable ──

    def variable_signals(self) -> Dict[str, Any]:
        """Las proyecciones vigentes, con su meta completa.

        A diferencia del eje macro —donde una señal proyectada va con peso 0 para no diluir
        la cobertura real del índice—, acá el índice del eje **ES** la proyección. Por eso
        llevan peso, y por eso `coverage_projected` de este eje sí dice algo: mide cuánto del
        producto está sostenido por un pronóstico admisible.

        Lleva además la cifra determinada del nowcast, que no es un pronóstico: con los
        tres meses del IMAE publicados el promedio trimestral del índice ES el índice de
        volumen del PIB, por identidad de construcción del BCRD. Es lo único real que
        este eje sirve, y sin ella la procedencia publica un número distinto del de la
        metodología.
        """
        from modules.macro_monitor.forecasting.procedencia import (
            es_publicable, proyeccion_por_serie,
        )
        from shared.registry.signals import GAP, PROJECTED, REAL, VariableSignal

        db = self._db
        if db is None:
            return {"period": None, "signals": [],
                    "coverage_kind": COVERAGE_PROJECTION}
        metas = _seguro(db, lambda d: proyeccion_por_serie(d), {}) or {}
        señales = []
        # La cifra determinada es lo ÚNICO de este eje que sí es dato real, y tiene que
        # llegar al registro: si no, la procedencia la ignora y publica un número distinto
        # del de la metodología. Es el defecto original en chico — dos cifras de cobertura
        # en la misma página.
        for _ in range(self._determinadas()):
            señales.append(VariableSignal(
                key="cifra_determinada_pib", label="PIB real · trimestre determinado",
                state=REAL, weight=1.0, scope="national", cadence="quarterly",
                source="BCRD — IMAE (identidad de construcción, verificada en cada lectura)"))
        for serie, meta in sorted(metas.items()):
            ok, motivo = es_publicable(meta)
            señales.append(VariableSignal(
                key=f"proyeccion_{serie}",
                # La UNIDAD en la etiqueta: `value` es una variación y `serie` nombra un
                # índice de volumen. Sin decirlo, quien lea 0,38 al lado de ese nombre
                # entiende un nivel.
                label=f"{serie} · {meta.horizon} ({_como_se_lee(meta.measure)})",
                # Una proyección que no pasa el gate NO es una proyección mala: es un GAP,
                # con el motivo escrito. Nunca se publica a medias.
                state=PROJECTED if ok else GAP,
                weight=1.0, source=f"{meta.model_id} · mm_forecast_log",
                value=meta.point, period=meta.horizon, scope="national",
                projection=meta if ok else None,
                note="" if ok else motivo,
            ))
        # La semántica viaja con las señales: sin ella el registro lee este eje como si
        # armara un índice de dato real, que es exactamente lo que no hace.
        return {"period": None, "signals": señales,
                "coverage_kind": COVERAGE_PROJECTION}

    # ── Muestra curada ──

    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        return ProductSnapshot(tier=tier, period="2026-08-20", payload=_SAMPLE_PAYLOAD,
                               entity_name=None)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        secciones = self.product_manifest().require_level(tier).sections
        p = _SAMPLE_PAYLOAD
        fijas = {
            SECCION_RESUMEN: _md_resumen_ejecutivo(p),
            SECCION_PROPOSITO: _PROPOSITO,
            SECCION_NOWCAST: _md_nowcast(p),
            SECCION_TRAYECTORIA: _md_trayectoria(p),
            SECCION_SECTORIAL: _md_sectorial(p),
            SECCION_DESEMPENO: _md_desempeno(p),
            SECCION_ESCENARIOS: _md_escenarios(p),
            SECCION_METODOLOGIA: _METODOLOGIA,
        }
        return {sec: fijas[sec] for sec in secciones}

    # ── Render ──

    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None,
                     fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        titulo = {"pulse": "Pulse · Proyecciones Macro",
                  "insight": "Insight · Proyecciones Macro"}.get(tier.value, DISPLAY)
        p = snapshot.payload
        tablas: List = []
        graficos: List = []

        # NO se arman tablas de portada. Las que había —«Proyecciones vigentes» e
        # «Incidencia sectorial proyectada»— publicaban exactamente las filas que la prosa de
        # §Trayectoria y §Lectura sectorial vuelve a publicar, y las de portada salían SIN
        # ENCABEZADO: la lista por comprensión emitía solo filas de dato. Un lector abría el
        # informe con 18 filas de números sin nombres de columna antes de la primera frase, y
        # después las mismas 18 con encabezado. Tras el arreglo de la lectura sectorial la de
        # portada era además un SUBCONJUNTO: 4 columnas contra 5.
        #
        # `render_product_pdf` ofrece `tables_last` para el caso vecino —«un informe que abre
        # con páginas de tablas antes de una sola frase se lee como un anexo», decisión del
        # dueño sobre brand_intel— pero acá no aplica: mover un duplicado no lo deja de ser.
        proys = p.get("proyecciones") or []
        escenarios = p.get("escenarios") or []
        # La trayectoria son las vigentes MÁS los escenarios: son puntos de la misma serie y
        # el informe ya publica los dos. Exigir >=2 sobre las vigentes dejaba el caso real de
        # producción —una vigente y seis escenarios— sin ningún gráfico, con siete puntos
        # disponibles.
        #
        # Los escenarios van ROTULADOS. Un escenario no tiene track record y no ancla ninguna
        # afirmación; fundirlo con un pronóstico en la misma línea borra la distinción que la
        # sección de escenarios se toma tres párrafos en sostener.
        items = [(str(d["horizonte"]), d["punto"]) for d in proys]
        items += [(f"{e['horizonte']} (esc.)", e["punto"]) for e in escenarios]
        if len(items) >= 2:
            # El eje se rotula con la medida DECLARADA, no con un «%» escrito acá: un
            # gráfico con la unidad equivocada es la forma más silenciosa de mentir.
            unidad = _unidad_de(list(proys) + list(escenarios))
            graficos.append({"title": f"Trayectoria proyectada del PIB ({unidad}) · "
                                      "«esc.» = escenario",
                             "items": items, "kind": "line",
                             "unit": _sufijo_de(proys[0] if proys else {}) or ""})

        titular = _titular_de(p.get("cifra_determinada"), proys)

        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=DISPLAY, title=titulo, period=snapshot.period,
            narratives=narratives, section_titles=_SECTION_TITLES, tables=tablas,
            charts=graficos, headline=titular, subtitle=None, watermark=level.watermark,
            sample=sample, output_dir=output_dir, fmt=fmt,
            period_label=ROTULO_DEL_PERIODO)


# ── Prosa determinista ──────────────────────────────────────────────────────────────


def _escenarios_vigentes(db: Session) -> List[Dict[str, Any]]:
    """Los horizontes largos del BVAR, que NO están en el ledger — y por eso hay que
    recomputarlos para mostrarlos. Es el precio de que un escenario no deje rastro de
    pronóstico, y es el precio correcto."""
    from modules.macro_monitor.forecasting import bloque, bvar

    armado = bloque.armar(db)
    if not armado.trimestres:
        return []
    import numpy as np
    # La serie y la medida salen del bloque —igual que en la emisión— y no de una constante
    # escrita acá: un escenario no entra al ledger, pero SÍ se publica, y se publica con su
    # unidad.
    proy = bvar.proyectar_bloque(
        np.array([list(f) for f in armado.Y], dtype=float), armado.nombres,
        armado.trimestres[-1],
        serie_objetivo=bloque.codigo_de_variable(db, OBJETIVO_DEL_BLOQUE),
        medida=bloque.medida_del_punto(OBJETIVO_DEL_BLOQUE))
    if proy is None:
        return []
    return [{"horizonte": e.horizonte, "punto": e.punto, "medida": e.measure or "",
             "intervalos": [list(t) for t in e.intervalos]} for e in proy.escenarios()]


def _rotas_en_detalle(rotas: List) -> str:
    """La coletilla del readiness. Silenciosa cuando no hay nada roto —que es el estado
    sano— y explícita cuando lo hay: si el veto no deja marca, el operador lee «todavía no»
    donde dice «nunca»."""
    if not rotas:
        return ""
    motivos = ", ".join(sorted({r.motivo for r in rotas}))
    return f"; {len(rotas)} SIN PODER PUNTUARSE ({motivos})"


def _como_se_lee(medida: Optional[str]) -> str:
    """La unidad, o el hecho de que no se declaró. «Sin declarar» se dice: callarlo deja la
    cifra leyéndose en la unidad que el lector suponga."""
    return med.COMO_SE_LEE.get(str(medida or ""), "unidad sin declarar")


def _sufijo_de(fila: Dict[str, Any]) -> str:
    """El sufijo que va PEGADO al número de esa fila. Vacío cuando la medida no lo tiene o
    no está declarada: escribir «%» por las dudas es la suposición que costó el defecto."""
    return med.SUFIJO.get(str(fila.get("medida") or ""), "")


def _unidad_de(filas: List[Dict[str, Any]]) -> str:
    """Cómo se lee la columna, para el encabezado. Con medidas mezcladas —o con ninguna
    declarada— se dice eso y no se elige una: una columna rotulada con la unidad equivocada
    es peor que una sin rotular."""
    medidas = {str(d.get("medida") or "") for d in filas}
    if len(medidas) == 1:
        como = med.COMO_SE_LEE.get(medidas.pop(), "")
        if como:
            return como
    return "unidad declarada por fila"


def _banda(intervalos, nivel: float) -> str:
    for tramo in (intervalos or []):
        if len(tramo) >= 3 and abs(float(tramo[0]) - nivel) < 1e-9:
            return f"{float(tramo[1]):.2f} … {float(tramo[2]):.2f}"
    return "—"


def _titular_de(cifra: Optional[Dict[str, Any]],
                proys: List[Dict[str, Any]]) -> Optional[str]:
    """El titular de portada. El «%» salía escrito a mano al lado del punto — la misma
    suposición que en las tablas, en el lugar más visible del documento."""
    if cifra:
        return f"{cifra['trimestre']} determinado · índice {cifra['indice']:.3f}"
    if proys:
        d = proys[0]
        return (f"{_nombre_de_serie(d['serie'])} {d['horizonte']} · "
                f"{d['punto']:.2f}{_sufijo_de(d)}")
    return None


#: Cómo se llama en la portada lo que este eje pone en `period`. NO es un período: es la
#: fecha hasta la que el modelo vio datos, y su propia sección de metodología ya la llamaba
#: «Corte del informe». «Período: 2026-09-06» describía mal el producto.
ROTULO_DEL_PERIODO = "Corte"


def _nombre_de_serie(code: str) -> str:
    """La etiqueta CURADA de una serie, nunca su ruta de hoja de cálculo.

    `canonical.CURATED_LABELS` existe, dice el comentario que la define, «para que un informe
    no lo cite por la ruta de la hoja de cálculo». Este informe la citaba igual: publicaba
    `bcrd.xls.pib_2018.serie_original_indice` en la tabla que el cliente lee.

    Sin etiqueta curada NO se inventa una legible a partir del código: se devuelve tal cual y
    el guard de la prosa lo caza. Maquillar el código acá haría desaparecer el síntoma sin
    que nadie curara la serie.
    """
    from shared.data.bcrd_excel.canonical import curated_label

    return curated_label(code) or str(code)


def _md_resumen_ejecutivo(p: Dict[str, Any]) -> str:
    """Las tres o cuatro frases que un lector usa para decidir si sigue leyendo.

    COMPUTADO del mismo payload que el resto, nunca escrito a mano: un resumen curado
    envejece contra las cifras que resume y termina diciendo algo que el informe desmiente
    tres páginas después. Y dice explícitamente qué NO ancla una afirmación — enterrarlo al
    final es la práctica que esta plataforma existe para no repetir.
    """
    partes: List[str] = []
    cif = p.get("cifra_determinada")
    if cif:
        var = (f", una variación de {cif['dlog_pct']:.2f} % contra el trimestre anterior"
               if cif.get("dlog_pct") is not None else "")
        partes.append(
            f"El trimestre {cif['trimestre']} ya está **determinado**: el índice de volumen "
            f"del PIB es {cif['indice']:.3f}{var}. No es una estimación —es una identidad de "
            "construcción del BCRD— y por eso se sirve sin banda de error.")

    proys = p.get("proyecciones") or []
    if proys:
        d = proys[0]
        anclan = [x for x in proys if x.get("ancla")]
        partes.append(
            f"La proyección vigente para {d['horizonte']} es de **{d['punto']:.2f}"
            f"{_sufijo_de(d)}** ({_como_se_lee(d.get('medida'))}), con una banda del 80 % de "
            f"{_banda(d.get('intervalos'), 0.80)}.")
        if not anclan:
            partes.append(
                "**Ninguna de las proyecciones vigentes pasa hoy el gate de admisibilidad**, "
                "así que ninguna cifra de este informe puede sostener una afirmación anclada. "
                "Se publican con su banda y con el motivo del rechazo, no a medias.")
        elif len(anclan) < len(proys):
            # La concordancia se computa: «1 pasan» es de las cosas que hacen que un
            # informe se lea como generado por una máquina, y esto se vende.
            verbo = "pasa" if len(anclan) == 1 else "pasan"
            partes.append(
                f"De las {len(proys)} proyecciones vigentes, {len(anclan)} {verbo} el gate de "
                "admisibilidad; el resto se publica con el motivo por el que no ancla.")

    sect = p.get("sectorial") or {}
    if sect.get("sectores"):
        mayor = max(sect["sectores"], key=lambda x: x["incidencia"])
        menor = min(sect["sectores"], key=lambda x: x["incidencia"])
        partes.append(
            f"En la desagregación sectorial de {sect.get('horizonte', 'el horizonte')}, quien "
            f"más aporta es **{mayor['etiqueta']}** ({mayor['incidencia']:.3f} pp) y quien "
            f"menos, {menor['etiqueta']} ({menor['incidencia']:.3f} pp).")

    if not partes:
        return ("No hay nada que resumir en este corte: ni cifra determinada ni proyecciones "
                "vigentes. La sección aparece igual — un resumen que solo sale cuando hay "
                "buenas noticias no es un resumen.")
    return "\n\n".join(partes)


_PROPOSITO = (
    "**Qué responde este informe.** Cuánto va a crecer la economía dominicana en los "
    "próximos trimestres, con qué incertidumbre, y qué actividades explican ese número.\n\n"
    "**Qué NO es.** No es una recomendación de inversión ni una proyección oficial: el BCRD "
    "publica las suyas y éstas son nuestras, con nuestros modelos y nuestro track record a "
    "la vista.\n\n"
    "**Alcance.** El sujeto es el país, no una entidad: no hay panel de pares que ordenar, "
    "así que este eje no lleva un score comparativo ni un Gini de discriminación. Se juzga "
    "por el error contra un random walk y por la cobertura empírica de sus intervalos, que "
    "viajan al lado de cada cifra.\n\n"
    "**Cadencia.** Trimestral, atada a la publicación del PIB por el BCRD. Cada proyección "
    "queda registrada antes de conocerse el resultado y se puntúa sola cuando el dato llega."
)


def _md_nowcast(p: Dict[str, Any]) -> str:
    cif = p.get("cifra_determinada")
    if cif:
        var = (f", una variación de **{cif['dlog_pct']:.4f} %** contra el trimestre anterior"
               if cif.get("dlog_pct") is not None else "")
        return (
            f"El índice de volumen del PIB de **{cif['trimestre']}** ya está **determinado**: "
            f"**{cif['indice']:.6f}**{var}.\n\n"
            "No es una estimación. Con los tres meses del IMAE publicados, el promedio "
            "trimestral del índice **es** el índice de volumen del PIB — una identidad de "
            "construcción del BCRD, verificada en cada lectura y no supuesta (diferencia "
            f"máxima histórica: {cif.get('diferencia_maxima_historica', 0.0):.4f} puntos). "
            "Por eso se sirve **sin banda de error**: ponerle una la disfrazaría de "
            "pronóstico.\n\n"
            "Su valor es de **oportunidad**: la cifra queda determinada unos quince días "
            "antes de que el BCRD publique el PIB del trimestre.")
    return ("El trimestre en curso todavía no tiene meses de IMAE suficientes para un "
            "nowcast, y no se estima a medias. Cuando el BCRD publique el primer mes, esta "
            "sección trae el punto y su banda; con los tres meses, la cifra determinada.")


def _n_trimestres_atras(periodo: str, n: int) -> Optional[str]:
    """*n* trimestres hacia atrás desde *periodo*, o ``None`` si alguno no resuelve."""
    actual: Optional[str] = periodo
    for _ in range(n):
        actual = periodo_anterior(actual)
        if actual is None:
            return None
    return actual


def _horizontes_ausentes(proys: List[Dict[str, Any]]) -> List[str]:
    """Los horizontes con track record que este corte NO publica, y por qué.

    El modelo declara `HORIZONTES_CON_TRACK_RECORD` horizontes y la sección de escenarios se
    toma tres párrafos en sostener que del siguiente en adelante NO son pronósticos: el
    lector cuenta, y encontrar menos sin explicación se lee como una errata.

    **La causa se reconstruye del ledger, no se persiste ni se copia de un texto.** Si el
    horizonte presente más cercano es +2T y apunta a 2026-Q3, el bloque terminaba en 2026-Q1
    y +1T apuntaba a 2026-Q2; y estaba vencido si su cierre no es posterior al `as_of` de la
    fila — que es la condición de `emision._es_hacia_adelante`, reproducida.

    Dos límites, declarados en vez de rellenados:

    * Solo se mira un modelo que tenga al menos un horizonte con distancia ≥ 1. El nowcast
      apunta al trimestre en curso (h = 0) y no publica una trayectoria: exigirle dos
      horizontes diría que le faltan dos que nunca tuvo.
    * Si el modelo no emitió NINGUNA fila, no hay de dónde derivar el fin del bloque y no se
      declara nada. Adivinarlo sería inventar la causa de una ausencia.
    """
    from modules.macro_monitor.forecasting.bvar import HORIZONTES_CON_TRACK_RECORD

    esperados = set(range(1, HORIZONTES_CON_TRACK_RECORD + 1))
    por_modelo: Dict[str, List[Dict[str, Any]]] = {}
    for d in proys:
        if d.get("h") is None:
            continue
        por_modelo.setdefault(str(d.get("modelo") or ""), []).append(d)

    lineas: List[str] = []
    for _modelo, filas in sorted(por_modelo.items()):
        presentes = {int(f["h"]) for f in filas}
        if not (presentes & esperados):
            continue                      # el nowcast (h = 0) no publica trayectoria
        faltan = sorted(esperados - presentes)
        if not faltan:
            continue
        ancla = min(filas, key=lambda f: int(f["h"]))
        fin_bloque = _n_trimestres_atras(str(ancla["horizonte"]), int(ancla["h"]))
        if fin_bloque is None:
            continue                      # horizonte relativo: no resuelve a calendario
        as_of = str(ancla.get("as_of") or "")
        corte = fin_del_periodo(as_of)
        bloque_lineas: List[str] = []
        for h in faltan:
            objetivo = _n_trimestres_atras(str(ancla["horizonte"]), int(ancla["h"]) - h)
            if objetivo is None:
                continue
            cierre = fin_del_periodo(objetivo)
            vencido = cierre is not None and corte is not None and cierre <= corte
            plantilla = _HORIZONTE_VENCIDO if vencido else _HORIZONTE_AUSENTE_SIN_CAUSA
            bloque_lineas.append(plantilla.format(rel=f"+{h}T", objetivo=objetivo,
                                                  as_of=as_of))
        if not bloque_lineas:
            continue
        lineas.append(_TRAYECTORIA_INCOMPLETA.format(
            presentes=len(presentes & esperados), esperados=len(esperados),
            fin_bloque=fin_bloque))
        lineas.append("")
        lineas.extend(bloque_lineas)
    return lineas


def _md_trayectoria(p: Dict[str, Any]) -> str:
    proys = p.get("proyecciones") or []
    if not proys:
        return ("No hay proyecciones vigentes para este corte. La operación de emisión las "
                "produce tras cada ingesta canónica.")
    lineas = [f"| serie | horizonte | punto ({_unidad_de(proys)}) | banda 80 % | "
              "¿ancla una afirmación? |",
              "|---|---|---:|---|---|"]
    for d in proys:
        ancla = "sí" if d.get("ancla") else f"no — {d.get('motivo', '')}"
        lineas.append(f"| {_nombre_de_serie(d['serie'])} | {d['horizonte']} | "
                      f"{d['punto']:.2f}{_sufijo_de(d)} | "
                      f"{_banda(d.get('intervalos'), 0.80)} | {ancla} |")
    lineas.append("")
    lineas.append(
        "«Ancla una afirmación» no es un adorno: una proyección solo puede sostener una "
        "respuesta si tiene backtest suficiente detrás. Cuando dice que no, el motivo "
        "está escrito — no se publica a medias ni se calla.")
    # Y el horizonte que NO está también se declara: el lector cuenta los que el modelo
    # promete, y una diferencia sin explicación se lee como una errata.
    ausentes = _horizontes_ausentes(proys)
    if ausentes:
        lineas.append("")
        lineas.extend(ausentes)
    return "\n".join(lineas)


def _md_sectorial(p: Dict[str, Any]) -> str:
    sect = p.get("sectorial")
    if not sect or not sect.get("sectores"):
        # El MOTIVO, no «no está disponible». Una sección que desaparece sin decir por qué
        # se lee como que el informe no la tiene.
        return p.get("sectorial_motivo") or _SIN_AGREGADO_QUE_DESAGREGAR
    lineas = [
        f"Desagregación de la proyección agregada de **{sect['horizonte']}** en las "
        "actividades del PIB. La suma ponderada **reconcilia exactamente** con el agregado "
        "que publicamos.",
        "",
        "| actividad | peso | proyectado | reconciliado | incidencia |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in sect["sectores"]:
        crudo = s.get("crecimiento_sin_reconciliar")
        col_crudo = f"{crudo:.2f} %" if crudo is not None else "—"
        lineas.append(f"| {s['etiqueta']} | {s['peso'] * 100:.2f} % | {col_crudo} | "
                      f"{s['crecimiento']:.2f} % | {s['incidencia']:.3f} pp |")
    lineas.append("")
    # Las DOS columnas, y no solo la reconciliada, porque el ajuste puede darle vuelta el
    # signo a un sector y con una sola columna eso se lee como una contracción proyectada.
    # Pasó: un informe publicó ocho actividades en rojo que el modelo daba todas en verde.
    lineas.append(
        f"«Proyectado» es la lectura del modelo sectorial; «reconciliado» es esa lectura "
        f"después de repartir la brecha contra el agregado, que fue de "
        f"**{sect.get('ajuste_pp', 0.0):+.3f} pp** por actividad. El reparto es proporcional "
        "al PESO y no al crecimiento: repartir por crecimiento le pega más al que más se "
        "mueve y puede darle vuelta el signo a un sector, que es justo la lectura que esta "
        "sección existe para dar. Las dos columnas van juntas para que un cambio de signo "
        "entre una y otra se vea como lo que es —el ajuste— y no como una contracción "
        "proyectada.")
    if sect.get("brechas"):
        faltan = ", ".join(sorted(sect["brechas"]))
        lineas.append(f"\n**No proyectadas:** {faltan}. Una actividad con huecos se declara, "
                      "no se rellena.")
    return "\n".join(lineas)


def _md_escenarios(p: Dict[str, Any]) -> str:
    """Los horizontes largos, nombrados como lo que son.

    El BVAR le gana al random walk en los ocho horizontes sobre la muestra completa, pero al
    excluir la pandemia esa ventaja no sobrevive más allá del corto plazo. Publicar «le gana
    en los 8» sería CIERTO Y ENGAÑOSO.
    """
    esc = p.get("escenarios") or []
    if not esc:
        return ("No hay escenarios para este corte. Se producen junto con la proyección "
                "agregada, a 3-8 trimestres.")
    lineas = [
        "Lo que sigue **no son pronósticos**: son escenarios. Se muestran por su forma y su "
        "banda, no por un historial de acierto — y no lo tienen a propósito. Más allá de dos "
        "trimestres, la ventaja del modelo sobre un random walk **no sobrevive** a excluir la "
        "pandemia de la muestra, así que no se le publica track record.",
        "",
        f"| horizonte | punto ({_unidad_de(esc)}) | banda 80 % |",
        "|---|---:|---|",
    ]
    for d in esc:
        lineas.append(f"| {d['horizonte']} | {d['punto']:.2f}{_sufijo_de(d)} | "
                      f"{_banda(d.get('intervalos'), 0.80)} |")
    lineas.append("")
    lineas.append("Ninguno de estos números puede sostener una afirmación anclada: la "
                  "estructura que los transporta **no tiene** identificador de backtest, así "
                  "que el gate de admisión los rechaza aunque alguien lo intente.")
    return "\n".join(lineas)


def _md_desempeno(p: Dict[str, Any]) -> str:
    """La sección desde el SNAPSHOT. La prosa sale de las constantes de `desempeno`, no de
    literales de acá: la frase de «todavía no hay puntuados» estaba duplicada palabra por
    palabra, y cuando se corrigió del otro lado —porque decía que los trimestres no habían
    cerrado cuando en realidad no PODÍAN cerrar— esta copia siguió mintiendo."""
    from modules.macro_monitor.forecasting import desempeno as desemp

    fs = p.get("desempeno") or []
    rotas = p.get("no_puntuables") or []
    if not fs:
        bloque = desemp.renglones_no_puntuables(rotas)
        if bloque:
            return "\n".join(bloque + ["", desemp.QUE_SI_SE_PUEDE_ESPERAR])
        return desemp.SIN_HISTORIAL
    lineas = ["Cada proyección queda registrada antes de conocerse el resultado, y se puntúa "
              "sola cuando el dato llega.", "",
              "| modelo | serie | horizonte | n | RMSE | MAE | calibración del intervalo |",
              "|---|---|---|---:|---:|---:|---|"]
    for f in fs:
        rmse = f"{f['rmse']:.3f}" if f.get("rmse") is not None else "—"
        mae = f"{f['mae']:.3f}" if f.get("mae") is not None else "—"
        cal = "; ".join(f"el del {n:.0%} acertó el {c:.0%} (n={k})"
                        for n, c, k in (f.get("interval_coverage") or [])) or "sin puntuar"
        lineas.append(f"| {f['modelo']} | {_nombre_de_serie(f['serie'])} | "
                  f"{f['horizonte']} | {f['n_oos']} | "
                      f"{rmse} | {mae} | {cal} |")
    lineas.append("")
    lineas.append(
        "El error medio y la calibración van juntos: un modelo cuyo intervalo del 80 % "
        "acierta el 45 % de las veces está mal calibrado aunque su error medio sea bajo, y "
        "quien dimensione riesgo con ese intervalo se va a equivocar.")
    if any(f.get("solapan") for f in fs):
        lineas.append(
            "En los conjuntos marcados las ventanas **se solapan**: los pronósticos comparten "
            "información, así que el `n` es mayor que el número de observaciones "
            "independientes que lo sostienen. Se declara, no se corrige con una fórmula "
            "inventada.")
    bloque = desemp.renglones_no_puntuables(rotas)
    if bloque:
        lineas.append("")
        lineas.extend(bloque)
    return "\n".join(lineas)


# ── Muestra CURADA ──────────────────────────────────────────────────────────────────
# Cifras ilustrativas; el informe real las computa del ledger. Se elige a propósito un
# cuadro con un resultado incómodo (un intervalo del 90 % que sobre-cubre) y una actividad
# no proyectada: una muestra que solo enseña aciertos vende un producto que no existe.
class _NoSeDesagrega(Exception):
    """La lectura sectorial no procede, y el motivo ya está escrito. Excepción propia y no
    `Exception` a secas: el `except` genérico de abajo existe para lo que falla, y confundir
    «no procede» con «falló» es lo que hace que un motivo se pierda en un warning."""


#: En CONSTANTES y no incrustadas: un literal se parte por ancho de línea y la frase deja de
#: existir en el fuente aunque el valor sea correcto.
_TRAYECTORIA_INCOMPLETA = (
    "**Este corte publica {presentes} de los {esperados} horizontes con track record del "
    "modelo.** El bloque terminaba en {fin_bloque} — hasta ahí llega el dato publicado de "
    "todas sus variables."
)

_HORIZONTE_VENCIDO = (
    "- **{rel}** apuntaba a {objetivo}, un trimestre que **ya había cerrado** al corte "
    "{as_of}. No es un pronóstico que falte: es uno que se evitó. Evaluarlo contra un dato "
    "que ya existía cuando se escribió infla el track record con retrospectiva, que es "
    "justo la contaminación que la disciplina point-in-time existe para impedir. El "
    "horizonte vuelve en cuanto el BCRD publique {objetivo} y el bloque avance."
)

_HORIZONTE_AUSENTE_SIN_CAUSA = (
    "- **{rel}** no está en el ledger de este corte y su trimestre objetivo ({objetivo}) "
    "seguía abierto al {as_of}: la ausencia **no** se explica por el rezago del bloque. Se "
    "declara sin atribuirle una causa."
)

_SIN_AGREGADO_QUE_DESAGREGAR = (
    "La lectura sectorial no está disponible para este corte: sin una proyección agregada "
    "vigente no hay nada que desagregar.")

_MEDIDAS_QUE_NO_SE_RESTAN = (
    "La lectura sectorial no se publica para este corte, y el motivo es de UNIDADES, no de "
    "datos faltantes: la proyección agregada vigente ({modelo}) viene en «{agregado}» y el "
    "panel sectorial proyecta en «{panel}». Restar una tasa trimestral de una suma de tasas "
    "interanuales publicaría como «brecha contra el agregado» lo que es una diferencia de "
    "medidas — pasó, y sacó ocho actividades contrayéndose en un informe donde el modelo "
    "proyectaba las dieciocho positivas. La sección vuelve en cuanto la proyección vigente "
    "sea la interanual del BVAR.")

_FALLO_SECTORIAL = "La lectura sectorial no se pudo construir para este corte:"

#: La serie REAL contra la que se puntúa. La muestra decía `"pib_real"` —el nombre de la
#: variable en el bloque, que no existe como serie—, y una vidriera que enseña el
#: identificador roto enseña a escribirlo.
_SERIE_PIB = "bcrd.xls.pib_2018.serie_original_indice"

_SAMPLE_PAYLOAD: Dict[str, Any] = {
    "proyecciones": [
        {"serie": _SERIE_PIB, "horizonte": "2026-Q3", "punto": 3.41,
         "medida": med.DLOG_PCT,
         "intervalos": [[0.80, 2.11, 4.71], [0.90, 1.62, 5.20]],
         "modelo": "bvar_minnesota.5v.v1", "as_of": "2026-08-20", "ancla": True,
         "motivo": "", "n_oos": 14},
        {"serie": _SERIE_PIB, "horizonte": "2026-Q4", "punto": 3.08,
         "medida": med.DLOG_PCT,
         "intervalos": [[0.80, 1.44, 4.72], [0.90, 0.82, 5.34]],
         "modelo": "bvar_minnesota.5v.v1", "as_of": "2026-08-20", "ancla": False,
         "motivo": "8 observaciones fuera de muestra: hacen falta al menos 12",
         "n_oos": 8},
    ],
    "cifra_determinada": {"trimestre": "2026-Q2", "indice": 133.133185,
                          "dlog_pct": 0.3809, "es_identidad": True,
                          "diferencia_maxima_historica": 0.0015},
    "sectorial": {
        "horizonte": "2026-Q3", "brecha_pp": -0.4178, "ajuste_pp": -0.4713,
        "brechas": {},
        # Cada sector lleva su crudo Y su reconciliado, y el ajuste (-0,4713 pp) es la
        # diferencia exacta entre las dos columnas. La muestra vieja traía solo el
        # reconciliado, y por eso enseñaba una tabla que el pipeline no podía producir.
        "sectores": [
            {"etiqueta": "Construcción", "crecimiento": 5.40,
             "crecimiento_sin_reconciliar": 5.87, "peso": 0.1226, "incidencia": 0.662},
            {"etiqueta": "Comercio", "crecimiento": 2.04,
             "crecimiento_sin_reconciliar": 2.51, "peso": 0.1173, "incidencia": 0.240},
            {"etiqueta": "Hoteles, bares y restaurantes", "crecimiento": 6.77,
             "crecimiento_sin_reconciliar": 7.24, "peso": 0.1000, "incidencia": 0.677},
            {"etiqueta": "Manufactura local", "crecimiento": 2.39,
             "crecimiento_sin_reconciliar": 2.86, "peso": 0.0906, "incidencia": 0.217},
            {"etiqueta": "Impuestos a la producción netos de subsidios", "crecimiento": 3.10,
             "crecimiento_sin_reconciliar": 3.57, "peso": 0.0687, "incidencia": 0.213},
        ],
    },
    "escenarios": [
        {"horizonte": "2027-Q1", "punto": 2.94, "medida": med.DLOG_PCT,
         "intervalos": [[0.80, 0.71, 5.17]]},
        {"horizonte": "2027-Q2", "punto": 2.81, "medida": med.DLOG_PCT,
         "intervalos": [[0.80, 0.24, 5.38]]},
    ],
    "desempeno": [
        {"modelo": "bridge_imae_pib.m2.v1", "serie": _SERIE_PIB, "horizonte": "+1T",
         "n_oos": 14, "rmse": 1.405, "mae": 1.062,
         "interval_coverage": [[0.80, 0.79, 14]], "solapan": False},
        {"modelo": "bvar_minnesota.5v.v1", "serie": _SERIE_PIB, "horizonte": "+2T",
         "n_oos": 13, "rmse": 4.640, "mae": 3.518,
         "interval_coverage": [[0.80, 0.85, 13], [0.90, 1.00, 13]], "solapan": True},
    ],
}


register_product(SECTOR_KEY, lambda db: MacroForecastProduct(db))
