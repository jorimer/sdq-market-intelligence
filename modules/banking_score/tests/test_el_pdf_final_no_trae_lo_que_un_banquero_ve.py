"""Lo que un banquero ve a simple vista en el Deep Dive regenerado, y que el código no frenaba.

Tercera revisión completa del Deep Dive 2025 de Banco Múltiple Santa Cruz en producción
(2026-09-15), con todos los defectos anteriores ya corregidos. Quedaban cinco:

1. «RD\\$28,686 millones»: el modelo escapó el signo de pesos en markdown y el PDF imprimió la
   barra, ocho veces.
2. «calculada en el contexto» y «el contexto de atribución lo califica»: vocabulario del
   sistema filtrado a un documento de cliente.
3. «una mora estresada que ya duplica ampliamente la mediana»: 9,06 sobre 4,78 es 1,9 veces.
   La razón no estaba servida, y el modelo la dedujo mal.
4. «factores intraanuales de calendario»: la estacionalidad vetada, dicha con otras palabras.
5. La metodología decía que la concentración top-10 y el HHI sectorial «no tienen dato en este
   período» mientras el texto citaba las dos cifras: la procedencia se leía del ÚLTIMO período
   del panel (2026-06-30, sin cubo de cartera), no del corte del informe.
"""
import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.narrative.terminos_vetados import terminos_en

from shared.auth.models import User  # noqa: F401 — registra users para las FK
from shared.database.base import Base


# ── 1 · El signo de pesos ─────────────────────────────────────────────────────

def test_el_signo_de_pesos_escapado_no_llega_al_pdf():
    from shared.products.render import _inline

    salida = _inline("la exposición individual más grande, con RD\\$28,686 millones")
    assert "RD$28,686" in salida
    assert "\\" not in salida


# ── 2 · Vocabulario del sistema en un documento de cliente ───────────────────

def test_las_frases_del_contexto_interno_no_llegan_al_texto():
    from shared.narrative.sanitize import strip_meta_commentary

    texto = ("la sobre-representación es de 23.76 puntos porcentuales, calculada en el contexto. "
             "El contexto de atribución lo califica como idiosincrático desfavorable.")
    limpio, quitado = strip_meta_commentary(texto)
    assert "contexto" not in limpio.lower(), limpio
    assert "23.76 puntos porcentuales." in limpio
    assert "La atribución lo califica como idiosincrático desfavorable." in limpio
    assert quitado


def test_contexto_como_palabra_de_la_prosa_no_se_toca():
    from shared.narrative.sanitize import strip_meta_commentary

    texto = "En el contexto macroeconómico actual, la liquidez del sistema se mantiene holgada."
    assert strip_meta_commentary(texto) == (texto, [])


# ── 3 · Un múltiplo que la razón servida no sostiene ─────────────────────────
#
# El veto es CONDICIONAL a la razón servida y lo declara el CONTEXTO del año, que ya la trae:
# «duplica» entra a la lista solo si 'veces_la_mediana_del_resto' no llega a 2. Se juzga con el
# detector general sobre el contexto que la RUTA le entrega al motor.

def _dentro(veces):
    return {"morosidad_estresada": {"cierre": {"disponible": True,
                                               "veces_la_mediana_del_resto": veces}}}


def _contexto_servido(monkeypatch, dentro):
    from modules.banking_score.products import BankingProduct
    from shared.narrative import claude_engine
    from shared.products import ProductSnapshot, ProductTier

    vistos = []

    async def _fake_generate(*, context, template, mode, axis, audience):
        vistos.append(context)
        return SimpleNamespace(text="El año se movió.")

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    snapshot = ProductSnapshot(tier=ProductTier.deep_dive, period="2025",
                               payload={"anio_por_trimestres": dentro},
                               entity_name="Banco Múltiple Santa Cruz")
    asyncio.run(BankingProduct().narratives(ProductTier.deep_dive, snapshot))
    return vistos[0]


def test_duplica_se_veta_si_la_razon_servida_no_llega_a_dos(monkeypatch):
    frase = "una mora estresada que ya duplica ampliamente la mediana del sistema"
    assert terminos_en(_contexto_servido(monkeypatch, _dentro(1.9)), frase)
    assert terminos_en(_contexto_servido(monkeypatch, _dentro(2.3)), frase) == []


def test_cada_multiplo_con_su_umbral(monkeypatch):
    bajo_dos = _contexto_servido(monkeypatch, _dentro(1.9))
    for frase in ("la mora duplicó la mediana", "es el doble de la mediana",
                  "más del doble de la mediana", "triplica la mediana"):
        assert terminos_en(bajo_dos, frase), frase
    bajo_tres = _contexto_servido(monkeypatch, _dentro(2.3))
    assert terminos_en(bajo_tres, "más del triple de la mediana")
    assert terminos_en(bajo_tres, "es el doble de la mediana") == []
    assert terminos_en(_contexto_servido(monkeypatch, _dentro(3.1)), "triplica la mediana") == []


