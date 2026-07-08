"""La consola de operaciones registra los syncs de macro (fiscal + publicaciones BCRD)."""
from shared.operations.service import OPERATIONS, Operation


def _register_into_clean():
    """Corre register() sobre un registro limpio y lo restaura (aísla del resto del suite)."""
    saved = dict(OPERATIONS)
    OPERATIONS.clear()
    try:
        from modules.macro_monitor.operations import register
        register()
        return dict(OPERATIONS)
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(saved)


def test_bcrd_publications_sync_is_registered_monthly():
    ops = _register_into_clean()
    assert "bcrd-publications-sync" in ops
    op = ops["bcrd-publications-sync"]
    assert isinstance(op, Operation)
    assert op.default_interval_hours == 720  # mensual
    assert not op.needs_params  # se auto-agenda al deploy (seed_default_schedules)


def test_fiscal_sync_still_registered():
    assert "fiscal-sync" in _register_into_clean()
