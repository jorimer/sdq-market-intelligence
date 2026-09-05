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
from shared.products.contract import EstadoBacktest
from shared.products.render import render_product_pdf

logger = logging.getLogger("sdq.products.valuation")

SECTOR_KEY = "valuation"
DISPLAY = "SDQ Valuación de Entidades"

SECCION_SPREAD = "spread_roe_ke"
SECCION_VALOR = "valor_y_rango"
SECCION_DESCOMPOSICION = "libro_vs_exceso"
SECCION_SUPUESTOS = "supuestos_y_sensibilidad"
SECCION_LIMITACIONES = "limitations"

_SECTION_TITLES = {
    # El resumen abre por el SPREAD y no por el valor: quien ve el spread entiende la
    # palanca; quien ve solo el valor discute el supuesto.
    SECCION_SPREAD: "Creación de valor · ROE − Ke",
    SECCION_VALOR: "Valor estimado y su rango",
    SECCION_DESCOMPOSICION: "Descomposición: libro y exceso",
    SECCION_SUPUESTOS: "Supuestos y sensibilidad al costo de capital",
    SECCION_LIMITACIONES: "Limitaciones",
}

#: Por qué el eje no puede entregar todavía. Se declara en una constante y no en un `if`
#: suelto para que el motivo viaje a readiness, al registro y al informe con el mismo texto.
SIN_MOTOR = (
    "El motor de valuación todavía no existe: faltan el costo de capital y el modelo de "
    "Excess Return. El eje está dado de alta para que su procedencia, su doctrina y su "
    "contrato queden fijados antes de que haya cifras — no para entregar."
)


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
                sections=(SECCION_SPREAD, SECCION_VALOR, SECCION_DESCOMPOSICION),
                narrative_templates=(), prosa_computada=True,
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=(SECCION_SPREAD, SECCION_VALOR, SECCION_DESCOMPOSICION,
                          SECCION_SUPUESTOS, SECCION_LIMITACIONES),
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
        """Los insumos EXISTEN —patrimonio y utilidad reconciliados en T-VL-1—; lo que falta
        es el motor. Se reporta la cobertura del insumo, no la del producto: mezclarlas
        haría parecer que falta dato cuando lo que falta es código."""
        return DataHealth(
            coverage=0.0, freshness_days=None, cadence="quarterly",
            sources=("SIB · estados de situación y resultados por entidad",
                     "SIMBAD · Superset público de la Superintendencia",
                     "BCRD · insumos del costo de capital"),
            detail=SIN_MOTOR)

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
        return ValidationState(approved=False, score=0.0, notes=SIN_MOTOR)

    def available_periods(self) -> List[str]:
        return []

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
        from modules.valuation import narrativa
        from modules.valuation.service import Lectura

        lec = _lectura_desde_payload(snapshot)
        secciones = self.product_manifest().require_level(tier).sections
        fijas = {
            SECCION_SPREAD: narrativa.resumen_del_spread(lec),
            SECCION_VALOR: narrativa.resumen_del_valor(lec),
            SECCION_DESCOMPOSICION: narrativa.resumen_de_descomposicion(lec),
            SECCION_SUPUESTOS: _SAMPLE_NARRATIVAS[SECCION_SUPUESTOS],
            SECCION_LIMITACIONES: _SAMPLE_NARRATIVAS[SECCION_LIMITACIONES],
        }
        return {sec: fijas[sec] for sec in secciones if sec in fijas}

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
        tablas: List = []
        titular = None
        if p.get("spread_pp"):
            alto, bajo = p["spread_pp"][0], p["spread_pp"][-1]
            titular = f"ROE − Ke: {alto:+.1f} pp a {bajo:+.1f} pp"
        if p.get("valor_rango") and p.get("pb_implicito"):
            tablas.append(("Valor y múltiplo implícito", [
                ["Valor estimado", f"RD$ {p['valor_rango'][1]:,.0f}",
                 f"RD$ {p['valor_rango'][0]:,.0f}"],
                ["P/B implícito (derivado)", f"{p['pb_implicito'][1]:.2f}x",
                 f"{p['pb_implicito'][0]:.2f}x"],
                ["Patrimonio libro", f"RD$ {p.get('patrimonio_libro', 0):,.0f}", ""],
            ]))
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=DISPLAY, title=titulo, period=snapshot.period,
            narratives=narratives, section_titles=_SECTION_TITLES, tables=tablas, charts=[],
            headline=titular, subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)

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
        secciones = self.product_manifest().require_level(tier).sections
        return {sec: _SAMPLE_NARRATIVAS[sec] for sec in secciones}

    # ── Procedencia ──

    def variable_signals(self) -> Dict[str, Any]:
        """Vacío mientras no haya motor. Devolver señales inventadas para que el eje
        "aparezca" en el registro sería exactamente lo que el registro existe para impedir."""
        return {"period": None, "signals": []}


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
    )


