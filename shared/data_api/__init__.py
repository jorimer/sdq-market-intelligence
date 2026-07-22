"""Data API — canal máquina-a-máquina de los activos propietarios de SDQ.

Spec: docs/SPEC_API_DATOS_PROPIETARIOS.md. Fase 1: manifiesto de exposición
auto-extensible + cuarentena calculada + llaves con cuota y bitácora + ``/catalog`` y
``/series``.

Lo que NO se expone (y no es una omisión de fase, es la doctrina): el payload crudo del
conector, la narrativa IA del Insight/Deep Dive, el núcleo de IP (prompts, doctrina,
pesos del modelo entrenado) y todo activo cuya licencia de origen no conste.
"""
from shared.data_api.manifest import (
    Q_LOW_READINESS,
    Q_NO_LICENSE,
    Q_NO_READER,
    Q_NOT_ACTIVATED,
    ExposedAsset,
    Manifest,
    build_manifest,
)
from shared.data_api.models import ApiKey, ApiUsage

__all__ = [
    "ApiKey",
    "ApiUsage",
    "ExposedAsset",
    "Manifest",
    "build_manifest",
    "Q_NO_LICENSE",
    "Q_NO_READER",
    "Q_NOT_ACTIVATED",
    "Q_LOW_READINESS",
]
