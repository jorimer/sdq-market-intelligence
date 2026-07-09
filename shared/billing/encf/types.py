"""Modelo de dominio del e-CF (Comprobante Fiscal Electrónico, DGII).

Representación agnóstica del transporte: el ensamblador (``assemble.py``) construye un
``EcfDocument`` a partir de una ``BillingTransaction``, y el constructor de XML (``xml.py``) lo
serializa al formato de la DGII. La firma XAdES, el envío a la DGII y la representación impresa
con QR son fases posteriores (requieren certificado + enrolamiento).

Alcance de SDQ: una sola línea de servicio, ITBIS 18% (gravado) o exento (exportación). Tipos
de e-CF relevantes: 31 (crédito fiscal, cliente RD con RNC), 32 (consumo, RD sin RNC), 46
(exportación de servicios, cliente del exterior). Ver la matriz en ``intended_encf_type``.

Moneda: el e-CF usa DOP como moneda base con un bloque ``OtraMoneda`` (USD + tipo de cambio)
cuando la venta es en USD (el caso de SDQ). Los montos base van en DOP; el bloque OtraMoneda
lleva los montos originales en USD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

# Tipos de e-CF (DGII).
ECF_CREDITO_FISCAL = "31"
ECF_CONSUMO = "32"
ECF_EXPORTACION = "46"

# Indicador de Facturación por línea (sección Detalle): 1=ITBIS1(18%), 3=ITBIS3(0%), 4=Exento.
IND_ITBIS_18 = 1
IND_ITBIS_0 = 3   # tipo 46 exige tasa cero (footnote spec)
IND_EXENTO = 4
# Indicador Bien o Servicio: SDQ vende servicios.
BIEN_O_SERVICIO_SERVICIO = 2


@dataclass(frozen=True)
class EcfEmisor:
    rnc: str
    razon_social: str
    direccion: str
    fecha_emision: str            # dd-MM-AAAA
    correo: Optional[str] = None


@dataclass(frozen=True)
class EcfComprador:
    razon_social: str
    rnc: Optional[str] = None                 # RD con RNC (tipo 31)
    identificador_extranjero: Optional[str] = None  # cliente del exterior (tipo 46)
    pais: Optional[str] = None                # ISO / nombre (tipo 46)


@dataclass(frozen=True)
class EcfItem:
    numero_linea: int
    indicador_facturacion: int    # IND_ITBIS_18 | IND_ITBIS_0 | IND_EXENTO
    nombre: str
    cantidad: Decimal
    precio_unitario: Decimal      # en DOP (moneda base del e-CF)
    monto: Decimal                # en DOP
    indicador_bien_servicio: int = BIEN_O_SERVICIO_SERVICIO


@dataclass(frozen=True)
class EcfOtraMoneda:
    """Bloque OtraMoneda: montos en la moneda original (USD) + tipo de cambio a DOP."""

    tipo_moneda: str              # p.ej. "USD"
    tipo_cambio: Decimal          # DOP por 1 unidad de la otra moneda
    monto_gravado_total: Decimal
    monto_exento: Decimal
    total_itbis: Decimal
    monto_total: Decimal


@dataclass(frozen=True)
class EcfTotals:
    """Totales en DOP (moneda base). Caso SDQ: una tasa 18% (tipo 31/32) o tasa cero (tipo 46,
    exportación → indicador 3, ITBIS tasa cero, monto en MontoGravadoI3)."""

    monto_gravado_total: Decimal = Decimal("0")
    monto_gravado_i1: Decimal = Decimal("0")   # base gravada a 18%
    monto_gravado_i3: Decimal = Decimal("0")   # base gravada a tasa cero (export, tipo 46)
    monto_exento: Decimal = Decimal("0")       # verdaderamente exento (no aplica a SDQ hoy)
    itbis1_rate: int = 18
    itbis3_rate: int = 0
    total_itbis: Decimal = Decimal("0")
    total_itbis1: Decimal = Decimal("0")
    monto_total: Decimal = Decimal("0")


@dataclass(frozen=True)
class EcfDocument:
    tipo_ecf: str                 # ECF_CREDITO_FISCAL | ECF_CONSUMO | ECF_EXPORTACION
    encf: str                     # e-NCF (secuencia autorizada por la DGII)
    fecha_vencimiento_secuencia: Optional[str]  # dd-MM-AAAA
    emisor: EcfEmisor
    comprador: EcfComprador
    items: List[EcfItem]
    totals: EcfTotals
    otra_moneda: Optional[EcfOtraMoneda] = None
    version: str = "1.0"
