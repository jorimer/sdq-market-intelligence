"""SDQ Banking · Revisión Anual — el producto cuya unidad es el AÑO, no el corte.

**Por qué es un producto APARTE y no una sección del Deep Dive trimestral.** Lo fijó el dueño
después de que yo propusiera lo contrario: «son dos deep dive / insight diferentes el cuarto
último del año al Year Review de una entidad». Tiene razón y la razón es de sujeto, no de
presentación:

- el Deep Dive al 31-dic responde **cómo está** la entidad en esa fecha;
- la Revisión Anual responde **cómo le fue** en el ejercicio.

Meter la segunda dentro del primero haría que el contenido del producto variara según el
período —«¿qué estoy comprando?»— y repetiría la confusión que originó todo esto: yo había
afirmado que el informe de diciembre ERA el informe anual. Es falso: la ventana móvil de doce
meses toca UNA magnitud (la utilidad neta, o sea ROA y ROE); los otros diecinueve indicadores
son fotos al 31 de diciembre y el score es una lectura AL CORTE.

**Por qué entra al catálogo como producto propio.** `sector_key` es en realidad la clave de
PRODUCTO, no la de un sector: el catálogo ya lista «Producto AGREGADO (no un sector)», uno
sub-nacional y otro cuyo sujeto es un instrumento normativo. Un producto cuya unidad es el año
entra ahí sin forzar el framework.

**Los tres niveles.** El Pulse anonimizado es el gancho (decisión comercial del dueño): da el
año del sistema sin nombres, y lo nombrado se vende. Cumple la doctrina de que el Pulse jamás
emite identificadores — acá se ejerce con `_anio_del_sistema_anonimo`, que DESCARTA las listas
nominadas del anuario en vez de recortarlas, porque recortar un nombre deja el resto.

**Lo que NO recomputa nada.** El cómputo del año de una entidad vive en `reports/revision_anual`
y el del sistema en `reports/anuario`; los dos están en producción. Este módulo es el envoltorio
de producto.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult
from shared.products import (DataHealth, Granularity, ProductSnapshot, ProductTier,
                             SectorProductManifest, TierLevelSpec, ValidationState)
from shared.products.contract import EstadoBacktest

logger = logging.getLogger("sdq.banking.year_review")

YEAR_REVIEW_KEY = "banking_year_review"

# La huella del CONTEXTO. Sin esta línea `_contexto_ia_version` no encuentra dónde se arma lo
# que ve el modelo, devuelve "" y **ningún arreglo de contexto invalida la caché** — que no
# tiene TTL. Este producto vivió así desde que lo construí: solo se invalidaba cuando algo
# tocaba la RECETA (prompts, modelo, `GUARD_VERSION`), o sea por casualidad.
from modules.banking_score.ai_context_files import AI_CONTEXT_FILES  # noqa: E402,F401


def year_review_manifest() -> SectorProductManifest:
    """Los tres niveles del producto anual.

    El Pulse es el GANCHO: el año del sistema sin nombres. El Insight da el año de UNA
    entidad. El Deep Dive agrega lo que responde la pregunta que el nivel no responde —si el
    movimiento fue suyo o del mercado—, contrastando contra su tipo de entidad y el sistema en
    el MISMO año.
    """
    return SectorProductManifest(
        sector_key=YEAR_REVIEW_KEY,
        display_name="SDQ Banking · Revisión Anual",
        levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("anio_del_sistema", "mapa_sectorial_sistema"),
                narrative_templates=("anio_del_sistema", "banking_sector_map_system"),
                audience="mercado", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("revision_anual",),
                narrative_templates=("revision_anual",),
                audience="comite_credito", cadence="recurring",
                base_report_type="revision_anual", price_band="medio"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("revision_anual", "mapa_sectorial", "contexto_de_mercado"),
                narrative_templates=("revision_anual", "banking_sector_map",
                                     "revision_anual_mercado"),
                audience="comite_credito", cadence="on_demand",
                base_report_type="revision_anual", price_band="alto"),
        },
    )


def _anio_del_sistema_anonimo(anuario: Dict[str, Any]) -> Dict[str, Any]:
    """El año del sistema SIN identificadores, para el nivel abierto.

    Se construye por LISTA BLANCA —se copia lo que puede salir— en vez de borrar las claves
    nominadas. Quitar `cambios_de_banda` y `extremos` de un dict que sigue creciendo es la
    receta para que el próximo campo con nombres salga solo; acá lo que no está declarado no
    viaja. `enforce_anonymized` es la red, no el diseño.
    """
    sis = anuario.get("sistema") or {}
    conteo = anuario.get("conteo_direccion") or {}
    return {
        "anio": anuario.get("anio"),
        "cortes": anuario.get("cortes"),
        "por_corte": sis.get("por_corte"),
        "cambio_mediana": sis.get("cambio_mediana"),
        "cambio_media": sis.get("cambio_media"),
        "estadistico_de_referencia": sis.get("estadistico_de_referencia"),
        "medias_y_medianas_divergen": sis.get("medias_y_medianas_divergen"),
        "lectura_del_sistema": sis.get("lectura"),
        # Cuántas mejoraron / empeoraron / quedaron estables — cifras, no nombres.
        "conteo_direccion": dict(conteo),
        # `por_tipo` trae `tipo_label` al lado de la clave; las dos pasan la anonimización
        # porque nombran un ESTRATO, no una entidad.
        "por_tipo": anuario.get("por_tipo"),
        "entidades_que_cambiaron_de_banda": len(anuario.get("cambios_de_banda") or []),
        "universo": {
            "comparables": (anuario.get("universo") or {}).get("comparables"),
            "vistas_en_el_anio": (anuario.get("universo") or {}).get("vistas_en_el_anio"),
            "parciales": len((anuario.get("universo") or {}).get("parciales") or []),
            "regla": (anuario.get("universo") or {}).get("regla"),
        },
    }


#: Por debajo de esto la entidad y su referencia se movieron "igual". Mismo criterio que el
#: resto del eje: forzar un lado sobre ruido no informa nada.
UMBRAL_CONTRASTE = 0.5


def _contraste_con_el_mercado(cambio_entidad, su_tipo, sistema, tipo) -> Dict[str, Any]:
    """El contraste, COMPUTADO. Es la sección entera del Deep Dive anual.

    Antes se servían tres números sueltos —el cambio de la entidad, el de su tipo y el del
    sistema— y una instrucción de cómo leerlos. La comparación la hacía el modelo, y comparar
    es exactamente la relación que la doctrina obliga a computar: «bajó 4 puntos» no dice nada
    hasta saber qué hizo su estrato.

    `es_idiosincratico` es el veredicto de la sección y por eso se computa, no se insinúa: la
    entidad se movió en sentido CONTRARIO a su tipo, o mucho más que él.
    """
    from modules.banking_score.etiquetas import etiqueta_de_tipo

    ce = None if cambio_entidad is None else float(cambio_entidad)
    ct = None if not su_tipo else _f(su_tipo.get("cambio_mediana"))
    cs = _f((sistema.get("sistema") or {}).get("cambio_mediana"))

    def _vs(ref, etiqueta):
        if ce is None or ref is None:
            return None
        d = round(ce - ref, 2)
        if abs(d) < UMBRAL_CONTRASTE:
            lectura = f"se movió en línea con {etiqueta}"
            sentido = "en línea"
        else:
            sentido = "mejor" if d > 0 else "peor"
            lectura = (f"se movió {abs(d):.2f} puntos {'por encima' if d > 0 else 'por debajo'} "
                       f"de {etiqueta}")
        return {"referencia": etiqueta, "cambio_de_la_referencia": ref,
                "brecha_pp": d, "sentido": sentido, "lectura": lectura}

    etiqueta_tipo = etiqueta_de_tipo(tipo)
    vs_tipo = _vs(ct, f"la mediana de {etiqueta_tipo}")
    vs_sistema = _vs(cs, "la mediana del sistema")

    # Idiosincrático = se movió CONTRA su estrato, o mucho más que él. Las dos condiciones
    # importan: caer mientras el tipo sube es propio, y caer cinco veces más que el tipo
    # también lo es aunque el signo coincida.
    idio = None
    if ce is not None and ct is not None:
        signo_opuesto = (ce > 0) != (ct > 0) and abs(ce - ct) >= UMBRAL_CONTRASTE
        mucho_mas = abs(ce - ct) >= max(2.0, abs(ct))
        idio = bool(signo_opuesto or mucho_mas)

    return {
        "cambio_de_la_entidad": ce,
        "vs_su_tipo": vs_tipo,
        "vs_el_sistema": vs_sistema,
        "tipo_de_entidad": etiqueta_tipo,
        "es_idiosincratico": idio,
        "es_idiosincratico_por_que": (
            None if idio is None else
            ("se movió en sentido contrario a su estrato, o mucho más que él: el movimiento "
             "es propio de la entidad" if idio else
             "acompañó a su estrato: el movimiento es sectorial, no propio")),
        "conteo_direccion": sistema.get("conteo_direccion"),
    }


def _f(x):
    """`float` o `None` — nunca 0.0 por defecto: un cero fabricado se lee como «no se movió»."""
    try:
        return None if x is None else round(float(x), 2)
    except (TypeError, ValueError):
        return None



def _amplitud_al_cierre(db: Session, bank: Bank, anio: int) -> Dict[str, Any]:
    """Los cuatro bloques de amplitud del Deep Dive TRIMESTRAL, computados AL CIERRE del año.

    **Por qué estaban afuera, y por qué era un error.** Los dejé fuera argumentando que «son
    del corte, no del año». El dueño lo refutó en una línea: *«la única diferencia entre un
    trimestre y un año con estos datos es el período comparado»*. Tiene razón — y el código
    trimestral lo dice explícitamente, porque los computa **al corte del informe** y no al
    último disponible. Un año TIENE un corte: su cierre. Excluir hechos no distingue dos
    productos, empobrece uno.

    Peor: la Revisión Anual traía una sección de «señales a vigilar» donde el MODELO elegía
    cuáles eran, existiendo un motor de alerta temprana que las computa. Eso es exactamente
    lo que la doctrina prohíbe — las relaciones se computan, no se derivan.

    Qué se sirve, en paridad EXACTA con el trimestral (mismo nivel, mismo corte):

    * `sensibilidades` — qué palanca mueve el score desde donde cerró el año;
    * `soporte_soberano` — atributo estructural de la entidad, que no depende del período;
    * `early_warning` y `propension_quiebra` — las banderas AL CIERRE;
    * `entorno_macro` — con la MISMA regla de consistencia: un telón fechado después del
      cierre se OMITE. Sin ella, la Revisión Anual 2020 describiría la macro de 2026.

    Best-effort en bloque: ninguno de estos es el sujeto del informe, y que falte uno no
    puede tumbar la entrega del año.
    """
    from modules.banking_score.models.models import RatingResult

    cierre = date(anio, 12, 31)
    out: Dict[str, Any] = {}
    rr = (db.query(RatingResult)
          .filter(RatingResult.bank_id == bank.id,
                  RatingResult.period_end == cierre,
                  RatingResult.model_type == ModelType.deterministic)
          .first())
    if rr is None:                       # sin cierre no hay año; ya lo exige `revision_anual`
        return out

    tipo = bank.bank_type.value if bank.bank_type else None
    # `Column[...]` en tiempo de tipos, `dict` en ejecución: se estrecha una vez acá en vez
    # de repetir `cast` en cada llamada.
    indicadores: Dict[str, Any] = cast(Dict[str, Any], rr.indicator_details or {})

    try:
        from modules.banking_score.scoring.sensitivity import sensitivity_table
        if indicadores:
            out["sensibilidades"] = sensitivity_table(indicadores, tipo)
    except Exception:  # noqa: BLE001
        logger.exception("Sensibilidades omitidas en la Revisión Anual %s de %s", anio, bank.name)

    try:
        from modules.banking_score.scoring.support import support_overlay
        out["soporte_soberano"] = support_overlay(
            db, bank, float(rr.overall_score), cast(str, rr.banda_resiliencia), cierre)
    except Exception:  # noqa: BLE001
        logger.exception("Soporte soberano omitido en la Revisión Anual %s de %s", anio, bank.name)

    try:
        from modules.banking_score.early_warning import bank_alerts
        out["early_warning"] = bank_alerts(db, str(bank.id), cierre)
    except Exception:  # noqa: BLE001
        logger.exception("Alerta temprana omitida en la Revisión Anual %s de %s", anio, bank.name)

    try:
        from modules.banking_score.propension_quiebra import evaluar_entidad
        prop = evaluar_entidad(db, str(bank.name), cierre)
        if prop:
            out["propension_quiebra"] = prop
    except Exception:  # noqa: BLE001
        logger.exception("Propensión omitida en la Revisión Anual %s de %s", anio, bank.name)

    try:
        # MAPA SECTORIAL al CIERRE del año. La lectura que exige el libro de las otras
        # noventa y una entidades, y la única del documento que un banco no puede
        # reproducir con su propia API. Vivía solo en el trimestral: los dos productos
        # ANUALES salían sin ella, que es justamente donde el comité mira el año entero.
        #
        # Al cierre y no al último corte disponible, por la misma razón que todo lo demás
        # de este payload: un año que se resume con el mapa de marzo se contradice con su
        # propio encabezado.
        from modules.banking_score.reports.mapa_sectorial import posicion_de_la_entidad
        mapa = posicion_de_la_entidad(db, bank, cierre)
        if mapa:
            out["mapa_sectorial"] = mapa
    except Exception:  # noqa: BLE001
        logger.exception("Mapa sectorial omitido en la Revisión Anual %s de %s", anio, bank.name)

    try:
        # La CAPACIDAD DE PAGO del deudor. En su PROPIO try y no dentro del anterior: son
        # dos lecturas distintas, y un fallo del mapa no tiene por qué llevarse puesta la
        # otra — es cómo un bloque se apaga por un motivo que no es el suyo.
        from modules.banking_score.reports.capacidad_de_pago import capacidad_de_pago
        cap = capacidad_de_pago(db, cierre)
        # El cruce con el TERRITORIO, cuando el mapa del bloque anterior salió. Se lee de
        # `out` y no de una variable: si el mapa falló, acá no hay provincias que cruzar y
        # el bloque queda sin esa lectura en vez de con una vacía.
        provincias = (out.get("mapa_sectorial") or {}).get("provincias") or []
        if cap and provincias:
            from modules.banking_score.reports.capacidad_de_pago import (
                holgura_donde_presta)
            donde = holgura_donde_presta(db, cierre, provincias)
            if donde:
                cap["holgura_donde_presta"] = donde
        if cap:
            out["capacidad_de_pago"] = cap
    except Exception:  # noqa: BLE001
        logger.exception("Capacidad de pago omitida en la Revisión Anual %s de %s",
                         anio, bank.name)

    try:
        from shared.contracts import load_macro_contract

        from modules.banking_score.products import _posterior_al_corte
        macro = load_macro_contract(db)
        factores = [f for f in (macro.get("factors") or []) if f.get("direction") != "n/d"]
        if factores and not _posterior_al_corte(macro.get("period"), cierre):
            out["entorno_macro"] = {"period": macro.get("period"), "factors": factores}
        elif factores:
            logger.info("Entorno macro omitido en la Revisión Anual %s: el telón (%s) es "
                        "posterior al cierre.", anio, macro.get("period"))
    except Exception:  # noqa: BLE001
        logger.exception("Entorno macro omitido en la Revisión Anual %s de %s", anio, bank.name)

    return out


class BankingYearReviewProduct:
    """``SectorProduct`` del producto anual de banca."""

    ESTADO_BACKTEST = EstadoBacktest(
        tiene_motor=True, eje_motor="banking_score",
        desenlace=("el mismo del Banking Score: distress financiero por entidad-trimestre. "
                   "Este producto NO introduce un motor propio — reencuadra en el AÑO las "
                   "mismas calificaciones ya validadas"),
        motivo=("La Revisión Anual no puntúa: describe el año de una calificación que ya "
                "existe. Su credencial es la del eje que la produce, y se lee de ahí."))

    sector_key = YEAR_REVIEW_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def product_manifest(self) -> SectorProductManifest:
        return year_review_manifest()

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError(
                "BankingYearReviewProduct requiere una sesión de DB para esta operación.")
        return self._db

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        db = self._require_db()
        anios = self.available_periods()
        if not anios:
            return DataHealth(coverage=0.0, freshness_days=None, sources=("SIB", "SIMBAD"),
                              detail="Ningún año cerrado: falta el corte de diciembre.")
        ultimo = int(anios[0])
        n = (db.query(func.count(RatingResult.id))
             .filter(RatingResult.period_end == date(ultimo, 12, 31),
                     RatingResult.model_type == ModelType.deterministic).scalar() or 0)
        # FRESCURA: días desde la observación MÁS NUEVA del panel — la misma definición que
        # usa el producto trimestral. Antes se medía contra el 31 de diciembre del año
        # cerrado, que no es una propiedad del dato sino del calendario: crecía sola y daba
        # un número distinto del que el trimestral publicaba para el mismo panel, así que los
        # dos informes de un mismo paquete se contradecían. Que el informe hable de su corte
        # y no del último dato lo resuelve `report_sections._frescura_md`, anclando al corte.
        ultima_obs = (db.query(func.max(RatingResult.period_end))
                      .filter(RatingResult.model_type == ModelType.deterministic).scalar())
        cierres = "un año cerrado" if len(anios) == 1 else f"{len(anios)} años cerrados"
        entidades = "1 entidad calificada" if n == 1 else f"{n} entidades calificadas"
        return DataHealth(
            coverage=1.0 if n else 0.0,
            freshness_days=(None if ultima_obs is None
                            else (date.today() - ultima_obs).days),
            sources=("SIB", "SIMBAD"),
            detail=f"{cierres}; {entidades} al cierre de {ultimo}.")

    def has_engine(self) -> bool:
        return bool(self.available_periods())

    def validation_state(self) -> ValidationState:
        # No es un motor nuevo: reencuadra en el año las calificaciones del eje 1.
        return ValidationState(approved=True, score=1.0,
                               notes="Reencuadre anual del Banking Score (eje 1, validado).")

    def available_periods(self) -> List[str]:
        """Los AÑOS CERRADOS, del más reciente al más antiguo.

        El período de este producto es un año, no un corte, y solo se listan los que tienen su
        cierre de diciembre: sin él no hay año, hay un tramo — la misma regla que el anuario
        del sistema y la Revisión Anual, declarada una sola vez y aplicada en las tres.
        """
        from modules.banking_score.reports.anuario import _anios_con_cierre
        return [str(a) for a in reversed(_anios_con_cierre(self._require_db()))]

    def scope_options(self) -> List[Dict[str, str]]:
        db = self._require_db()
        filas = (db.query(Bank).filter(Bank.is_active.is_(True))
                 .order_by(Bank.name).all())
        return [{"value": str(b.id), "label": str(b.name),
                 "group": b.bank_type.value if b.bank_type else "otros"} for b in filas]

    def _anio(self, period: str) -> int:
        """El año del período pedido. Vacío = el último CERRADO (invariante del contrato)."""
        disponibles = self.available_periods()
        if not disponibles:
            raise ValueError("No hay ningún año cerrado: falta el corte de diciembre.")
        texto = (period or "").strip()
        if not texto:
            return int(disponibles[0])
        # Se acepta "2025" y también "2025-12-31", porque la barra superior manda una fecha.
        try:
            return int(texto[:4])
        except ValueError:
            raise ValueError(f"Período no reconocido para un producto anual: '{period}'.")

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        anio = self._anio(period)

        if tier == ProductTier.pulse:
            from modules.banking_score.reports.anuario import anuario_del_sistema
            datos = anuario_del_sistema(db, anio)
            if datos is None:
                raise ValueError(
                    f"No hay Revisión Anual {anio} del sistema: el año no cerró o el panel no "
                    "alcanza. Elegí un año ya cerrado.")
            payload_sistema = _anio_del_sistema_anonimo(datos)
            # EL LIBRO DE CRÉDITO DEL PAÍS al cierre del año. Este producto describe el año
            # del SISTEMA y salía sin la única lectura que abre ese sistema por dentro: a qué
            # sectores presta el país, con qué mora y a qué precio.
            #
            # Es la lectura de SISTEMA, no la de entidad: acá no hay entidad que posicionar, y
            # además el nivel es anónimo por doctrina. `sistema_por_sector` agrega todas las
            # supervisadas, así que no introduce ningún identificador.
            try:
                from modules.banking_score.reports.mapa_sectorial import sistema_por_sector
                sis = sistema_por_sector(db, date(anio, 12, 31))
                if sis and sis.get("sectores"):
                    payload_sistema["mapa_sectorial_sistema"] = sis
            except Exception:  # noqa: BLE001 — el snapshot nunca depende de esta tabla
                logger.exception("Mapa del sistema omitido en el año %s", anio)
            return ProductSnapshot(tier=tier, period=str(anio),
                                   payload=payload_sistema, entity_name=None)

        if not scope:
            raise ValueError("Se requiere una entidad para la Revisión Anual.")
        bank = db.query(Bank).filter(Bank.id == scope).first()
        if bank is None:
            raise ValueError(f"Entidad no encontrada: {scope}.")

        # EL AÑO CONTRA LOS AÑOS. Hasta el 2026-08-27 este producto y el trimestral servían
        # el MISMO informe —los dos llamaban a `revision_anual`, que es un híbrido: trae el
        # camino dentro del año Y la comparación contra el cierre anterior—. El dueño lo
        # separó: acá el año TOTAL contra los anteriores y la tendencia; el año por dentro
        # —la serie de sus trimestres— es «SDQ Banking Intelligence».
        from modules.banking_score.reports.anio_contra_anios import anio_contra_anios
        rev = anio_contra_anios(db, bank, anio)
        if rev is None:
            raise ValueError(
                f"No hay Revisión Anual {anio} de {bank.name}: el año no cerró (falta el "
                "corte de diciembre) o la entidad no tiene panel suficiente.")
        payload: Dict[str, Any] = {"revision_anual": rev}

        if tier == ProductTier.deep_dive:
            # El contraste contra el MERCADO: es lo que separa «bajó 4 puntos» de «bajó 4
            # puntos mientras su tipo subió 1». Ya computado por el anuario del sistema.
            from modules.banking_score.reports.anuario import anuario_del_sistema
            sistema = anuario_del_sistema(db, anio)
            if sistema:
                tipo = bank.bank_type.value if bank.bank_type else None
                su_tipo = next((t for t in (sistema.get("por_tipo") or [])
                                if t.get("tipo") == tipo), None)
                # El cambio del año sale de `contra_el_anio_anterior`. Al separar las dos
                # lecturas, esta línea siguió pidiendo `cambio_score` —la clave del cómputo
                # VIEJO— y `.get` devolvía None sin romper nada: el contraste entero se
                # apagó en silencio y el informe salió diciendo que la comparación «no pudo
                # computarse». Un `.get` sobre una clave renombrada no falla, DESAPARECE.
                cambio = (rev.get("contra_el_anio_anterior") or {}).get("cambio")
                payload["contexto_de_mercado"] = _contraste_con_el_mercado(
                    cambio, su_tipo, sistema, tipo)
            payload.update(_amplitud_al_cierre(db, bank, anio))
        return ProductSnapshot(tier=tier, period=str(anio), payload=payload,
                               entity_name=str(bank.name))

    # ── Narrativa ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        from shared.narrative.claude_engine import narrative_engine
        manifest = self.product_manifest().require_level(tier)
        out: Dict[str, str] = {}
        secciones = list(manifest.sections)
        # SIN DATO NO HAY SECCIÓN. El cubo de créditos empieza en 2021: un año anterior no
        # tiene desglose, y tampoco una entidad sin cartera clasificada. Pedirle al modelo
        # que narre un mapa que no existe produce una sección hueca — y el gate de
        # degradación tumba el informe entero.
        for clave in ("mapa_sectorial", "mapa_sectorial_sistema"):
            if clave in secciones and not (snapshot.payload or {}).get(clave):
                secciones = [s for s in secciones if s != clave]
        for seccion in secciones:
            plantilla = ("banking_sector_map_system" if seccion == "mapa_sectorial_sistema"
                         else "anio_del_sistema" if seccion == "anio_del_sistema"
                         else "revision_anual_mercado" if seccion == "contexto_de_mercado"
                         else "banking_sector_map" if seccion == "mapa_sectorial"
                         else "revision_anual")
            ctx: Dict[str, Any] = {"period": snapshot.period}
            if snapshot.entity_name:
                ctx["entity_name"] = snapshot.entity_name
            ctx.update(snapshot.payload or {})
            res = await narrative_engine.generate(
                context=ctx, template=plantilla, mode="deep",
                axis="banking",
                audience="inversionista" if tier == ProductTier.pulse else "comite_credito")
            out[seccion] = res.text
        return out

    # ── Muestra curada ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        """Datos DEMO sintéticos. La entidad es inventada: usar una real convertiría el
        material comercial en una opinión publicada sobre ella."""
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period=SAMPLE_ANIO,
                                   payload=_sample_payload(tier), entity_name=None,
                                   entity_roster=(SAMPLE_ENTIDAD,))
        return ProductSnapshot(tier=tier, period=SAMPLE_ANIO, payload=_sample_payload(tier),
                               entity_name=SAMPLE_ENTIDAD)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Prosa CURADA del exemplar. NO usa el motor: lo que se usa para vender no puede
        depender de que el modelo tenga un buen día."""
        _resolver_narrativa_del_mapa()
        secciones = self.product_manifest().require_level(tier).sections
        return {s: SAMPLE_NARRATIVES[s] for s in secciones}

    # ── Render ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None,
                     fmt: str = "pdf") -> str:
        from modules.banking_score.reports.pdf_generator import generate_pdf_report
        manifest = self.product_manifest().require_level(tier)
        payload = snapshot.payload or {}
        # `scoring_result` NO va vacío: el generador lee de ahí el mapa sectorial para
        # dibujar su tabla. Con `{}` la sección salía con su párrafo y sin las nueve
        # columnas que el párrafo interpreta — que es la mitad del entregable.
        return await generate_pdf_report(
            report_type="revision_anual",
            bank_name=snapshot.entity_name or "Sistema Bancario",
            scoring_result={k: v for k, v in payload.items()
                            if k in ("mapa_sectorial", "mapa_sectorial_sistema")},
            period=str(snapshot.period),
            narratives=narratives,
            output_dir=output_dir,
            sections=list(manifest.sections),
            tier=tier.value,
            watermark=manifest.watermark,
            sample=sample,
            revision=payload.get("revision_anual"),
        )


