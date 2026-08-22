"""Factura desglosada (PDF con marca SDQ) — monetización Fase 4.

Genera la factura de una ``BillingTransaction`` con el desglose fiscal exigido: subtotal de
la suscripción/compra + impuesto (ITBIS o exento) = total cobrado. Aunque a PayPal se le
cobra el total, la factura al cliente **desglosa** ambos renglones.

Reusa la paleta y el logo 'Arco' del renderer de reportes (``shared/products/render.py``) para
mantener la marca 1:1. Devuelve ``bytes`` (PDF) para servir sin tocar disco.

Nota fiscal: el ``invoice_number`` es un correlativo interno. La validez fiscal la da el
**comprobante** — el NCF (régimen impreso) o el e-NCF (electrónico). Sin ninguno de los dos,
la factura sale rotulada como **comprobante interno**, no como factura: es una brecha que se
declara en el documento, no se disimula.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle
from sqlalchemy.orm import Session

from shared.billing.skus import sku_label
from shared import brand
from shared.products.render import BLUE, GRAY, NAVY, _draw_logo

_MARGIN = 0.7 * inch
# Paleta: se LEE de `shared.brand`. El comprobante es una superficie de marca más.
_LIGHT = HexColor(brand.SURFACE_2)
_LINE = HexColor(brand.BORDER_STRONG)
_INK = HexColor(brand.INK)
# La leyenda de exención de ITBIS tiene que saltar a la vista: es el rojo SEMÁNTICO de la
# paleta, no el `signal red` decorativo que se retiró.
_EXENTO = HexColor(brand.ALERT)

# Prosa que el documento fiscal debe respetar → constantes con nombre. Un literal incrustado
# en el layout se parte por ancho de línea y deja de existir como frase en el fuente.
LEYENDA_COMPROBANTE_INTERNO = (
    "Comprobante interno. No válido como crédito fiscal: este cobro aún no tiene un "
    "comprobante fiscal asignado (NCF o e-NCF)."
)
LEYENDA_EXENTO_EXPORTACION = (
    "Operación exenta de ITBIS — exportación de servicios (cliente del exterior)."
)
LEYENDA_CIERRE = "Gracias por su compra. El acceso al producto se refleja en «Mi plan»."


def _styles() -> Dict[str, ParagraphStyle]:
    return {
        "issuer": ParagraphStyle("issuer", fontName="Helvetica-Bold", fontSize=13,
                                 textColor=NAVY, leading=16),
        "issuerMeta": ParagraphStyle("issuerMeta", fontName="Helvetica", fontSize=8.5,
                                     textColor=GRAY, leading=12),
        "docTitle": ParagraphStyle("docTitle", fontName="Helvetica-Bold", fontSize=20,
                                   textColor=NAVY, leading=22, alignment=2),
        "docMeta": ParagraphStyle("docMeta", fontName="Helvetica", fontSize=9,
                                  textColor=_INK, leading=13, alignment=2),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8,
                                textColor=GRAY, leading=11, spaceAfter=2),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                               textColor=_INK, leading=13),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5,
                               textColor=_INK, leading=13),
        "cellR": ParagraphStyle("cellR", fontName="Helvetica", fontSize=9.5,
                                textColor=_INK, leading=13, alignment=2),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.8,
                                textColor=GRAY, leading=10.5),
        "exempt": ParagraphStyle("exempt", fontName="Helvetica-Oblique", fontSize=8.5,
                                 textColor=_EXENTO, leading=12),
    }


def _money(value: Any, currency: str) -> str:
    try:
        return f"{currency} {float(value):,.2f}"
    except (TypeError, ValueError):
        return f"{currency} {value}"


def _furniture(canvas, doc):
    w, h = A4
    canvas.saveState()
    # Banda navy superior con el logo Arco.
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 0.45 * inch, w, 0.45 * inch, fill=1, stroke=0)
    _draw_logo(canvas, _MARGIN, h - 0.4 * inch, 0.28 * inch)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(white)
    canvas.drawString(_MARGIN + 0.4 * inch, h - 0.3 * inch, "SDQ·MIP — Market Intelligence")
    # Pie.
    canvas.setStrokeColor(_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(_MARGIN, 0.62 * inch, w - _MARGIN, 0.62 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GRAY)
    canvas.drawString(_MARGIN, 0.45 * inch,
                      "Documento generado por SDQ·MIP. Las consultas de facturación: "
                      "facturación@sdqconsulting.com.do")
    canvas.drawRightString(w - _MARGIN, 0.45 * inch, f"Página {canvas.getPageNumber()}")
    canvas.restoreState()


def _fiscal_identity(tx) -> Optional[Dict[str, Any]]:
    """Identidad fiscal del documento: ``{regime, number, doc_type, label, valid_until}`` o
    ``None`` si el cobro todavía no tiene comprobante asignado.

    El número **nunca sale solo**: viaja con el tipo y su etiqueta. Sin eso, un '02' impreso
    junto a un número no dice si es Consumo (NCF) o nada (e-CF), y el lector lo reatribuye."""
    from shared.billing.fiscal.types import REGIME_ECF, REGIME_NCF, doc_label

    ncf = (getattr(tx, "ncf_number", None) or "").strip()
    if ncf:
        doc_type = (getattr(tx, "ncf_type", None) or "").strip()
        return {"regime": REGIME_NCF, "number": ncf, "doc_type": doc_type,
                "label": doc_label(REGIME_NCF, doc_type),
                "valid_until": getattr(tx, "ncf_valid_until", None)}
    encf = (getattr(tx, "encf_number", None) or "").strip()
    if encf:
        doc_type = (getattr(tx, "encf_type", None) or "").strip()
        return {"regime": REGIME_ECF, "number": encf, "doc_type": doc_type,
                "label": doc_label(REGIME_ECF, doc_type), "valid_until": None}
    return None


def render_invoice_pdf(db: Session, tx, user) -> bytes:
    """Renderiza la factura (PDF) de una transacción para su dueño. ``tx`` es una
    ``BillingTransaction``; ``user`` el cliente."""
    from shared.settings.service import get_invoice_issuer

    issuer = get_invoice_issuer(db)
    st = _styles()
    ccy = tx.currency or "USD"
    # El documento es una FACTURA solo si lleva comprobante fiscal — NCF impreso o e-NCF
    # electrónico. Si no lleva ninguno, es un comprobante interno y lo dice.
    fiscal = _fiscal_identity(tx)
    is_internal = fiscal is None

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=_MARGIN, rightMargin=_MARGIN,
                            topMargin=0.75 * inch, bottomMargin=0.8 * inch,
                            title=f"Factura {tx.invoice_number or ''}",
                            author="SDQ Market Intelligence")
    el: list = [Spacer(1, 0.15 * inch)]

    # Cabecera: emisor (izq) + título/número/fecha (der).
    issuer_lines = [Paragraph(issuer["name"], st["issuer"])]
    if issuer.get("rnc"):
        issuer_lines.append(Paragraph(f"RNC: {issuer['rnc']}", st["issuerMeta"]))
    else:
        issuer_lines.append(Paragraph("RNC: pendiente de configurar", st["issuerMeta"]))
    issuer_lines.append(Paragraph(issuer.get("address", ""), st["issuerMeta"]))
    issuer_lines.append(Paragraph(issuer.get("email", ""), st["issuerMeta"]))

    created = tx.created_at.strftime("%d/%m/%Y") if tx.created_at else datetime.now().strftime("%d/%m/%Y")
    doc_title = "COMPROBANTE" if is_internal else "FACTURA"
    right = [Paragraph(doc_title, st["docTitle"])]
    if fiscal is not None:
        # Rótulo del número según su régimen: bajo NCF impreso se rotula "NCF"; bajo e-CF,
        # "e-NCF". Y la etiqueta del tipo va SIEMPRE al lado del número.
        tag = "NCF" if fiscal["regime"] == "ncf" else "e-NCF"
        right.append(Paragraph(f"{tag}: {fiscal['number']}", st["docMeta"]))
        if fiscal["label"]:
            right.append(Paragraph(fiscal["label"], st["docMeta"]))
        if fiscal["valid_until"]:
            right.append(Paragraph(
                f"Válido hasta: {fiscal['valid_until'].strftime('%d/%m/%Y')}", st["docMeta"]))
    right += [Paragraph(f"Nº interno {tx.invoice_number or '—'}", st["docMeta"]),
              Paragraph(f"Fecha: {created}", st["docMeta"])]
    head = Table([[issuer_lines, right]], colWidths=[doc.width * 0.58, doc.width * 0.42])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [head, Spacer(1, 0.25 * inch)]

    # Facturar a (cliente).
    client_name = getattr(user, "full_name", None) or getattr(user, "email", "")
    bill_to = [Paragraph("FACTURAR A", st["label"]),
               Paragraph(client_name, st["body"]),
               Paragraph(getattr(user, "email", ""), st["small"])]
    # En una factura de crédito fiscal el RNC del COMPRADOR es obligatorio: sin él, el
    # cliente no puede usarla como crédito fiscal y el comprobante pierde su razón de ser.
    client_tax_id = (getattr(user, "tax_id", None) or "").strip()
    if client_tax_id:
        bill_to.append(Paragraph(f"RNC/Cédula: {client_tax_id}", st["small"]))
    if tx.country:
        bill_to.append(Paragraph(f"País de facturación: {tx.country}", st["small"]))
    meta = [Paragraph("DETALLES DEL PAGO", st["label"]),
            Paragraph("Medio de pago: PayPal", st["body"]),
            Paragraph(f"Referencia: {tx.provider_ref or '—'}", st["small"]),
            Paragraph(f"Estado: {'Pagada' if tx.status == 'paid' else tx.status}", st["small"])]
    who = Table([[bill_to, meta]], colWidths=[doc.width * 0.58, doc.width * 0.42])
    who.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [who, Spacer(1, 0.28 * inch)]

    # Renglón + totales.
    tax_label = tx.tax_label or "Impuesto"
    rate = f"{float(tx.tax_rate):g}%" if tx.tax_rate is not None else "0%"
    desc = sku_label(tx.sku)
    if tx.kind == "subscription":
        desc = f"{desc} — suscripción"
    rows = [
        [Paragraph("DESCRIPCIÓN", st["label"]), Paragraph("IMPORTE", ParagraphStyle(
            "labelR", parent=st["label"], alignment=2))],
        [Paragraph(desc, st["cell"]), Paragraph(_money(tx.subtotal, ccy), st["cellR"])],
    ]
    data_rows = 1  # filas de detalle (para el estilo de líneas)
    table = Table(rows, colWidths=[doc.width * 0.72, doc.width * 0.28])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    # Cabecera del renglón con estilo blanco: reescribir las celdas de encabezado en blanco.
    rows[0][0] = Paragraph("<font color='white'>DESCRIPCIÓN</font>", st["label"])
    rows[0][1] = Paragraph("<font color='white'>IMPORTE</font>",
                           ParagraphStyle("labelRW", parent=st["label"], alignment=2))

    # Totales (subtotal / impuesto / total).
    tot_style = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY),
        ("TOPPADDING", (0, -1), (-1, -1), 7),
    ])
    tot_rows = [
        [Paragraph("Subtotal", st["cellR"]), Paragraph(_money(tx.subtotal, ccy), st["cellR"])],
        [Paragraph(f"{tax_label} ({rate})", st["cellR"]),
         Paragraph(_money(tx.tax_amount, ccy), st["cellR"])],
        [Paragraph("<b>Total</b>", st["cellR"]),
         Paragraph(f"<b>{_money(tx.total, ccy)}</b>", st["cellR"])],
    ]
    totals = Table(tot_rows, colWidths=[doc.width * 0.44, doc.width * 0.28],
                   hAlign="RIGHT")
    totals.setStyle(tot_style)
    el += [table, Spacer(1, 0.12 * inch), totals]

    if tx.tax_exempt:
        el += [Spacer(1, 0.16 * inch), Paragraph(LEYENDA_EXENTO_EXPORTACION, st["exempt"])]

    # Nota de comprobante interno cuando falta el dato fiscal (brecha legal/servicio).
    if is_internal:
        el += [Spacer(1, 0.22 * inch), Paragraph(LEYENDA_COMPROBANTE_INTERNO, st["small"])]
    el += [Spacer(1, 0.22 * inch), Paragraph(LEYENDA_CIERRE, st["small"])]

    doc.build(el, onFirstPage=_furniture, onLaterPages=_furniture)
    return buf.getvalue()
