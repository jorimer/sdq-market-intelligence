"""La migración de datos que completa la procedencia recortada de trámites (d4b8f2a6c913).

Se prueba la función que corre la migración contra una base SQLite con la tabla real, porque
lo que importa no es que la migración «corra» —un UPDATE que no coincide con nada también
corre en verde— sino QUÉ filas cambia y cuáles deja quietas.
"""
import importlib.util
import pathlib

import pytest
from sqlalchemy import create_engine, text

RAIZ = pathlib.Path(__file__).resolve().parents[3]
MIGRACION = (RAIZ / "infrastructure" / "alembic" / "versions"
             / "d4b8f2a6c913_tramites_procedencia_historica_entera.py")


def _migracion():
    spec = importlib.util.spec_from_file_location("migracion_tramites", MIGRACION)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_los_textos_congelados_son_los_del_conector():
    """Si el conector cambia su texto, las filas recortadas son prefijo del VIEJO y esta
    migración ya no las reconoce: el test lo dice en vez de dejar una migración que no toca
    nada y pasa en verde."""
    from shared.data import gobdo_tramites

    mig = _migracion()
    assert mig.SOURCE == gobdo_tramites.SOURCE
    assert mig.LICENSE == gobdo_tramites.LICENSE
    # Y el recorte que se busca es de verdad un recorte: si entraran, no habría qué completar.
    assert len(mig.SOURCE) > mig._TOPE_SOURCE_VIEJO
    assert len(mig.LICENSE) > mig._TOPE_LICENSE_VIEJO


@pytest.fixture
def base():
    from modules.social_dev.models.models import SocialIndicator

    motor = create_engine("sqlite://")
    SocialIndicator.__table__.create(motor)
    yield motor
    motor.dispose()


def _insertar(conn, ident, theme, period, source, license_):
    conn.execute(text(
        "INSERT INTO sd_indicators (id, theme, period, source, license) "
        "VALUES (:i, :t, :p, :s, :l)"),
        {"i": ident, "t": theme, "p": period, "s": source, "l": license_})


def _fila(conn, ident):
    return conn.execute(text("SELECT source, license FROM sd_indicators WHERE id = :i"),
                        {"i": ident}).one()


def test_completa_SOLO_lo_recortado_y_es_idempotente(base):
    mig = _migracion()
    recortada = (mig.SOURCE[:40], mig.LICENSE[:120])
    with base.begin() as conn:
        _insertar(conn, "vieja", "tramites_catalogados", "2026-08", *recortada)
        _insertar(conn, "desglose", "tramites_por_institucion", "2026-08", *recortada)
        _insertar(conn, "entera", "tramites_catalogados", "2026-09", mig.SOURCE, mig.LICENSE)
        # El mismo prefijo en un tema que NO es de trámites no es de este conector.
        _insertar(conn, "ajena", "pobreza_monetaria", "2026-08", *recortada)
        _insertar(conn, "otra", "tramites_catalogados", "2026-07", "ONE", "CC-BY 4.0")

        cambios = mig._completar(conn)
        assert cambios == {"source": 2, "license": 2}, cambios

        for ident in ("vieja", "desglose", "entera"):
            assert tuple(_fila(conn, ident)) == (mig.SOURCE, mig.LICENSE), ident
        assert tuple(_fila(conn, "ajena")) == recortada
        assert tuple(_fila(conn, "otra")) == ("ONE", "CC-BY 4.0")

        # Correr de nuevo no toca nada: CI hace upgrade → downgrade -1 → upgrade.
        assert mig._completar(conn) == {"source": 0, "license": 0}
