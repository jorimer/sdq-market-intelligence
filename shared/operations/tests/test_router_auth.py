"""Gate de la consola de Operaciones: jerárquico (super_admin ⊇ admin).

Regresión: el chequeo plano `role != UserRole.admin` dejaba afuera a super_admin
(que debe poder TODO lo de admin). Ahora usa `role_satisfies`.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from shared.auth.models import UserRole
from shared.operations.router import _require_admin


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.super_admin])
def test_require_admin_allows_admin_and_above(role):
    _require_admin(SimpleNamespace(role=role))  # no debe levantar


@pytest.mark.parametrize("role", [UserRole.analyst, UserRole.viewer])
def test_require_admin_blocks_below_admin(role):
    with pytest.raises(HTTPException) as exc:
        _require_admin(SimpleNamespace(role=role))
    assert exc.value.status_code == 403
