"""Régimen de comprobante fiscal (DGII): NCF tradicional y e-NCF electrónico.

Los dos regímenes conviven en el modelo porque SDQ está EN TRANSICIÓN bajo la Ley 32-23:
hoy factura con **NCF tradicional** (serie B — la DGII autoriza un rango y el emisor lo
consume), y cuando tenga el certificado digital pasa a **e-CF** (e-NCF firmado, con TrackID
y acuse ACECF). Un solo asignador sirve a los dos (``shared/billing/fiscal/sequences.py``);
acá vive lo único que de verdad difiere: prefijo, largo de la secuencia y tipos válidos.

Formato del número:

- NCF   → ``B`` + tipo(2) + secuencia(**8**)  = 11 caracteres  (p.ej. ``B0200000001``)
- e-NCF → ``E`` + tipo(2) + secuencia(**10**) = 13 caracteres  (p.ej. ``E320000000001``)

El régimen ACTIVO es config de admin (``shared/settings/service.py:get_fiscal_regime``), no
una constante: emitir por los dos a la vez sería doble numeración de la misma venta, y el
cambio de llave es exactamente lo que hay que hacer al habilitarse como emisor electrónico.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping

REGIME_NCF = "ncf"
REGIME_ECF = "ecf"
REGIMES = (REGIME_NCF, REGIME_ECF)

# ── Tipos de NCF tradicional (Decreto 254-06 / Norma 06-2018) ──
NCF_CREDITO_FISCAL = "01"
NCF_CONSUMO = "02"
NCF_NOTA_DEBITO = "03"
NCF_NOTA_CREDITO = "04"
NCF_EXPORTACIONES = "16"

# ── Tipos de e-CF (Ley 32-23) ──
ECF_CREDITO_FISCAL = "31"
ECF_CONSUMO = "32"
ECF_NOTA_DEBITO = "33"
ECF_NOTA_CREDITO = "34"
ECF_EXPORTACIONES = "46"

# Etiqueta del comprobante — la que se imprime en la factura. Es PROSA que el documento
# fiscal debe respetar: vive en una constante, no incrustada en el renderer.
NCF_LABELS: Dict[str, str] = {
    NCF_CREDITO_FISCAL: "Factura de Crédito Fiscal",
    NCF_CONSUMO: "Factura de Consumo",
    NCF_NOTA_DEBITO: "Nota de Débito",
    NCF_NOTA_CREDITO: "Nota de Crédito",
    NCF_EXPORTACIONES: "Comprobante para Exportaciones",
}

ECF_LABELS: Dict[str, str] = {
    ECF_CREDITO_FISCAL: "Factura de Crédito Fiscal Electrónica",
    ECF_CONSUMO: "Factura de Consumo Electrónica",
    ECF_NOTA_DEBITO: "Nota de Débito Electrónica",
    ECF_NOTA_CREDITO: "Nota de Crédito Electrónica",
    ECF_EXPORTACIONES: "Comprobante de Exportaciones Electrónico",
}

# Equivalencia NCF → e-CF. La usa el cambio de régimen: el tipo que hoy se emite como B02
# mañana se emite como E32, y así la matriz fiscal (``intended_doc_type``) no se reescribe.
NCF_TO_ECF: Dict[str, str] = {
    NCF_CREDITO_FISCAL: ECF_CREDITO_FISCAL,
    NCF_CONSUMO: ECF_CONSUMO,
    NCF_NOTA_DEBITO: ECF_NOTA_DEBITO,
    NCF_NOTA_CREDITO: ECF_NOTA_CREDITO,
    NCF_EXPORTACIONES: ECF_EXPORTACIONES,
}
ECF_TO_NCF: Dict[str, str] = {v: k for k, v in NCF_TO_ECF.items()}


class FiscalTypeError(ValueError):
    """Tipo de comprobante inválido para el régimen dado."""


@dataclass(frozen=True)
class RegimeSpec:
    """Lo que distingue a un régimen: prefijo de serie, largo de secuencia y tipos válidos."""

    regime: str
    prefix: str          # 'B' (NCF) | 'E' (e-NCF)
    seq_digits: int      # 8 (NCF) | 10 (e-NCF)
    labels: Mapping[str, str]
    label: str           # nombre del régimen para la UI

    @property
    def max_sequence(self) -> int:
        """Mayor correlativo representable (el rango autorizado no puede excederlo)."""
        return 10 ** self.seq_digits - 1

    @property
    def length(self) -> int:
        return 1 + 2 + self.seq_digits


SPECS: Dict[str, RegimeSpec] = {
    REGIME_NCF: RegimeSpec(regime=REGIME_NCF, prefix="B", seq_digits=8, labels=NCF_LABELS,
                           label="NCF (comprobante impreso)"),
    REGIME_ECF: RegimeSpec(regime=REGIME_ECF, prefix="E", seq_digits=10, labels=ECF_LABELS,
                           label="e-CF (factura electrónica)"),
}


def spec_for(regime: str) -> RegimeSpec:
    """Especificación de un régimen. Lanza ``FiscalTypeError`` si no existe."""
    s = SPECS.get((regime or "").strip().lower())
    if s is None:
        raise FiscalTypeError(
            f"Régimen fiscal inválido: '{regime}'. Use 'ncf' (impreso) o 'ecf' (electrónico).")
    return s


def valid_types(regime: str) -> tuple:
    """Tipos de comprobante válidos del régimen, en orden."""
    return tuple(spec_for(regime).labels.keys())


def validate_type(regime: str, doc_type: str) -> str:
    """Normaliza y valida un tipo dentro de su régimen. Devuelve el tipo de 2 dígitos."""
    spec = spec_for(regime)
    t = (doc_type or "").strip()
    if t not in spec.labels:
        raise FiscalTypeError(
            f"Tipo de comprobante '{doc_type}' inválido para {spec.label}. "
            f"Válidos: {', '.join(spec.labels)}.")
    return t


def doc_label(regime: str, doc_type: str) -> str:
    """Etiqueta imprimible del comprobante (p.ej. 'Factura de Consumo')."""
    return spec_for(regime).labels.get((doc_type or "").strip(), "Comprobante fiscal")


def format_number(regime: str, doc_type: str, number: int) -> str:
    """``B``/``E`` + tipo(2) + secuencia con relleno de ceros. Ej.: ('ncf','02',1) →
    'B0200000001'; ('ecf','32',1) → 'E320000000001'."""
    spec = spec_for(regime)
    t = validate_type(regime, doc_type)
    n = int(number)
    if n < 0 or n > spec.max_sequence:
        raise FiscalTypeError(
            f"Correlativo {n} fuera del formato de {spec.label} "
            f"(máximo {spec.max_sequence}).")
    return f"{spec.prefix}{t}{n:0{spec.seq_digits}d}"


def parse_number(value: str) -> tuple:
    """Descompone un número fiscal en ``(regime, doc_type, correlativo)``. Lanza
    ``FiscalTypeError`` si no corresponde a ningún régimen. Inverso de ``format_number``."""
    v = (value or "").strip().upper()
    for spec in SPECS.values():
        if len(v) == spec.length and v[0] == spec.prefix:
            doc_type, seq = v[1:3], v[3:]
            if doc_type in spec.labels and seq.isdigit():
                return (spec.regime, doc_type, int(seq))
    raise FiscalTypeError(f"Número de comprobante fiscal irreconocible: '{value}'.")