# ── Muestra curada (exemplar tier-1) ──────────────────────────────────────
#
# El framework exige que todo producto del catálogo ofrezca una MUESTRA, y con razón: un
# producto listado que no puede mostrarse es una vidriera rota. La muestra es un EXEMPLAR
# CURADO —datos sintéticos + prosa escrita a mano—, nunca una generación al vuelo: lo que se
# usa para vender no puede depender de que el modelo tenga un buen día.
#
# La entidad de la muestra es INVENTADA a propósito. Usar una real convertiría el material
# comercial en una opinión publicada sobre esa entidad.

SAMPLE_ANIO = "2025"
SAMPLE_ENTIDAD = "Banco Múltiple Demostración"

#: El año de la muestra tiene un VALLE INTERMEDIO, que es justo el hecho que este producto
#: existe para mostrar: cierra en 71.8 —casi donde abrió— y en el medio cayó a 63.4. El
#: informe al corte de diciembre mostraría «prácticamente sin cambio».
SAMPLE_REVISION = {
    "anio": 2025, "entidad": SAMPLE_ENTIDAD,
    "cortes_del_anio": ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"],
    "cortes_faltantes": [],
    # `score` es el GLOBAL y `banda` es la del eje de RESILIENCIA, que es otro número. La
    # muestra lo exhibe a propósito: 72.4 no podría ser «Sólida» si la banda saliera del
    # score global, porque ese umbral es 75. La resiliencia viaja al lado para que se vea.
    "serie": [{"corte": "2024-12-31", "score": 72.4, "resiliencia": 76.2, "banda": "Sólida"},
              {"corte": "2025-03-31", "score": 68.1, "resiliencia": 75.4, "banda": "Sólida"},
              {"corte": "2025-06-30", "score": 63.4, "resiliencia": 71.0, "banda": "Adecuada"},
              {"corte": "2025-09-30", "score": 67.9, "resiliencia": 73.8, "banda": "Adecuada"},
              {"corte": "2025-12-31", "score": 71.8, "resiliencia": 75.9, "banda": "Sólida"}],
    "apertura": {"corte": "2024-12-31", "score": 72.4, "resiliencia": 76.2, "banda": "Sólida"},
    "cierre": {"corte": "2025-12-31", "score": 71.8, "resiliencia": 75.9, "banda": "Sólida"},
    "cambio_score": -0.6,
    "regla_del_score": ("el score del año es el DEL CIERRE; no se promedian los trimestres"),
    "camino": {"amplitud": 9.0,
               "pico": {"corte": "2024-12-31", "score": 72.4},
               "valle": {"corte": "2025-06-30", "score": 63.4},
               "trimestres_al_alza": 2, "trimestres_a_la_baja": 2,
               "valle_intermedio": True,
               "lectura": ("el año se movió en un rango de 9.00 puntos; el peor momento fue "
                           "2025-06 y NO el cierre, así que el año tuvo una recuperación que "
                           "la foto de diciembre no muestra")},
    "cambios_de_banda": [{"corte": "2025-06-30", "desde": "Sólida", "hasta": "Adecuada"},
                         {"corte": "2025-12-31", "desde": "Adecuada", "hasta": "Sólida"}],
    "balance": [
        {"indicador": "solvencia", "apertura": 15.9, "cierre": 14.6, "cambio": -1.3,
         "subio": False},
        {"indicador": "morosidad", "apertura": 2.1, "cierre": 2.9, "cambio": 0.8,
         "subio": True},
        {"indicador": "liquidez_inmediata", "apertura": 26.4, "cierre": 29.1, "cambio": 2.7,
         "subio": True},
    ],
    "posicion": {"apertura": {"sector": {"percentile": 71}},
                 "cierre": {"sector": {"percentile": 64}}},
}

