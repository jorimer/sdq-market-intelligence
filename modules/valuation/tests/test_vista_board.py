"""La vista board: el spread abre, el valor sigue, y los cinco puntos son INVARIANTES.

**Por qué los cinco puntos se testean en vez de puntuarse.** La barra de insight es la
rúbrica que la casa aplica a la prosa de IA —postura, mecanismo, asimetría, falsabilidad,
decisión—. Este eje **computa** su prosa, así que los cinco dejan de depender de que un modelo
los acierte y pasan a ser propiedades del texto que un test puede exigir. Es una garantía más
fuerte, no más débil.

**Y el orden es la decisión de producto.** El resumen ejecutivo abre con `ROE − Ke`, no con el
valor: un consejo que ve el spread entiende la palanca; uno que ve solo el valor discute el
supuesto.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.models.models import MacroSeries
from modules.valuation import narrativa
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.service import a_payload, historia_de, valuar_entidad
from shared.auth.models import User  # noqa: F401 — registra la tabla para las FK
from shared.database.base import Base

BANCO = "banco-de-prueba"
CURVA = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
         ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    for p, v in CURVA:
        s.add(MacroSeries(series_code=SERIE_RF, period=p, value=v))
    s.commit()
    yield s
    s.close()


def _entidad(db, *, roe_objetivo: float, nombre="Banco de Prueba"):
    """Siembra una entidad cuyo ROE sobre patrimonio de APERTURA sea el pedido."""
    from modules.banking_score.models.models import Bank, BankingData, BankType, DataSource

    db.add(Bank(id=BANCO, name=nombre, bank_type=BankType.banca_multiple))
    from datetime import date

    # El patrimonio CRECE, que es lo que hace distinguibles las dos bases: con patrimonio
    # constante, ROE sobre apertura y sobre cierre dan lo mismo y el test no probaría nada.
    patrimonios = [1_000_000.0 * (1.06 ** i) for i in range(5)]
    # Cuatro cortes por año con utilidad ACUMULADA del ejercicio (como publica la SIB). La
    # utilidad del año se fija sobre la APERTURA (el diciembre anterior), de modo que el ROE
    # de doce meses sobre apertura sea exactamente `roe_objetivo` en cada diciembre.
    from modules.valuation.tests._siembra import sembrar_trimestres
    sembrar_trimestres(db, BANCO, patrimonio_diciembre=patrimonios,
                       anios=(2022, 2023, 2024, 2025, 2026), roe_anual_pct=roe_objetivo)
    db.commit()
    return nombre


# ── el orden: el spread ABRE ────────────────────────────────────────────────────────


def test_el_payload_pone_el_spread_ANTES_que_el_valor(db):
    _entidad(db, roe_objetivo=20.0)
    lec = valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba")
    claves = list(a_payload(lec))
    assert claves.index("spread") < claves.index("valor"), (
        "el valor aparece antes que el spread: quien lea de arriba hacia abajo discute el "
        "supuesto en vez de entender la palanca")


def test_la_PRIMERA_frase_del_resumen_es_el_veredicto_no_el_valor(db):
    _entidad(db, roe_objetivo=20.0)
    lec = valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba")
    parrafos = narrativa.resumen_del_spread(lec).split("\n\n")
    primera = parrafos[0]
    # El veredicto nombra la ENTIDAD y el spread; la asimetría habla de múltiplos sobre el
    # libro. Distinguirlos es lo que hace que este test detecte un reordenamiento — una
    # aserción que solo buscara la palabra «valor» pasaría con los párrafos al revés.
    assert "spread" in primera.lower() and "%" in primera
    assert "extremo favorable" not in primera and "× su libro" not in primera, (
        "el resumen abre con la asimetría de múltiplos: eso es el valor, no la lectura")
    assert "extremo favorable" in "\n\n".join(parrafos[1:]), (
        "la asimetría desapareció del texto en vez de moverse después")


# ── los cinco puntos, como invariantes ──────────────────────────────────────────────


@pytest.mark.parametrize("roe", [20.0, 4.0])
def test_el_resumen_cumple_los_CINCO_puntos(db, roe):
    """Se prueba con una entidad que crea valor y con otra que lo destruye: un texto que
    solo cumpliera los cinco en el caso favorable no sirve."""
    _entidad(db, roe_objetivo=roe)
    lec = valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba")
    t = narrativa.resumen_del_spread(lec)
    parrafos = t.split("\n\n")
    assert len(parrafos) >= 5, "faltan párrafos: los cinco puntos no pueden compartir uno"
    # 1 POSTURA: hay un veredicto, no una descripción.
    assert any(w in parrafos[0].lower() for w in ("crea valor", "destruyendo", "respuesta única"))
    # 2 MECANISMO: nombra el canal causal.
    assert "por encima de lo que su capital exige" in t
    # 3 ASIMETRÍA: cuantifica los dos extremos.
    assert "extremo favorable" in t and "adverso" in t and "×" in t
    # 4 FALSABILIDAD: dice qué cambiaría la lectura.
    assert "cambiaría la lectura" in t or "resolvería la ambigüedad" in t
    # 5 DECISIÓN: conecta con lo que la audiencia decide.
    assert "qué supuesto habría" in t
    assert "recomendación de comprar o vender" in t


def test_el_texto_NO_recomienda_comprar_ni_vender(db):
    _entidad(db, roe_objetivo=20.0)
    lec = valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba")
    t = narrativa.resumen_del_spread(lec).lower()
    for prohibido in ("recomendamos comprar", "recomendamos vender", "conviene comprar"):
        assert prohibido not in t


# ── el caso incómodo ────────────────────────────────────────────────────────────────


def test_cuando_el_spread_cruza_el_cero_el_texto_lo_DICE_primero(db):
    """Es el hallazgo del eje: la entidad no tiene respuesta única. Promediar los extremos
    para dar un veredicto sería esconder justamente lo que hay que informar."""
    _entidad(db, roe_objetivo=17.0)      # cae dentro del rango de Ke
    lec = valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba")
    if not lec.cambia_de_signo:
        pytest.skip("el ROE sembrado no cayó dentro del rango de Ke en esta curva")
    primera = narrativa.resumen_del_spread(lec).split("\n\n")[0]
    assert "no tiene una respuesta única" in primera
    assert "hallazgo" in primera


def test_destruir_valor_exige_que_el_spread_sea_negativo_en_TODO_el_rango(db):
    """Si cruza el cero, la respuesta honesta no es «destruye» sino «depende»."""
    _entidad(db, roe_objetivo=4.0)
    lec = valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba")
    assert lec.destruye_valor is (lec.spread_alto_pp < 0)


# ── el ROE, sobre apertura ──────────────────────────────────────────────────────────


def test_el_ROE_de_la_historia_va_sobre_patrimonio_de_APERTURA(db):
    _entidad(db, roe_objetivo=15.0)
    h = historia_de(db, BANCO)
    assert h.roe_pct, "no se computó ningún ROE"
    # En cada DICIEMBRE, sobre APERTURA da exactamente el objetivo; sobre CIERRE daría
    # 15/1,06 = 14,15 %.
    diciembres = {p: r for p, r in zip(h.periodos_con_roe, h.roe_pct) if p.endswith("-12-31")}
    assert diciembres and all(r == pytest.approx(15.0, abs=1e-6) for r in diciembres.values())
    i = h.periodos.index("2023-12-31")
    util = h.utilidad[i]
    assert util is not None
    sobre_cierre = util / h.patrimonio[i] * 100.0
    assert sobre_cierre < 14.5, (
        "el fixture no distingue las dos bases: con patrimonio constante, ROE sobre "
        "apertura y sobre cierre dan lo mismo y el test no prueba nada")
    # El primer AÑO no tiene apertura de doce meses: sus cuatro cortes no tienen ROE. Se
    # declaran con cuatro cortes menos en vez de inventarles una base.
    assert len(h.roe_pct) == len(h.patrimonio) - 4
    assert not any(p.startswith("2022") for p in h.periodos_con_roe)


def test_sin_dos_cierres_no_se_valua_y_se_dice(db):
    """`None`, no un esqueleto con ceros."""
    from datetime import date

    from modules.banking_score.models.models import Bank, BankingData, BankType, DataSource

    db.add(Bank(id="solo-uno", name="Uno Solo", bank_type=BankType.banca_multiple))
    db.add(BankingData(bank_id="solo-uno", period_end=date(2026, 12, 31),
                       patrimonio_tecnico=1000.0, utilidad_neta=100.0,
                       source=DataSource.sib_api))
    db.commit()
    assert valuar_entidad(db, bank_id="solo-uno", nombre="Uno Solo") is None


# ── la procedencia viaja ────────────────────────────────────────────────────────────


def test_el_payload_declara_cuanto_es_RUBRICA(db):
    _entidad(db, roe_objetivo=20.0)
    p = a_payload(valuar_entidad(db, bank_id=BANCO, nombre="Banco de Prueba"))
    pr = p["procedencia"]
    assert 0.0 < pr["fraccion_de_rubrica"] < 1.0
    assert pr["retencion_supuesta"] and len(pr["retencion_evidencia"]) > 80, (
        "la retención es un supuesto que gobierna el terminal: tiene que viajar con su motivo")
