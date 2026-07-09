"""Tests del ensamblado + constructor de XML e-CF (sin firma). Verifican el mapeo de tipo
(31/32/46), que los totales cuadran (DOP = venta × TC), el bloque OtraMoneda y que el XML es
bien formado."""
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as NS

from shared.billing.encf.assemble import assemble_ecf
from shared.billing.encf.xml import build_ecf_xml

ISSUER = {"name": "SDQ Consulting Group, SRL", "rnc": "131000000",
          "address": "Santo Domingo, RD", "email": "facturacion@sdq.do"}


def _tx(currency="USD", subtotal="100.00", tax="18.00", total="118.00", exempt=False, encf_type="31"):
    return NS(currency=currency, subtotal=subtotal, tax_amount=tax, total=total,
              tax_exempt=exempt, encf_type=encf_type, created_at=datetime(2026, 7, 9))


def _text(root, path):
    el = root.find(path)
    return el.text if el is not None else None


def test_credito_fiscal_31_gravado_18():
    tx = _tx(encf_type="31")
    doc = assemble_ecf(tx, issuer=ISSUER, client_name="Banco XYZ", client_rnc="101000000",
                       encf="E310000000001", dop_per_currency=Decimal("60.00"))
    assert doc.tipo_ecf == "31" and doc.comprador.rnc == "101000000"
    root = ET.fromstring(build_ecf_xml(doc))
    assert _text(root, "Encabezado/IdDoc/TipoeCF") == "31"
    assert _text(root, "Encabezado/IdDoc/eNCF") == "E310000000001"
    # DOP = 100 × 60 = 6000 gravado; ITBIS = 18 × 60 = 1080; total = 118×60 = 7080.
    assert _text(root, "Encabezado/Totales/MontoGravadoI1") == "6000.00"
    assert _text(root, "Encabezado/Totales/ITBIS1") == "18"
    assert _text(root, "Encabezado/Totales/TotalITBIS") == "1080.00"
    assert _text(root, "Encabezado/Totales/MontoTotal") == "7080.00"
    # Comprador con RNC.
    assert _text(root, "Encabezado/Comprador/RNCComprador") == "101000000"


def test_consumo_32_no_rnc():
    tx = _tx(encf_type="32")
    doc = assemble_ecf(tx, issuer=ISSUER, client_name="Cliente Final",
                       encf="E320000000001", dop_per_currency=Decimal("60"))
    assert doc.tipo_ecf == "32" and doc.comprador.rnc is None
    root = ET.fromstring(build_ecf_xml(doc))
    assert _text(root, "Encabezado/IdDoc/TipoeCF") == "32"
    assert root.find("Encabezado/Comprador/RNCComprador") is None


def test_exportacion_46_tasa_cero():
    tx = _tx(subtotal="100.00", tax="0.00", total="100.00", exempt=True, encf_type="46")
    doc = assemble_ecf(tx, issuer=ISSUER, client_name="Fund LP (US)", client_country="US",
                       encf="E460000000001", dop_per_currency=Decimal("60"))
    assert doc.tipo_ecf == "46"
    root = ET.fromstring(build_ecf_xml(doc))
    assert _text(root, "Encabezado/IdDoc/TipoeCF") == "46"
    # Tasa cero → MontoGravadoI3 = 6000, TotalITBIS = 0, sin MontoGravadoI1.
    assert _text(root, "Encabezado/Totales/MontoGravadoI3") == "6000.00"
    assert root.find("Encabezado/Totales/MontoGravadoI1") is None
    assert _text(root, "Encabezado/Totales/TotalITBIS") == "0.00"
    # Ítem con indicador de facturación 3 (ITBIS tasa cero) y país comprador.
    assert _text(root, "DetallesItems/Item/IndicadorFacturacion") == "3"
    assert _text(root, "Encabezado/Comprador/PaisComprador") == "US"


def test_otra_moneda_block_for_usd():
    tx = _tx(encf_type="31")
    doc = assemble_ecf(tx, issuer=ISSUER, client_name="Banco XYZ", client_rnc="101000000",
                       encf="E310000000002", dop_per_currency=Decimal("60"))
    root = ET.fromstring(build_ecf_xml(doc))
    assert _text(root, "Encabezado/Totales/OtraMoneda/TipoMoneda") == "USD"
    assert _text(root, "Encabezado/Totales/OtraMoneda/TipoCambio") == "60.0000"
    # Montos originales en USD.
    assert _text(root, "Encabezado/Totales/OtraMoneda/MontoTotalOtraMoneda") == "118.00"
    assert _text(root, "Encabezado/Totales/OtraMoneda/TotalITBISOtraMoneda") == "18.00"


def test_no_otra_moneda_when_dop():
    tx = _tx(currency="DOP", subtotal="1000.00", tax="180.00", total="1180.00", encf_type="32")
    doc = assemble_ecf(tx, issuer=ISSUER, client_name="Cliente", encf="E320000000009",
                       dop_per_currency=Decimal("1"))
    root = ET.fromstring(build_ecf_xml(doc))
    assert root.find("Encabezado/Totales/OtraMoneda") is None
    assert _text(root, "Encabezado/Totales/MontoTotal") == "1180.00"


def test_item_line_is_service():
    tx = _tx(encf_type="31")
    doc = assemble_ecf(tx, issuer=ISSUER, client_name="Banco", client_rnc="101",
                       encf="E310000000003", dop_per_currency=Decimal("60"))
    root = ET.fromstring(build_ecf_xml(doc))
    assert _text(root, "DetallesItems/Item/IndicadorBienoServicio") == "2"  # Servicio
    assert _text(root, "DetallesItems/Item/NumeroLinea") == "1"
    assert _text(root, "DetallesItems/Item/MontoItem") == "6000.00"
