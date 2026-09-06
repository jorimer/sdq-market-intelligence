"""El producto del eje `valuation`. Registrado y DECLARADAMENTE sin motor todavía.

Que un eje esté en el catálogo no lo hace vendible: `has_engine()` devuelve False hasta que
existan el costo de capital (T-VL-3) y el Excess Return (T-VL-4), y con eso el readiness no
alcanza ningún umbral y ningún nivel se activa. Es el comportamiento correcto — el alta del
eje y la capacidad de entregar son dos cosas, y confundirlas es cómo se publica una vidriera
vacía.

**Lo que este eje NO hace, y se dice acá arriba porque es la confusión cara.** `banking_score`
responde «qué tan sana está» —Perfil SDQ, propensión a quiebra, alertas tempranas— y
**ninguna de esas salidas se convierte en un valor**. Un score alto describe solidez, no
precio. Una entidad puede estar sólida y destruir valor; una entidad rentable puede valer
menos que su libro.

**El método.** Excess Return (residual income): la entidad vale su libro más el valor presente
de lo que gane POR ENCIMA de lo que su capital exige. De ahí sale la lectura que abre el
informe —`ROE − Ke`— y de ahí sale que el valor sea un RANGO: el costo de capital no se
observa, se estima, y cincuenta puntos básicos mueven el resultado.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

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
from shared.products.contract import EstadoBacktest
from shared.products.render import render_product_pdf
# La huella de la caché de informes se busca en el módulo del PRODUCTO. La lista vive en
# `ai_context.py`; acá se re-exporta el MISMO objeto, no una copia — dos listas divergen.
from modules.valuation.ai_context import AI_CONTEXT_FILES  # noqa: F401,E402


logger = logging.getLogger("sdq.products.valuation")

SECTOR_KEY = "valuation"
DISPLAY = "SDQ Valuación de Entidades"

# ── La estructura del informe ────────────────────────────────────────────────────
#
# Sigue el orden de un informe de valuación profesional —resumen, propósito y alcance,
# antecedentes, análisis financiero, metodología, conclusión, supuestos— con dos
# adaptaciones que el sector impone y que conviene decir en voz alta:
#
# 1. **No hay EBITDA.** El estándar genérico de valuación de empresas lo pide, y en una
#    entidad financiera no significa nada: no hay depreciación relevante, el interés no es
#    un costo de financiamiento sino el negocio, y el apalancamiento es materia prima. El
#    análisis financiero va sobre lo que SÍ mide a un banco — patrimonio, resultado, ROE
#    sobre apertura, crecimiento del balance.
# 2. **El resumen abre por el SPREAD y no por el valor.** Quien ve el spread entiende la
#    palanca; quien ve solo el valor discute el supuesto. Es la decisión de diseño que ya
#    estaba y se conserva.
SECCION_RESUMEN = "resumen_ejecutivo"
SECCION_PROPOSITO = "proposito_y_alcance"
SECCION_ANTECEDENTES = "antecedentes_de_la_entidad"
SECCION_FINANCIERO = "analisis_financiero"
SECCION_SPREAD = "spread_roe_ke"
SECCION_METODOLOGIA = "metodologia"
SECCION_VALOR = "valor_y_rango"
SECCION_DESCOMPOSICION = "libro_vs_exceso"
#: El panel de transacciones LLEGA al informe: tabla de comparables, mediana y rango,
#: y la posición del rango de salida contra ellos. Contraste, no método.
SECCION_CONTRASTE = "contraste_de_mercado"
SECCION_SUPUESTOS = "supuestos_y_sensibilidad"
SECCION_LIMITACIONES = "limitations"
SECCION_FUENTES = "fuentes_y_procedencia"
#: Vías abiertas, descartes con motivo y lo que cada comparable NO permite afirmar. Un
#: panel chico sin explicación se lee como falta de trabajo; el anexo es el trabajo.
SECCION_ANEXO_PANEL = "anexo_panel_de_transacciones"

_SECTION_TITLES = {
    SECCION_RESUMEN: "Resumen ejecutivo",
    SECCION_PROPOSITO: "Propósito y alcance",
    SECCION_ANTECEDENTES: "La entidad y su posición",
    SECCION_FINANCIERO: "Análisis financiero",
    SECCION_SPREAD: "Creación de valor · ROE − Ke",
    SECCION_METODOLOGIA: "Metodología de valuación",
    SECCION_VALOR: "Conclusión de valor",
    SECCION_DESCOMPOSICION: "Descomposición: libro y exceso",
    SECCION_CONTRASTE: "Contraste de mercado · transacciones bancarias del Caribe",
    SECCION_SUPUESTOS: "Supuestos y sensibilidad al costo de capital",
    SECCION_LIMITACIONES: "Limitaciones y condiciones",
    SECCION_FUENTES: "Fuentes y procedencia",
    SECCION_ANEXO_PANEL: "Anexo · Panel de transacciones: vías abiertas y descartes",
}

#: Por qué el eje no puede entregar todavía. Se declara en una constante y no en un `if`
#: suelto para que el motivo viaje a readiness, al registro y al informe con el mismo texto.
#:
#: CORREGIDO. Antes decía que el motor no existía, y eso dejó de ser cierto cuando se
#: construyeron el costo de capital y el Excess Return — pero el texto quedó, y readiness
#: siguió publicando «sin motor» durante todo ese tiempo. El costo de decir mal lo que falta
#: es concreto: «sin motor» se lee como código faltante y manda a escribir código, cuando lo
#: que falta es el DATO, y el dato está bloqueado por otra cosa.
FALTA_LA_CURVA = (
    "El motor de valuación EXISTE —costo de capital y Excess Return, con sus tests— y lo que "
    "falta es su insumo: la tasa libre de riesgo larga en pesos. Sale del cuadro V.1 del "
    "BCRD, «Valores subastados en moneda nacional», y ese archivo NO está habilitado para "
    "escritura, así que la serie no existe en ninguna base.\n\n"
    "No se habilita porque el archivo tiene dos defectos abiertos: de sus 15 columnas de "
    "datos el spec produce 12 series —tres de MONTO se pierden sin aviso— y 132 pares "
    "(serie, mes) traen dos registros, 99 en desacuerdo. La serie de la curva en sí sale "
    "limpia; lo que falla es el archivo alrededor.\n\n"
    "O sea que no falta código del eje: falta arreglar la extracción del cuadro V.1. Lo "
    "vigila `shared/data/bcrd_excel/tests/test_ninguna_serie_apunta_al_vacio.py`, que exige "
    "que ninguna serie nombrada en producción venga de un archivo apagado."
)
#: Nombre viejo, conservado porque el texto viaja a readiness y al registro por esta clave.
SIN_MOTOR = FALTA_LA_CURVA


def valuation_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name=DISPLAY, levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=(SECCION_SPREAD,), narrative_templates=(), prosa_computada=True,
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=(SECCION_RESUMEN, SECCION_PROPOSITO, SECCION_ANTECEDENTES,
                          SECCION_FINANCIERO, SECCION_SPREAD, SECCION_VALOR,
                          SECCION_DESCOMPOSICION, SECCION_CONTRASTE,
                          SECCION_LIMITACIONES),
                narrative_templates=(), prosa_computada=True,
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            # El Deep Dive agrega las dos que un comité de crédito o una contraparte piden
            # para poder DISCUTIR el número: cómo se construyó y de dónde salió cada insumo.
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=(SECCION_RESUMEN, SECCION_PROPOSITO, SECCION_ANTECEDENTES,
                          SECCION_FINANCIERO, SECCION_SPREAD, SECCION_METODOLOGIA,
                          SECCION_VALOR, SECCION_DESCOMPOSICION, SECCION_CONTRASTE,
                          SECCION_SUPUESTOS, SECCION_LIMITACIONES, SECCION_FUENTES,
                          SECCION_ANEXO_PANEL),
                narrative_templates=(), prosa_computada=True,
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


class ValuationProduct:

    ESTADO_BACKTEST = EstadoBacktest(
        tiene_motor=False, obstaculo="dato_pendiente",
        dato_que_falta=("la HISTORIA de ROE y patrimonio de las adquiridas, que es lo que "
                        "el motor necesita para valuarlas a la fecha de su operación. El "
                        "balance por entidad solo lo ingerimos de República Dominicana; los "
                        "conteos vigentes los computan `panel.transacciones.estado()` y "
                        "`contraste_del_modelo()` y no se transcriben acá"),
        desenlace="el precio efectivamente pagado en una transacción sobre la entidad",
        motivo=("Una valuación se valida contra lo que alguien PAGÓ, y eso son DOS cosas que "
                "no hay que confundir. La primera es tener múltiplos comparables: a cuánto "
                "sobre libro se paga un banco del Caribe. La segunda es contrastar ESTE "
                "modelo, que exige correr el Excess Return sobre cada adquirida a la fecha "
                "de su operación y comparar su valor con el precio — y para eso hace falta "
                "la historia de ROE y patrimonio de esa entidad, que solo tenemos donde "
                "ingerimos el balance por entidad.\n\n"
                "Un panel de comparables completo abre la vista de fusiones y adquisiciones "
                "y NO valida el modelo. Mientras las adquiridas del panel estén mayormente "
                "fuera de nuestra cobertura de balances, el eje publica el modelo, sus "
                "supuestos y su sensibilidad, y declara que sus valores no están "
                "contrastados contra precios pagados."))
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def product_manifest(self) -> SectorProductManifest:
        return valuation_manifest()

    # ── Readiness ──

    def data_signals(self) -> DataHealth:
        """Los insumos del BALANCE existen —patrimonio y utilidad reconciliados en T-VL-1—;
        lo que falta es la curva en pesos que alimenta `Ke`.

        La cobertura no se escribe a mano: se COMPUTA como la fracción de insumos presentes,
        y hoy son dos de tres. Un 0,0 escrito a mano decía «no hay nada» cuando el balance
        por entidad estaba completo, y eso manda a arreglar lo que no está roto."""
        insumos = {
            "patrimonio por entidad (SIB)": True,
            "utilidad por entidad (SIB)": True,
            "curva soberana en pesos (BCRD, cuadro V.1)": self.has_engine(),
        }
        presentes = sum(1 for ok in insumos.values() if ok)
        return DataHealth(
            coverage=presentes / len(insumos), freshness_days=self._dias_del_ultimo_corte(),
            cadence="quarterly",
            sources=("SIB · estados de situación y resultados por entidad",
                     "SIMBAD · Superset público de la Superintendencia",
                     "BCRD · cuadro V.1, valores subastados en moneda nacional",
                     "Panel de transacciones bancarias RD/Caribe · relevamiento propio sobre "
                     "anuncios, memorias auditadas y filings ante la SEC"),
            detail=FALTA_LA_CURVA if not insumos[
                "curva soberana en pesos (BCRD, cuadro V.1)"] else "")

    def _dias_del_ultimo_corte(self) -> Optional[int]:
        """Cuántos días tiene el último cierre con patrimonio publicado.

        Se COMPUTA del dato, y antes iba en `None` escrito a mano. No era neutral: la
        frescura sin fecha no vale como «al día» —«no sé de cuándo es» y «está fresco» son
        cosas distintas— y el gate la penalizaba a la mitad. El eje quedaba castigado por no
        declarar algo que sí podía medir.

        Es el cierre del BALANCE y no el de la curva: la cadencia del producto es trimestral
        porque la Superintendencia publica por trimestre, y la curva es mensual. Fresco es
        que el último trimestre esté; que la curva del mes pasado no se haya subastado no
        envejece la valuación.
        """
        from datetime import date as _date

        from sqlalchemy import text as _sql
        if self._db is None:
            return None
        try:
            fila = self._db.execute(_sql(
                "SELECT MAX(period_end) FROM banking_data "
                "WHERE patrimonio_tecnico IS NOT NULL")).first()
        except Exception as e:  # noqa: BLE001 — medir la frescura no puede costar el readiness
            logger.warning("no se pudo medir la frescura de valuación: %s", e)
            return None
        if fila is None or fila[0] is None:
            return None
        corte = fila[0]
        if isinstance(corte, str):
            try:
                corte = _date.fromisoformat(corte[:10])
            except ValueError:
                return None
        return (_date.today() - corte).days

    def has_engine(self) -> bool:
        """Ahora SÍ hay motor. Lo que decide es si hay con qué correrlo: la curva en pesos
        para `Ke` y al menos una entidad con patrimonio publicado."""
        if self._db is None:
            return False
        try:
            with self._db.begin_nested():
                from modules.macro_monitor.forecasting.panel import observaciones
                from modules.valuation.engine.cost_of_capital import SERIE_RF
                return bool([v for _p, v in observaciones(self._db, SERIE_RF) if v])
        except Exception as e:  # noqa: BLE001
            logger.warning("no se pudo verificar el motor de valuación: %s", e)
            return False

    def validation_state(self) -> ValidationState:
        """No aprobada, y el motivo NO es el mismo que el de los datos.

        Son dos cosas distintas y decirlas con el mismo texto las confundía: el dato que
        falta es la curva en pesos; la validación falta porque el panel de transacciones
        —que llegó a ocho comparables— abre la vista de M&A y **no** contrasta el modelo.
        Ese motivo lo computa el propio panel.
        """
        from modules.valuation.panel.transacciones import contraste_del_modelo
        return ValidationState(approved=False, score=0.0,
                               notes=contraste_del_modelo().motivo)

    #: Cierres con patrimonio que hacen falta para valuar. El ROE va sobre patrimonio de
    #: APERTURA, así que el primer cierre no tiene con qué computarlo: hacen falta DOS.
    CIERRES_MINIMOS = 2

    def available_periods(self) -> List[str]:
        """Los cortes que el eje puede valuar. Antes devolvía `[]` escrito a mano.

        No era inocuo: con readiness en 0,85 el eje quedaba «publicable» y el selector no
        ofrecía ningún período, así que el producto se listaba y no se podía pedir. Un
        producto listado que no se puede mostrar es una vidriera rota — y el gate de
        readiness no lo ve, porque mide insumos y no la entrega.

        Se ofrecen solo los cortes en los que ALGUNA entidad tiene ya dos cierres: pedir uno
        anterior devolvería el mismo error para todas, y ofrecer una opción que falla al
        elegirla es peor que no ofrecerla.
        """
        from sqlalchemy import text as _sql
        if self._db is None:
            return []
        try:
            filas = self._db.execute(_sql(
                "SELECT period_end FROM banking_data WHERE patrimonio_tecnico IS NOT NULL "
                "GROUP BY period_end ORDER BY period_end DESC")).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("no se pudieron listar los períodos de valuación: %s", e)
            return []
        cortes = [str(f[0])[:10] for f in filas]
        # El más viejo no se ofrece: contra él ninguna entidad tiene apertura.
        return cortes[:-1] if len(cortes) > 1 else []

    #: Los tipos que este eje puede valuar: entidades de INTERMEDIACIÓN. El modelo de Excess
    #: Return descuenta el exceso de ROE sobre el costo de capital de un negocio que toma
    #: depósitos y presta, y el panel de múltiplos contra el que se contrastaría son bancos.
    #:
    #: Quedan FUERA las cambiarias —agentes de cambio y casas de remesas—, y no por falta de
    #: dato: tienen patrimonio y utilidad, así que la aritmética corre y devuelve un número
    #: de aspecto normal. Lo que no tienen es el negocio que el modelo supone. Ofrecerlas
    #: sería ordenar lo que no es comparable, con el agravante de que el resultado no se ve
    #: mal. Eran 41 de las 92 que el selector ofrecía.
    #:
    #: Las asociaciones de ahorros y préstamos SÍ entran: son entidades de intermediación
    #: supervisadas. Que sean mutuales —sin acciones que comprar— es un caveat del informe,
    #: no un motivo para no poder valuarlas.
    TIPOS_VALUABLES = ("banca_multiple", "aap", "banco_ahorro_credito", "corporacion_credito")

    def scope_options(self) -> List[Dict[str, str]]:
        """Entidades que el eje puede valuar HOY, para el selector de los niveles nombrados.

        Dos condiciones, y las dos existen para no ofrecer algo que no se puede entregar:
        al menos dos cierres con patrimonio —el ROE va sobre apertura— y un tipo de entidad
        que el modelo sepa valuar. Una opción que falla al elegirla es peor que no ofrecerla;
        una que NO falla y devuelve un número sin sentido es peor todavía.
        """
        from sqlalchemy import text as _sql
        if self._db is None:
            return []
        marcadores = ", ".join(f":t{i}" for i in range(len(self.TIPOS_VALUABLES)))
        params: Dict[str, object] = {"n": self.CIERRES_MINIMOS}
        params.update({f"t{i}": t for i, t in enumerate(self.TIPOS_VALUABLES)})
        try:
            filas = self._db.execute(_sql(
                "SELECT b.id, b.name, b.bank_type, COUNT(d.period_end) AS n "
                "FROM banks b JOIN banking_data d ON d.bank_id = b.id "
                "WHERE d.patrimonio_tecnico IS NOT NULL "
                f"AND b.bank_type IN ({marcadores}) "
                "GROUP BY b.id, b.name, b.bank_type HAVING COUNT(d.period_end) >= :n "
                "ORDER BY b.name"), params).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("no se pudieron listar las entidades de valuación: %s", e)
            return []
        return [{"value": str(f[0]), "label": str(f[1]), "group": str(f[2] or "")}
                for f in filas]

    def scope_kind(self) -> str:
        return "entity"

    # ── Producción ──

    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        """La valuación de una entidad. `scope` la nombra en los niveles nombrados."""
        from sqlalchemy import text as _sql

        from modules.valuation.service import a_payload, valuar_entidad

        db = self._db
        if db is None:
            raise ValueError(SIN_MOTOR)
        if tier != ProductTier.pulse and not scope:
            raise ValueError(
                "Este nivel valúa una entidad concreta: falta indicar cuál.")
        fila = db.execute(_sql(
            "SELECT id, name FROM banks WHERE id = :s OR name = :s LIMIT 1"),
            {"s": scope}).first() if scope else None
        if fila is None:
            raise ValueError(f"No se encontró la entidad «{scope}».")
        lec = valuar_entidad(db, bank_id=str(fila[0]), nombre=str(fila[1]))
        if lec is None:
            # Se DECLARA por qué, en vez de devolver ceros: un motor sin su entrada no
            # falla, desaparece.
            raise ValueError(
                f"No hay con qué valuar «{fila[1]}»: hacen falta al menos dos cierres con "
                "patrimonio publicado para computar un ROE sobre patrimonio de apertura.")
        return ProductSnapshot(tier=tier, period=lec.periodo, payload=a_payload(lec),
                               entity_name=str(fila[1]))

    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        """Prosa COMPUTADA. No pasa por el motor de IA — ver el docstring del módulo."""
        lec = _lectura_desde_payload(snapshot)
        secciones = self.product_manifest().require_level(tier).sections
        posicion, cuota = self._posicion_en_su_tipo(lec)
        # CORREGIDO. Dos de estas secciones se servían con la prosa de la MUESTRA, así que un
        # informe real de una entidad real terminaba diciendo «cifras ilustrativas de una
        # entidad ficticia» y publicando una fórmula de `Ke` con prima de riesgo país, que
        # este modelo no tiene. Ahora todas salen del dato, y del MISMO constructor que la
        # muestra: `_secciones_computadas`. Eran dos diccionarios copiados a mano.
        todas = _secciones_computadas(lec, posicion=posicion, cuota_pct=cuota,
                                      con_anexo=SECCION_ANEXO_PANEL in secciones)
        return {sec: todas[sec] for sec in secciones if sec in todas}

    def _posicion_en_su_tipo(self, lec: Any) -> Tuple[Optional[Tuple[int, int]],
                                                      Optional[float]]:
        """Puesto por patrimonio DENTRO de su clase, y cuota del patrimonio del grupo.

        Se computa sobre el padrón completo de la clase al mismo corte. Una posición de
        mercado afirmada sin computarla es una opinión, y comparar contra un subconjunto
        elegido hace ver a cualquier entidad como se la quiera hacer ver.
        """
        from sqlalchemy import text as _sql
        if self._db is None or not lec.tipo_de_entidad:
            return None, None
        try:
            filas = self._db.execute(_sql(
                "SELECT b.name, d.patrimonio_tecnico FROM banks b "
                "JOIN banking_data d ON d.bank_id = b.id "
                "WHERE b.bank_type = :t AND d.period_end = :p "
                "AND d.patrimonio_tecnico IS NOT NULL "
                "ORDER BY d.patrimonio_tecnico DESC"),
                {"t": lec.tipo_de_entidad, "p": lec.periodo}).fetchall()
        except Exception as e:  # noqa: BLE001 — la posición no puede costar el informe
            logger.warning("no se pudo computar la posición de %s: %s", lec.entidad, e)
            return None, None
        if len(filas) < 2:
            return None, None
        nombres = [str(f[0]) for f in filas]
        if lec.entidad not in nombres:
            return None, None
        total_grupo = sum(float(f[1]) for f in filas)
        cuota = (100.0 * lec.patrimonio_libro / total_grupo) if total_grupo else None
        return (nombres.index(lec.entidad) + 1, len(nombres)), cuota

    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None,
                     fmt: str = "pdf") -> str:
        """Renderiza lo que se le pase. NO exige motor, a propósito.

        El motor hace falta para PRODUCIR un snapshot, no para maquetar uno ya producido — y
        la muestra curada es un payload constante. Hacer fallar el render dejaría al eje sin
        vidriera por una razón que no le corresponde a esta capa.
        """
        level = self.product_manifest().require_level(tier)
        titulo = {"pulse": "Pulse · Valuación", "insight": "Insight · Valuación",
                  "deep_dive": "Deep Dive · Valuación"}.get(tier.value, DISPLAY)
        p = snapshot.payload
        # CORREGIDO. Estas claves se leían PLANAS —`p["spread_pp"]`, `p["valor_rango"]`— y el
        # payload las trae ANIDADAS bajo `spread` y `valor`. O sea que ni el titular ni la
        # tabla se renderizaban nunca, en ningún informe, y nada fallaba: el `.get` devolvía
        # `None` y el bloque se saltaba. `_lectura_desde_payload`, tres funciones más abajo,
        # sí las leía anidadas — dos lecturas del mismo dato que se desincronizaron.
        sp = p.get("spread") or {}
        va = p.get("valor") or {}
        tablas: List = []
        titular = None
        if sp.get("spread_pp"):
            alto, bajo = sp["spread_pp"][0], sp["spread_pp"][-1]
            titular = f"ROE − Ke: {alto:+.1f} pp a {bajo:+.1f} pp"
        if va.get("rango") and va.get("pb_implicito"):
            libro = va.get("patrimonio_libro") or 0
            tablas.append(("Conclusión de valor", [
                ["", "Extremo favorable", "Extremo adverso"],
                ["Valor estimado", f"RD$ {va['rango'][1]:,.0f}", f"RD$ {va['rango'][0]:,.0f}"],
                ["P/B implícito (derivado)", f"{va['pb_implicito'][1]:.2f}x",
                 f"{va['pb_implicito'][0]:.2f}x"],
                ["Patrimonio libro", f"RD$ {libro:,.0f}", ""],
            ]))
        if sp.get("ke_rango_pct"):
            ke = sp["ke_rango_pct"]
            tablas.append(("Costo de capital y retorno", [
                ["", "Bajo", "Alto"],
                ["Ke (RD$)", f"{ke[0]:.2f} %", f"{ke[1]:.2f} %"],
                ["ROE proyectado", f"{sp.get('roe_proyectado_pct', 0):.2f} %", ""],
                ["Spread ROE − Ke", f"{sp['spread_pp'][0]:+.2f} pp",
                 f"{sp['spread_pp'][-1]:+.2f} pp"],
            ]))
        # La ENTIDAD va en la portada. Un informe de valuación cuya tapa no nombra al sujeto
        # valuado no se puede archivar ni citar: decía solo «SDQ Valuación de Entidades».
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=DISPLAY, title=titulo, period=snapshot.period,
            narratives=narratives, section_titles=_SECTION_TITLES, tables=tablas, charts=[],
            headline=titular, subtitle=(snapshot.entity_name or p.get("entidad") or None),
            watermark=level.watermark, sample=sample, output_dir=output_dir, fmt=fmt)

    # ── Muestra CURADA ──
    #
    # El framework exige que todo producto del catálogo se pueda mostrar: un producto listado
    # que no se puede enseñar es una vidriera rota. Con dos cuidados que acá pesan más que en
    # otros ejes:
    #
    # 1. La entidad es EXPLÍCITAMENTE FICTICIA. Mostrar una valuación de un banco real que
    #    todavía no podemos computar sería fabricar una cifra financiera sobre una empresa
    #    que existe — el daño no se arregla con una marca de agua.
    # 2. Las cifras enseñan el MÉTODO, no un resultado: el spread abre la lectura, el valor
    #    va como rango, y el ejemplo elegido es uno donde el valor CAMBIA DE SIGNO dentro del
    #    rango de Ke, porque ése es el hallazgo que el eje existe para dar y una muestra que
    #    solo enseña casos limpios vende un producto que no existe.

    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        return ProductSnapshot(tier=tier, period="2025-12-31", payload=_SAMPLE_PAYLOAD,
                               entity_name=(None if tier == ProductTier.pulse
                                            else _ENTIDAD_FICTICIA))

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        return _sample_narrativas_de(self.product_manifest().require_level(tier).sections)

    # ── Procedencia ──

    def variable_signals(self) -> Dict[str, Any]:
        """Vacío mientras no haya motor. Devolver señales inventadas para que el eje
        "aparezca" en el registro sería exactamente lo que el registro existe para impedir."""
        return {"period": None, "signals": []}


def _secciones_computadas(lec: Any, *, posicion: Optional[Tuple[int, int]] = None,
                          cuota_pct: Optional[float] = None,
                          con_anexo: bool = False) -> Dict[str, str]:
    """TODA la prosa del eje, de una `Lectura`. Es la única fuente: la usan el informe
    real y la muestra curada.

    Eran dos diccionarios copiados a mano —uno en `narratives()` y otro en la muestra— y
    dos copias del mismo mapa se desincronizan: esta misma semana una muestra escrita
    aparte tapó un defecto de unidades en otro eje. Con un solo constructor, la muestra
    no puede decir algo que el producto no dice, ni callar una sección que el producto
    sí trae.
    """
    from modules.valuation import narrativa

    metodologia = narrativa.metodologia(lec)
    return {
        SECCION_RESUMEN: narrativa.resumen_ejecutivo(lec),
        SECCION_PROPOSITO: narrativa.proposito_y_alcance(lec),
        SECCION_ANTECEDENTES: narrativa.antecedentes(lec, posicion=posicion,
                                                     cuota_pct=cuota_pct),
        SECCION_FINANCIERO: narrativa.analisis_financiero(lec),
        SECCION_SPREAD: narrativa.resumen_del_spread(lec),
        SECCION_METODOLOGIA: metodologia,
        SECCION_VALOR: narrativa.resumen_del_valor(lec),
        SECCION_DESCOMPOSICION: narrativa.resumen_de_descomposicion(lec),
        # `con_anexo` lo decide el llamador leyendo el manifiesto del nivel: el insight no
        # trae el anexo y su puntero apunta al Deep Dive.
        SECCION_CONTRASTE: narrativa.contraste_de_mercado(lec, con_anexo=con_anexo),
        # CORREGIDO. §Supuestos servía el MISMO texto que §Metodología: un informe de trece
        # secciones con dos idénticas. Ahora trae los parámetros que produjeron ESTA cifra.
        SECCION_SUPUESTOS: narrativa.supuestos_y_sensibilidad(lec),
        SECCION_LIMITACIONES: narrativa.limitaciones(lec),
        SECCION_FUENTES: narrativa.fuentes_y_procedencia(lec),
        SECCION_ANEXO_PANEL: narrativa.anexo_del_panel(),
    }


def _lectura_desde_payload(snapshot: ProductSnapshot):
    """Reconstruye la `Lectura` desde el payload, para que la prosa no recompute nada.

    Recomputar acá sería una SEGUNDA valuación al lado de la que el snapshot ya trae, y dos
    cálculos del mismo hecho se desincronizan: la prosa terminaría citando cifras que la
    tabla no muestra.
    """
    from modules.valuation.service import Lectura

    p = snapshot.payload
    sp, va, pr = p.get("spread", {}), p.get("valor", {}), p.get("procedencia", {})
    return Lectura(
        entidad=str(p.get("entidad") or snapshot.entity_name or ""),
        periodo=str(p.get("periodo") or snapshot.period),
        moneda=str(p.get("moneda") or "DOP"),
        roe_proyectado_pct=float(sp.get("roe_proyectado_pct") or 0.0),
        ke_bajo_pct=float((sp.get("ke_rango_pct") or [0, 0])[0]),
        ke_alto_pct=float((sp.get("ke_rango_pct") or [0, 0])[1]),
        spread_alto_pp=float((sp.get("spread_pp") or [0, 0])[0]),
        spread_bajo_pp=float((sp.get("spread_pp") or [0, 0])[1]),
        cambia_de_signo=bool(sp.get("cambia_de_signo")),
        patrimonio_libro=float(va.get("patrimonio_libro") or 0.0),
        valor_bajo=float((va.get("rango") or [0, 0])[0]),
        valor_alto=float((va.get("rango") or [0, 0])[1]),
        pb_bajo=float((va.get("pb_implicito") or [0, 0])[0]),
        pb_alto=float((va.get("pb_implicito") or [0, 0])[1]),
        fraccion_de_rubrica=float(pr.get("fraccion_de_rubrica") or 0.0),
        advertencias=tuple(p.get("advertencias") or ()),
        serie_spread=tuple((str(x.get("periodo")), float(x.get("roe_pct") or 0.0))
                           for x in (p.get("serie_spread") or [])),
        tipo_de_entidad=str(p.get("tipo_de_entidad") or ""),
        retencion=float(pr.get("retencion_supuesta") or 0.0),
        g_terminal_pct=float(pr.get("g_terminal_pct") or 0.0),
        evidencia_del_tipo=str(pr.get("evidencia_del_tipo") or ""),
        persistencia=float(pr.get("persistencia") or 0.0),
        rf_pct=_par(pr.get("rf_pct")), beta=_par(pr.get("beta")), erp=_par(pr.get("erp")),
        n_observaciones_rf=int(pr.get("n_observaciones_rf") or 0),
    )


def _par(v: Any) -> Tuple[float, float]:
    """Un rango `[bajo, alto]` del payload, o `(0, 0)` si no viajó — nunca un número
    inventado con forma de rango."""
    try:
        return (float(v[0]), float(v[1]))
    except (TypeError, IndexError, ValueError):
        return (0.0, 0.0)


#: Ficticia y que lo diga en el nombre. No es un banco real con los datos cambiados: es un
#: ejemplo, y la diferencia importa porque una valuación atribuida a una entidad que existe
#: es una afirmación sobre esa entidad.
def _evidencia_de_muestra() -> str:
    """La evidencia del tipo de la entidad ilustrativa, de la MISMA tabla que la real."""
    from modules.valuation.engine import por_tipo
    return por_tipo.evidencia_de("banca_multiple")


_ENTIDAD_FICTICIA = "Banco Múltiple Ejemplo (entidad ilustrativa)"

# CORREGIDO — la muestra usaba claves PLANAS y el payload real las trae ANIDADAS. Eran dos
# formas del mismo dato, y de ahí salía el defecto del render: leía las planas, así que con
# la muestra el titular y las tablas aparecían y en un informe REAL no aparecían nunca. La
# muestra ahora tiene exactamente la forma que produce `a_payload`.
_SAMPLE_PAYLOAD: Dict[str, Any] = {
    "entidad": _ENTIDAD_FICTICIA,
    "periodo": "2025-12-31",
    "moneda": "DOP",
    "es_ilustrativo": True,
    "tipo_de_entidad": "banca_multiple",
    # CORREGIDO. La muestra publicaba un Ke de 12,4–14,9 %: 2,5 pp de ancho, que el motor
    # NO puede producir —solo β × ERP abre 3,375 pp—. Una vidriera que enseñaba un número
    # que el método no da. Ahora los extremos salen del motor sobre estos mismos insumos
    # (Rf 7,70–7,90 %, β 0,85–1,15, ERP 5,5–7,0 %; `test_la_base_del_valor_se_declara`
    # cruza la identidad) y el valor es el de `excess_return.valuar` con ellos.
    "spread": {
        "roe_proyectado_pct": 13.2,
        "ke_rango_pct": [12.375, 15.95],
        "spread_pp": [0.825, -2.75],
        "cambia_de_signo": True,
        "destruye_valor": False,
    },
    "valor": {
        "patrimonio_libro": 18_400_000_000.0,
        "rango": [15_160_349_086.0, 19_567_266_652.0],
        "pb_implicito": [0.8239, 1.0634],
    },
    "procedencia": {
        "fraccion_de_rubrica": 0.45,
        "retencion_supuesta": 0.75,
        "persistencia": 0.902,
        "g_terminal_pct": 9.03,
        "evidencia_del_tipo": _evidencia_de_muestra(),
        "horizonte_anios": 5,
        "rf_pct": [7.70, 7.90],
        "beta": [0.85, 1.15],
        "erp": [5.5, 7.0],
        "n_observaciones_rf": 8,
    },
    # Horizonte explícito de cinco años, el mismo que usa el servicio.
    "serie_spread": [{"periodo": f"{a}-12-31", "roe_pct": r} for a, r in
                     ((2021, 12.1), (2022, 13.8), (2023, 12.9), (2024, 13.5), (2025, 13.2))],
    "advertencias": [],
}

#: El AVISO que convierte una muestra en una muestra. Va en la primera sección de cada nivel
#: y no en una al final: quien lee dos párrafos tiene que haberlo visto.
_AVISO_ILUSTRATIVO = (
    "\n\n_Cifras ilustrativas de una entidad ficticia. El informe real las computa del "
    "estado publicado por la Superintendencia para la entidad que se valúa._")


def _sample_narrativas_de(secciones) -> Dict[str, str]:
    """La prosa de la muestra sale de las MISMAS funciones que la real.

    Antes era un diccionario escrito a mano y por eso se desincronizó: la muestra publicaba
    una fórmula de `Ke` con prima de riesgo país que el modelo no usa, y ese texto además
    terminó sirviéndose en informes reales. Con una sola fuente de prosa, la muestra no puede
    decir algo que el producto no dice.
    """
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2025-12-31",
                           payload=_SAMPLE_PAYLOAD, entity_name=_ENTIDAD_FICTICIA)
    todas = _secciones_computadas(_lectura_desde_payload(snap),
                                  con_anexo=SECCION_ANEXO_PANEL in secciones)
    salida = {s: todas[s] for s in secciones if s in todas}
    primera = next((s for s in secciones if s in salida), None)
    if primera:
        salida[primera] = salida[primera] + _AVISO_ILUSTRATIVO
    return salida


register_product(SECTOR_KEY, lambda db: ValuationProduct(db))