#: Ficticia y que lo diga en el nombre. No es un banco real con los datos cambiados: es un
#: ejemplo, y la diferencia importa porque una valuación atribuida a una entidad que existe
#: es una afirmación sobre esa entidad.
_ENTIDAD_FICTICIA = "Banco Múltiple Ejemplo (entidad ilustrativa)"

_SAMPLE_PAYLOAD: Dict[str, Any] = {
    "entidad": _ENTIDAD_FICTICIA,
    "es_ilustrativo": True,
    "patrimonio_libro": 18_400_000_000.0,
    "roe_proyectado_pct": 13.2,
    "ke_rango_pct": [12.4, 14.9],
    "spread_pp": [0.8, -1.7],
    "valor_rango": [19_900_000_000.0, 16_800_000_000.0],
    "pb_implicito": [1.08, 0.91],
    "cambia_de_signo": True,
}

_SAMPLE_NARRATIVAS: Dict[str, str] = {
    SECCION_SPREAD: (
        "La entidad rinde un **ROE proyectado de 13,2 %** contra un costo de capital estimado "
        "entre **12,4 % y 14,9 %**. El spread va de **+0,8 pp a −1,7 pp**: en el extremo "
        "favorable del rango crea valor, y en el desfavorable lo destruye.\n\n"
        "Esa ambigüedad **es el hallazgo**, no una debilidad del análisis. Una entidad cuyo "
        "ROE cae dentro del rango de su propio costo de capital no tiene una respuesta única "
        "sobre si vale más o menos que su libro — y quien decida sobre ella necesita saber "
        "exactamente eso.\n\n"
        "_Cifras ilustrativas de una entidad ficticia; el informe las computa del estado "
        "publicado de la entidad real._"
    ),
    SECCION_VALOR: (
        "Valor estimado entre **RD$ 16.800 y 19.900 millones**, contra un patrimonio libro de "
        "**RD$ 18.400 millones**. El múltiplo P/B implícito va de **0,91× a 1,08×** — y es "
        "**derivado**, no asumido: sale del valor, no lo produce.\n\n"
        "El rango **cruza el libro**. No se publica un punto medio: promediar los dos extremos "
        "daría una cifra que ningún supuesto sostiene.\n\n"
        "_Cifras ilustrativas de una entidad ficticia._"
    ),
    SECCION_DESCOMPOSICION: (
        "Del valor, **RD$ 18.400 millones son libro** y el resto es el valor presente del "
        "exceso —lo que la entidad gana por encima de lo que su capital exige—. En el extremo "
        "desfavorable del rango ese exceso es **negativo**: la entidad valdría menos que su "
        "patrimonio contable.\n\n"
        "_Cifras ilustrativas de una entidad ficticia._"
    ),
    SECCION_SUPUESTOS: (
        "El costo de capital se estima como `Ke = Rf + β × ERP + CRP`. **La beta no se "
        "desapalanca**: Hamada supone que la deuda es financiamiento y que existe un "
        "apalancamiento óptimo separable de la operación, y en un banco los depósitos son "
        "**materia prima** — esa premisa es falsa.\n\n"
        "**β y ERP viajan como rúbrica**, no como dato real: son supuestos de comparables "
        "latinoamericanos, no observaciones dominicanas. La sensibilidad se publica en pasos "
        "de 50 puntos básicos porque es la escala a la que el resultado se mueve.\n\n"
        "_Cifras ilustrativas de una entidad ficticia._"
    ),
    SECCION_LIMITACIONES: (
        "Esta valuación **no está contrastada contra precios pagados**. El panel de "
        "transacciones sí permite decir a cuánto sobre valor libro se ha pagado un banco del "
        "Caribe, que es una referencia de mercado; contrastar este modelo es otra cosa y "
        "exige valuar cada adquirida a la fecha de su operación, para lo que hace falta su "
        "historia de balance. Mientras eso no exista, el eje no afirma que sus valores "
        "predicen precios.\n\n"
        "Un score de solidez **no es un proxy de precio**: una entidad sólida puede estar "
        "destruyendo valor, y este informe responde cuánto vale, no qué tan sana está.\n\n"
        "Nada de lo anterior es una recomendación de comprar o vender."
    ),
}


register_product(SECTOR_KEY, lambda db: ValuationProduct(db))
