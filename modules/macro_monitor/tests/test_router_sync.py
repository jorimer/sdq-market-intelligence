"""Regresión: las operaciones del router macro deben ser síncronas (``def``).

El motor Excel y las llamadas al BCRD/Claude son bloqueantes; declarar un endpoint
``async def`` las correría dentro del event loop y una sola ingesta lenta congelaría
al único worker de uvicorn (502 en cascada). FastAPI threadpolea las funciones
``def``, así que este test falla si alguien reintroduce ``async def`` sin volver
async todo el I/O subyacente. Ver el docstring de ``api/router.py``.
"""
import inspect

from fastapi.routing import APIRoute

from modules.macro_monitor.api.router import router


def _endpoints():
    return [r for r in router.routes if isinstance(r, APIRoute)]


def test_router_has_endpoints():
    # Guardia: si el import o el registro se rompe, no queremos un test que pase vacío.
    assert len(_endpoints()) >= 20


def test_no_path_operation_is_async():
    """Ningún endpoint puede ser una corutina mientras el I/O aguas abajo sea síncrono."""
    offenders = [
        f"{r.methods} {r.path}"
        for r in _endpoints()
        if inspect.iscoroutinefunction(r.endpoint)
    ]
    assert not offenders, (
        "Estos endpoints son `async def` pero llaman trabajo síncrono bloqueante "
        "(descarga BCRD / parseo Excel / Claude / SQLAlchemy sync). Decláralos `def` "
        f"para que FastAPI los corra en su threadpool: {offenders}"
    )
