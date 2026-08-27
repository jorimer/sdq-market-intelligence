"""El barrido que busca el PRÓXIMO falso positivo en la prosa ya generada.

Lo que estos tests protegen es que el barrido no MIENTA, que en un instrumento de este tipo
es fácil: un barrido que no encuentra nada se lee igual que «está todo bien».

  * lo que la regla YA reconoce no vuelve a aparecer — si no, el ranking se llena de lo
    resuelto y tapa lo pendiente;
  * una cita normal («cerró en 96,75 %») NO aparece: si apareciera, el ruido sería la mayoría
    y nadie miraría el ranking;
  * una forma irrealis que la regla no conoce SÍ aparece, que es el motivo entero;
  * y el total cuadra: cifras = reconocidas + con forma + sin forma. Un residuo sin explicar
    invita a suponer que el barrido no leyó todo.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
from shared.observability.barrido_del_guard import barrido_del_guard
from shared.products.models import ProductReportCache


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ProductReportCache.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _informe(db, narrativas, sector="banking", period="2025-12-31"):
    db.add(ProductReportCache(sector_key=sector, tier="deep_dive", scope="x",
                              period=period, lang="es", fingerprint="f",
                              narratives=narrativas))
    db.commit()


#: La frase REAL que mató la Revisión Anual del 2026-08-27, tal como la escribió el modelo.
FRASE_QUE_MATO_UN_INFORME = (
    "El nivel actual, 96.75%, sugiere que la presión no está agotada— la cobertura puede "
    "cruzar por debajo del 100% sin que se requiera un deterioro adicional de gran magnitud.")


def test_encuentra_la_forma_que_la_regla_TODAVIA_no_conoce(db):
    """El caso entero. Con la regla vieja, «puede cruzar» habría salido primero en el
    ranking — días antes de que el dueño perdiera una generación descubriéndolo."""
    _informe(db, {"revision_anual": FRASE_QUE_MATO_UN_INFORME})
    out = barrido_del_guard(db)
    formas = {f["forma"] for f in out["formas"]}
    # Hoy la regla ya reconoce «cruzar», así que la cifra NO llega al ranking…
    assert out["reconocidas_como_umbral"] >= 1
    # …y lo que queda es la cita real del contexto, sin forma irrealis cerca.
    assert "cruzar" not in formas


def test_una_forma_DESCONOCIDA_sube_al_ranking(db):
    """La prueba que importa: una construcción irrealis que la regla no cubre tiene que
    aparecer. Se usa un verbo deliberadamente ajeno a la lista para que el test siga
    teniendo sentido cuando la lista crezca."""
    _informe(db, {"seccion": "el indicador podría desbordar 250% en ese escenario"})
    out = barrido_del_guard(db)
    formas = {f["forma"] for f in out["formas"]}
    assert "desbordar" in formas or "podría" in formas


def test_una_CITA_normal_no_ensucia_el_ranking(db):
    """Si las citas entraran, serían la mayoría y el ranking dejaría de servir."""
    _informe(db, {"s": "La cobertura de provisiones cerró en 96.75% y la mora en 1.96%."})
    out = barrido_del_guard(db)
    assert out["formas"] == []
    assert out["fuera_sin_forma_irrealis"] == 2


def test_el_total_CUADRA(db):
    """cifras = reconocidas + sin forma + las que entraron al ranking. Un residuo sin
    explicar invita a suponer que el barrido no leyó todo."""
    _informe(db, {"a": "si la mora cruza 3% el margen cae",
                  "b": "el ROA fue 0.33% en el año",
                  "c": "el índice podría desbordar 250% con ese shock"})
    out = barrido_del_guard(db)
    en_ranking = sum(1 for _ in out["formas"])
    assert out["cifras_con_unidad"] == 3
    assert out["reconocidas_como_umbral"] + out["fuera_sin_forma_irrealis"] + 1 == 3
    assert en_ranking >= 1


def test_un_corpus_vacio_lo_DECLARA_en_vez_de_parecer_limpio(db):
    """Cero hallazgos sobre cero informes no es «está todo bien». Los contadores lo dicen."""
    out = barrido_del_guard(db)
    assert out["informes_leidos"] == 0
    assert out["cifras_con_unidad"] == 0
    assert out["formas"] == []


def test_acota_por_sector(db):
    _informe(db, {"s": "podría desbordar 250%"}, sector="banking")
    _informe(db, {"s": "podría desbordar 250%"}, sector="law", period="2024-12-31")
    assert barrido_del_guard(db, sector="banking")["informes_leidos"] == 1
    assert barrido_del_guard(db)["informes_leidos"] == 2
