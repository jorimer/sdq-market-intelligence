"""El contraste y el canal de discrepancias.

Dos cosas se protegen aquí. Que una discrepancia solo se abra cuando se puede DEFENDER
—significancia, no corazonada— porque lo que se abre acaba en la mesa con el proveedor.
Y que el informe del cliente no pueda montarse sobre una conclusión en discusión: esa
exclusión es estructural (``usable_conclusions``), no una frase que alguien vigila.
"""
from types import SimpleNamespace
from typing import Optional

from modules.brand_intel import service as svc
from modules.brand_intel.engines import contrast as ctr
from modules.brand_intel.ingest import conclusions as conc
from modules.brand_intel.models.models import BrandDiscrepancy

WAVES = ["w1", "w2", "w3"]


def _conclusion(direction="sube", slugs=("focal",), metric="favourite_place",
                wave: Optional[str] = None, cid="c-1"):
    return SimpleNamespace(id=cid, direction=direction, subject_slugs=list(slugs),
                           metric_code=metric, wave_code=wave)


def _series(points, slug="focal", metric="favourite_place"):
    """points: [(wave, value, base_n)] ya en orden."""
    return {(slug, metric): points}


# ─────────────────────────── el motor ───────────────────────────

def test_movimiento_significativo_en_la_direccion_afirmada_coincide():
    s = _series([("w1", 30.0, 300), ("w2", 45.0, 300)])
    out = ctr.contrast_conclusion(_conclusion("sube"), s, WAVES)
    assert out.verdict == ctr.COINCIDE


def test_movimiento_significativo_contrario_discrepa():
    """Solo el choque frontal —sube contra baja— abre mesa con el proveedor."""
    s = _series([("w1", 45.0, 300), ("w2", 30.0, 300)])
    out = ctr.contrast_conclusion(_conclusion("sube"), s, WAVES)
    assert out.verdict == ctr.DISCREPA


def test_no_distinguible_de_ruido_es_estable():
    """El proveedor dice estable y los datos no detectan movimiento: coinciden."""
    s = _series([("w1", 30.0, 300), ("w2", 31.0, 300)])
    out = ctr.contrast_conclusion(_conclusion("estable"), s, WAVES)
    assert out.verdict == ctr.COINCIDE


def test_estable_del_proveedor_contra_movimiento_significativo_discrepa():
    s = _series([("w1", 30.0, 300), ("w2", 45.0, 300)])
    out = ctr.contrast_conclusion(_conclusion("estable"), s, WAVES)
    assert out.verdict == ctr.DISCREPA


def test_sube_del_proveedor_contra_ruido_no_es_discrepancia():
    """Bajo el umbral no se puede sostener NI refutar: no se lleva a la mesa."""
    s = _series([("w1", 30.0, 300), ("w2", 31.0, 300)])
    out = ctr.contrast_conclusion(_conclusion("sube"), s, WAVES)
    assert out.verdict == ctr.NO_EVALUABLE


def test_sin_base_no_hay_veredicto():
    """Sin base no hay umbral, y sin umbral no hay nada que defender."""
    s = _series([("w1", 30.0, None), ("w2", 45.0, None)])
    out = ctr.contrast_conclusion(_conclusion("sube"), s, WAVES)
    assert out.verdict == ctr.NO_EVALUABLE


def test_sin_direccion_o_sin_metrica_no_es_contrastable():
    s = _series([("w1", 30.0, 300), ("w2", 45.0, 300)])
    assert ctr.contrast_conclusion(_conclusion(""), s, WAVES).verdict == ctr.NO_EVALUABLE
    assert ctr.contrast_conclusion(_conclusion(metric=None), s, WAVES).verdict == \
        ctr.NO_EVALUABLE


def test_si_alguna_marca_acompana_al_proveedor_no_hay_discrepancia():
    """«A y B suben»: A sube y B baja → la conclusión se sostiene en parte.

    Una objeción a medias no se lleva a la mesa del socio — la discrepancia exige que
    ninguna marca evaluable lo acompañe y al menos una lo contradiga de frente.
    """
    s = {("a", "favourite_place"): [("w1", 30.0, 300), ("w2", 45.0, 300)],
         ("b", "favourite_place"): [("w1", 45.0, 300), ("w2", 30.0, 300)]}
    out = ctr.contrast_conclusion(_conclusion("sube", slugs=("a", "b")), s, WAVES)
    assert out.verdict == ctr.COINCIDE


