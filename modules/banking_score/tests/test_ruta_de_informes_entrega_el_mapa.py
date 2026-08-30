"""El `full_rating` que sale POR HTTP trae el mapa sectorial — no solo el motor.

Por qué este archivo es de RUTA y no de motor. `POST /{bank_id}/generate` arma su
`scoring_result` **a mano** desde el `RatingResult`: no usa el snapshot del producto. Todo
dato que se enganche solo del lado de productos llega al Deep Dive y NO al `full_rating`,
que es el SDQ Rating — el documento que efectivamente se entrega al cliente. Van cinco
defectos por esa grieta, y todos tenían el motor probado y en verde.

Así que acá se pide el informe POR HTTP y se comprueba que el contexto que recibió el
generador de narrativas traía el mapa. Es la única forma de que el cableado quede probado:
un test de `posicion_de_la_entidad` no dice nada sobre si la ruta la llama.
"""

from datetime import date

import pytest

from modules.banking_score.models.models import Bank, BankType, CarteraSectorial
from modules.banking_score.reports.narrative import REPORT_SECTIONS
from modules.banking_score.tests.test_api import (
    auth_headers, client, register_and_login, seed_test_bank,
)

CORTE = date(2024, 12, 31)


@pytest.fixture(autouse=True)
def setup_db():
    """Las tablas. El fixture homónimo de `test_api` es `autouse` SOLO en ese archivo: se
    reutiliza su motor en memoria, no su ciclo de vida."""
    from shared.database.base import Base
    from modules.banking_score.tests.test_api import engine
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    from modules.banking_score.tests.test_api import TestSessionLocal
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sembrar_panel(db, bank_id):
    """La entidad y UN competidor en el mismo sector: sin el competidor no hay «resto del
    sistema» y la comparación no existiría, así que el test pasaría por el motivo
    equivocado."""
    otro = Bank(name="Banco Vecino", bank_type=BankType.banca_multiple, is_active=True)
    db.add(otro)
    db.flush()
    db.add(CarteraSectorial(
        bank_id=bank_id, period_end=CORTE, sector="F - CONSTRUCCIÓN",
        provincia="DISTRITO NACIONAL", deuda=100_000_000, vencida=12_000_000,
        vencida_31_90=1_000_000, deuda_con_tasa=100_000_000, tasa_ponderada=14.0))
    db.add(CarteraSectorial(
        bank_id=otro.id, period_end=CORTE, sector="F - CONSTRUCCIÓN",
        provincia="SANTIAGO", deuda=200_000_000, vencida=4_000_000,
        vencida_31_90=200_000, deuda_con_tasa=200_000_000, tasa_ponderada=11.0))
    db.commit()


def test_el_full_rating_declara_la_seccion():
    assert "mapa_sectorial" in REPORT_SECTIONS["full_rating"]


def test_la_RUTA_le_pasa_el_mapa_al_generador(db_session, monkeypatch):
    """El cableado. Se intercepta `generate_report_narratives` para leer el
    `scoring_result` REAL que la ruta construyó."""
    bank = seed_test_bank(db_session)
    _sembrar_panel(db_session, bank.id)
    token = register_and_login(email="ruta-mapa@sdq.do")
    h = auth_headers(token)
    client.post(f"/api/v1/banking-score/{bank.id}/run?period_end=2024-12-31", headers=h)

    visto = {}

    async def _espia(report_type, bank_name, scoring_result, period,
                     benchmarks=None, anuario=None, revision=None):
        visto["scoring_result"] = scoring_result
        return {s: f"Análisis sustantivo de {s} para {bank_name} en {period}."
                for s in REPORT_SECTIONS.get(report_type, ["executive_summary"])}

    monkeypatch.setattr(
        "modules.banking_score.reports.narrative.generate_report_narratives", _espia)
    r = client.post(
        f"/api/v1/banking-score/reports/{bank.id}/generate"
        f"?period_end=2024-12-31&report_type=full_rating", headers=h)
    assert r.status_code in (200, 201), r.text

    mapa = visto.get("scoring_result", {}).get("mapa_sectorial")
    assert mapa, ("la ruta NO le pasó el mapa al generador: la sección saldría con el "
                  "relleno estático y sin la tabla, y nada fallaría")
    fila = mapa["sectores"][0]
    assert fila["sector"] == "F - CONSTRUCCIÓN"
    # Y llega COMPUTADO contra el resto: 12% de mora contra 2% del vecino.
    assert fila["mora_pct"] == 12.0
    assert fila["mora_del_resto_del_sector_pct"] == 2.0
    assert fila["brecha_de_mora_pp"] == 10.0
    assert fila["spread_de_tasa_pp"] == 3.0


def test_sin_desglose_la_ruta_NO_fabrica_un_mapa_vacio(db_session, monkeypatch):
    """Los cortes anteriores al backfill del cubo no tienen desglose. Una tabla de guiones
    se lee como «esta entidad no presta», que es falso."""
    bank = seed_test_bank(db_session)          # sin sembrar `cartera_sectorial`
    token = register_and_login(email="ruta-sin-mapa@sdq.do")
    h = auth_headers(token)
    client.post(f"/api/v1/banking-score/{bank.id}/run?period_end=2024-12-31", headers=h)

    visto = {}

    async def _espia(report_type, bank_name, scoring_result, period,
                     benchmarks=None, anuario=None, revision=None):
        visto["scoring_result"] = scoring_result
        return {s: f"Análisis sustantivo de {s} para {bank_name} en {period}."
                for s in REPORT_SECTIONS.get(report_type, ["executive_summary"])}

    monkeypatch.setattr(
        "modules.banking_score.reports.narrative.generate_report_narratives", _espia)
    r = client.post(
        f"/api/v1/banking-score/reports/{bank.id}/generate"
        f"?period_end=2024-12-31&report_type=full_rating", headers=h)
    assert r.status_code in (200, 201), r.text
    assert "mapa_sectorial" not in visto.get("scoring_result", {})


