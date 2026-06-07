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
