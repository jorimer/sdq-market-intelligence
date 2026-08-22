"""Unir dos cuotas NO es sumarlas, y este test existe porque sumarlas costó un indicador.

El 3.20 de la END pide la participación dominicana en las exportaciones mundiales de
productos agropecuarios. «Agropecuarios» no es una categoría que el emisor publique: es la
unión de alimentos y materias primas agrícolas. La primera evaluación sumó las dos CUOTAS
—0,1183% + 0,0169% = 0,1352%— y descartó el indicador con un Δ del 39% contra la línea base.

El número era inválido, no bajo. Cada cuota tiene su propio denominador mundial, así que su
suma no es la cuota de nada. Unidas por NIVELES la ventana da 0,0994% contra una base legal
de 0,097: Δ 2,4%.

El error es aritmético y silencioso —produce un número plausible— así que la única defensa es
un test que lo distinga. Los datos de acá están elegidos para que las dos formas den
resultados MUY distintos: si alguien vuelve a sumar cuotas, este test se pone rojo.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.social_dev.models.models import SocialIndicator
from modules.social_dev import social_sync as S


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


#: Un mercado GRANDE donde el país pesa poco y uno CHICO donde pesa mucho. Es la forma que
#: hace divergir las dos aritméticas: la cuota grande domina la unión por niveles, y la suma
#: de cuotas la infla con un porcentaje que se calculó sobre otro denominador.
EXPORT_PAIS, EXPORT_MUNDO = 1000.0, 100000.0
COMP = {
    # código: (% de las exportaciones del país, % de las del mundo)
    "GRANDE": (90.0, 80.0),      # país 900 · mundo 80.000 → cuota 1,125%
    "CHICA": (10.0, 0.5),        # país 100 · mundo    500 → cuota 20,0%
}
# Unión por NIVELES: (900 + 100) / (80.000 + 500) = 1,2422%
UNION_CORRECTA = (900.0 + 100.0) / (80000.0 + 500.0) * 100
# Suma de CUOTAS, el error: 1,125 + 20,0 = 21,125% — diecisiete veces más.
SUMA_DE_CUOTAS = 1.125 + 20.0


def _stub_fetch(code, paises, mrv=None, **kw):
    pais = paises[0]
    if code == "TX.VAL.MRCH.CD.WT":
        v = EXPORT_PAIS if pais == "DOM" else EXPORT_MUNDO
    else:
        p, m = COMP[code]
        v = p if pais == "DOM" else m
    return [{"date": "2007", "value": v}], None


def _correr(db, monkeypatch, composiciones):
    monkeypatch.setattr("shared.data.wdi_client.fetch_wb_indicator", _stub_fetch)
    monkeypatch.setattr(S, "PARTICIPACION_EXPORTADORA",
                        {"X": ("world_export_share_test", composiciones, "%")})
    S._sync_participacion_exportadora(db, lambda _p: None)
    fila = db.query(SocialIndicator).filter_by(theme="world_export_share_test").one()
    return fila.value


def test_dos_composiciones_se_unen_por_NIVELES_no_sumando_cuotas(db, monkeypatch):
    valor = _correr(db, monkeypatch, ("GRANDE", "CHICA"))
    assert valor == pytest.approx(UNION_CORRECTA, rel=1e-9)
    assert valor != pytest.approx(SUMA_DE_CUOTAS, rel=1e-3), (
        "se sumaron las cuotas: cada una tiene su propio denominador mundial y su suma no "
        "es la cuota de nada")


def test_los_dos_metodos_divergen_de_verdad_en_este_fixture():
    """El contrapeso: si los datos hicieran coincidir las dos aritméticas, el test de arriba
    pasaría sin probar nada."""
    assert abs(SUMA_DE_CUOTAS - UNION_CORRECTA) / UNION_CORRECTA > 10


def test_una_sola_composicion_sigue_dando_la_cuota_de_esa_categoria(db, monkeypatch):
    """El camino del 3.19 no cambió al generalizar a varias composiciones."""
    assert _correr(db, monkeypatch, ("GRANDE",)) == pytest.approx(900.0 / 80000.0 * 100)


def test_sin_composicion_es_la_cuota_del_total(db, monkeypatch):
    """El camino del 3.18: sin recorte, país sobre mundo."""
    assert _correr(db, monkeypatch, ()) == pytest.approx(EXPORT_PAIS / EXPORT_MUNDO * 100)


def test_el_3_20_declara_sus_DOS_composiciones():
    """Si alguien lo reduce a una, el indicador vuelve a medir media categoría."""
    _tema, comps, _u = S.PARTICIPACION_EXPORTADORA["3.20"]
    assert set(comps) == {"TX.VAL.FOOD.ZS.UN", "TX.VAL.AGRI.ZS.UN"}
