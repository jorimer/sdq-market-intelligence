"""Contrato MOTOR ↔ ROUTER de Perfil SDQ y rankings en pensiones.

**Por qué existe este archivo.** Es el gemelo de
``modules/insurance_intel/tests/test_contrato_perfil_sdq.py``, que existe porque el
2026-08-10 el ``/perfil-sdq`` de seguros devolvió 500 en producción (``KeyError
'pendiente_error_estandar'``) con miles de tests en verde: los del motor llamaban al motor y
los del router usaban un motor simulado, así que nadie cruzaba la frontera.

Pensiones expone el MISMO endpoint y no tenía ni un test con ``TestClient``: la frontera
motor↔router estaba descubierta entera. Es la doctrina repetida del repo — *un guard existe
en un motor y falta en el otro*.

Se cubre además ``/rankings``, que arma su fila con ``{k: p[k] for k in (...)}`` — indexado
DIRECTO, sin ``.get``: exactamente el mismo modo de fallo. Una clave que el router lee y el
motor no escribe ahí no degrada, revienta con 500.

Estos tests no verifican el valor del score (para eso está ``test_perfil_sdq_pensiones.py``,
que llama al motor); verifican que el endpoint RESPONDE y que cada clave que el router
promete existe. Es barato y es exactamente el hueco que se pagó caro.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from shared.auth.dependencies import get_current_user
from shared.auth.models import User  # noqa: F401 — registra el modelo
from shared.data.sipen_client import afp_catalog
from shared.database.base import Base
from shared.database.session import get_db
from shared.indices.freshness import _MENSUAL
from modules.pension_intel.models.models import (  # noqa: F401
    PensionEntity, PensionRating,
)

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)

# ⚠️ `app` es un singleton de módulo: registrar los overrides al importar los deja puestos
# para TODA la sesión de pytest y rompe los tests de otros módulos que declaran los suyos.
# Se ponen y se quitan dentro del fixture, y se restaura lo que hubiera antes.
_USUARIO = lambda: User(email="t@t.do", role="admin",  # noqa: E731
                        full_name="T", password_hash="x")

# Identidades del ROSTER OFICIAL (`shared.data.sipen_client.AFPS`), no inventadas: el ISA
# solo puntúa entidades activas del catálogo y el panel se arma sobre ellas. Con slugs de
# fantasía el test correría contra un panel vacío — el falso verde que se quiere evitar.
# Se resuelven DESDE el roster para que un rename de AFP rompa acá y no en producción.
_ROSTER = dict(afp_catalog())
_POPULAR, _ATLANTICO = "afp_popular", "afp_atlantico"
_JMMB, _ROMANA, _SIEMBRA = "afp_jmmb_bdi", "afp_romana", "afp_siembra"

_CORTE = "2025-04"     # corte del panel
_ATRASADO = "2025-01"  # tres meses atrás ⇒ `stale=True`

# Scores de dimensión del caso REAL que documenta el router: Atlántico y JMMB comparten
# banda "Frágil" en el ISA por razones OPUESTAS.
_DIMS = {
    _POPULAR: {"solvencia": 80.0, "riesgo": 70.0, "rentabilidad": 75.0,
               "costo": 60.0, "escala": 95.0},
    _ATLANTICO: {"solvencia": 55.5, "riesgo": 93.0, "rentabilidad": 7.1,
                 "costo": 40.7, "escala": 12.0},
    _JMMB: {"solvencia": 15.2, "riesgo": 96.1, "rentabilidad": 47.4,
            "costo": 50.4, "escala": 20.0},
    _ROMANA: {"solvencia": 70.0, "riesgo": 88.0, "rentabilidad": 55.0,
              "costo": 65.0, "escala": 5.0},
}


def _breakdown(scores, ausentes=()):
    """La columna JSON `dimensions` con la MISMA forma que emite `compute_isa`.

    `ausentes` marca `present=False` DEJANDO el score puesto: el router filtra por
    `present`, no por `score is not None`, y esa distinción es parte del contrato.
    """
    return [{"key": k, "label": k.title(), "weight": 0.2, "direction": "higher",
             "provenance": "test", "present": k not in ausentes,
             "raw": v, "score": v}
            for k, v in scores.items()]


@pytest.fixture(autouse=True)
def base():
    previos = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _USUARIO
    Base.metadata.create_all(bind=engine)
    db = TestSessionLocal()
    for slug in (_POPULAR, _ATLANTICO, _JMMB, _ROMANA, _SIEMBRA):
        db.add(PensionEntity(slug=slug, name=_ROSTER[slug], afp_code=None, is_active=True))
    for slug, scores in _DIMS.items():
        db.add(PensionRating(
            entity_slug=slug, period=_ATRASADO if slug == _ROMANA else _CORTE,
            overall_score=sum(scores.values()) / len(scores),
            band="Adecuada", coverage=1.0, dimensions=_breakdown(scores),
            model_version="0.1"))
    # Rescore SUPERADO de Popular: mismo slug, corte viejo. `_ranked_ratings` se queda con
    # el último período, así que esta fila no debe aparecer en ninguna de las dos superficies.
    db.add(PensionRating(
        entity_slug=_POPULAR, period="2024-12", overall_score=1.0, band="Frágil",
        coverage=0.4, dimensions=_breakdown({"rentabilidad": 1.0}), model_version="0.1"))
    # AFP sin ninguna dimensión puntuable: el ISA la muestra SIN veredicto. Recorre el
    # camino `None` de rank, posición y banda en ambos endpoints.
    db.add(PensionRating(
        entity_slug=_SIEMBRA, period=_CORTE, overall_score=None, band=None,
        coverage=0.0, dimensions=_breakdown({"rentabilidad": 30.0}, ausentes=("rentabilidad",)),
        model_version="0.1"))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previos)


# Toda clave que el router promete en cada fila del perfil: las que arma él mismo, las que
# escribe el motor (`perfil_panel` / `calcular_ejes`) y las que agrega `annotate_freshness`.
# Si alguien suma una al router sin escribirla en el motor, esto lo dice ANTES del deploy.
_CLAVES_PERFIL = {
    "slug", "name", "period", "isa", "banda_isa",
    "ejecucion", "banda_ejecucion", "cobertura_ejecucion",
    "resiliencia", "banda_resiliencia", "cobertura_resiliencia",
    "dimensiones", "fuera_de_los_ejes",
    "posicion_ejecucion", "posicion_resiliencia",
    "universo", "requiere_posicion_visible",
    "stale", "periods_behind", "period_unit",
}

# `/rankings` indexa DIRECTO (`p[k]`): cada una de estas es un 500 si el motor deja de
# escribirla. Las tres últimas las agrega `annotate_freshness` sobre la fila ya armada.
_CLAVES_RANKING = {
    "rank", "slug", "name", "overall_score", "band", "coverage", "period",
    "stale", "periods_behind", "period_unit",
}


def _perfil():
    r = client.get("/api/v1/pension-intel/perfil-sdq")
    assert r.status_code == 200, r.text
    return r.json()


def _rankings():
    r = client.get("/api/v1/pension-intel/rankings")
    assert r.status_code == 200, r.text
    return r.json()


def test_perfil_sdq_responde_200_y_trae_todas_las_claves():
    payload = _perfil()
    assert set(payload) >= {"perfil", "count", "period_end", "ejes", "metodologia"}
    filas = payload["perfil"]
    assert filas, "panel vacío: el test no probaría nada"
    for fila in filas:
        faltan = _CLAVES_PERFIL - set(fila)
        assert not faltan, f"{fila['slug']}: el router promete claves que el motor no da: {faltan}"


def test_rankings_responde_200_y_trae_todas_las_claves():
    """El indexado directo de `/rankings` no degrada: una clave ausente es un 500."""
    payload = _rankings()
    assert set(payload) >= {"rankings", "count", "period_end", "scale"}
    filas = payload["rankings"]
    assert filas, "ranking vacío: el test no probaría nada"
    assert payload["count"] == len(filas)
    for fila in filas:
        faltan = _CLAVES_RANKING - set(fila)
        assert not faltan, f"{fila['slug']}: el router promete claves que el motor no da: {faltan}"


def test_las_dos_superficies_muestran_el_MISMO_universo():
    """Perfil y ranking se arman del mismo `_ranked_ratings`: si divergen, el documento se
    contradice entre secciones. Una AFP por slug — el rescore viejo de Popular no duplica."""
    perfil = _perfil()
    rankings = _rankings()
    slugs_perfil = [f["slug"] for f in perfil["perfil"]]
    slugs_rank = [f["slug"] for f in rankings["rankings"]]
    assert sorted(slugs_perfil) == sorted(slugs_rank)
    assert len(slugs_perfil) == len(set(slugs_perfil)) == 5
    assert perfil["count"] == rankings["count"] == 5
    # El período que viaja es el ÚLTIMO, no el del rescore superado.
    popular = next(f for f in rankings["rankings"] if f["slug"] == _POPULAR)
    assert popular["period"] == _CORTE and popular["overall_score"] != 1.0


def test_el_nombre_del_roster_viaja_con_el_slug_en_ambas_superficies():
    """El sujeto viaja con el número: el router resuelve el nombre desde `PensionEntity`."""
    for payload, clave in ((_perfil(), "perfil"), (_rankings(), "rankings")):
        nombres = {f["slug"]: f["name"] for f in payload[clave]}
        assert nombres[_ATLANTICO] == _ROSTER[_ATLANTICO] == "AFP Atlántico"
        assert nombres[_JMMB] == _ROSTER[_JMMB]


def test_una_dimension_no_presente_no_entra_a_los_ejes():
    """El router filtra por `present`, no por `score is not None`. Siembra trae un score
    puesto con `present=False`: si el filtro se aflojara, el eje se calcularía sobre un dato
    que el ISA declaró ausente."""
    fila = next(f for f in _perfil()["perfil"] if f["slug"] == _SIEMBRA)
    assert fila["ejecucion"] is None and fila["banda_ejecucion"] is None
    assert fila["resiliencia"] is None and fila["banda_resiliencia"] is None
    assert fila["cobertura_ejecucion"] == 0.0 and fila["cobertura_resiliencia"] == 0.0
    # Sin eje no hay posición: no se la inventa ni se la rellena con el último puesto.
    assert fila["posicion_ejecucion"] is None and fila["posicion_resiliencia"] is None


def test_la_afp_sin_veredicto_aparece_en_el_ranking_SIN_rank():
    """No se oculta (desaparecer sin aviso es peor) ni se la ordena contra las demás."""
    filas = _rankings()["rankings"]
    siembra = next(f for f in filas if f["slug"] == _SIEMBRA)
    assert siembra["overall_score"] is None and siembra["rank"] is None
    ranks = [f["rank"] for f in filas if f["rank"] is not None]
    assert ranks == list(range(1, len(ranks) + 1))
    # Las puntuadas van primero y en orden descendente.
    puntuadas = [f["overall_score"] for f in filas if f["overall_score"] is not None]
    assert puntuadas == sorted(puntuadas, reverse=True)


def test_el_corte_atrasado_se_marca_stale_en_las_dos_superficies():
    """Una AFP que dejó de reportar no puede seguir apareciendo comparable de igual a igual
    (pasó sin avisar en el ISF con Autoseguro)."""
    for payload, clave in ((_perfil(), "perfil"), (_rankings(), "rankings")):
        assert payload["period_end"] == _CORTE
        por_slug = {f["slug"]: f for f in payload[clave]}
        assert por_slug[_ROMANA]["stale"] is True
        assert por_slug[_ROMANA]["periods_behind"] == 3
        assert por_slug[_ROMANA]["period_unit"] == _MENSUAL
        assert por_slug[_POPULAR]["stale"] is False


def test_el_split_separa_dos_fragiles_por_razones_opuestas_END_TO_END():
    """El caso que documenta el router, medido a través del ENDPOINT: que el motor lo
    resuelva no prueba que el router le pase las dimensiones que necesita."""
    filas = {f["slug"]: f for f in _perfil()["perfil"]}
    atlantico, jmmb = filas[_ATLANTICO], filas[_JMMB]
    assert atlantico["resiliencia"] > jmmb["resiliencia"]   # Atlántico es más sólida…
    assert atlantico["ejecucion"] < jmmb["ejecucion"]       # …y rinde mucho peor
    # Escala queda fuera de ambos ejes pero se sigue reportando (decisión auditable, §6.4).
    assert "escala" not in atlantico["dimensiones"]
    assert atlantico["fuera_de_los_ejes"]["escala"] == _DIMS[_ATLANTICO]["escala"]


def test_la_posicion_relativa_viaja_junto_a_la_banda():
    """Regla de N chico (§4.2): el sistema tiene 7 AFP y el umbral es 15, así que la
    marca está siempre puesta — la banda sola engaña con un universo de este tamaño."""
    filas = _perfil()["perfil"]
    assert all(f["universo"] == 5 and f["requiere_posicion_visible"] for f in filas)
    posiciones = sorted(f["posicion_ejecucion"] for f in filas
                        if f["posicion_ejecucion"] is not None)
    assert posiciones == list(range(1, len(posiciones) + 1))
