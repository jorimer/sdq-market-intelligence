"""REGLA ESTRUCTURAL: lo que se escribe cabe en la columna que lo recibe.

**El defecto, que ya mordió dos veces en este repo.** SQLite NO valida el largo de un
`VARCHAR` y PostgreSQL SÍ. Un literal que se pasa de largo atraviesa toda la suite en verde
—4.486 tests— y revienta en producción al comitear, con `StringDataRightTruncation`, y se
lleva la transacción ENTERA por delante: no falla la fila larga, falla el commit.

La primera vez fue `mm_series.series_code` con los códigos jerárquicos del motor de Excel.
La segunda fue la procedencia de los conteos regionales: «ONE (cómputo SDQ sobre el panel
regional)», 41 caracteres contra un `varchar(40)`. Entre las dos, la lección escrita no
alcanzó — por eso ahora se lee el código.

**Qué comprueba.** Cada literal de cadena que se le pasa a `_upsert_indicator` contra el
largo declarado del `Column` correspondiente. Resuelve también las constantes del módulo,
que es donde vive la prosa larga.

Al agregar un módulo con esta misma forma —un helper de upsert y un modelo con `String(n)`—
conviene copiar este test antes que la lección.
"""
import ast
import inspect

import pytest
from sqlalchemy import String

from modules.social_dev import social_sync
from modules.social_dev.models.models import SocialIndicator

#: Argumento del helper → columna que lo recibe. Explícito porque el nombre no siempre
#: coincide: `entity` va a `entity_key` y `disagg` a `disaggregation`.
_ARG_A_COLUMNA = {
    "theme": "theme", "period": "period", "entity": "entity_key",
    "disagg": "disaggregation", "unit": "unit", "source": "source",
}


def _limites():
    out = {}
    for col in SocialIndicator.__table__.columns:
        if isinstance(col.type, String) and col.type.length:
            out[col.name] = col.type.length
    return out


def _literales():
    """`[(arg, valor, línea)]` para cada cadena que llega al upsert, resueltas las
    constantes del módulo. Lo que no se puede resolver estáticamente se ignora — el test
    protege lo que SÍ puede ver, y decirlo es más honesto que fingir cobertura total."""
    arbol = ast.parse(inspect.getsource(social_sync))
    globales = {k: v for k, v in vars(social_sync).items() if isinstance(v, str)}
    out = []
    for n in ast.walk(arbol):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_upsert_indicator"):
            continue
        for kw in n.keywords:
            if kw.arg not in _ARG_A_COLUMNA:
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                out.append((kw.arg, kw.value.value, kw.value.lineno))
            elif isinstance(kw.value, ast.Name) and kw.value.id in globales:
                out.append((kw.arg, globales[kw.value.id], kw.value.lineno))
    return out


def test_el_test_ve_literales_de_verdad():
    """Sin esto, un cambio de nombre del helper volvería al test vacuo y siempre verde."""
    assert len(_literales()) >= 10


@pytest.mark.parametrize("arg,valor,linea", _literales())
def test_ningun_literal_excede_su_columna(arg, valor, linea):
    limite = _limites()[_ARG_A_COLUMNA[arg]]
    assert len(valor) <= limite, (
        f"social_sync.py:{linea} — {arg}={valor!r} mide {len(valor)} y la columna "
        f"`{_ARG_A_COLUMNA[arg]}` admite {limite}. En SQLite pasa; en Postgres el COMMIT "
        f"ENTERO falla con StringDataRightTruncation y se pierde toda la corrida.")
