"""Nombre legible de cada clave del registro de gasto.

El panel mostraba la clave técnica —``GET /api/v1/products/banking/deep_dive/report``— y
quien lee quiere saber qué PRODUCTO consumió eso, no por qué ruta entró. Un endpoint es
una decisión de implementación; el informe Deep Dive de banca es la cosa que costó dinero.

**Dónde vive cada nombre.** Se reusa la fuente que ya existe, jamás se reinventa:

* Operaciones → ``Operation.label`` del registro de la consola. Es literalmente el nombre
  que el operador ya ve al lado del interruptor, así que coinciden por construcción.
* Sectores → ``display_name`` del catálogo de productos.
* Rutas → una tabla declarada acá, porque no existe otra fuente. Es corta a propósito.

**La clave cruda NO se pierde.** El panel la conserva en el título emergente: cuando algo
hay que depurar, la ruta es lo que se necesita, y una etiqueta bonita que la reemplace
convierte una investigación de dos minutos en una de veinte.

**Lo que no se reconoce se devuelve tal cual.** Un endpoint nuevo aparecerá con su ruta
—feo pero cierto— en vez de con un nombre inventado o un «Otro» que lo esconda entre los
demás.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

#: Motivos de la llamada. Son tres y no crecen solos.
_MOTIVOS: Dict[str, str] = {
    "narrativa": "Redacción del análisis",
    "guard_numerico": "Verificación de cifras",
    "vision": "Lectura de láminas (visión)",
    "digest": "Resumen de publicaciones",
    "extraccion": "Extracción de documentos",
    "otro": "Otros usos",
}

#: Módulos que no son un sector del catálogo y por tanto no tienen ``display_name``.
_MODULOS: Dict[str, str] = {
    "brand_intel": "Inteligencia de marca",
    "source_intel": "Inteligencia de fuentes",
    "law_intel": "Evaluación de leyes",
    "social_dev": "Desarrollo social",
}

#: Niveles de producto, tal como se nombran de cara al cliente.
_NIVELES: Dict[str, str] = {
    "insight": "Insight",
    "deep_dive": "Deep Dive",
    "pulse": "Pulse",
}

#: Rutas conocidas. El orden importa: gana la primera que case.
_RUTAS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"^\w+ /api/v1/products/(?P<sector>[\w-]+)/(?P<nivel>[\w-]+)/report$"),
     "Informe {nivel} · {sector}"),
    (re.compile(r"^\w+ /api/v1/brand-intel/engagements/(?P<slug>[\w-]+)/report"),
     "Informe de marca · {slug}"),
    (re.compile(r"^\w+ /api/v1/brand-intel/engagements/(?P<slug>[\w-]+)/ingest-pdf"),
     "Lectura del mazo · {slug}"),
    (re.compile(r"^\w+ /api/v1/(?P<mod>[\w-]+)/insight/(?P<tema>[\w-]+)$"),
     "Insight de {tema} · {mod}"),
    (re.compile(r"^\w+ /api/v1/law-intel/(?P<ley>[\w-]+)/fuentes/barrido$"),
     "Barrido de fuentes · {ley}"),
    (re.compile(r"^\w+ /api/v1/banking-score/reports/[^/]+/generate$"),
     "Informe de calificación · Banca"),
)

#: El mismo eje se nombra distinto según dónde aparezca: la ruta dice ``banking-score``,
#: el catálogo de productos lo indexa como ``banking`` y el registro guarda ``banking``.
#: Sin este puente, el insight de banca salía etiquetado «banking_score».
_ALIAS_SECTOR = {"banking_score": "banking", "banking-score": "banking",
                 "macro_monitor": "macro", "insurance_intel": "insurance",
                 "pension_intel": "pension", "trade_intel": "trade",
                 "sector_intel": "sector", "esg_climate": "esg"}


def _sector(clave: str) -> Optional[str]:
    """``display_name`` del catálogo de productos, si la clave es un sector."""
    try:
        from shared.products.registry import CATALOG_BY_KEY

        entrada = CATALOG_BY_KEY.get(clave)
        return getattr(entrada, "display_name", None) if entrada else None
    except Exception:  # noqa: BLE001 — sin catálogo se cae al nombre crudo
        return None


def _operacion(clave: str) -> Optional[str]:
    """``label`` del registro de operaciones: el mismo texto que ve el operador."""
    try:
        from shared.operations.service import OPERATIONS

        op = OPERATIONS.get(clave)
        return getattr(op, "label", None) if op else None
    except Exception:  # noqa: BLE001
        return None


def etiqueta_modulo(clave: Optional[str]) -> str:
    if not clave:
        return "Sin módulo"
    return (_sector(clave) or _sector(_ALIAS_SECTOR.get(clave, ""))
            or _MODULOS.get(clave) or clave)


def etiqueta_motivo(clave: Optional[str]) -> str:
    return _MOTIVOS.get(clave or "", clave or "—")


def etiqueta_disparador(clave: Optional[str]) -> str:
    """Nombre legible de un disparador: operación, ruta conocida, o la clave tal cual."""
    if not clave:
        return "Sin atribuir"
    if clave == "desconocido":
        # No es un disparador: son las llamadas anteriores a que existiera la atribución.
        # Decirlo evita que se lea como un origen misterioso que hay que investigar.
        return "Sin atribuir (anterior al registro)"

    de_operacion = _operacion(clave)
    if de_operacion:
        return de_operacion

    for patron, plantilla in _RUTAS:
        m = patron.match(clave)
        if not m:
            continue
        partes = m.groupdict()
        if "sector" in partes:
            partes["sector"] = _sector(partes["sector"]) or partes["sector"]
        if "mod" in partes:
            partes["mod"] = etiqueta_modulo(partes["mod"].replace("-", "_"))
        if "nivel" in partes:
            partes["nivel"] = _NIVELES.get(partes["nivel"], partes["nivel"])
        return plantilla.format(**partes)

    return clave
