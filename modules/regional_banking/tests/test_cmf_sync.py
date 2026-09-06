"""El sync de Chile: qué persiste, y —sobre todo— que el dato LLEGUE al modelo.

**Por qué el test llega hasta el contexto y no se queda en la tabla.** En T-BR-8 el tipo de
informe quedó registrado en sus treinta superficies y las secciones regionales igual salieron
por el caso genérico: el dato nunca llegó al modelo. Se había verificado el REGISTRO, no la
ALIMENTACIÓN. Persistir una fila y comprobar que la fila existe no prueba nada sobre el
documento; lo que hay que exigir es que el bloque del país aparezca en el contexto que el
modelo efectivamente ve.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401
from modules.regional_banking.ai_context import (
    ComparacionNoArmonizada,
    contexto_armonizado,
    contexto_por_sistema,
    exigir_comparable,
)
from modules.regional_banking.cmf_sync import cmf_sync
from modules.regional_banking.models.models import CountryBankingAggregate
from shared.data.cmf_client import INDICADORES, CMFClient
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    yield sesion
    sesion.close()


def _sync(db):
    return cmf_sync(db, client=CMFClient(mode="fixture"))


# ── Persistencia ──────────────────────────────────────────────────
def test_persiste_con_la_norma_chilena(db):
    resumen = _sync(db)
    assert resumen["synced"] > 0 and not resumen["errors"]
    assert resumen["country"] == "CHL"
    normas = {f.norma_contable for f in db.query(CountryBankingAggregate).all()}
    assert normas == {"CMF Chile — Compendio de Normas Contables 2022"}


def test_persiste_los_ONCE_indicadores(db):
    _sync(db)
    metricas = {f.metric for f in db.query(CountryBankingAggregate)
                .filter_by(iso_code="CHL").all()}
    assert metricas == set(INDICADORES.values())


def test_resincronizar_actualiza_y_no_duplica(db):
    """La clave única es (país, corte, métrica, fuente). Un sync mensual pisa lo suyo."""
    _sync(db)
    antes = db.query(CountryBankingAggregate).count()
    _sync(db)
    assert db.query(CountryBankingAggregate).count() == antes


def test_la_derivacion_es_VERBATIM_y_no_derived(db):
    """El emisor publica el ratio calculado; nosotros lo copiamos. Colombia es al revés —ahí
    el agregado lo computamos— y de esa distinción depende a qué alcanza la cuarentena por
    licencia restrictiva. Declararlo mal sería declarar de MENOS una obligación."""
    _sync(db)
    assert {f.meta["derivacion"] for f in db.query(CountryBankingAggregate).all()} \
        == {"verbatim"}


# ── Que el dato LLEGUE al modelo, no solo a la tabla ──────────────
def test_el_bloque_de_CHILE_llega_al_contexto_del_modelo(db):
    """El cierre de T-CL-2. Que la fila esté en la base no significa que el boletín la vea."""
    _sync(db)
    ctx = contexto_por_sistema(db)
    bloques = {b["iso3"]: b for b in ctx["bloques_por_pais"]}
    assert "CHL" in bloques, (
        "Chile se persistió y NO llegó al contexto: la sección saldría por el caso genérico "
        "y nadie vería un error, que es exactamente lo que pasó en T-BR-8")
    chile = bloques["CHL"]
    assert chile["pais"] == "Chile"
    assert chile["norma_contable"] == ["CMF Chile — Compendio de Normas Contables 2022"]
    assert {s["metrica"] for s in chile["series"]} == set(INDICADORES.values())


def test_cada_cifra_de_chile_llega_con_su_NOMBRE(db):
    """El sujeto viaja con el número. «consumo: 2,39 %» sin nombre se redacta como cualquier
    cosa: el saldo, la mora o la provisión de esa cartera."""
    _sync(db)
    chile = next(b for b in contexto_por_sistema(db)["bloques_por_pais"]
                 if b["iso3"] == "CHL")
    sin_nombre = [s["metrica"] for s in chile["series"] if not s.get("nombre")]
    assert not sin_nombre, f"llegaron sin nombre: {sin_nombre}"
    mora = next(s for s in chile["series"] if s["metrica"] == "mora_90_consumo")
    assert "consumo" in mora["nombre"].lower() and "moros" in mora["nombre"].lower()


def test_chile_NO_entra_en_la_tabla_armonizada(db):
    """Chile no está en EMFA. Si apareciera en §3 estaría comparándose en nivel con países
    que miden otra cosa con el mismo nombre."""
    _sync(db)
    ctx = contexto_armonizado(db)
    # Sin valor por defecto A PROPÓSITO: con `.get("filas", [])` este test pasaba en el
    # vacío, porque la clave se llama `tabla_comparable`. Un contexto que cambie de forma
    # tiene que romper acá, no seguir dando verde sobre una lista que nunca existió.
    isos = {f["iso3"] for f in ctx["tabla_comparable"]}
    assert "CHL" not in isos


# ── El guard, ejercitado CON Chile ────────────────────────────────
def test_el_guard_LEVANTA_si_alguien_pone_a_chile_al_lado_de_otro_pais(db):
    """El guard existía, pero nunca había corrido con Chile adentro. Un guard que no se
    ejercitó con el caso nuevo es una hipótesis, no una protección."""
    _sync(db)
    chile = db.query(CountryBankingAggregate).filter_by(iso_code="CHL").first()
    otro = CountryBankingAggregate(
        iso_code="COL", period_end=chile.period_end, metric="morosidad", value=4.2,
        source="SFC Colombia", license="x", norma_contable="CUIF Colombia (SFC)")
    with pytest.raises(ComparacionNoArmonizada, match="CHL"):
        exigir_comparable([chile, otro])


def test_un_solo_pais_no_compara_con_nadie(db):
    """Contraprueba del guard: si levantara siempre, el test de arriba pasaría sin medir."""
    _sync(db)
    filas = db.query(CountryBankingAggregate).filter_by(iso_code="CHL").all()
    assert exigir_comparable(filas) == filas


def test_la_operacion_esta_REGISTRADA(db):
    """Un sync que no se puede disparar no existe. Es la misma regla que la de los tipos de
    informe: se registra en todas sus superficies o desaparece en una de ellas."""
    from shared.operations.service import OPERATIONS

    assert "cmf-chile-sync" in OPERATIONS, (
        f"la operación no está registrada; hay {sorted(OPERATIONS)}. Sin ella el sync no se "
        "puede disparar ni agendar, y el conector queda escrito y muerto")
    op = OPERATIONS["cmf-chile-sync"]
    assert op.default_interval_hours == 720, "el reporte de la CMF es mensual"
