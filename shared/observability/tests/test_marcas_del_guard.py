"""Las marcas del guard se pueden CONSULTAR, no solo encontrar por casualidad.

Los dos falsos vetos de agosto de 2026 —«69 %» por redondeo y «132 %», que era la razón 1,32
servida— se descubrieron porque el dueño los vio en pantalla: un informe roto por cada dato
que ya estaba en la base. El patrón vivía en un `logger.warning`, que no es evento de Sentry,
y en un contador que dice cuántas marcas hubo pero no cuáles.

Lo que se protege acá es que la consulta responda la pregunta que importa: **¿esta cifra se
repite?** Una que reaparece entre ejes y períodos es la firma de un falso positivo estructural;
una que aparece sola es lo que el guard vino a atrapar.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
from shared.observability.marcas_del_guard import marcas_del_guard
from shared.observability.models import LLMCall


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[LLMCall.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _fila(db, *, marcas=None, flags=None, module="banking_score", template="banking_risk",
          dias=0):
    detalle = {"truncada": False}
    if marcas is not None:
        detalle["guard_marcas"] = marcas
        detalle["guard_flags"] = len(marcas)
    if flags is not None:
        detalle["guard_flags"] = flags
    f = LLMCall(purpose="narrativa", model="m", cost_usd=0.1, module=module,
                template=template, cache_hit=False, detail=detalle)
    f.created_at = datetime.now(timezone.utc) - timedelta(days=dias)
    db.add(f)
    db.commit()
    return f


def test_agrupa_por_CIFRA_para_que_la_repeticion_se_vea(db):
    """Es la propiedad entera: la misma cifra en dos ejes es un falso positivo estructural."""
    _fila(db, marcas=["132%: no coincide con ningún valor servido"], module="banking_score")
    _fila(db, marcas=["132%: no coincide con ningún valor servido"], module="insurance",
          template="insurance_risk")
    _fila(db, marcas=["7,4%: no coincide con ningún valor servido"])

    out = marcas_del_guard(db)
    top = out["cifras"][0]
    assert top["cifra"] == "132%"
    assert top["veces"] == 2
    assert top["modulos"] == ["banking_score", "insurance"], "la repetición cruza ejes"
    assert [c["cifra"] for c in out["cifras"]] == ["132%", "7,4%"], "ordenado por frecuencia"


def test_una_narrativa_LIMPIA_no_ensucia_el_conteo(db):
    _fila(db, marcas=["132%: x"])
    _fila(db)  # sin marcas ni flags
    out = marcas_del_guard(db)
    assert out["narrativas_generadas"] == 2
    assert out["narrativas_con_marca"] == 1


def test_una_fila_VIEJA_con_contador_y_sin_texto_se_cuenta_y_se_declara(db):
    """`guard_flags` existe desde antes que `guard_marcas`.

    Si esas filas se ignoraran, un total bajo se leería como «no pasó nada» cuando en
    realidad es «no lo estábamos guardando» — el mismo modo de falla que `stale=null`.
    """
    _fila(db, flags=2)
    out = marcas_del_guard(db)
    assert out["narrativas_con_marca"] == 1
    assert "sin detalle" in out["cifras"][0]["cifra"] + out["cifras"][0]["ejemplo"]


def test_el_rango_por_defecto_deja_fuera_lo_viejo(db):
    _fila(db, marcas=["132%: x"], dias=0)
    _fila(db, marcas=["999%: x"], dias=45)
    cifras = {c["cifra"] for c in marcas_del_guard(db)["cifras"]}
    assert cifras == {"132%"}


def test_se_puede_acotar_a_un_eje(db):
    _fila(db, marcas=["132%: x"], module="banking_score")
    _fila(db, marcas=["55%: x"], module="insurance")
    out = marcas_del_guard(db, modulo="insurance")
    assert [c["cifra"] for c in out["cifras"]] == ["55%"]


def test_los_HIT_de_cache_no_se_cuentan(db):
    """Un HIT no generó texto: contarlo inflaría la marca por cada vista del mismo informe."""
    f = _fila(db, marcas=["132%: x"])
    f.cache_hit = True
    db.commit()
    assert marcas_del_guard(db)["cifras"] == []
