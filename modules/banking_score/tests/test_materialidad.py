"""El umbral de materialidad de las cambiarias: primero medir, después cortar.

`docs/PROPUESTA_CAMBIARIAS_FIDUCIARIAS.md` §0 (2026-06-08) decidió acotar el alcance a los
agentes con balance material —«calificar las 35 AC completas añade ruido: balances cercanos a
cero»— y dejó el umbral sin calibrar. La v1 salió con las 42, y medido el 2026-08-19 esas
entidades son el 47 % del panel del backtest y el 63 % de sus eventos.

Estos tests fijan dos cosas: que el perfil encuentre el escalón real de la escalera de tamaños
(para que el piso salga de la evidencia y no de una intuición), y que SIN piso declarado no se
filtre nada — un umbral a medio aplicar es peor que ninguno.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import modules.banking_score.models.models  # noqa: F401 — registra las tablas
import shared.auth.models  # noqa: F401 — destino de la FK
from modules.banking_score.models.models import Bank, BankingData, BankType
from modules.banking_score.scoring.materialidad import es_material, perfil_de_materialidad
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


def _entidad(db, clave, activos_por_periodo, tipo=BankType.cambiaria):
    db.add(Bank(id=clave, name=f"E {clave}", bank_type=tipo))
    for periodo, valor in activos_por_periodo.items():
        db.add(BankingData(bank_id=clave, period_end=periodo, activos_totales=valor))


P1, P2 = date(2024, 3, 31), date(2024, 6, 30)
P3, P4 = date(2024, 9, 30), date(2024, 12, 31)


def test_el_perfil_encuentra_el_escalon_cuando_EXISTE(db):
    """Tres agentes con balance real y una cola de ventanillas casi vacías.

    Es la forma que la propuesta afirmaba: si existe, el salto aparece solo y el piso no lo
    elige nadie a ojo.
    """
    for i, monto in enumerate([5_000_000_000.0, 3_000_000_000.0, 1_000_000_000.0]):
        _entidad(db, f"ARC{i}", {P1: monto * 0.9, P2: monto})
    for i in range(6):
        _entidad(db, f"AC{i}", {P1: 900_000.0 - i * 100, P2: 1_000_000.0 - i * 100})
    db.commit()

    perfil = perfil_de_materialidad(db)
    assert perfil["ok"] is True
    assert perfil["n_entidades"] == 9
    escalon = perfil["escalon"]
    assert escalon["hay_escalon"] is True
    assert escalon["mayor_salto_limpio"]["posicion"] == 3
    assert escalon["piso_sugerido"] == pytest.approx(950_000.0, rel=0.01)  # mediana, no último
    # Y las filas vienen ordenadas de mayor a menor, con su cuota del sistema.
    assert perfil["por_entidad"][0]["activos_ultimo"] == 5_000_000_000.0
    assert perfil["por_entidad"][0]["cuota_del_sistema_de_su_tipo"] > 0.5


def test_una_escalera_CONTINUA_no_inventa_un_escalon(db):
    """La forma que el panel real resultó tener: tamaños que bajan sin cortes.

    Con la escalera continua, el veredicto tiene que decir que el piso lo elegiría una
    persona y no el dato. Antes de este test, el salto más grande se leía como escalón
    aunque fuera de 1,5×.
    """
    monto = 3_000_000_000.0
    for i in range(12):
        _entidad(db, f"E{i}", {P1: monto * 0.95, P2: monto})
        monto /= 1.8  # baja parejo: ninguna vecina se separa un orden de magnitud
    db.commit()

    escalon = perfil_de_materialidad(db)["escalon"]
    assert escalon["hay_escalon"] is False
    assert escalon["piso_sugerido"] is None
    assert "no hay escalón" in escalon["veredicto"]


def test_una_serie_ROTA_no_puede_hacerse_pasar_por_escalon(db):
    """El caso real: Placidoiv, mediana RD$8,3 MM y último RD$48,7 M — 170× contra sí misma.

    En la primera corrida esa entidad ERA el único «escalón» del panel, y calibrar el piso
    ahí habría sido calibrarlo sobre un artefacto.
    """
    monto = 3_000_000_000.0
    for i in range(8):
        _entidad(db, f"E{i}", {P1: monto * 0.95, P2: monto})
        monto /= 1.8
    # La última: opera normal toda su serie y colapsa SOLO en el último corte. Con una serie
    # de dos puntos la mediana es el promedio y la anomalía se diluye — que es justamente por
    # qué la mediana necesita historia para ser el tamaño estable.
    _entidad(db, "ROTA", {P1: 8_300_000.0, P2: 8_400_000.0, P3: 8_200_000.0, P4: 48_709.0})
    db.commit()

    perfil = perfil_de_materialidad(db)
    anomalas = perfil["anomalias_ultimo_vs_su_propia_mediana"]
    assert [a["entidad"] for a in anomalas] == ["E ROTA"]
    assert anomalas[0]["razon_contra_su_propia_mediana"] > 100
    # Y el escalón NO se fija con ella.
    assert perfil["escalon"]["hay_escalon"] is False
    for salto in perfil["saltos_mas_grandes"]:
        if salto["razon"] > 100:
            assert salto["alguna_vecina_es_anomala"] is True


def test_sin_piso_declarado_no_se_filtra_nada(db):
    """Un umbral a medio aplicar filtraría sin que nadie sepa con qué criterio."""
    assert es_material("cambiaria", 1.0, piso=None) is True
    assert es_material("cambiaria", None, piso=None) is True


def test_con_piso_declarado_corta_solo_a_los_tipos_acotados():
    assert es_material("cambiaria", 2_000_000.0, piso=1_000_000.0) is True
    assert es_material("cambiaria", 500_000.0, piso=1_000_000.0) is False
    # Un banco múltiple no entra en la regla: su alcance nunca estuvo acotado.
    assert es_material("banca_multiple", 1.0, piso=1_000_000.0) is True


def test_una_entidad_sin_activo_no_es_material_bajo_piso():
    """Sin activo no se puede afirmar que supera el piso, y el silencio no aprueba."""
    assert es_material("cambiaria", None, piso=1_000_000.0) is False


def test_sin_entidades_del_tipo_lo_declara_en_vez_de_devolver_vacio(db):
    salida = perfil_de_materialidad(db, tipo="fiduciaria")
    assert salida["ok"] is False and "no hay entidades" in salida["motivo"]


def test_entidades_sin_activo_cargado_se_declaran(db):
    _entidad(db, "X", {})
    db.commit()
    salida = perfil_de_materialidad(db)
    assert salida["ok"] is False and "activo total" in salida["motivo"]