SAMPLE_SISTEMA = {
    "anio": 2025, "cortes": ["2024-12-31", "2025-12-31"],
    "por_corte": [{"corte": "2024-12-31", "mediana": 68.34, "media": 64.83, "n": 82},
                  {"corte": "2025-12-31", "mediana": 67.93, "media": 65.41, "n": 82}],
    "cambio_mediana": -0.41, "cambio_media": 0.58,
    "estadistico_de_referencia": "mediana", "medias_y_medianas_divergen": True,
    "lectura_del_sistema": ("la mediana del sistema cayó 0.41 puntos en 2025, mientras la "
                            "media subió 0.58"),
    "conteo_direccion": {"mejora": 30, "deterioro": 40, "estable": 12},
    "por_tipo": [{"tipo": "banca_multiple", "n": 16, "cambio_mediana": -1.88,
                  "direccion": "deterioro"}],
    "entidades_que_cambiaron_de_banda": 16,
    "universo": {"comparables": 82, "vistas_en_el_anio": 88, "parciales": 6,
                 "regla": "los agregados se computan solo sobre las entidades comparables"},
}

SAMPLE_MERCADO = {
    "cambio_mediano_del_sistema": -0.41,
    "su_tipo_de_entidad": {"tipo": "banca_multiple", "n": 16, "cambio_mediana": -1.88,
                           "direccion": "deterioro"},
    "conteo_direccion": {"mejora": 30, "deterioro": 40, "estable": 12},
    "como_leerlo": ("el movimiento de la entidad se lee CONTRA el de su tipo y el del sistema "
                    "en el mismo año"),
}

