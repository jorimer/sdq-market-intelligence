"""Las credenciales de la cuenta E2E. La contraseña NO vive en el repo: se lee del entorno.

Hasta el 2026-09-14 catorce scripts traían la contraseña escrita. El dueño la cambió en prod y
todos quedaron rotos a la vez, cada uno a su manera. Ahora hay UNA fuente: el correo vive acá y la
contraseña en `SDQ_E2E_PASSWORD`, que pone quien corre el script.

Sin la variable, el script se detiene ANTES de intentar iniciar sesión. No es cortesía: cada login
fallido suma a `failed_login_attempts`, y al bloquearse la cuenta `get_current_user` rechaza
también los tokens que ya estaban emitidos. Un script que prueba con una contraseña vieja puede
dejar sin acceso a quien sí la tiene.
"""
from __future__ import annotations

import os
import sys

E2E_EMAIL = "claude@sdqconsulting.com.do"

#: La variable de entorno de donde se lee la contraseña de la cuenta E2E.
ENV_VAR = "SDQ_E2E_PASSWORD"


def e2e_password() -> str:
    """La contraseña de la cuenta E2E, del entorno. Detiene el script si no está definida."""
    valor = os.environ.get(ENV_VAR, "")
    if not valor:
        sys.exit(
            f"Falta la variable de entorno {ENV_VAR} con la contraseña de la cuenta E2E "
            f"({E2E_EMAIL}). Definila antes de correr este script; no se intenta el login sin "
            "ella, porque un intento fallido cuenta para el bloqueo de la cuenta.")
    return valor
