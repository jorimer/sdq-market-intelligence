"""Ensamblado de un ``EcfDocument`` desde una ``BillingTransaction`` (monetización Fase 4).

Convierte el cobro ya facturado (subtotal + ITBIS + total, en la moneda de venta) en el
documento e-CF de la DGII: tipo, emisor, comprador, una línea de servicio y los totales. Como
SDQ factura en USD y el e-CF usa DOP como base, se convierte con un tipo de cambio y se anexa
el bloque ``OtraMoneda`` (USD original + TC). No firma ni envía (fases posteriores).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from shared.billing.encf.types import (
    ECF_CONSUMO,
    ECF_CREDITO_FISCAL,
    ECF_EXPORTACION,
    IND_ITBIS_0,
    IND_ITBIS_18,
    EcfComprador,
    EcfDocument,
    EcfEmisor,
    EcfItem,
    EcfOtraMoneda,
    EcfTotals,
)

_CENTS = Decimal("0.01")
_DOP = "DOP"


def _q(v: Decimal) -> Decimal:
    return v.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _fmt_date(dt: Optional[datetime]) -> str:
    return (dt or datetime.now()).strftime("%d-%m-%Y")


def assemble_ecf(tx, *, issuer: Dict[str, str], client_name: str,
                 client_rnc: Optional[str] = None, client_country: Optional[str] = None,
                 encf: str, fecha_vencimiento_secuencia: Optional[str] = None,
                 dop_per_currency: Decimal = Decimal("1"),
                 item_name: str = "Servicio de inteligencia de mercado SDQ") -> EcfDocument:
    """Arma el e-CF de una transacción. ``dop_per_currency`` = tipo de cambio DOP por 1 unidad
    de la moneda de venta (1 si ya es DOP). ``client_rnc`` presente → tipo 31 (crédito fiscal);
    exterior/exento → tipo 46; consumidor local sin RNC → tipo 32."""
    sale_ccy = (tx.currency or "USD").upper()
    tipo = tx.encf_type or _tipo_for(tx, client_rnc)
    rate = _d(dop_per_currency) if _d(dop_per_currency) > 0 else Decimal("1")

    # Montos en la moneda de venta.
    sub_sale = _d(tx.subtotal)
    tax_sale = _d(tx.tax_amount)
    total_sale = _d(tx.total)
    # Montos en DOP (base fiscal del e-CF).
    sub_dop = _q(sub_sale * rate)
    tax_dop = _q(tax_sale * rate)
    total_dop = _q(total_sale * rate)

    export = tipo == ECF_EXPORTACION or bool(tx.tax_exempt)
    if export:
        # Exportación → indicador 3 (ITBIS tasa cero): base en MontoGravadoI3, ITBIS 0.
        item_ind = IND_ITBIS_0
        totals = EcfTotals(monto_gravado_i3=sub_dop, total_itbis=Decimal("0"),
                           monto_total=total_dop)
        om_gravado = _q(sub_sale)
        om_exento = Decimal("0")
    else:
        item_ind = IND_ITBIS_18
        totals = EcfTotals(monto_gravado_total=sub_dop, monto_gravado_i1=sub_dop,
                           total_itbis=tax_dop, total_itbis1=tax_dop, monto_total=total_dop)
        om_gravado = _q(sub_sale)
        om_exento = Decimal("0")

    item = EcfItem(numero_linea=1, indicador_facturacion=item_ind, nombre=item_name,
                   cantidad=Decimal("1"), precio_unitario=sub_dop, monto=sub_dop)

    emisor = EcfEmisor(rnc=(issuer.get("rnc") or "").strip(),
                       razon_social=issuer.get("name") or "",
                       direccion=issuer.get("address") or "",
                       fecha_emision=_fmt_date(getattr(tx, "created_at", None)),
                       correo=issuer.get("email"))
    comprador = EcfComprador(
        razon_social=client_name or "Cliente",
        rnc=(client_rnc or None) if not export else None,
        identificador_extranjero=(client_rnc or None) if export and client_rnc else None,
        pais=client_country if export else None)

    # Bloque OtraMoneda solo si la venta NO es en DOP.
    otra = None
    if sale_ccy != _DOP:
        otra = EcfOtraMoneda(tipo_moneda=sale_ccy, tipo_cambio=rate,
                             monto_gravado_total=om_gravado, monto_exento=om_exento,
                             total_itbis=_q(tax_sale), monto_total=_q(total_sale))

    return EcfDocument(tipo_ecf=tipo, encf=encf,
                       fecha_vencimiento_secuencia=fecha_vencimiento_secuencia,
                       emisor=emisor, comprador=comprador, items=[item], totals=totals,
                       otra_moneda=otra)


def _tipo_for(tx, client_rnc: Optional[str]) -> str:
    """Matriz fiscal cuando la transacción no trae ``encf_type``: exento→46; RD con RNC→31;
    RD sin RNC→32."""
    if getattr(tx, "tax_exempt", False):
        return ECF_EXPORTACION
    return ECF_CREDITO_FISCAL if client_rnc else ECF_CONSUMO
