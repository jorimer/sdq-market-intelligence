"""Ingesta de comercio bilateral ABIERTO POR CAPÍTULO (Comtrade).

**Por qué existe.** El motor de Research declaró fuera de alcance la pregunta "¿qué le
importamos a China, desglosado por bien?". No lo estaba: el cliente de Comtrade pedía
producto × mundo y socio × total, nunca las dos juntas, y la misma API responde el cruce en
una llamada. Era un límite de la CONSULTA, no del sistema — y el informe además INFIRIÓ la
composición ("bienes de consumo masivo, insumos industriales…") pudiendo medirla.

El Excel de la DGA no puede suplirlo: publica capítulo × valor SIN país de origen.
"""
import logging
from typing import Any, Dict, List, Optional, cast

from sqlalchemy.orm import Session

from modules.trade_intel.models.models import TradeDirection, TradePartnerChapter

logger = logging.getLogger("sdq.trade_intel.partner_chapters")

RD_M49 = "214"
FUENTE = "UN Comtrade"
LICENCIA = "https://comtrade.un.org/db/help/licenseagreement.aspx"

# La lista de socios se DERIVA del dato (`socios_con_flujo`), no se fija a mano. La versión
# anterior traía cinco elegidos por juicio y cubría el 70,2% del valor importado: dejaba fuera
# a Italia, Colombia, Alemania y 187 países más — justo la parte que responde "¿y quién más me
# lo puede vender?" en una pregunta sobre restringir importaciones por origen.
#
# Coste real medido: 192 socios × 3 años ≈ 10 min para un sync ANUAL. El argumento de que
# "traer los ~200 no aporta" no se sostenía.
SOCIOS_FALLBACK = {"156": "China", "842": "USA"}


def _upsert(db: Session, *, period: str, partner: str, partner_code: str,
            direction: TradeDirection, chapter: str, value: Optional[float]) -> bool:
    # Por CÓDIGO: el nombre es etiqueta y cambia con la fuente que lo resuelva.
    row = (db.query(TradePartnerChapter)
           .filter_by(period=period, partner_code=partner_code, direction=direction,
                      chapter=chapter)
           .first())
    creada = row is None
    if row is None:
        row = TradePartnerChapter(period=period, partner_code=partner_code,
                                  direction=direction, chapter=chapter)
        db.add(row)
    # cast: SQLAlchemy tipa las columnas como Column[...]; el driver convierte el valor.
    row.partner = cast(Any, partner)      # etiqueta: se refresca con la fuente actual
    row.value = cast(Any, value)
    row.source = cast(Any, FUENTE)
    row.license = cast(Any, LICENCIA)
    return creada


def _años_presentes(db: Session, partner_code: str) -> set:
    """Años que ese socio YA tiene ingeridos, por CÓDIGO.

    Por código y no por nombre: consultarlo por la etiqueta hacía que un cambio de rótulo
    —"Estados Unidos" → "USA"— pareciera un socio nuevo y disparara una re-ingesta completa.
    """
    return {r[0] for r in (db.query(TradePartnerChapter.period)
                           .filter(TradePartnerChapter.partner_code == partner_code)
                           .distinct().all())}


def _renombrar(db: Session, partner_code: str, nombre: str) -> int:
    """Alinea la etiqueta de un socio con la de la fuente. Devuelve filas tocadas."""
    n = (db.query(TradePartnerChapter)
         .filter(TradePartnerChapter.partner_code == partner_code,
                 TradePartnerChapter.partner != nombre)
         .update({"partner": nombre}, synchronize_session=False))
    if n:
        db.commit()
    return int(n or 0)


