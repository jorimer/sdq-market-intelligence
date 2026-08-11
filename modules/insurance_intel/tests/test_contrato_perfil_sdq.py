"""Contrato MOTOR ↔ ROUTER de Perfil SDQ en seguros.

**Por qué existe este archivo.** El 2026-08-10 el endpoint `/perfil-sdq` devolvió 500 en
producción con 3.255 tests en verde: la clave nueva se había agregado al motor y al router
pero no a `calcular_ejes`, y ningún test cruzaba la frontera — los del motor llamaban al
motor, los del router usaban un motor simulado. Una clave que el router lee y el motor no
escribe solo se ve levantando la app de verdad contra una base de verdad.

Estos tests no verifican el valor del score; verifican que el endpoint RESPONDE y que cada
clave que el router promete existe. Es barato y es exactamente el hueco que se pagó caro.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from shared.auth.dependencies import get_current_user
from shared.auth.models import User  # noqa: F401 — registra el modelo
from shared.database.base import Base
from shared.database.session import get_db
from modules.insurance_intel.models.models import (  # noqa: F401
    InsuranceEntity, InsuranceSeries,
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
# para TODA la sesión de pytest y rompe los tests de otros módulos que declaran los suyos
# (51 fallos en banking_score la primera vez). Se ponen y se quitan dentro del fixture.
_USUARIO = lambda: User(email="t@t.do", role="admin",  # noqa: E731
                        full_name="T", password_hash="x")

# Nombres del ROSTER OFICIAL, no inventados: `panel_por_aseguradora` agrupa por la identidad
# autorizada y una entidad que no matchea el roster se cae del panel — con slugs de fantasía
# el test pasaría contra un panel vacío, que es exactamente el falso verde que se quiere evitar.
_NOMBRES = {"normal": "Seguros Pepín, S. A.",
            "fronting": "Angloamericana de Seguros, S. A."}
# Slug CANÓNICO con el que sale del panel, que no es el de la entidad cargada: el agrupamiento
# reemplaza la identidad por la del roster. Que estos dos difieran es parte del contrato.
_CANON = {"normal": "pepin", "fronting": "angloamericana"}

_SERIES = {
    "normal": dict(primas_devengadas=1000.0, siniestros_incurridos=550.0,
                   gastos_operativos=300.0, primas_cedidas=300.0,
                   productos_inversion=50.0, ingresos_totales=2000.0,
                   gastos_totales=1800.0, patrimonio=900.0,
                   activos_totales=3000.0, pasivos_totales=2100.0,
                   activos_liquidos=1200.0, reservas_tecnicas=800.0,
                   # Índices OFICIALES (Ley 146-02 Art. 160-162): vienen del feed
                   # de solvencia, no se derivan. Sin ellos la cobertura de
                   # Resiliencia queda en 0.33 y el eje se apaga por otra razón,
                   # y el test afirmaría algo que no probó.
                   indice_solvencia=1.8, indice_liquidez=1.4),
    "fronting": dict(primas_devengadas=1000.0, siniestros_incurridos=1200.0,
                     gastos_operativos=350.0, primas_cedidas=880.0,
                     productos_inversion=50.0, ingresos_totales=2400.0,
                     gastos_totales=2200.0, patrimonio=900.0,
                     activos_totales=3000.0, pasivos_totales=2100.0,
                     activos_liquidos=1200.0, reservas_tecnicas=800.0,
                     indice_solvencia=1.8, indice_liquidez=1.4),
}


@pytest.fixture(autouse=True)
def base():
    previos = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _USUARIO
    Base.metadata.create_all(bind=engine)
    db = TestSessionLocal()
    for slug, vals in _SERIES.items():
        db.add(InsuranceEntity(slug=slug, name=_NOMBRES[slug], entity_type="aseguradora",
                               is_active=True))
        for año in ("2021", "2022", "2023", "2024"):
            for code, v in vals.items():
                db.add(InsuranceSeries(entity_slug=slug, period=año, series_code=code,
                                       value=v, dimension=None))
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previos)


# Toda clave que el router promete en cada fila. Si alguien agrega una al router sin
# escribirla en el motor, este test lo dice ANTES del deploy.
_CLAVES_FILA = {
    "slug", "name", "period", "ejecucion", "banda_ejecucion", "ejecucion_no_publicable",
    "combined_ratio_promedio", "ejercicios", "pendiente_combined",
    "pendiente_error_estandar", "tendencia", "ciclo_comparable", "cesion_promedio",
    "cesion_alta", "resiliencia", "banda_resiliencia", "cobertura_resiliencia",
    "cobertura_suficiente", "dimensiones_resiliencia",
}


def _filas(payload):
    return next(v for v in payload.values() if isinstance(v, list) and v)


def test_perfil_sdq_responde_200_y_trae_todas_las_claves():
    r = client.get("/api/v1/insurance-intel/perfil-sdq")
    assert r.status_code == 200, r.text
    for fila in _filas(r.json()):
        faltan = _CLAVES_FILA - set(fila)
        assert not faltan, f"{fila['slug']}: el router promete claves que el motor no da: {faltan}"


def test_la_cedente_extrema_no_publica_ejecucion_pero_si_resiliencia():
    filas = {f["slug"]: f for f in _filas(client.get(
        "/api/v1/insurance-intel/perfil-sdq").json())}
    fronting = filas[_CANON["fronting"]]
    assert fronting["ejecucion"] is None and fronting["banda_ejecucion"] is None
    assert "cede 88%" in fronting["ejecucion_no_publicable"]
    assert fronting["resiliencia"] is not None
    normal = filas[_CANON["normal"]]
    assert normal["ejecucion"] is not None and normal["ejecucion_no_publicable"] is None


def test_validation_corre_el_cruce_en_vivo():
    r = client.get("/api/v1/insurance-intel/validation")
    assert r.status_code == 200, r.text
    coh = r.json()["coherencia_resultado"]
    assert set(coh) == {"hallazgos", "explicados", "total_evaluadas"}
    # La cedente tiene combined 155% con resultado POSITIVO: es contradicción, pero la
    # compuerta ya la explica ⇒ va a `explicados`, no a `hallazgos` abiertos.
    assert not coh["hallazgos"], coh["hallazgos"]
    assert [e["slug"] for e in coh["explicados"]] == [_CANON["fronting"]]
    assert coh["explicados"][0]["motivo_declarado"]
