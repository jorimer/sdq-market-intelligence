"""SPEC-4 — eje base de sector desde ``bcrd_sectors`` (cubre las hojas del VAB sin producto dedicado).

Doctrina del dueño (2026-07-15): "sin producto profundo ≠ no podemos comentar; si tenemos fuente
confiable, comentamos con lo que hay". Las 17 hojas del PIB-por-origen del BCRD tienen aporte al Valor
Agregado + crecimiento real; devolver cobertura 0 para una de ellas niega dato confiable que sí
poseemos. Este registro cubre las hojas que NO tienen eje productizado propio: cada una responde con
el piso de inteligencia del BCRD (aporte al VAB + crecimiento + ranking) en vez de caer a scoping.

Los sectores YA productizados (turismo→tourism, agropecuario→agribusiness, construcción→construction,
energía→energy, zonas francas→free_zones, comunicaciones→telecom) NO están aquí: conservan su eje
dedicado con fuentes propias y más profundidad. El eje base es el nivel "Pulse" de la escalera de
valor; el enriquecimiento por-sector (salud→SISALRIL, enseñanza→MINERD/MESCyT, etc.) es roadmap aparte.

``financiero`` está aquí a nivel de SECTOR (VAB agregado) con un puente al eje de banca (SIB) para el
detalle por entidad — la decisión del dueño para SPEC-2.
"""
from __future__ import annotations

from typing import Dict, Tuple

SECTOR_BASE_SOURCE = "BCRD · PIB por sectores de origen (Valor Agregado)"

# slug (hoja de bcrd_sectors) → (display_name, keywords de ruteo). SOLO hojas sin eje dedicado.
# Keywords en forma normalizada (sin acentos, minúsculas); stems permitidos (el matcher usa
# frontera de palabra + sufijo, igual que AXIS_KEYWORDS).
BASE_SECTORS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "mineria": ("Minería y Canteras",
                ("miner", "minas", "cantera", "ferroniquel", "extractiv")),
    "comercio": ("Comercio interno",
                 ("comercio interno", "comercio minorista", "comercio mayorista", "comercio local")),
    "transporte": ("Transporte y Almacenamiento",
                   ("transporte", "almacenamiento", "carga terrestre")),
    "inmobiliario": ("Actividades Inmobiliarias y de Alquiler",
                     ("inmobiliari", "bienes raices", "alquiler de vivienda")),
    "ensenanza": ("Enseñanza",
                  ("ensenanza", "educacion", "educativ", "escolar", "universitari")),
    "salud": ("Salud",
              ("salud", "hospital", "sanitari", "clinica")),
    "administracion_publica": ("Administración Pública",
                               ("administracion publica", "sector publico", "gasto publico")),
    "servicios_profesionales": ("Servicios Profesionales",
                                ("servicios profesionales", "consultoria")),
    "otros_servicios": ("Otros Servicios de Mercado",
                        ("otros servicios de mercado",)),
    # SPEC-2: sector financiero a nivel VAB + puente a banca (ver pull_sector_base).
    "financiero": ("Sector financiero (VAB)",
                   ("sector financiero", "financiero", "intermediacion financiera")),
}


def base_sector_keywords() -> Dict[str, Tuple[str, ...]]:
    """``{slug: keywords}`` para el ruteo léxico (usado por ``detect_axes``)."""
    return {slug: kws for slug, (_name, kws) in BASE_SECTORS.items()}


def is_base_sector(sector_key: str) -> bool:
    return sector_key in BASE_SECTORS