def sync_partner_chapters(db: Session, years: List[int],
                          socios: Optional[Dict[str, str]] = None,
                          set_phase=None, forzar: bool = False) -> Dict[str, Any]:
    """Ingiere ``{socio × capítulo}`` para *years*. Idempotente por (período, socio, capítulo).

    **REANUDABLE.** Recorrer los 192 socios toma ~40 minutos y la corrida del 2026-08-13 murió
    en el socio 118 por un reinicio del contenedor. Sin reanudación, terminar la cola obliga a
    rehacerlo entero —otros 40 minutos con el mismo riesgo—, así que un socio que ya tiene
    TODOS los años pedidos se salta.

    El salto es por socio × AÑO, no por socio: uno que entró con 2025 pero no con 2024 se
    vuelve a pedir. Dar por hecho el socio completo habría dejado huecos invisibles.

    ``forzar=True`` re-pide todo — necesario cuando la fuente REVISA años ya publicados, que
    es lo normal en estadística de comercio.

    Un socio que la fuente no devuelve NO se rellena ni se borra: se cuenta como vacío y se
    reporta. Un fallo de red en un socio no aborta los demás.
    """
    from shared.data.comtrade_client import fetch_partner_chapters, socios_con_flujo

    set_phase = set_phase or (lambda _m: None)
    total_pais = None
    if socios is None:
        # Derivados del dato y ORDENADOS POR VALOR: si la ingesta se corta a la mitad, lo que
        # queda adentro es lo que más pesa, y la cobertura reportada lo dice.
        set_phase("Resolviendo la lista de socios")
        try:
            lista = socios_con_flujo(RD_M49, max(years))
            socios = {c: n for c, n, _ in lista}
            total_pais = sum(v for _, _, v in lista)
            valor_socio = {n: v for _, n, v in lista}
        except Exception as e:  # noqa: BLE001 — sin lista, no se inventa: se usa el mínimo
            logger.warning("No se pudo derivar la lista de socios: %s", e)
            socios, valor_socio = SOCIOS_FALLBACK, {}
    else:
        valor_socio = {}

    creadas = actualizadas = 0
    vacios: List[str] = []
    fallidos: List[str] = []
    ingeridos: List[str] = []
    saltados: List[str] = []
    renombradas = 0
    pedidos = {str(a) for a in years}

    for i, (code, nombre) in enumerate(socios.items(), 1):
        # La ETIQUETA se refresca SIEMPRE, incluso al saltar. Saltar el socio no debe saltar
        # su nombre: tras deduplicar por código quedaron etiquetas mezcladas —"Estados Unidos"
        # y "España" junto a "Brazil" e "Italy"— y esperar a la próxima ingesta anual las
        # habría dejado así hasta 2027. Cuesta un UPDATE y hace el desorden auto-reparable.
        renombradas += _renombrar(db, code, nombre)
        if not forzar and pedidos <= _años_presentes(db, code):
            saltados.append(nombre)
            ingeridos.append(nombre)      # cuenta para la cobertura: el dato está
            continue
        set_phase(f"{nombre} ({i}/{len(socios)})")
        try:
            por_año = fetch_partner_chapters(RD_M49, code, years, flow="M")
        except Exception as e:  # noqa: BLE001 — un socio caído no tumba la ingesta
            logger.warning("Comtrade socio %s no disponible: %s", nombre, e)
            fallidos.append(nombre)
            continue
        if not por_año:
            vacios.append(nombre)
            continue
        ingeridos.append(nombre)
        for period, capitulos in por_año.items():
            for chapter, value in capitulos.items():
                if _upsert(db, period=period, partner=nombre, partner_code=code,
                           direction=TradeDirection.import_, chapter=chapter, value=value):
                    creadas += 1
                else:
                    actualizadas += 1
        db.commit()

    # COBERTURA: qué fracción del valor importado del país quedó efectivamente ingerida. Es
    # la cifra que impide leer el panel como exhaustivo cuando no lo es.
    cobertura = None
    if total_pais:
        cubierto = sum(valor_socio.get(n, 0.0) for n in ingeridos)
        cobertura = round(cubierto / total_pais * 100, 1)
    return {"socios_intentados": len(socios), "socios_ingeridos": len(ingeridos),
            "socios_saltados": len(saltados),
            "años": years, "filas_creadas": creadas, "filas_actualizadas": actualizadas,
            "cobertura_valor_pct": cobertura, "etiquetas_alineadas": renombradas,
            # Brechas declaradas, no silenciadas.
            "socios_sin_dato": vacios, "socios_fallidos": fallidos}


def importaciones_por_capitulo(db: Session, partner: str,
                               period: Optional[str] = None) -> Dict[str, Any]:
    """Lo que el motor de Research necesita: ``{period, partner, total, capitulos:[…]}``.

    Sin dato devuelve ``capitulos: []`` y ``period: None`` — la brecha se declara, no se
    rellena con el agregado del mundo, que mediría otra cosa.
    """
    q = db.query(TradePartnerChapter).filter(
        TradePartnerChapter.partner == partner,
        TradePartnerChapter.direction == TradeDirection.import_)
    if period:
        q = q.filter(TradePartnerChapter.period == period)
    else:
        ult = (db.query(TradePartnerChapter.period)
               .filter(TradePartnerChapter.partner == partner)
               .order_by(TradePartnerChapter.period.desc()).first())
        if not ult:
            return {"partner": partner, "period": None, "total_usd_mm": None,
                    "capitulos": [], "fuente": FUENTE}
        period = ult[0]
        q = q.filter(TradePartnerChapter.period == period)

    filas = [r for r in q.all() if r.value is not None]
    total = sum(float(cast(Any, r.value)) for r in filas)
    caps: List[Dict[str, Any]] = [
        {"capitulo": str(r.chapter), "usd_mm": round(float(cast(Any, r.value)), 2),
         "pct": (round(float(cast(Any, r.value)) / total * 100, 2) if total else None)}
        for r in filas]
    caps.sort(key=lambda d: -float(d["usd_mm"]))
    return {"partner": partner, "period": period,
            "total_usd_mm": round(total, 2) if filas else None,
            "n_capitulos": len(caps), "capitulos": caps, "fuente": FUENTE}
