"""Una ruta inexistente bajo /api/ devuelve 404 JSON, no el index.html de la SPA.

En producción el catch-all de la SPA (mount en "/") atrapaba también lo que empieza
por /api/, así que `GET /api/v1/operations/no-existe` devolvía **HTTP 200 con
text/html**. No es cosmético: es una TRAMPA DE VERIFICACIÓN. Un endpoint que nunca se
desplegó "responde 200", y un chequeo de despliegue que mire solo el código de estado
da verde sobre una ruta que no existe — misma familia que «un deploy fallido sirve la
versión vieja y responde status: ok». Y a un cliente de la Data API un typo en la ruta
le devolvía HTML con 200 en vez de un error accionable.

El defecto vive en el ORDEN DE MONTAJE, no en un handler: por eso estos tests van por
HTTP contra **la app de verdad** —`app.main.app`, con sus ~380 rutas registradas— y no
contra una FastAPI() vacía con el StaticFiles suelto, que es donde el defecto NO se
reproduce (ver test_spa_serving.py, que prueba el motor de caché y el fallback).
"""
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, montar_spa


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """La app REAL con una SPA de mentira montada encima.

    En el CI del backend `frontend/dist` no existe, así que el mount no se hace y sin
    esto el test pasaría en verde contra el código roto: sin catch-all, FastAPI ya
    devuelve 404 por su cuenta. Se monta a mano y se restauran las rutas al salir.
    """
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>SDQ</title>")

    rutas_originales = list(app.router.routes)
    # Si el dist real existe (dev local) ya hay un catch-all montado: sacarlo, o el
    # nuestro quedaría detrás y nunca se ejercería.
    app.router.routes[:] = [r for r in rutas_originales if getattr(r, "name", None) != "frontend"]
    montar_spa(app, str(dist))
    try:
        yield TestClient(app)
    finally:
        app.router.routes[:] = rutas_originales


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/operations/no-existe-xyz",
        "/api/v1/no-existe-el-modulo/nada",
        "/api/data/v1/no-existe",  # el contrato público tiene su propio prefijo
        "/api/",
        "/api",
    ],
)
def test_ruta_de_api_inexistente_devuelve_404_json(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 404, f"{path} → {r.status_code} (¿lo atrapó la SPA?)"
    assert r.headers["content-type"].startswith("application/json"), r.headers["content-type"]
    assert "no encontrada" in r.json()["detail"].lower()


def test_no_solo_el_GET(client: TestClient) -> None:
    """Un POST a una ruta de API inexistente tampoco es asunto de la SPA."""
    for metodo in (client.post, client.put, client.delete, client.patch):
        r = metodo("/api/v1/operations/no-existe-xyz")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")


def test_la_ruta_de_api_registrada_conserva_su_error(client: TestClient) -> None:
    """Lo que SÍ existe sigue contestando lo suyo: 401 JSON, no el 404 nuevo."""
    r = client.get("/api/v1/operations/fuentes")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")


def test_la_data_api_registrada_conserva_su_error(client: TestClient) -> None:
    """El contrato público máquina-a-máquina no cambia de comportamiento."""
    r = client.get("/api/data/v1/catalog")
    assert r.status_code in (401, 403), r.status_code
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("path", ["/", "/banking-score", "/datos/operaciones", "/a/b/c/d"])
def test_las_rutas_del_frontend_siguen_sirviendo_el_index(client: TestClient, path: str) -> None:
    """BrowserRouter: un deep link del frontend recibe el shell y el router se encarga."""
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_un_asset_faltante_sigue_dando_404(client: TestClient) -> None:
    r = client.get("/assets/no-existe.js")
    assert r.status_code == 404


# ── Una ruta que SÍ existe, pedida con otro método: 405, no 404 ──────────────────
#
# El mount de la SPA gana el match antes de que el router ofrezca su 405, así que el primer
# arreglo respondía «Ruta no encontrada» también sobre rutas reales pedidas con el método
# equivocado. Ese 404 manda a buscar algo que está ahí.


@pytest.mark.parametrize(
    "metodo,path,admitido",
    [
        ("get", "/api/v1/auth/login", "POST"),
        # con parámetros de path: el router tiene que reconocerla igual
        ("get", "/api/v1/products/construction/deep_dive/activate", "POST"),
        ("delete", "/api/v1/operations/fuentes", "GET"),
    ],
)
def test_ruta_existente_con_otro_metodo_devuelve_405_con_Allow(
        client: TestClient, metodo: str, path: str, admitido: str) -> None:
    r = getattr(client, metodo)(path)
    assert r.status_code == 405, f"{metodo.upper()} {path} → {r.status_code}"
    assert r.headers["content-type"].startswith("application/json")
    # `Allow` lo exige el estándar en un 405, y es lo que le dice al cliente qué hacer.
    assert admitido in r.headers.get("allow", ""), r.headers.get("allow")
    detalle = r.json()["detail"]
    assert "no permitido" in detalle.lower() and admitido in detalle
    assert "no encontrada" not in detalle.lower()


def test_el_metodo_correcto_sigue_llegando_al_handler(client: TestClient) -> None:
    """El 405 no puede tragarse la ruta buena: POST sin cuerpo llega y lo valida el handler."""
    r = client.post("/api/v1/auth/login", json={})
    assert r.status_code == 422, r.status_code
