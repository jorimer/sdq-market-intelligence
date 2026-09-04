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
