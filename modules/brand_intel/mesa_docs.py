"""La nota técnica para la mesa con el proveedor.

Es el documento espejo del informe del cliente, y su opuesto deliberado. El informe del
cliente nunca cuestiona al proveedor y no imprime láminas; esta nota existe SOLO para la
conversación entre SDQ y el proveedor, y por eso aquí van **todos los recibos**: la frase
literal con su lámina, el movimiento que las cifras confirmadas sostienen, el delta por
marca y el umbral de detectabilidad que hace defendible el desacuerdo. Sin el umbral, la
objeción es una opinión; con él, es aritmética que ambas partes pueden repetir.

El tono es de conciliación, no de auditoría: la regla de la alianza es no auditar al
proveedor delante de su cliente, y esta nota es precisamente el mecanismo que lo hace
posible — el desacuerdo viaja aquí, se discute primero, y solo lo acordado vuelve al
informe. El documento dice eso en su portada.

Nunca se mezcla con el informe del cliente: otro título, otra marca de agua, otro
endpoint, y ninguna función compartida con ``report_docs`` más allá del renderizador de
la casa.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.brand_intel import service as svc
from modules.brand_intel.engines.metrics import label_for
from modules.brand_intel.models.models import BrandDiscrepancy, BrandEngagement

#: Orden de estados en la nota: primero lo que la mesa tiene que trabajar.
_STATE_ORDER = {"abierta": 0, "discutida": 1, "acordada": 2, "retirada": 3}

_STATE_LABEL = {
    "abierta": "Abierta — pendiente de discusión",
    "discutida": "Discutida — sin acuerdo aún",
    "acordada": "Acordada",
    "retirada": "Objeción retirada por SDQ",
}

_DIRECTION_LABEL = {"sube": "al alza", "baja": "a la baja", "estable": "estabilidad"}


def build_mesa(db: Session, engagement: BrandEngagement) -> Optional[Dict[str, Any]]:
    """El contenido de la nota, o ``None`` si la mesa está vacía.

    Una mesa vacía no produce documento: generar una nota que dice "no hay nada que
    discutir" invita a agendar una reunión para leerla. La pantalla ya enseña ese estado.
    """
    rows = (db.query(BrandDiscrepancy)
            .filter(BrandDiscrepancy.engagement_id == engagement.id).all())
    if not rows:
        return None
    rows.sort(key=lambda d: (_STATE_ORDER.get(str(d.status), 9), d.created_at or 0))

    abiertas = [d for d in rows if str(d.status) in ("abierta", "discutida")]
    nombres = {str(b.slug): str(b.name) for b in svc.brands(db, str(engagement.id))}
    return {
        "brand_names": nombres,
        "engagement": {
            "slug": str(engagement.slug),
            "client": engagement.client_name,
            "focal_brand": str(engagement.focal_brand),
            "provider": engagement.research_provider or "el proveedor",
            "market": engagement.market,
        },
        "total": len(rows),
        "abiertas": len(abiertas),
        "discrepancies": rows,
    }


def narratives_for(mesa: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Las secciones de la nota: un preámbulo, un punto POR TEMA, y el alcance.

    Un punto por discrepancia repetía el mismo movimiento bajo cada frase — tres puntos
    de «lugar favorito» decían tres veces «+12 pp sobre ±7 pp». Agrupar por métrica dice
    el movimiento UNA vez y cuelga debajo las conclusiones del informe que toca: la mesa
    discute temas, no repeticiones.

    Y una regla de imparcialidad: una marca sin dos olas confirmadas en NUESTRA base no
    aparece en el punto — ese hueco es de la carga de SDQ, no del informe del proveedor,
    y presentarlo en su contra trasladaría un problema interno a la mesa. Va aparte, en
    «Alcance de la comparación», atribuido a quien corresponde.

    La lámina se imprime aquí a propósito — este documento es la mesa, y en la mesa se
    abre el mazo.
    """
    provider = str(mesa["engagement"]["provider"])
    nombres: Dict[str, str] = mesa.get("brand_names") or {}
    n: Dict[str, str] = {}
    titles: Dict[str, str] = {}

    titles["preambulo"] = "Objeto de esta nota"
    n["preambulo"] = (
        f"Este documento es material de trabajo entre SDQ y {provider}, previo a "
        "cualquier entrega al cliente. Recoge los puntos donde las cifras confirmadas "
        "del tracker sostienen una lectura distinta de la que el informe afirma, para "
        "conciliarlos juntos.\n\n"
        "Cada punto compara el movimiento afirmado con el movimiento observado entre "
        "las mismas olas, y solo está aquí si supera el **umbral de detectabilidad al "
        "95%** dado el tamaño de muestra: por debajo de ese umbral un movimiento no se "
        "distingue de ruido muestral y SDQ no lo plantea. Las conclusiones del informe "
        "se citan **literales, con su lámina**, para que la verificación sea inmediata."
        "\n\nMientras un punto siga abierto, el análisis de SDQ que dependa de esa "
        "conclusión queda retenido y no llega al cliente."
    )

    # ── agrupar por métrica: la mesa discute temas, no repeticiones ──
    grupos: Dict[str, List[Any]] = {}
    for d in mesa["discrepancies"]:
        grupos.setdefault(str(d.metric_code), []).append(d)

    sin_serie: Dict[str, List[str]] = {}
    for i, (metric, ds) in enumerate(grupos.items(), start=1):
        key = f"punto_{i}"
        titles[key] = f"Punto {i} · {label_for(metric)}"

        # El movimiento observado, UNA vez por marca evaluable. Lo no evaluable en
        # nuestra base se aparta hacia «Alcance»: no es un cargo contra el proveedor.
        vistos: Dict[str, str] = {}
        for d in ds:
            for pb in d.per_brand or []:
                slug = str(pb.get("brand"))
                if pb.get("verdict") == "sin_serie":
                    sin_serie.setdefault(metric, []).append(slug)
                    continue
                vistos.setdefault(slug, str(pb.get("note") or pb.get("verdict") or ""))
        partes: List[str] = []
        if vistos:
            partes.append("**Lo que observan las cifras confirmadas:**\n" + "\n".join(
                f"- {nombres.get(s, s)}: {nota}" for s, nota in vistos.items()))

        partes.append("**Conclusiones del informe que toca este punto:**")
        for d in ds:
            estado = _STATE_LABEL.get(str(d.status), str(d.status))
            dice = _DIRECTION_LABEL.get(str(d.provider_direction),
                                        str(d.provider_direction))
            linea = (f"- (lámina {d.page_number} · afirma {dice} · {estado}) "
                     f"«{d.claim}»")
            if d.resolution_note:
                firmado = f" — {d.updated_by}" if d.updated_by else ""
                linea += f"\n  Resolución: {d.resolution_note}{firmado}"
            partes.append(linea)
        n[key] = "\n\n".join(partes)

    # ── alcance: los huecos de NUESTRA base, atribuidos a quien corresponde ──
    titles["alcance"] = "Alcance de la comparación"
    if sin_serie:
        lineas = []
        for metric, slugs in sin_serie.items():
            unicos = sorted({nombres.get(s, s) for s in slugs})
            lineas.append(f"- {label_for(metric)}: {', '.join(unicos)}")
        n["alcance"] = (
            "La comparación cubre las marcas con al menos dos olas confirmadas en la "
            "base de datos de SDQ. Las siguientes quedan fuera **por cobertura de "
            "nuestra propia carga de datos — no por inconsistencia del informe del "
            "proveedor**:\n" + "\n".join(lineas) +
            "\n\nSDQ completará esa cobertura antes de extender la comparación."
        )
    else:
        n["alcance"] = ("Todas las marcas citadas en los puntos cuentan con al menos "
                        "dos olas confirmadas en la base de SDQ.")

    return n, titles


def render(db: Session, engagement: BrandEngagement, fmt: str = "pdf",
           output_dir: Optional[str] = None) -> Optional[str]:
    """Escribe la nota en PDF o Word. ``None`` si la mesa está vacía."""
    from shared.products.render import render_product_pdf

    mesa = build_mesa(db, engagement)
    if mesa is None:
        return None
    narratives, titles = narratives_for(mesa)

    return render_product_pdf(
        sector_key="brand_intel_mesa",
        display_name=str(mesa["engagement"]["focal_brand"]),
        title="Nota técnica para la mesa con el proveedor",
        period=f"{mesa['abiertas']} punto(s) por conciliar · {mesa['total']} en total",
        narratives=narratives,
        section_titles=titles,
        subtitle=" · ".join(x for x in [
            str(mesa["engagement"]["provider"]),
            mesa["engagement"].get("client"),
            mesa["engagement"].get("market")] if x),
        watermark=("Documento de trabajo SDQ ↔ proveedor · NO distribuir al cliente"),
        output_dir=output_dir,
        fmt=fmt,
    )