def test_una_entidad_SIN_desglose_sigue_pudiendo_emitir_su_SDQ_Rating(db_session):
    """El riesgo que introduce declarar la sección en `full_rating`.

    `full_rating` está entre los tipos que FALLAN CERRADO ante una sección degradada: si se
    le pide al modelo narrar un mapa que no existe, la sección sale hueca y el informe
    entero se aborta con 503. Todos los cortes anteriores al backfill del cubo están en esa
    situación, y también cualquier entidad sin cartera clasificada. El filtro tiene que
    quitar la sección ANTES de pedirla, no después.

    Se comprueba sobre `generate_report_narratives`, que es el punto por el que pasan las
    DOS rutas —la de informes y la de productos—: es donde el filtro protege a ambas."""
    import asyncio
    from modules.banking_score.reports.narrative import generate_report_narratives

    pedidas = []

    async def _falso_motor(*a, **k):
        pedidas.append(k.get("template") or (a[0] if a else None))
        raise AssertionError("no debería llegar acá en este test")

    narr = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        generate_report_narratives(
            report_type="full_rating", bank_name="Banco Sin Cubo",
            scoring_result={"overall_score": 70, "indicators": {}, "sub_components": {}},
            period="2019-12-31"))
    assert "mapa_sectorial" not in narr, (
        "sin desglose la sección NO debe pedirse: `full_rating` falla cerrado ante una "
        "sección hueca, así que el informe entero dejaría de emitirse")
    # Y el resto del informe sí se produce: el filtro quita una sección, no el documento.
    assert "executive_summary" in narr and len(narr) >= 8


class TestElSDQRatingLlevaSuTablaDePares:
    """El §Análisis Comparativo afirmaba «rezagado frente a sus pares» sin imprimir una sola
    tabla de pares: la comparación le quedaba al lector como acto de fe.

    El bloque ya se computaba del lado de PRODUCTOS. Esta ruta no lo pedía, así que las dos
    superficies emitían el mismo documento con distinto contenido — el defecto de siempre.
    """

    def test_la_ruta_le_pasa_el_bloque_de_pares_al_PDF(self, db_session, monkeypatch):
        from modules.banking_score.models.models import Bank as _B
        bank = seed_test_bank(db_session)
        # Un SEGUNDO banco con calificación: `_named_peers` devuelve None con menos de dos,
        # y sin él este test pasaría por el motivo equivocado.
        otro = _B(name="Banco Par", bank_type=BankType.banca_multiple, is_active=True)
        db_session.add(otro)
        db_session.commit()

        token = register_and_login(email="ruta-pares@sdq.do")
        h = auth_headers(token)
        for b in (bank, otro):
            client.post(f"/api/v1/banking-score/{b.id}/run?period_end=2024-12-31", headers=h)

        visto = {}

        async def _espia_pdf(**kw):
            visto.update(kw)
            return "/tmp/no-se-escribe.pdf"

        async def _narrativas(report_type, bank_name, scoring_result, period,
                              benchmarks=None, anuario=None, revision=None):
            return {s: f"Análisis de {s}."
                    for s in REPORT_SECTIONS.get(report_type, ["executive_summary"])}

        monkeypatch.setattr(
            "modules.banking_score.reports.narrative.generate_report_narratives", _narrativas)
        monkeypatch.setattr(
            "modules.banking_score.reports.pdf_generator.generate_pdf_report", _espia_pdf)
        r = client.post(
            f"/api/v1/banking-score/reports/{bank.id}/generate"
            f"?period_end=2024-12-31&report_type=full_rating", headers=h)
        assert r.status_code in (200, 201), r.text

        assert visto.get("peer_block"), (
            "el SDQ Rating sale sin tabla de pares: el comparativo afirma una posición "
            "relativa que el documento no muestra")
        # Y la AMPLITUD, que le da a la tabla de indicadores sus columnas de percentil y
        # tendencia; sin ella salen vacías y nadie lo nota.
        sr = visto["scoring_result"]
        assert "percentiles" in sr and "trayectorias" in sr

    def test_lo_EXCLUSIVO_del_Deep_Dive_no_se_cuela_en_esta_ruta(self, db_session,
                                                                monkeypatch):
        """Las sensibilidades y el entorno macro los declara el catálogo como exclusivos del
        Deep Dive. Subirlos acá sería una decisión comercial, no un arreglo — y se tomaría
        sin que nadie la tomara."""
        bank = seed_test_bank(db_session)
        token = register_and_login(email="ruta-tier@sdq.do")
        h = auth_headers(token)
        client.post(f"/api/v1/banking-score/{bank.id}/run?period_end=2024-12-31", headers=h)

        visto = {}

        async def _espia_pdf(**kw):
            visto.update(kw)
            return "/tmp/no-se-escribe.pdf"

        async def _narrativas(report_type, bank_name, scoring_result, period,
                              benchmarks=None, anuario=None, revision=None):
            return {s: f"Análisis de {s}."
                    for s in REPORT_SECTIONS.get(report_type, ["executive_summary"])}

        monkeypatch.setattr(
            "modules.banking_score.reports.narrative.generate_report_narratives", _narrativas)
        monkeypatch.setattr(
            "modules.banking_score.reports.pdf_generator.generate_pdf_report", _espia_pdf)
        client.post(
            f"/api/v1/banking-score/reports/{bank.id}/generate"
            f"?period_end=2024-12-31&report_type=full_rating", headers=h)
        sr = visto["scoring_result"]
        assert "sensibilidades" not in sr
        assert "entorno_macro" not in sr
