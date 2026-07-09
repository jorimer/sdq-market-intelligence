"""Factura desglosada (PDF con marca SDQ) — monetización Fase 4.

Genera la factura de una ``BillingTransaction`` con el desglose fiscal exigido: subtotal de
la suscripción/compra + impuesto (ITBIS o exento) = total cobrado. Aunque a PayPal se le
cobra el total, la factura al cliente **desglosa** ambos renglones.

Reusa la paleta y el logo 'Arco' del renderer de reportes (``shared/products/render.py``) para
mantener la marca 1:1. Devuelve ``bytes`` (PDF) para servir sin tocar disco.

Nota fiscal: el ``invoice_number`` es un correlativo interno. Sin un RNC del emisor y una
secuencia NCF de la DGII cargados, la factura sale rotulada como **comprobante interno** (no
válido como crédito fiscal) — es una brecha legal/de servicio que el dueño cierra en /admin.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict

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
from shared.products.render import BLUE, GRAY, NAVY, SIGNAL, _draw_logo

_MARGIN = 0.7 * inch
_LIGHT = HexColor("#F1F5F9")
_LINE = HexColor("#CBD5E1")
_INK = HexColor("#0F172A")


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
                                 textColor=SIGNAL, leading=12),
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


def render_invoice_pdf(db: Session, tx, user) -> bytes:
    """Renderiza la factura (PDF) de una transacción para su dueño. ``tx`` es una
    ``BillingTransaction``; ``user`` el cliente."""
    from shared.settings.service import get_invoice_issuer

    issuer = get_invoice_issuer(db)
    st = _styles()
    ccy = tx.currency or "USD"
    is_internal = not (issuer.get("rnc") or "").strip()

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
    doc_title = "FACTURA" if not is_internal else "COMPROBANTE"
    right = [Paragraph(doc_title, st["docTitle"]),
             Paragraph(f"Nº {tx.invoice_number or '—'}", st["docMeta"]),
             Paragraph(f"Fecha: {created}", st["docMeta"])]
    head = Table([[issuer_lines, right]], colWidths=[doc.width * 0.58, doc.width * 0.42])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [head, Spacer(1, 0.25 * inch)]

    # Facturar a (cliente).
    client_name = getattr(user, "full_name", None) or getattr(user, "email", "")
    bill_to = [Paragraph("FACTURAR A", st["label"]),
               Paragraph(client_name, st["body"]),
               Paragraph(getattr(user, "email", ""), st["small"])]
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
        el += [Spacer(1, 0.16 * inch),
               Paragraph("Operación exenta de ITBIS — exportación de servicios (cliente del "
                         "exterior).", st["exempt"])]

    # Nota de comprobante interno cuando falta el dato fiscal (brecha legal/servicio).
    if is_internal:
        el += [Spacer(1, 0.22 * inch),
               Paragraph("Comprobante interno. No válido como crédito fiscal hasta cargar el "
                         "RNC del emisor y la secuencia de NCF autorizada por la DGII.",
                         st["small"])]
    el += [Spacer(1, 0.22 * inch),
           Paragraph("Gracias por su compra. El acceso al producto se refleja en «Mi plan».",
                     st["small"])]

    doc.build(el, onFirstPage=_furniture, onLaterPages=_furniture)
    return buf.getvalue()
