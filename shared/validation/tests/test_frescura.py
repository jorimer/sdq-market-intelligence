"""La huella de insumo: tres estados, y el tercero es el que importa.

`stale=False` (vigente), `stale=True` (el insumo cambió) y `stale=None` (indeterminado).
Confundir el tercero con el primero es exactamente cómo producción sirvió durante 19 días un
Gini calculado con un score que ya no existía.
"""
import pytest

import shared.operations.service as svc
from shared.validation.frescura import (
    MOTORES, MotorValidacion, con_frescura, es_publicable, firmar, registrar_motor, sellar,
)


class _DBFalsa:
    """Lo mínimo que la frescura le pide a una sesión: poder revertir si algo falla."""

    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture()
def motor_de_prueba():
    """Un motor cuyo insumo es una caja que el test mueve a mano."""
    estado = {"n": 3, "suma": 10.0}
    guardado = dict(MOTORES)
    registrar_motor(MotorValidacion(
        eje="_prueba", operacion="op-prueba", clave="prueba_backtest_report",
        partes=lambda _db: dict(estado), sin_cascada_motivo="motor de prueba",
    ))
    try:
        yield estado
    finally:
        MOTORES.clear()
        MOTORES.update(guardado)


# ── La firma ──────────────────────────────────────────────────────

def test_la_firma_no_depende_del_orden_de_las_claves():
    assert firmar({"a": 1, "b": 2}) == firmar({"b": 2, "a": 1})


def test_la_firma_cambia_con_el_valor():
    assert firmar({"suma": 10.0}) != firmar({"suma": 10.01})


# ── Los tres estados ──────────────────────────────────────────────

def test_reporte_recien_sellado_esta_vigente(motor_de_prueba):
    db = _DBFalsa()
    rep = sellar({"gini": 0.16}, "_prueba", db)
    assert rep["input_fingerprint"]
    assert rep["generated_at"]
    assert con_frescura(rep, "_prueba", db)["stale"] is False
    assert es_publicable(rep)


def test_cambiar_el_insumo_marca_el_reporte_obsoleto(motor_de_prueba):
    """El caso real: la recalibración no agrega filas, solo mueve el score."""
    db = _DBFalsa()
    rep = sellar({"gini": 0.4436}, "_prueba", db)
    motor_de_prueba["suma"] = 11.0          # mismo n, otro score — la recalibración
    salida = con_frescura(rep, "_prueba", db)
    assert salida["stale"] is True
    assert "insumo cambió" in salida["stale_reason"]
    assert not es_publicable(salida)


def test_reporte_sin_huella_queda_indeterminado_no_vigente(motor_de_prueba):
    """Un reporte anterior a la huella no se puede declarar al día. Ni obsoleto: no se sabe."""
    salida = con_frescura({"gini": 0.16, "generated_at": "2026-07-27T00:00:00Z"},
                          "_prueba", _DBFalsa())
    assert salida["stale"] is None
    assert not es_publicable(salida)


def test_eje_sin_motor_queda_indeterminado():
    salida = con_frescura({"gini": 0.1}, "_eje_inexistente", _DBFalsa())
    assert salida["stale"] is None
    assert "sin motor" in salida["stale_reason"]


def test_si_la_lectura_del_insumo_falla_no_tumba_la_respuesta():
    """Una advertencia rota no debe convertirse en una caída del endpoint."""
    guardado = dict(MOTORES)
    registrar_motor(MotorValidacion(
        eje="_roto", operacion="op", clave="roto_backtest_report",
        partes=lambda _db: (_ for _ in ()).throw(RuntimeError("tabla ausente")),
        sin_cascada_motivo="prueba",
    ))
    db = _DBFalsa()
    try:
        salida = con_frescura({"input_fingerprint": "abc"}, "_roto", db)
        assert salida["stale"] is None
        assert db.rollbacks == 1
    finally:
        MOTORES.clear()
        MOTORES.update(guardado)


def test_el_insumo_no_cubierto_viaja_en_la_respuesta():
    """Un `stale=False` que calla lo que no verificó afirma de más."""
    guardado = dict(MOTORES)
    registrar_motor(MotorValidacion(
        eje="_parcial", operacion="op", clave="parcial_backtest_report",
        partes=lambda _db: {"n": 1}, sin_cascada_motivo="prueba",
        insumo_no_cubierto=("mortalidad OWID, descargada en cada corrida",),
    ))
    db = _DBFalsa()
    try:
        salida = con_frescura(sellar({}, "_parcial", db), "_parcial", db)
        assert salida["stale"] is False
        assert salida["stale_scope"] == ["mortalidad OWID, descargada en cada corrida"]
    finally:
        MOTORES.clear()
        MOTORES.update(guardado)


# ── La cascada, sobre el grafo REAL ───────────────────────────────

def test_re_puntuar_dispara_la_validacion_sin_intervencion(monkeypatch):
    """El grafo declarado en producción: cada motor, disparado por sus fuentes reales.

    No es un grafo de juguete: se lee del registro que arma `app.main`, que es el mismo que
    corre en el despliegue.
    """
    import app.main  # noqa: F401 — auto-registro real

    esperado = {
        "rescore": "backtest",
        "perfil-sdq-backfill": "backtest",
        "sector-snapshot": "sector-gate-e",
        "idm-snapshot": "idm-convergent-validity",
        "esg-sync": "esg-backtest",
        "sipen-sync": "pension-backtest",
        "insurance-financials-sync": "insurance-backtest",
    }
    for arriba, abajo in esperado.items():
        disparadas = []
        monkeypatch.setattr(svc, "trigger",
                            lambda name, origin="manual", user_id=None, params=None:
                            (disparadas.append(name), {"started": True})[1])
        svc._fire_cascade(arriba)
        assert abajo in disparadas, f"'{arriba}' terminó y no re-validó '{abajo}'"


def test_la_cascada_corre_de_verdad_al_terminar_la_operacion(monkeypatch):
    """End-to-end de la mecánica: la de arriba termina y la de abajo EJECUTA su runner.

    Contra una base en memoria y con el hilo del ejecutor vuelto síncrono, así que corre el
    camino real (`trigger` → runner → registro de la corrida → cascada), no una simulación.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from shared.database.base import Base
    import shared.operations.models  # noqa: F401 — registra operation_runs/schedules
    import shared.settings.models    # noqa: F401 — registra app_settings

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(svc, "SessionLocal", sessionmaker(bind=engine, autoflush=False))

    guardadas = dict(svc.OPERATIONS)
    svc.OPERATIONS.clear()
    corridas = []
    try:
        svc.register_operation(svc.Operation(
            "e2e-score", "Score", "d", lambda *a: {"ok": True}, 24, triggers=["e2e-valida"]))
        svc.register_operation(svc.Operation(
            "e2e-valida", "Valida", "d",
            lambda *a: corridas.append("valida") or {"gini": 0.16}, 0))
        monkeypatch.setattr(svc, "_spawn", lambda target: target())  # síncrono en test
        svc.trigger("e2e-score", origin="manual")
        assert corridas == ["valida"]
    finally:
        svc.OPERATIONS.clear()
        svc.OPERATIONS.update(guardadas)