#: Prosa CURADA. No sale del motor: es el material con el que se vende.
SAMPLE_NARRATIVES = {
    "mapa_sectorial_sistema": (
        "El crédito del sistema se concentra en **hogares, no en empresas**: consumo "
        "(26.50%) y vivienda (19.00%) suman casi la mitad del libro del país, y son dos "
        "negocios opuestos. La vivienda se coloca a 11.47% con el 84.25% de la cartera "
        "respaldada por garantía y una mora de 0.78%. El consumo se coloca a 26.58% con "
        "apenas 11.81% de garantía y una mora de 4.31% — cinco veces y media la de "
        "vivienda. El precio no es una anomalía: es el reflejo de que una cartera está "
        "colateralizada y la otra no.\n\n"
        "**El sector a vigilar no es el de mayor mora, sino el de mayor mora TEMPRANA.** "
        "Construcción registra 0.45% de mora de 31 a 90 días —la más alta del sistema, "
        "cuatro veces la de comercio— sobre una mora vencida de apenas 1.13%. Ese "
        "diferencial es la señal: lo que hoy está entre 31 y 90 días es lo que en el "
        "próximo corte será vencido, y ordena por anticipación en vez de por daño ya "
        "consumado.\n\n"
        "**Alojamiento y servicios de comida es el sector con el perfil más particular del "
        "sistema:** 88.72% de su deuda está en moneda extranjera y 82.19% respaldada por "
        "garantía, con la tasa más baja del libro (7.74%) y la mora más baja (0.33%). Es "
        "coherente: un sector con ingresos en divisas, activos hipotecables y por tanto "
        "acceso al crédito más barato del mercado. El riesgo de ese perfil no está en la "
        "mora sino en la exposición cambiaria, que no aparece en esta tabla.\n\n"
        "Al próximo cierre, la mora temprana de construcción es el indicador que confirmaría "
        "o descartaría un deterioro que la mora vencida todavía no muestra."
    ),
    # «mapa_sectorial» NO está acá: su prosa se REUSA del producto trimestral —el mapa al
    # cierre del año ES el mapa de ese corte, y una segunda redacción del mismo hecho puede
    # terminar contradiciendo a la primera— y `products` importa de este módulo, así que
    # resolverla en el literal daría un ciclo. La inserta `_resolver_narrativa_del_mapa`.
    # Tampoco va como `None`: dejaría el dict con valores opcionales y cada consumidor
    # tendría que defenderse de una clave que en la práctica siempre está.
    "anio_del_sistema": (
        "El sistema bancario cerró 2025 prácticamente donde lo abrió, y esa quietud aparente "
        "esconde el hecho del año: la mediana cayó 0,41 puntos mientras la media subió 0,58. "
        "Las dos cifras son correctas y dicen lo contrario. A la media la levantan unos pocos "
        "extremos, así que el año se lee por la mediana — y por la mediana, el sistema "
        "retrocedió.\n\n"
        "El movimiento no fue parejo. La banca múltiple, el estrato de mayor peso, retrocedió "
        "1,88 puntos en su mediana: casi cinco veces el retroceso del sistema. Cuarenta "
        "entidades se deterioraron, treinta mejoraron y doce quedaron estables, de modo que "
        "el retroceso mediano es un desplazamiento del centro y no el efecto de unos pocos "
        "casos.\n\n"
        "El orden se computa sobre las 82 entidades con los cinco cortes del año, de 88 "
        "vistas. Las seis restantes tienen el año incompleto y quedan fuera del orden: un año "
        "parcial no se compara contra uno completo."),
    "revision_anual": (
        "El año de esta entidad no se lee en su cierre. Cerró en 71,8 puntos contra 72,4 de "
        "apertura —seis décimas, ruido— y ese casi-empate es exactamente lo que un informe al "
        "31 de diciembre habría reportado.\n\n"
        "Lo que ocurrió en el medio es otra cosa. El score cayó nueve puntos hasta 63,4 en "
        "junio, perdió la banda Sólida en ese trimestre y la recuperó recién en el cierre. "
        "Fueron dos cambios de banda en doce meses, no cero.\n\n"
        "El balance explica de dónde vino la caída y por qué la recuperación no la revierte "
        "del todo. La solvencia abrió el año en 15,9% y cerró en 14,6%: 1,3 puntos menos de "
        "colchón, un movimiento de balance que la mejora del segundo semestre no deshizo. La "
        "morosidad subió de 2,1% a 2,9%. La liquidez inmediata mejoró 2,7 puntos, y es la "
        "pata que sostiene el cierre.\n\n"
        "Contra el sistema, la entidad perdió terreno: abrió el año en el percentil 71 y lo "
        "cerró en el 64. Mejoró contra sí misma en el segundo semestre y aun así quedó más "
        "abajo en la fila."),
    "contexto_de_mercado": (
        "El retroceso de seis décimas de esta entidad es, en apariencia, mejor que el de su "
        "estrato: la mediana de la banca múltiple cayó 1,88 puntos en el mismo año y la del "
        "sistema 0,41. Medido contra sus pares, la entidad terminó el año por encima del "
        "movimiento típico.\n\n"
        "Pero el contraste tiene un límite que conviene decir. La caída del primer semestre "
        "—nueve puntos— es muy superior a cualquier movimiento sectorial del período, así que "
        "no se explica por el mercado: fue idiosincrática. Lo que sí acompañó al sector fue la "
        "recuperación, en un semestre donde treinta entidades mejoraron.\n\n"
        "La lectura, entonces, es doble: el año cierra mejor que el estrato, y el episodio "
        "que lo definió fue propio."),
}


