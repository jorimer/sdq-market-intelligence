"""Registro de los modelos del módulo en `Base.metadata`.

No es ceremonia: una tabla que no está en `Base.metadata` cuando la app arranca es una tabla
que `create_all` no crea en dev ni en tests, y que un `alembic revision --autogenerate`
propone **BORRAR**, porque no la ve en el modelo y sí en la base. El daño no aparece el día
que se escribe: aparece el día que alguien autogenera una migración.

`tpm_forecast_log` estaba en esa situación desde que se creó. Se registra acá junto con el
ledger nuevo, y un test lo vigila.
"""
from modules.macro_monitor.forecasting import models as _forecasting  # noqa: F401
from modules.macro_monitor.models import models as _models  # noqa: F401
from modules.macro_monitor.tpm_modeling import models as _tpm  # noqa: F401
