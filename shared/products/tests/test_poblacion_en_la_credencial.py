"""REGLA: la POBLACIÓN sobre la que se midió viaja con la cifra de validación.

**El caso.** El Gini de banca se cita desde siempre con su N —«Gini 0,2287 · n=1.693»— y ese N
incluye un **47 % de entidades que no otorgan crédito**: agentes de intermediación cambiaria y
fiduciarias, que además aportan el **63 % de los eventos** del desenlace. No están por
descuido: `banking_score/SPEC.md` §1 define el producto como un *Financial Entity Score* sobre
todo el universo supervisado por la SIB, y entran por diseño.

Pero un lector que ve «Gini · n» entiende «discriminación entre bancos», que no es lo que se
midió. Es la misma forma del defecto que la doctrina ya nombró —el sujeto se reatribuye al más
cercano cuando no viaja con el número— y que publicó «cuatro compañías concentran el 87,1 %»
cuando eran cuatro ramos.

**La regla:** el motor computa su población del propio panel y la credencial la lleva pegada.
Nunca se transcribe: la composición cambia con cada trimestre ingerido, y una cuota escrita a
mano se desincroniza en la primera corrida.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import modules.banking_score.models.models  # noqa: F401 — registra las tablas
import shared.auth.models  # noqa: F401 — destino de la FK
from modules.banking_score.models.models import (
    Bank, BankingData, BankType, ModelType, RatingResult,
)
from modules.banking_score.validation.report import (
    NOTA_POBLACION, SIN_LIBRO_DE_CREDITO, build_backtest_report, poblacion_del_panel,
)
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


P0, P1 = date(2024, 3, 31), date(2024, 6, 30)


def _entidad(db, clave, tipo, evento):
    db.add(Bank(id=clave, name=f"E {clave}", bank_type=tipo))
    for p in (P0, P1):
        db.add(RatingResult(bank_id=clave, period_end=p, overall_score=70,
                            solidez_score=70, model_type=ModelType.deterministic))
    db.add(BankingData(bank_id=clave, period_end=P0, morosidad_pct=2.0, solvencia_pct=15.0,
                       activos_totales=1000, utilidad_neta=1))
    db.add(BankingData(bank_id=clave, period_end=P1, morosidad_pct=5.0 if evento else 2.0,
                       solvencia_pct=15.0, activos_totales=1000, utilidad_neta=1))


@pytest.fixture()
def panel_mixto(db):
    """La forma del panel real: casi mitad cambiarias, y son las que más eventos aportan."""
    for i in range(8):
        _entidad(db, f"C{i}", BankType.cambiaria, evento=i < 6)
    for i in range(10):
        _entidad(db, f"B{i}", BankType.banca_multiple, evento=i < 2)
    db.commit()
    return db


def test_la_poblacion_se_computa_del_panel_y_nombra_a_quien_no_presta(panel_mixto):
    obs = __import__("modules.banking_score.validation.outcomes_derivation",
                     fromlist=["derive_observations"]).derive_observations(panel_mixto)
    pob = poblacion_del_panel(panel_mixto, obs)
    assert pob["n_observaciones"] == 18
    sin_credito = pob["sin_libro_de_credito"]
    assert sin_credito["tipos"] == ["cambiaria"]
    assert sin_credito["n"] == 8
    assert sin_credito["cuota_de_observaciones"] == pytest.approx(8 / 18, abs=0.001)
    # Y aportan MÁS eventos que su cuota de panel: es el hecho que hay que poder decir.
    assert sin_credito["cuota_de_eventos"] > sin_credito["cuota_de_observaciones"]


def test_el_reporte_publica_la_poblacion_y_la_declara_en_un_caveat(panel_mixto):
    rep = build_backtest_report(panel_mixto, n_boot=30)
    assert rep["ok"] is True
    assert rep["poblacion_del_panel"]["nota"] == NOTA_POBLACION
    assert any("NO otorgan crédito" in c for c in rep["caveats"]), (
        "Si buena parte del panel no presta, el reporte tiene que decirlo donde se lee la "
        "cifra, no en un documento aparte."
    )


def test_un_panel_solo_de_bancos_no_arrastra_el_caveat(db):
    """La declaración es un hecho computado, no una coletilla fija."""
    for i in range(10):
        _entidad(db, f"B{i}", BankType.banca_multiple, evento=i < 3)
    db.commit()
    rep = build_backtest_report(db, n_boot=30)
    assert rep["poblacion_del_panel"]["sin_libro_de_credito"]["n"] == 0
    assert not any("NO otorgan crédito" in c for c in rep["caveats"])


def test_sin_base_la_poblacion_declara_el_motivo_en_vez_de_desaparecer():
    """Un dato que desaparece cuando falta su insumo se lee como que no hacía falta."""
    pob = poblacion_del_panel(None, [])
    assert pob["nota"] == NOTA_POBLACION
    assert pob["motivo"]


def test_los_tipos_sin_libro_de_credito_estan_nombrados_no_inferidos():
    """Se nombran para poder decir qué parte del panel son, no para excluirlos."""
    assert set(SIN_LIBRO_DE_CREDITO) == {"cambiaria", "fiduciaria"}


def test_la_credencial_lleva_la_poblacion_pegada():
    """La tabla comercial la copia del reporte; no la reconstruye ni la escribe a mano."""
    from shared.products.credenciales import _poblacion

    reporte = {"poblacion_del_panel": {
        "por_tipo_de_entidad": [{"tipo_de_entidad": "cambiaria", "n": 794}],
        "sin_libro_de_credito": {"tipos": ["cambiaria"], "n": 794,
                                 "cuota_de_observaciones": 0.469},
        "nota": NOTA_POBLACION}}
    salida = _poblacion(reporte)
    assert salida["sin_libro_de_credito"]["cuota_de_observaciones"] == 0.469
    assert salida["nota"] == NOTA_POBLACION
    # Un motor que no declara población no inventa una.
    assert _poblacion({"gini": 0.2}) is None