def test_sin_razon_servida_no_se_inventa_un_veto(monkeypatch):
    for dentro in ({"morosidad_estresada": None}, _dentro(None), _dentro(True)):
        ctx = _contexto_servido(monkeypatch, dentro)
        assert terminos_en(ctx, "intensidad estacional"), "los términos fijos se declaran igual"
        assert terminos_en(ctx, "la mora casi duplica la del año anterior") == [], dentro


# ── 4 · La estacionalidad dicha con otras palabras ───────────────────────────

def test_factores_de_calendario_es_la_misma_especulacion(monkeypatch):
    assert terminos_en(
        _contexto_servido(monkeypatch, _dentro(1.9)),
        "respondió a factores intraanuales de calendario o de reconocimiento de ingresos")


# ── 5 · La procedencia se lee AL CORTE del informe ───────────────────────────

def test_la_metodologia_le_pasa_el_corte_a_quien_lo_acepta():
    from shared.products.report_sections import _provenance_md

    vistos = []

    class _Producto:
        sector_key = "banking"

        def variable_signals(self, as_of=None):
            vistos.append(as_of)
            return {"signals": []}

    class _Viejo:
        sector_key = "otro"

        def variable_signals(self):
            vistos.append("sin_corte")
            return {"signals": []}

    _provenance_md(_Producto(), as_of="2025")
    _provenance_md(_Viejo(), as_of="2025")
    assert vistos == ["2025", "sin_corte"]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_banca_declara_la_procedencia_del_corte_y_no_la_del_ultimo_periodo(db):
    from modules.banking_score.models.models import (Bank, BankType, ModelType,
                                                     RatingResult)
    from modules.banking_score.products import BankingProduct

    b = Bank(name="Banco Múltiple Santa Cruz", bank_type=BankType.banca_multiple)
    db.add(b)
    db.flush()
    con_top10 = {"concentracion_top10": {"available": True, "score": 40.0}}
    sin_top10 = {"concentracion_top10": {"available": False}}
    db.add(RatingResult(bank_id=b.id, period_end=dt.date(2025, 12, 31), overall_score=63.5,
                        rating_tier="SDQ-A", model_type=ModelType.deterministic,
                        model_version="1.2", indicator_details=con_top10))
    db.add(RatingResult(bank_id=b.id, period_end=dt.date(2026, 6, 30), overall_score=63.0,
                        rating_tier="SDQ-A", model_type=ModelType.deterministic,
                        model_version="1.2", indicator_details=sin_top10))
    db.commit()

    def _top10(raw):
        return next(s for s in raw["signals"] if s.key == "concentracion_top10")

    prod = BankingProduct(db)
    assert _top10(prod.variable_signals()).real_fraction == 0.0, \
        "la fixture tiene que ejercitar el último período sin dato"
    al_corte = prod.variable_signals(as_of="2025")
    assert _top10(al_corte).real_fraction == 1.0
    assert al_corte["period"] == "2025-12-31"


def test_el_bloque_de_la_estresada_sirve_cuantas_veces_la_mediana(db):
    from modules.banking_score.models.models import Bank, BankType, BankingData
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_al_corte

    corte = dt.date(2025, 12, 31)
    componentes = dict(estresada_vencido_pct=2.34, estresada_cobranza_pct=0.08,
                       estresada_tc31a60_pct=0.0, estresada_reestructurado_rea_pct=2.91,
                       estresada_reestructurado_temporal_pct=0.03, castigos_pct=3.67,
                       estresada_adjudicado_pct=0.02)
    sc = Bank(name="Banco Múltiple Santa Cruz", bank_type=BankType.banca_multiple)
    otros = [Bank(name=f"Banco {i}", bank_type=BankType.banca_multiple) for i in range(3)]
    db.add_all([sc, *otros])
    db.flush()
    db.add(BankingData(bank_id=sc.id, period_end=corte, morosidad_estresada_pct=9.06,
                       **componentes))
    for b, total in zip(otros, (4.0, 4.78, 6.0)):
        db.add(BankingData(bank_id=b.id, period_end=corte, morosidad_estresada_pct=total))
    db.commit()
    bloque = morosidad_estresada_al_corte(db, sc, corte)
    assert bloque["mediana_estresada_del_resto_del_sistema_pct"] == pytest.approx(4.78)
    assert bloque["veces_la_mediana_del_resto"] == pytest.approx(1.9, abs=0.01)
