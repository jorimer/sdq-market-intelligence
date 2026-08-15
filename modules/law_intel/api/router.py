"""Law Intel — API.

prefix: /api/v1/law-intel

Sirve el REGISTRO de un expediente: lo que la ley manda. No mide cumplimiento — el dato real
y el semáforo meta-vs-real llegan con los bindings. La separación es deliberada: permite
responder «¿cambió la meta o cambió el dato?», que es la pregunta que el artículo 20 de la
Ley 1-12 vuelve interesante al dejar que el propio evaluado mueva las metas por vía
administrativa.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from modules.law_intel.registro import ESCALAS, Expediente, cargar, expedientes
from shared.auth.dependencies import get_current_user
from shared.auth.models import User

logger = logging.getLogger("sdq.law_intel.api")
router = APIRouter()


def _expediente(expediente_id: str) -> Expediente:
    try:
        return cargar(expediente_id)
    except Exception as exc:                       # noqa: BLE001 — se traduce a 404/500
        logger.warning("expediente no cargable: %s (%s)", expediente_id, exc)
        raise HTTPException(status_code=404, detail=f"Expediente no encontrado: {expediente_id}")


@router.get("/instrumentos")
def listar_instrumentos(_: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Las leyes con expediente cargado."""
    filas = []
    for eid in expedientes():
        e = cargar(eid)
        filas.append({
            "id": e.id, "expediente": eid, "titulo": e.titulo, "norma": e.norma,
            "vigencia_hasta": e.meta.get("vigencia_hasta"),
            "indicadores": len(e.numerados), "filas_medibles": len(e.indicadores),
        })
    return {"instrumentos": filas}


@router.get("/{expediente_id}/indicadores")
def indicadores(expediente_id: str,
                eje: Optional[int] = Query(None, ge=1, le=4),
                incluir_subfilas: bool = Query(True),
                _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """El registro que fija la ley: línea base y metas por período.

    `admite_delta` viaja con cada fila para que ningún consumidor reste lo que no se resta:
    solo la escala numérica admite una diferencia meta-vs-real. Una banda PEFA se ordena, un
    umbral se cumple o no, y una meta redactada exige juicio.
    """
    e = _expediente(expediente_id)
    filas: List[Any] = e.indicadores if incluir_subfilas else e.numerados
    if eje is not None:
        filas = [i for i in filas if i.eje == eje]
    return {
        "instrumento": {"id": e.id, "titulo": e.titulo, "norma": e.norma},
        "conteo": {
            "numerados": len([i for i in filas if not i.subfila_de]),
            "filas": len(filas),
            # El denominador de un eje cambia según se cuenten indicadores numerados o filas
            # medibles. Se publican los dos para que ninguna cifra derivada elija en silencio.
            "por_eje_declarado": e.meta.get("indicadores_por_eje"),
        },
        "indicadores": [{
            "id": i.id, "eje": i.eje, "indicador": i.nombre, "subfila_de": i.subfila_de,
            "escala": i.escala, "admite_delta": i.admite_delta,
            "base": {"anio": i.base_anio, "anio_texto": i.base_anio_texto, "valor": i.base_valor},
            "metas": i.metas,
            "anios_sin_meta_numerica": i.anios_sin_meta_numerica,
        } for i in filas],
    }


@router.get("/{expediente_id}/procedencia")
def procedencia(expediente_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """De dónde sale el registro y qué fuentes admite el expediente.

    La procedencia se GENERA del expediente, nunca se redacta: es la misma regla que rige el
    resto de la plataforma. Y las fuentes admitidas se publican porque son lo que sostiene
    que el producto se venda a una parte interesada sin dejar de ser independiente.
    """
    e = _expediente(expediente_id)
    reg = e.meta.get("registro") or {}
    return {
        "instrumento": {"id": e.id, "titulo": e.titulo, "norma": e.norma,
                        "promulgada": e.meta.get("promulgada")},
        "registro": {
            "articulos": e.meta.get("articulos_indicadores"),
            "extraido_por": reg.get("extraido_por"),
            "metas_verificadas_a_mano": reg.get("metas_verificadas_a_mano"),
            "nota": reg.get("nota"),
        },
        "fuentes_admitidas": e.meta.get("fuentes_admitidas"),
        "escalas": ESCALAS,
    }