def _resolver_narrativa_del_mapa() -> None:
    """`SAMPLE_NARRATIVES` se declara arriba y la prosa del mapa vive en `products`, que
    importa de este módulo: resolverla en el literal daría un ciclo. Se completa acá, una
    vez, y el test estructural exige que quede resuelta."""
    if "mapa_sectorial" not in SAMPLE_NARRATIVES:
        from modules.banking_score.products import SAMPLE_NARRATIVES as TRIMESTRAL

        SAMPLE_NARRATIVES["mapa_sectorial"] = TRIMESTRAL["mapa_sectorial"]


#: El libro del PAÍS por sector, para la muestra del nivel abierto. Cifras sintéticas pero
#: coherentes entre sí: los pesos suman cien y la tasa de cada sector se explica por su
#: garantía —consumo caro y sin garantía, vivienda barata y colateralizada—, que es lo que
#: hace que una tabla parezca real cuando alguien la mira con criterio.
SAMPLE_MAPA_SISTEMA: Dict[str, Any] = {
    "corte": f"{SAMPLE_ANIO}-12-31",
    "credito_total_del_sistema": 2_100_000_000_000.0,
    "sectores": [
        {"sector": "Y - CONSUMO DE BIENES Y SERVICIOS", "deuda": 556_500_000_000.0,
         "peso_en_el_sistema_pct": 26.50, "entidades_que_prestan": 38, "mora_pct": 4.31,
         "mora_temprana_31_90_pct": 0.26, "tasa_promedio_ponderada_pct": 26.58,
         "garantia_sobre_deuda_pct": 11.81, "dolarizacion_de_la_deuda_pct": 4.96},
        {"sector": "Z - COMPRA Y REMODELACIÓN DE VIVIENDA", "deuda": 399_000_000_000.0,
         "peso_en_el_sistema_pct": 19.00, "entidades_que_prestan": 31, "mora_pct": 0.78,
         "mora_temprana_31_90_pct": 0.04, "tasa_promedio_ponderada_pct": 11.47,
         "garantia_sobre_deuda_pct": 84.25, "dolarizacion_de_la_deuda_pct": 9.64},
        {"sector": "G - COMERCIO AL POR MAYOR Y AL POR MENOR", "deuda": 252_000_000_000.0,
         "peso_en_el_sistema_pct": 12.00, "entidades_que_prestan": 36, "mora_pct": 1.70,
         "mora_temprana_31_90_pct": 0.11, "tasa_promedio_ponderada_pct": 13.65,
         "garantia_sobre_deuda_pct": 22.14, "dolarizacion_de_la_deuda_pct": 12.06},
        {"sector": "F - CONSTRUCCIÓN", "deuda": 134_400_000_000.0,
         "peso_en_el_sistema_pct": 6.40, "entidades_que_prestan": 29, "mora_pct": 1.13,
         "mora_temprana_31_90_pct": 0.45, "tasa_promedio_ponderada_pct": 11.82,
         "garantia_sobre_deuda_pct": 69.98, "dolarizacion_de_la_deuda_pct": 19.98},
        {"sector": "H - ALOJAMIENTO Y SERVICIOS DE COMIDA", "deuda": 126_000_000_000.0,
         "peso_en_el_sistema_pct": 6.00, "entidades_que_prestan": 24, "mora_pct": 0.33,
         "mora_temprana_31_90_pct": 0.10, "tasa_promedio_ponderada_pct": 7.74,
         "garantia_sobre_deuda_pct": 82.19, "dolarizacion_de_la_deuda_pct": 88.72},
    ],
    "que_es": ("el crédito de TODAS las entidades supervisadas abierto por sector "
               "económico; la mora temprana de 31 a 90 días se deteriora antes que la "
               "vencida, así que ordena por anticipación y no por daño consumado"),
}


