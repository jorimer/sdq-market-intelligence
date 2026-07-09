"""Constructor del XML e-CF (DGII) desde un ``EcfDocument`` — sin firmar.

Serializa el documento al formato ``<ECF>`` de la DGII (secciones Encabezado, Detalle de
Ítems, InformacionReferencia/OtraMoneda según aplique). Deliberadamente **sin firma**: la
firma XAdES, el envío y la representación impresa son fases posteriores que requieren el
certificado y el enrolamiento. El XML producido es la entrada de la firma.

Alcance SDQ (una línea de servicio, 18% o exportación tasa cero). Los tags y su estructura
siguen el "Formato Comprobante Fiscal Electrónico (e-CF) v1.0" (DGII). Antes de certificar, el
XML debe validarse contra el XSD oficial de la DGII (slice de validación/firma).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from xml.sax.saxutils import escape

from shared.billing.encf.types import EcfDocument, EcfItem


def _money(v: Decimal) -> str:
    """Monto con 2 decimales, punto decimal, sin separador de miles (regla DGII)."""
    return f"{Decimal(v):.2f}"


def _tag(name: str, value, indent: int) -> str:
    if value is None or value == "":
        return ""
    return f"{'  ' * indent}<{name}>{escape(str(value))}</{name}>\n"


def _item_xml(it: EcfItem) -> str:
    x = ["    <Item>\n"]
    x.append(_tag("NumeroLinea", it.numero_linea, 3))
    x.append(_tag("IndicadorFacturacion", it.indicador_facturacion, 3))
    x.append(_tag("NombreItem", it.nombre, 3))
    x.append(_tag("IndicadorBienoServicio", it.indicador_bien_servicio, 3))
    x.append(_tag("CantidadItem", f"{it.cantidad:.2f}".rstrip("0").rstrip(".") or "1", 3))
    x.append(_tag("PrecioUnitarioItem", _money(it.precio_unitario), 3))
    x.append(_tag("MontoItem", _money(it.monto), 3))
    x.append("    </Item>\n")
    return "".join(x)


def build_ecf_xml(doc: EcfDocument) -> str:
    """Devuelve el XML e-CF (string UTF-8, sin firmar) del documento."""
    e, c, t = doc.emisor, doc.comprador, doc.totals
    out: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>\n', "<ECF>\n", "  <Encabezado>\n"]

    # IdDoc
    out.append("    <IdDoc>\n")
    out.append(_tag("TipoeCF", doc.tipo_ecf, 3))
    out.append(_tag("eNCF", doc.encf, 3))
    out.append(_tag("FechaVencimientoSecuencia", doc.fecha_vencimiento_secuencia, 3))
    out.append("    </IdDoc>\n")

    # Emisor
    out.append("    <Emisor>\n")
    out.append(_tag("RNCEmisor", e.rnc, 3))
    out.append(_tag("RazonSocialEmisor", e.razon_social, 3))
    out.append(_tag("DireccionEmisor", e.direccion, 3))
    out.append(_tag("CorreoEmisor", e.correo, 3))
    out.append(_tag("FechaEmision", e.fecha_emision, 3))
    out.append("    </Emisor>\n")

    # Comprador
    out.append("    <Comprador>\n")
    out.append(_tag("RNCComprador", c.rnc, 3))
    out.append(_tag("IdentificadorExtranjero", c.identificador_extranjero, 3))
    out.append(_tag("RazonSocialComprador", c.razon_social, 3))
    out.append(_tag("PaisComprador", c.pais, 3))
    out.append("    </Comprador>\n")

    # Totales
    out.append("    <Totales>\n")
    out.append(_tag("MontoGravadoTotal", _money(t.monto_gravado_total), 3) if t.monto_gravado_total else "")
    out.append(_tag("MontoGravadoI1", _money(t.monto_gravado_i1), 3) if t.monto_gravado_i1 else "")
    out.append(_tag("MontoGravadoI3", _money(t.monto_gravado_i3), 3) if t.monto_gravado_i3 else "")
    out.append(_tag("MontoExento", _money(t.monto_exento), 3) if t.monto_exento else "")
    out.append(_tag("ITBIS1", t.itbis1_rate, 3) if t.monto_gravado_i1 else "")
    out.append(_tag("ITBIS3", t.itbis3_rate, 3) if t.monto_gravado_i3 else "")
    out.append(_tag("TotalITBIS", _money(t.total_itbis), 3))
    out.append(_tag("TotalITBIS1", _money(t.total_itbis1), 3) if t.total_itbis1 else "")
    out.append(_tag("MontoTotal", _money(t.monto_total), 3))
    out.append(_otra_moneda_xml(doc))
    out.append("    </Totales>\n")

    out.append("  </Encabezado>\n")

    # Detalle de Ítems
    out.append("  <DetallesItems>\n")
    for it in doc.items:
        out.append(_item_xml(it))
    out.append("  </DetallesItems>\n")

    out.append("</ECF>\n")
    return "".join(p for p in out if p)


def _otra_moneda_xml(doc: EcfDocument) -> str:
    om = doc.otra_moneda
    if om is None:
        return ""
    x = ["      <OtraMoneda>\n"]
    x.append(_tag("TipoMoneda", om.tipo_moneda, 4))
    x.append(_tag("TipoCambio", f"{om.tipo_cambio:.4f}", 4))
    x.append(_tag("MontoGravadoTotalOtraMoneda", _money(om.monto_gravado_total), 4) if om.monto_gravado_total else "")
    x.append(_tag("MontoExentoOtraMoneda", _money(om.monto_exento), 4) if om.monto_exento else "")
    x.append(_tag("TotalITBISOtraMoneda", _money(om.total_itbis), 4) if om.total_itbis else "")
    x.append(_tag("MontoTotalOtraMoneda", _money(om.monto_total), 4))
    x.append("      </OtraMoneda>\n")
    return "".join(p for p in x if p)
