"""Instantáneas comiteadas — el respaldo NUNCA se usa en silencio.

El riesgo de un camino de respaldo no es que falle: es que funcione tan bien que nadie
note que ya no se está leyendo la fuente. En este repo ya pasó (los "promedios del
sistema" hardcodeados quedaron como camino permanente). Estos tests fijan las tres
propiedades que lo evitan: la procedencia viaja, la fecha viaja, y cuando fallan los dos
caminos se propaga el error del VIVO, que es el problema a resolver.
"""
import json

import pytest

from shared.data import snapshots


@pytest.fixture
def dir_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    return tmp_path


def test_el_vivo_gana_y_lo_declara(dir_tmp):
    snapshots.write_snapshot("x", [("a", 1)], source="S")
    filas, prov = snapshots.live_or_snapshot("x", lambda: [("vivo", 9)], source="S")
    assert filas == [("vivo", 9)] and prov == "live"


def test_si_el_vivo_falla_cae_a_la_instantanea_CON_su_fecha(dir_tmp):
    """Sin la fecha, quien lee no puede distinguir un dato de hoy de uno de hace un año."""
    snapshots.write_snapshot("x", [("a", 1), ("b", 2)], source="S")

    def _boom():
        raise ConnectionError("timed out")

    filas, prov = snapshots.live_or_snapshot("x", _boom, source="S")
    assert filas == [("a", 1), ("b", 2)]
    assert prov.startswith("snapshot:")
    assert len(prov.split(":", 1)[1]) == 10          # AAAA-MM-DD


def test_el_vivo_vacio_tambien_cae_al_respaldo(dir_tmp):
    """Cero filas no es un resultado: es la misma falla con otra cara."""
    snapshots.write_snapshot("x", [("a", 1)], source="S")
    filas, prov = snapshots.live_or_snapshot("x", lambda: [], source="S")
    assert filas == [("a", 1)] and prov.startswith("snapshot:")


def test_sin_respaldo_se_propaga_el_error_del_VIVO(dir_tmp):
    """El problema a resolver es que la fuente no se alcanza; el respaldo ausente es una
    consecuencia. Si se propagara ``SnapshotMissing`` se investigaría lo secundario."""
    def _boom():
        raise ConnectionError("403 Forbidden")

    with pytest.raises(ConnectionError, match="403"):
        snapshots.live_or_snapshot("no_existe", _boom, source="S")


def test_una_instantanea_vacia_no_cuenta_como_respaldo(dir_tmp):
    (dir_tmp / "x.json").write_text(json.dumps({"captured_at": "2026-01-01", "rows": []}),
                                    encoding="utf-8")
    with pytest.raises(ConnectionError):
        snapshots.live_or_snapshot("x", lambda: (_ for _ in ()).throw(ConnectionError("x")),
                                   source="S")


def test_la_edad_es_consultable_para_que_la_frescura_la_vea(dir_tmp):
    from datetime import datetime, timedelta, timezone

    snapshots.write_snapshot("x", [("a", 1)], source="S")
    # UTC en los dos lados: la captura estampa UTC y comparar contra la fecha local
    # produce edades negativas cuando el día ya cambió allá y acá no.
    hoy = datetime.now(timezone.utc).date()
    assert snapshots.snapshot_age_days("x", today=hoy) == 0
    assert snapshots.snapshot_age_days("x", today=hoy + timedelta(days=45)) == 45
    assert snapshots.snapshot_age_days("inexistente") is None


def test_las_tuplas_sobreviven_al_viaje_por_json(dir_tmp):
    """JSON no distingue tupla de lista; el consumidor espera tuplas."""
    snapshots.write_snapshot("x", [("provincia", "azua", 2025, 74.5)], source="S")
    filas, _ = snapshots.live_or_snapshot(
        "x", lambda: (_ for _ in ()).throw(ConnectionError("x")), source="S")
    assert filas == [("provincia", "azua", 2025, 74.5)]


def test_los_nombres_del_script_de_captura_son_los_que_la_sync_pide():
    """Un nombre que no coincide produce un respaldo HUÉRFANO: escrito, comiteado y jamás
    leído. No falla nada — simplemente el vivo sigue siendo el único camino, y el día que
    la fuente no responda la sync trae cero filas como si no hubiera respaldo.

    Pasó al partir la captura del MINERD en dos niveles educativos: la clave de la sync
    cambió a `minerd_coverage_levels` y el script seguía escribiendo `minerd_coverage`.
    """
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[3]
    script = ast.parse((raiz / "scripts" / "refresh_social_snapshots.py")
                       .read_text(encoding="utf-8"))
    nombres = set()
    for n in ast.walk(script):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SNAPSHOT_NAMES" for t in n.targets):
            nombres = {c.value for c in n.value.values                      # type: ignore[attr-defined]
                       if isinstance(c, ast.Constant)}
    assert nombres, "no se pudo leer SNAPSHOT_NAMES del script de captura"

    sync = (raiz / "modules" / "social_dev" / "social_sync.py").read_text(encoding="utf-8")
    pedidos = set()
    for n in ast.walk(ast.parse(sync)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "live_or_snapshot" and n.args
                and isinstance(n.args[0], ast.Constant)):
            pedidos.add(n.args[0].value)
    assert pedidos, "la sync dejó de usar live_or_snapshot; este test se volvió decorativo"

    huerfanos = sorted(nombres - pedidos)
    sin_respaldo = sorted(pedidos - nombres)
    assert not huerfanos, f"el script captura respaldos que nadie lee: {huerfanos}"
    assert not sin_respaldo, (
        f"la sync pide respaldos que el script no captura: {sin_respaldo}. Cuando la "
        "fuente no responda, esas filas serán cero.")
