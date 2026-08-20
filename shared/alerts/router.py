"""API de la watchlist — ``/api/v1/alerts``.

Cada usuario ve y administra SOLO sus vigilancias (filtradas por ``user_id``; nunca se
exponen ajenas — una 404 y no una 403, para no revelar que existen). Errores en español.

**Los dos códigos de error no son intercambiables.** Un dato mal formado es 422 (lo arregla
el cliente cambiando el pedido); un eje que su plan no alcanza es 402 con el upsell, y uno no
publicado es 404 — eso lo decide ``enforce_access``, que ya sabe traducir la decisión y es la
misma que usa la superficie comercial. Duplicar ese criterio acá lo haría divergir.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.alerts import reglas, service
from shared.alerts.service import AlertValidationError
from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from shared.products.access import AccessDecision, enforce_access

router = APIRouter()


class _NuevaVigilancia(BaseModel):
    sector_key: str = Field(..., description="Clave del eje en el catálogo de productos.")
    subject: Optional[str] = Field(
        None, description="Sujeto a vigilar (lo que acepta scope). null = todo el eje.")
    rule_codes: Optional[List[str]] = Field(
        None, description="Disparadores que interesan. null = todos los del eje.")
    min_severity: str = Field("media", description="alta | media | baja")
    channels: Optional[List[str]] = Field(None, description="Canales de entrega.")
    digest: str = Field("inmediato", description="inmediato | diario | semanal")


class _EditarVigilancia(BaseModel):
    rule_codes: Optional[List[str]] = None
    min_severity: Optional[str] = None
    channels: Optional[List[str]] = None
    digest: Optional[str] = None
    active: Optional[bool] = None


def _422(e: AlertValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/rules", summary="Catálogo de disparadores")
async def get_rules(db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Qué puede hacer sonar una alerta, y **qué aporta cada eje HOY**.

    ``implementado`` dice si el disparador tiene motor; ``cobertura_por_eje`` dice cuáles de
    esos disparadores alcanzan realmente a cada eje. Las dos cosas son distintas y las dos
    hacen falta: una regla implementada sobre un eje que no la alimenta es una vigilancia
    que nunca suena, y presentarla como activa se lee como que no pasó nada.
    """
    from shared.alerts.productores import cobertura

    return {
        # Se computa contra el registro vivo, no se declara a mano: una tabla escrita a mano
        # se desincroniza el día que un eje registra su motor.
        "cobertura_por_eje": cobertura(db),
        "rules": [reglas.serializar(d) for d in reglas.CATALOGO],
        "severidades": list(reglas.SEVERIDADES),
        "canales_disponibles": list(service.canales_disponibles()),
        # Existen en el código pero este despliegue no los tiene configurados: no es lo
        # mismo que "no lo ofrecemos", y la UI tiene que poder decirlo.
        "canales_no_configurados": list(service.canales_no_configurados()),
        "canales_planificados": list(service.CANALES_PLANIFICADOS),
        "digests": list(service.DIGESTS),
    }


@router.get("/events", summary="Historial de señales de mis vigilancias")
async def get_events(limit: int = 50, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Publicadas Y vetadas, juntas. ``vetadas`` resume por motivo: es lo que convierte
    «no recibí nada» en «hay tres señales retenidas porque el dato no está vigente»."""
    return service.eventos_para(db, str(current_user.id), limit=max(1, min(limit, 200)))


@router.get("/subscriptions", summary="Mis vigilancias")
async def get_subscriptions(db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)
                            ) -> Dict[str, Any]:
    items = service.listar(db, str(current_user.id))
    return {"subscriptions": items, "total": len(items),
            "max": service.MAX_POR_USUARIO}


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED,
             summary="Vigilar un eje o un sujeto")
async def post_subscription(body: _NuevaVigilancia, db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)
                            ) -> Dict[str, Any]:
    """Idempotente: re-vigilar lo que ya se vigila reactiva y reconfigura esa vigilancia en
    vez de fallar. Así el botón «Vigilar» no necesita saber si ya existe."""
    try:
        row = service.crear(
            db, current_user, sector_key=body.sector_key, subject=body.subject,
            rule_codes=body.rule_codes, min_severity=body.min_severity,
            channels=body.channels, digest=body.digest)
    except AlertValidationError as e:
        raise _422(e)
    except PermissionError as e:
        decision = e.args[0] if e.args else None
        if isinstance(decision, AccessDecision):
            enforce_access(decision)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tenés acceso a este producto.")
    return service.serializar(row)


@router.patch("/subscriptions/{sub_id}", summary="Editar una vigilancia")
async def patch_subscription(sub_id: str, body: _EditarVigilancia,
                             db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)
                             ) -> Dict[str, Any]:
    row = service.obtener(db, str(current_user.id), sub_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Vigilancia no encontrada.")
    try:
        row = service.actualizar(
            db, row, rule_codes=body.rule_codes, min_severity=body.min_severity,
            channels=body.channels, digest=body.digest, active=body.active)
    except AlertValidationError as e:
        raise _422(e)
    return service.serializar(row)


@router.delete("/subscriptions/{sub_id}", summary="Dejar de vigilar")
async def delete_subscription(sub_id: str, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)
                              ) -> Dict[str, Any]:
    row = service.obtener(db, str(current_user.id), sub_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Vigilancia no encontrada.")
    service.eliminar(db, row)
    return {"id": sub_id, "deleted": True}