def _sample_mapa() -> Dict[str, Any]:
    """El mapa de la muestra anual: el MISMO del producto trimestral, con el sujeto y el
    corte de este producto.

    Se reusa en vez de escribir una segunda tabla sintética a mano. Dos muestras del mismo
    concepto se desincronizan —y la muestra es lo único del payload que nadie recomputa—,
    así que la segunda copia sería la que termina diciendo algo que la primera no dice."""
    from modules.banking_score.products import SAMPLE_MAPA_SECTORIAL

    mapa = dict(SAMPLE_MAPA_SECTORIAL)
    mapa["entidad"] = SAMPLE_ENTIDAD
    mapa["corte"] = f"{SAMPLE_ANIO}-12-31"
    return mapa


def _sample_payload(tier: ProductTier) -> Dict[str, Any]:
    if tier == ProductTier.pulse:
        return {**SAMPLE_SISTEMA, "mapa_sectorial_sistema": SAMPLE_MAPA_SISTEMA}
    payload: Dict[str, Any] = {"revision_anual": dict(SAMPLE_REVISION)}
    if tier == ProductTier.deep_dive:
        payload["contexto_de_mercado"] = dict(SAMPLE_MERCADO)
        payload["mapa_sectorial"] = _sample_mapa()
    return payload


from shared.products.registry import register_product  # noqa: E402

register_product(YEAR_REVIEW_KEY, lambda db: BankingYearReviewProduct(db))
