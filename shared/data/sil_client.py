"""SIL Ciudadano — el registro legislativo de la Cámara de Diputados, en JSON y sin credencial.

Es la fuente que faltaba para las obligaciones de la Ley 1-12 cuyo cumplimiento es un ACTO
DEL CONGRESO: constituir una comisión, remitir un informe con el Proyecto de Presupuesto. Esos
actos no se publican en la Gaceta y por eso la base normativa —que sí los buscaba— los declara
fuera de su alcance.

**Lo que esta fuente NO declara, y hay que computar.** JurisAI dice de su propio corpus hasta
dónde está completo (`vacio_es_concluyente`) y eso es lo que permite publicar «no se dictó».
El SIL no declara nada: devuelve una lista y punto. Una lista vacía puede ser «no existe» o
«el endpoint no busca lo que creés». Por eso ninguna consulta de este cliente se usa sola para
concluir una ausencia — ver `modules/law_intel/congreso.py`, que exige un control positivo.

**Dos superficies con confianza distinta.** Los metadatos —qué documentos tiene el expediente
de una iniciativa, con su título y su fecha— viajan por `www.diputadosrd.gob.do`, con
certificado válido. El PDF de cada documento vive en `ssilappl.camaradediputados.gob.do`, que
presenta un **certificado autofirmado**: no se descarga desde acá. Es la misma distinción que
el emisor de la base normativa llama `registral` contra `texto` — sabemos que el documento
existe y cuándo se depositó; no leímos qué dice.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("sdq.data.sil")

BASE = "https://www.diputadosrd.gob.do/sil/api"
SOURCE = "SIL Ciudadano · Cámara de Diputados"

#: El host que sirve los PDF. Se nombra para poder DECLARAR por qué no se lee, en vez de que
#: el hueco parezca un olvido: su certificado es autofirmado y bajar contenido de ahí exigiría
#: apagar la verificación TLS dentro de la ruta que sostiene una acusación al Estado.
HOST_DOCUMENTOS = "ssilappl.camaradediputados.gob.do"

_TIMEOUT = 45


class SILUnavailable(RuntimeError):
    """No se pudo consultar el registro. NUNCA se degrada a «el acto no consta»."""


def _get(ruta: str, params: Dict[str, Any] | None = None) -> Any:  # pragma: no cover - red
    try:
        r = httpx.get(f"{BASE}/{ruta}", params=params or {}, timeout=_TIMEOUT,
                      follow_redirects=True,
                      headers={"User-Agent": "SDQ-MarketIntelligence/1.0"})
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SILUnavailable(f"{ruta}: {type(e).__name__}: {e}")


def tipos_de_comision() -> List[Dict[str, Any]]:
    """El catálogo de tipos. Trae `Bicamerales Permanentes` y `Bicamerales Especiales`.

    Que el propio registro DISTINGA las dos es lo que vuelve interpretable una lista vacía en
    la primera: no es que el sistema no sepa nombrar comisiones bicamerales — sabe, y las usa.
    """
    return list(_get("comision/tipo") or [])


def comisiones(tipo_id: int) -> List[Dict[str, Any]]:
    """Comisiones de un tipo. Sirve SOLO el período legislativo vigente.

    Comprobado: pasar `periodoId` del período anterior devuelve exactamente el mismo conjunto,
    todo con fechas de designación del período actual. El parámetro que el SPA inyecta no
    mueve esta respuesta, así que el alcance de cualquier lectura es el período en curso — y
    eso se declara, no se asume.
    """
    return list(_get("comision/comisiones", {"tipoId": tipo_id}) or [])


def iniciativas(keyword: str, page: int = 1) -> Dict[str, Any]:
    """Búsqueda paginada de iniciativas: `{page, pageSize, total, results}`."""
    d = _get("iniciativa/getIniciativas", {"page": page, "keyword": keyword})
    return d if isinstance(d, dict) else {"page": page, "pageSize": 0, "total": 0, "results": []}


def documentos(iniciativa_id: int, page: int = 1) -> Dict[str, Any]:
    """Documentos del expediente de una iniciativa. Metadatos, no contenido.

    El PDF queda del otro lado de `HOST_DOCUMENTOS`, con certificado autofirmado: acá se sabe
    que el documento existe, cómo se titula y cuándo se cargó.
    """
    d = _get("iniciativa/documentos", {"page": page, "id": iniciativa_id})
    return d if isinstance(d, dict) else {"page": page, "pageSize": 0, "total": 0, "results": []}


def todas_las_paginas(fn, *args, limite_paginas: int = 30) -> List[Dict[str, Any]]:
    """Recorre una respuesta paginada del SIL hasta agotarla.

    El tope existe para que un `total` mal informado por el emisor no convierta una consulta
    en un bucle infinito contra un sitio público. Si se alcanza, se registra: un recorte
    silencioso se leería como «esto es todo lo que hay».
    """
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= limite_paginas:
        d = fn(*args, page)
        out.extend(d.get("results") or [])
        tam = int(d.get("pageSize") or 0)
        if not tam or page * tam >= int(d.get("total") or 0):
            return out
        page += 1
    logger.warning("SIL: se alcanzó el tope de %s páginas; la lectura puede estar incompleta",
                   limite_paginas)
    return out
