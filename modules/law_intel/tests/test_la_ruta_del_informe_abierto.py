"""La ruta del informe abierto entrega un ARCHIVO.

El tercer entregable del producto de leyes —el único que se comparte con externos— se sirve
por esta ruta. Durante un día devolvió `"2026-08-26"` con HTTP 200: un helper de dos líneas
se coló entre el decorador y la función, y la ruta quedó servida por el helper.

Los tests seguían verdes porque probaban `render()`, que funcionaba perfecto, **por debajo
de la ruta**. Es el mismo modo de fallo que ya cobró cuatro defectos en este repositorio: la
ruta no tiene los guardrails que tiene el motor. Acá se prueba la ruta.

El guard estructural que cubre la CLASE del defecto en todos los routers está en
`shared/tests/test_toda_ruta_recibe_su_path.py`; éste cubre el caso concreto de punta a
punta, que es lo que confirma que el archivo sale de verdad.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.database.session import get_db
from modules.law_intel.api.router import router

PREFIJO = "/api/v1/law-intel"


def _client():
    app = FastAPI()
    app.include_router(router, prefix=PREFIJO)

    class _U:
        role, organization_id, email = UserRole.admin, None, "analista@sdq.test"

    # La sesión no se usa: el renderizador está doblado y `_expediente` lee del disco. Lo
    # que se prueba acá es la RUTA, no lo que hay debajo.
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: _U()
    return TestClient(app)


def test_la_ruta_devuelve_un_ARCHIVO_y_no_una_cadena(tmp_path, monkeypatch):
    """El síntoma exacto del defecto: 200 con una fecha adentro."""
    falso = tmp_path / "informe.pdf"
    falso.write_bytes(b"%PDF-1.4 contenido")
    monkeypatch.setattr("modules.law_intel.informe_abierto.render",
                        lambda *a, **k: str(falso))

    r = _client().get(f"{PREFIJO}/ley_167_21/informe-abierto?fmt=pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    # La prueba que el defecto habría pasado: un 200 con JSON adentro.
    assert not r.headers["content-type"].startswith("application/json")


def test_el_nombre_del_archivo_lleva_la_NORMA(tmp_path, monkeypatch):
    """Dos leyes distintas producían el mismo archivo y la segunda descarga pisaba a la
    primera. El sujeto es lo que las distingue."""
    falso = tmp_path / "x.pdf"
    falso.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("modules.law_intel.informe_abierto.render",
                        lambda *a, **k: str(falso))

    cd = _client().get(
        f"{PREFIJO}/ley_167_21/informe-abierto").headers.get("content-disposition", "")
    assert "167-21" in cd.replace("_", "-")


def test_un_expediente_INEXISTENTE_da_404_y_no_500():
    r = _client().get(f"{PREFIJO}/no_existe_esta_ley/informe-abierto")
    assert r.status_code == 404


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_los_dos_formatos_se_sirven_con_su_tipo(tmp_path, monkeypatch, fmt):
    falso = tmp_path / f"x.{fmt}"
    falso.write_bytes(b"contenido")
    monkeypatch.setattr("modules.law_intel.informe_abierto.render",
                        lambda *a, **k: str(falso))

    r = _client().get(f"{PREFIJO}/ley_167_21/informe-abierto?fmt={fmt}")
    assert r.status_code == 200
    assert ("pdf" if fmt == "pdf" else "wordprocessingml") in r.headers["content-type"]


def test_un_formato_que_no_existe_se_RECHAZA():
    """Sin el patrón, `fmt=txt` llegaría al renderizador y fallaría adentro."""
    assert _client().get(
        f"{PREFIJO}/ley_167_21/informe-abierto?fmt=txt").status_code == 422
