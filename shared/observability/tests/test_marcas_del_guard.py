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


def test_la_frase_viaja_con_la_cifra(db):
    """Sin la frase, «38 %: no coincide» no distingue una invención de una forma derivada.

    Son los dos casos OPUESTOS que este guard confunde, y hasta ahora la única manera de
    verlo era regenerar el informe —88 a 264 s y costo de modelo— y perderlo otra vez.
    """
    f = _fila(db, marcas=["38%: no coincide con ningún valor servido"])
    f.detail = dict(f.detail, guard_fragmentos=[
        {"cifra": "38%: no coincide con ningún valor servido",
         "frase": "…la eficiencia operativa se ubica en 38% de los ingresos…"}])
    db.commit()
    c = marcas_del_guard(db)["cifras"][0]
    assert c["frases"] == ["…la eficiencia operativa se ubica en 38% de los ingresos…"]


def test_dos_frases_distintas_para_la_misma_cifra_se_conservan(db):
    """Repetir la cifra en el mismo sentido es una derivación que falta; usarla para cosas
    distintas es relleno. Colapsarlas a una borraría justo esa diferencia."""
    for frase in ("…margen de 72% sobre ingresos…", "…cobertura del 72% de los depósitos…"):
        f = _fila(db, marcas=["72%: no coincide con ningún valor servido"])
        f.detail = dict(f.detail, guard_fragmentos=[
            {"cifra": "72%: no coincide con ningún valor servido", "frase": frase}])
        db.commit()
    c = marcas_del_guard(db)["cifras"][0]
    assert c["veces"] == 2 and len(c["frases"]) == 2


def test_una_fila_sin_fragmento_no_rompe(db):
    """Las filas anteriores a este cambio no tienen `guard_fragmentos`."""
    _fila(db, marcas=["55%: x"])
    assert marcas_del_guard(db)["cifras"][0]["frases"] == []


# ── La regla de DOS CAPAS, medida en sombra ────────────────────────────

def _con_capa(db, cifra="100%", capa="det", modulo="banking", template="revision_anual"):
    from shared.observability.models import LLMCall
    f = LLMCall(purpose="narrativa", model="m", cost_usd=0.0, module=modulo,
                template=template, cache_hit=False,
                detail={"guard_flags": 1, "guard_marcas": [cifra],
                        "guard_fragmentos": [{"cifra": cifra, "frase": "…texto…",
                                              "capa": capa}]})
    db.add(f)
    db.commit()
    return f


def test_separa_las_marcas_del_REGEX_de_las_que_confirma_el_juez(db):
    """La pregunta que decide la calibración, y que el registro no podía contestar.

    El lazo fusiona `det + llm` para repararlos juntos y el origen se perdía; sin él, «cuántos
    informes murieron por el detector mecánico solo» solo se podía responder con una opinión.
    """
    _con_capa(db, capa="det")
    _con_capa(db, capa="det")
    _con_capa(db, cifra="38%", capa="ambos")
    _con_capa(db, cifra="72%", capa="juez")

    r = marcas_del_guard(db)["regla_de_dos_capas"]
    assert r["publicadas_pese_a_la_marca"] == 2
    assert r["bloquearon_la_entrega"] == 2
    assert r["marcas_con_capa_registrada"] == 4


def test_las_marcas_VIEJAS_no_se_reparten_entre_capas(db):
    """Suponerles una capa sería fabricar el dato que se está midiendo — y el número que sale
    de ahí se usa para decidir si se afloja un guard que protege documentos que se venden."""
    from shared.observability.models import LLMCall
    db.add(LLMCall(purpose="narrativa", model="m", cost_usd=0.0, module="banking",
                   template="banking_summary", cache_hit=False,
                   detail={"guard_flags": 1, "guard_marcas": ["69%"]}))
    db.commit()
    _con_capa(db, capa="ambos")

    r = marcas_del_guard(db)["regla_de_dos_capas"]
    assert r["por_capa"].get("(sin registrar)") == 1
    assert r["marcas_con_capa_registrada"] == 1
    assert r["publicadas_pese_a_la_marca"] == 0


def test_sin_marcas_la_regla_no_finge_un_veredicto(db):
    r = marcas_del_guard(db)["regla_de_dos_capas"]
    assert r["por_capa"] == {}
    assert r["marcas_con_capa_registrada"] == 0
