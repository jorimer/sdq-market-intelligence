"""Una tabla que no está en `Base.metadata` al arrancar es una tabla que se puede borrar sola.

`create_all` no la crea en dev ni en tests, y `alembic revision --autogenerate` propone
DROPearla: no la ve en el modelo y sí en la base. El daño no aparece el día que se escribe el
modelo — aparece el día que alguien autogenera una migración y no lee el diff completo.

`tpm_forecast_log` vivía así desde que se creó. Este test cubre las dos.
"""
import pytest

from shared.database.base import Base


@pytest.mark.parametrize("tabla", ["mm_forecast_log", "tpm_forecast_log", "mm_series"])
def test_la_tabla_del_modulo_esta_en_el_metadata(tabla):
    import modules.macro_monitor.models  # noqa: F401 — es lo que las registra

    assert tabla in Base.metadata.tables, (
        f"«{tabla}» no está registrada: `create_all` no la crea y un autogenerate propondría "
        "borrarla")


def test_el_ledger_conserva_su_clave_de_cinco_campos():
    import modules.macro_monitor.models  # noqa: F401

    tabla = Base.metadata.tables["mm_forecast_log"]
    unicas = [c for c in tabla.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert unicas, "el ledger perdió su restricción de unicidad: un rerun duplicaría el historial"
    cols = {c.name for c in unicas[0].columns}
    assert cols == {"model_id", "target_series", "horizon", "as_of", "revision"}, (
        f"la clave del ledger cambió: {sorted(cols)}. Sin `revision`, corregir un pronóstico "
        "obliga a pisar el original.")


# ── La migración que agrega `measure`, y su backfill ────────────────────────────────


def _migracion():
    """El módulo de la migración, cargado por ruta: `versions/` no es un paquete."""
    import importlib.util
    from pathlib import Path

    ruta = (Path(__file__).resolve().parents[4] / "infrastructure" / "alembic" / "versions"
            / "d1e6f3a9c7b2_measure_en_mm_forecast_log.py")
    spec = importlib.util.spec_from_file_location("mig_measure", ruta)
    assert spec is not None and spec.loader is not None, ruta
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_el_modelo_declara_la_medida_del_punto():
    """Sin ella la puntuación supone que `point` es comparable con el valor de
    `target_series`, y no lo es: una tasa contra un índice da 132,75 de error."""
    import modules.macro_monitor.models  # noqa: F401

    assert "measure" in Base.metadata.tables["mm_forecast_log"].columns


def test_el_backfill_de_la_migracion_es_TAN_ANGOSTO_como_dice():
    """Se ejecuta de verdad contra una base de juguete. El backfill afirma algo sobre filas
    que ya existen en producción, y una migración de datos que nadie corrió antes es una
    apuesta: lo que hay que probar es que NO toca lo que no puede identificar.
    """
    from sqlalchemy import create_engine, text

    mig = _migracion()
    eng = create_engine("sqlite://")
    with eng.begin() as cx:
        cx.execute(text("create table mm_forecast_log ("
                        "id text, model_id text, target_series text, measure text)"))
        for id_, model_id, serie, medida in [
            ("a", "bvar_minnesota.5v.v1", "pib_real", None),      # el defecto A
            ("b", "bridge_imae_pib.m2.v1", mig.PIB_CODE, None),   # el defecto B
            ("c", "otro_motor.v1", "alguna.otra.serie", None),    # ni se toca
            ("d", "bvar_minnesota.5v.v1", "otra.serie", "level"),  # ya declarada: no se pisa
        ]:
            cx.execute(text("insert into mm_forecast_log values (:i, :m, :s, :me)"),
                       {"i": id_, "m": model_id, "s": serie, "me": medida})
        cx.execute(text(mig.BACKFILL_MEASURE))
        cx.execute(text(mig.BACKFILL_TARGET_SERIES).bindparams(pib=mig.PIB_CODE))
        filas = {r[0]: (r[1], r[2]) for r in
                 cx.execute(text("select id, target_series, measure from mm_forecast_log"))}

    assert filas["a"] == (mig.PIB_CODE, None), (
        "la fila del BVAR: su `target_series` tenía que normalizarse —«pib_real» no es un "
        "`series_code` con ninguna versión del código— y su MEDIDA tenía que quedar en NULL. "
        "La transformación del PIB en el bloque cambió de trimestral a interanual el mismo "
        "día en que se escribieron estas filas, y `as_of` no tiene hora: la fila no registra "
        "con cuál se produjo, y las dos difieren en puntos porcentuales enteros")
    assert filas["b"] == (mig.PIB_CODE, "dlog_pct"), (
        "el nowcast SÍ se puede afirmar: `nowcast.estimar` nunca cambió de medida")
    assert filas["c"] == ("alguna.otra.serie", None), (
        "el backfill le inventó una medida a un motor que no conoce")
    assert filas["d"] == ("otra.serie", "level"), (
        "el backfill pisó una medida que la fila ya declaraba")


def _migracion_por_ruta(nombre: str):
    import importlib.util
    from pathlib import Path

    ruta = (Path(__file__).resolve().parents[4] / "infrastructure" / "alembic" / "versions"
            / nombre)
    spec = importlib.util.spec_from_file_location(nombre.split("_")[0], ruta)
    assert spec is not None and spec.loader is not None, ruta
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_la_medida_de_la_fila_del_BVAR_se_estampa_SOLO_donde_se_probo():
    """La fila del 2026-09-05 se determinó por cronología (es 4h34m anterior al commit que
    introdujo la variación interanual) y por reproducción del modelo. El `where` tiene que
    llegar exactamente hasta ahí: una fila del mismo modelo emitida DESPUÉS es interanual, y
    estamparla como trimestral metería el error equivocado en el track record."""
    from sqlalchemy import create_engine, text

    mig = _migracion_por_ruta("a4c8e1b70d93_medida_de_la_fila_del_bvar.py")
    eng = create_engine("sqlite://")
    with eng.begin() as cx:
        cx.execute(text("create table mm_forecast_log ("
                        "id text, model_id text, target_series text, as_of text, "
                        "measure text)"))
        for id_, model_id, serie, as_of, medida in [
            # la fila real: trimestral, determinada
            ("real", "bvar_minnesota.5v.v1", mig.PIB_CODE, "2026-09-05", None),
            # una emitida DESPUÉS del cambio: ya trae su medida, y no se toca
            ("post", "bvar_minnesota.5v.v1", mig.PIB_CODE, "2026-12-05", "yoy_pct"),
            # una del futuro sin medida: NO se le inventa una
            ("futura", "bvar_minnesota.5v.v1", mig.PIB_CODE, "2026-12-05", None),
            # el nowcast ya lo resolvió la migración anterior
            ("nowcast", "bridge_imae_pib.m2.v1", mig.PIB_CODE, "2026-09-05", "dlog_pct"),
            # otro motor, otra serie: ni se mira
            ("ajeno", "otro.v1", "otra.serie", "2026-09-05", None),
        ]:
            cx.execute(text("insert into mm_forecast_log values (:i,:m,:s,:a,:me)"),
                       {"i": id_, "m": model_id, "s": serie, "a": as_of, "me": medida})
        cx.execute(text(mig.ESTAMPAR_MEDIDA).bindparams(
            pib=mig.PIB_CODE, corte=mig.ULTIMO_DIA_TRIMESTRAL))
        got = dict(cx.execute(text("select id, measure from mm_forecast_log")).all())

    assert got["real"] == "dlog_pct", "la fila que se determinó quedó sin estampar"
    assert got["post"] == "yoy_pct", "pisó una medida ya declarada"
    assert got["futura"] is None, (
        "le inventó la medida a una fila posterior al cambio: ésa es interanual y quedaría "
        "con el error de otra unidad en el track record")
    assert got["nowcast"] == "dlog_pct"
    assert got["ajeno"] is None
