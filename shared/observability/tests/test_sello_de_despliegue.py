"""El sello de despliegue: QUÉ COMMIT está sirviendo esta réplica.

**El fallo que lo motivó.** Un despliegue falló, la plataforma dejó corriendo el proceso
ANTERIOR, y `/health` siguió respondiendo `status: ok` con la DB en 10 ms — porque el
proceso sano era el viejo. Se verificó producción durante ochenta minutos contra un cambio
que nunca se había desplegado. «Sano» y «sano y viejo» eran indistinguibles desde afuera.

Se detectó solo porque ese cambio agregaba un CAMPO nuevo y visible. Uno que alterara una
cifra existente habría pasado inadvertido, y se habría reportado «verificado en prod».
"""
import pytest

from shared.observability import health


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    for v in health._VARS_COMMIT + health._VARS_RAMA + ("RAILWAY_DEPLOYMENT_ID",):
        monkeypatch.delenv(v, raising=False)


def test_sin_sello_se_DECLARA_que_no_se_puede_afirmar_la_version():
    """Ausente es `None` con su motivo, nunca `"unknown"` ni `"dev"`. Un valor inventado acá
    es PEOR que ninguno: quien lo lea creerá que verificó el commit y no lo hizo."""
    d = health.deployment_stamp()
    assert d["commit"] is None and d["commit_short"] is None
    assert "NO se puede afirmar" in d["nota"]


def test_con_la_variable_de_la_plataforma_se_publica_el_commit(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "ab56fd1e2c3d4f5a6b7c8d9e0f1a2b3c4d5e6f7a")
    monkeypatch.setenv("RAILWAY_GIT_BRANCH", "main")
    d = health.deployment_stamp()
    assert d["commit_short"] == "ab56fd1", "el corto se cotea de un vistazo con git log"
    assert d["branch"] == "main"
    assert d["nota"] is None, "con sello no hay nada que declarar"


def test_el_sello_HORNEADO_en_la_imagen_sirve_si_la_plataforma_no_inyecta(monkeypatch):
    """Las dos vías fallan distinto: la de ejecución depende de que la plataforma inyecte;
    la horneada viaja con la imagen aunque se despliegue a mano o en otro proveedor."""
    monkeypatch.setenv("GIT_COMMIT", "deadbeefcafe")
    assert health.deployment_stamp()["commit_short"] == "deadbee"


def test_una_variable_VACIA_no_cuenta_como_sello(monkeypatch):
    """El `ARG` del Dockerfile tiene default `""`: si nadie lo pasa, la variable EXISTE y
    está vacía. Tratarla como valor publicaría un commit en blanco como si fuera un sello."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "")
    monkeypatch.setenv("GIT_COMMIT", "   ")
    assert health.deployment_stamp()["commit"] is None


def test_las_dos_sondas_llevan_el_sello(monkeypatch):
    """La de liveness TAMBIÉN: es la más barata y la que no toca dependencias, así que es la
    que se consulta para preguntar «¿qué está corriendo?» sin cargar la base."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc1234def")
    assert health.liveness()["deployment"]["commit_short"] == "abc1234"
    _, payload = health.readiness()
    assert payload["deployment"]["commit_short"] == "abc1234"


def test_la_imagen_DECLARA_el_arg_o_el_sello_horneado_no_existe():
    """El código que lee `GIT_COMMIT` no sirve de nada si el Dockerfile no lo hornea: sería
    un guard sin su entrada, que no falla — desaparece, y `/health` diría «sin sello» para
    siempre sin que nadie lo note.

    También exige que el `ARG` vaya DESPUÉS de las capas de dependencias: puesto arriba,
    cambia en cada commit e invalida la caché del build entero."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[3]
    df = (raiz / "infrastructure" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG RAILWAY_GIT_COMMIT_SHA" in df
    assert "ENV GIT_COMMIT=$RAILWAY_GIT_COMMIT_SHA" in df
    assert df.index("ARG RAILWAY_GIT_COMMIT_SHA") > df.index("COPY requirements"), (
        "el ARG del commit va al final: arriba invalida la caché de dependencias en cada "
        "commit y cada build vuelve a instalar todo")
