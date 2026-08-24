"""Admin-only settings API: app config + sector data-source APIs.

All routes require the ``admin`` role. Secrets are write-only — responses never
include stored keys, only "is set" flags and a masked placeholder.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.auth.dependencies import require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from shared.settings import service
from shared.settings.schemas import (
    SettingsIn,
    SmtpTestOut,
    SettingsOut,
    TestConnectionIn,
    TestConnectionOut,
)

router = APIRouter()

_admin = require_role(UserRole.admin)


@router.get("", response_model=SettingsOut)
async def read_settings(
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
) -> SettingsOut:
    """Return current settings with all secrets masked."""
    return service.get_settings(db)


@router.put("", response_model=SettingsOut)
async def write_settings(
    payload: SettingsIn,
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
) -> SettingsOut:
    """Update settings. Masked secret fields are left unchanged."""
    return service.update_settings(db, payload)


@router.delete("/sector-apis/{provider}")
async def delete_sector_api(
    provider: str,
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
) -> dict:
    """Remove a configured sector data-source API."""
    if not service.delete_sector_api(db, provider):
        raise HTTPException(status_code=404, detail=f"Proveedor '{provider}' no encontrado")
    return {"deleted": True, "provider": provider}


@router.post("/test", response_model=TestConnectionOut)
async def test_connection(
    payload: TestConnectionIn,
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
) -> TestConnectionOut:
    """Test connectivity to a provider's API (through the proxy if configured)."""
    return service.test_connection(db, payload)


@router.post("/smtp/test", response_model=SmtpTestOut)
async def test_smtp(
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin),
) -> SmtpTestOut:
    """Manda un correo de prueba REAL a la casilla del admin que lo pide.

    El destinatario NO se recibe por parámetro a propósito. Un endpoint autenticado que
    manda correo a la dirección que le pasen es un relay abierto con credenciales ajenas:
    bastaría una cuenta de admin comprometida para mandar correo firmado con el dominio de
    la instalación. Se manda a quien está pidiendo la prueba, que además es el único que
    puede confirmar que llegó.
    """
    destino = str(getattr(current_user, "email", "") or "")
    if not destino:
        return SmtpTestOut(status="error",
                           detail="Tu usuario no tiene correo cargado, así que no hay a "
                                  "dónde mandar la prueba.")
    return SmtpTestOut(**service.probar_smtp(db, destino))