def test_la_ola_nombrada_manda_sobre_la_ultima():
    """La conclusión comenta SU ola: el movimiento juzgado es w2 vs w1, no w3 vs w2."""
    s = _series([("w1", 30.0, 300), ("w2", 45.0, 300), ("w3", 30.0, 300)])
    out = ctr.contrast_conclusion(_conclusion("sube", wave="w2"), s, WAVES)
    assert out.verdict == ctr.COINCIDE           # w3 vs w2 habría dado DISCREPA


# ─────────────────────── el canal en el servicio ───────────────────────

def _store(db, engagement, claim, direction="baja", metric="favourite_place",
           wave_label="Ola 2"):
    conc.store_conclusions(db, str(engagement.id), [conc.Conclusion(
        claim=claim, page_number=19, kind="hallazgo", subjects=("Focal",),
        topic="", metric_code=metric, direction=direction,
        wave_label=wave_label, confident=True,
    )])
    db.flush()


def test_el_contraste_abre_discrepancia_solo_donde_puede_defenderla(db, engagement):
    # Fixture real: favourite_place de focal va 30 → 32 con base 300 (no significativo).
    # "baja" contra ruido no abre mesa; "estable" coincide.
    _store(db, engagement, "Focal pierde preferencia de forma sostenida.", "baja")
    out = svc.contrast_conclusions(db, str(engagement.id))
    db.flush()

    assert out["discrepan"] == 0
    assert db.query(BrandDiscrepancy).count() == 0


def test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement):
    from modules.brand_intel.models.models import BrandObservation, BrandWave

    # Se fabrica un movimiento significativo real: 30 → 60 con base 300.
    w2 = (db.query(BrandWave).filter(BrandWave.engagement_id == engagement.id,
                                     BrandWave.code == "w2").one())
    obs = (db.query(BrandObservation)
           .filter(BrandObservation.engagement_id == engagement.id,
                   BrandObservation.wave_id == w2.id,
                   BrandObservation.brand_slug == "focal",
                   BrandObservation.metric_code == "favourite_place").one())
    obs.value = 60.0
    db.flush()

    _store(db, engagement, "Focal pierde preferencia de forma sostenida.", "baja")
    out = svc.contrast_conclusions(db, str(engagement.id))
    db.flush()

    assert out["discrepan"] == 1
    d = db.query(BrandDiscrepancy).one()
    assert d.status == "abierta"
    assert d.claim == "Focal pierde preferencia de forma sostenida."
    assert d.page_number == 19                    # el recibo viaja copiado
    assert d.provider_direction == "baja"


def test_correr_el_contraste_dos_veces_no_duplica_la_mesa(db, engagement):
    test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement)
    svc.contrast_conclusions(db, str(engagement.id))
    db.flush()
    assert db.query(BrandDiscrepancy).count() == 1


def test_una_discrepancia_trabajada_no_se_reabre_sola(db, engagement):
    test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement)
    d = db.query(BrandDiscrepancy).one()
    svc.update_discrepancy(db, str(engagement.id), str(d.id),
                           "retirada", "Ipsos usa media móvil; el corte es distinto.",
                           actor="analista@sdq.do")
    db.flush()

    svc.contrast_conclusions(db, str(engagement.id))
    db.flush()
    d = db.query(BrandDiscrepancy).one()
    assert d.status == "retirada"                 # el estado es de la persona


def test_cerrar_sin_nota_se_rechaza(db, engagement):
    test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement)
    d = db.query(BrandDiscrepancy).one()
    import pytest
    with pytest.raises(ValueError):
        svc.update_discrepancy(db, str(engagement.id), str(d.id),
                               "acordada", "", actor="analista@sdq.do")


# ───────────────── la garantía estructural del informe ─────────────────

def test_una_conclusion_en_discusion_no_llega_al_redactor(db, engagement):
    test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement)

    usable = svc.usable_conclusions(db, str(engagement.id))
    assert usable == []                           # la única conclusión está bloqueada


def test_retirar_la_objecion_devuelve_la_conclusion_al_informe(db, engagement):
    test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement)
    d = db.query(BrandDiscrepancy).one()
    svc.update_discrepancy(db, str(engagement.id), str(d.id),
                           "retirada", "Se revisó el corte con Ipsos.",
                           actor="analista@sdq.do")
    db.flush()

    assert len(svc.usable_conclusions(db, str(engagement.id))) == 1


def test_discutida_sigue_bloqueando(db, engagement):
    test_una_discrepancia_defendible_se_abre_con_la_conclusion_copiada(db, engagement)
    d = db.query(BrandDiscrepancy).one()
    svc.update_discrepancy(db, str(engagement.id), str(d.id),
                           "discutida", None, actor="analista@sdq.do")
    db.flush()

    assert svc.usable_conclusions(db, str(engagement.id)) == []
