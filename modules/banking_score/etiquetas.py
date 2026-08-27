"""Nombres legibles de los tipos de entidad — FUENTE ÚNICA.

Existían DOS copias que no coincidían: `api/router_scoring.py` decía «intermediación
cambiaria» y `reports/pdf_generator.py` decía «Agentes de cambio» para la misma clave. El
mismo tipo de entidad tenía dos nombres según qué pantalla mirabas.

Se conserva la forma del PDF —«Agentes de cambio»— porque es la que ya salió publicada en el
anuario del sistema, y cambiarla ahora haría que un documento entregado y uno nuevo se
contradijeran.

**Por qué esto importa más allá de la prolijidad:** la clave CRUDA (`aap`, `banca_multiple`)
viajaba al contexto del modelo, incluido el nivel ABIERTO del producto anual. Ahí el modelo
tiene que adivinar qué es «aap» o imprimirlo tal cual, en material de mercado. La etiqueta
viaja ahora al lado de la clave.
"""
from __future__ import annotations

from typing import Dict

#: `bank_type` → nombre legible. Es el nombre que se PUBLICA.
TIPO_LABEL: Dict[str, str] = {
    "banca_multiple": "Banca múltiple",
    "aap": "Asociaciones de ahorros y préstamos",
    "banco_ahorro_credito": "Bancos de ahorro y crédito",
    "corporacion_credito": "Corporaciones de crédito",
    "cambiaria": "Agentes de cambio",
    "fiduciaria": "Fiduciarias",
}


def etiqueta_de_tipo(tipo: str | None) -> str:
    """El nombre publicable de un tipo. Devuelve la clave si no está mapeada — visible, para
    que un tipo nuevo se note en vez de salir en blanco."""
    return TIPO_LABEL.get(tipo or "", tipo or "sin tipo")
