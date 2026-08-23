"""REGLA ESTRUCTURAL: lo que se escribe cabe en la columna que lo recibe.

**El defecto, que ya mordió dos veces en este repo.** SQLite NO valida el largo de un
`VARCHAR` y PostgreSQL SÍ. Un literal que se pasa de largo atraviesa toda la suite en verde
—4.486 tests— y revienta en producción al comitear, con `StringDataRightTruncation`, y se
lleva la transacción ENTERA por delante: no falla la fila larga, falla el commit.

La primera vez fue `mm_series.series_code` con los códigos jerárquicos del motor de Excel.
La segunda fue la procedencia de los conteos regionales: «ONE (cómputo SDQ sobre el panel
regional)», 41 caracteres contra un `varchar(40)`. Entre las dos, la lección escrita no
alcanzó — por eso se leyó el código.

**Y mordió una TERCERA vez, el 2026-08-22, POR EL AGUJERO DE ESTE MISMO TEST.** La unidad
«% de las exportaciones mundiales de manufacturas» —48 caracteres— no vive en una constante
suelta sino DENTRO de un diccionario del módulo, y el resolvedor solo miraba constantes de
tipo cadena. Tres unidades pasaron así, la sync de producción murió dos días seguidos y
nadie se enteró porque `last_run` seguía mostrando el resultado de la corrida anterior.

La lección de la lección: un guard que declara su punto ciego no queda absuelto por
declararlo. Ahora resuelve también las cadenas que viven dentro de diccionarios, listas y
tuplas del módulo, que es donde la prosa larga se mudó en cuanto el guard miró las
constantes.

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


def _cadenas_de(valor):
    """Toda cadena que cuelgue de una estructura, por anidada que esté."""
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _cadenas_de(v)
    elif isinstance(valor, (list, tuple, set)):
        for v in valor:
            yield from _cadenas_de(v)


def _cadenas_en_estructuras():
    """`[(constante, cadena)]` de todo lo que vive dentro de dicts, listas y tuplas del
    módulo. Es el agujero por el que entró la tercera ocurrencia: el resolvedor de arriba
    mira `ast.Name` contra constantes de tipo CADENA, y la prosa larga se había mudado a los
    valores de un diccionario."""
    out = []
    for nombre, val in vars(social_sync).items():
        if nombre.startswith("__") or not isinstance(val, (dict, list, tuple, set)):
            continue
        for s in _cadenas_de(val):
            out.append((nombre, s))
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


def test_ninguna_cadena_de_una_ESTRUCTURA_se_pasa_del_ancho_mas_corto():
    """El agujero de la tercera ocurrencia, cerrado.

    No se puede saber estáticamente a qué columna va cada cadena de un diccionario, así que
    se las mide contra el ancho MÁS CORTO de las columnas de texto. Es conservador a
    propósito: una etiqueta que cabe en `theme` (60) pero no en `unit` (40) es exactamente
    la que rompió producción, y distinguirlas exigiría adivinar el destino.
    """
    limites = _limites()
    # `period` recibe un año de cuatro dígitos y nunca prosa: incluirlo en el mínimo bajaría
    # la vara a 10 y el guard marcaría hasta las etiquetas de tema, que caben de sobra. El
    # ancho que importa es el de las columnas que SÍ reciben texto libre —`unit` y `source`,
    # ambas de 40—, y es el que rompió producción tres veces.
    mas_corto = min(v for k, v in limites.items() if k != "period")
    largas = [(n, s) for n, s in _cadenas_en_estructuras() if len(s) > mas_corto]
    assert not largas, (
        f"estas cadenas viven en estructuras del módulo y NO caben en la columna de texto "
        f"más angosta ({mas_corto}): "
        + "; ".join(f"{n} → «{s[:46]}» ({len(s)})" for n, s in largas)
        + ". Postgres rechaza el COMMIT ENTERO, no la fila.")


def test_el_barrido_de_estructuras_ve_cadenas_de_verdad():
    """Su contrapeso: si alguien renombra las constantes, el test de arriba quedaría vacuo y
    siempre verde — que es como el agujero sobrevivió dos revisiones."""
    cadenas = _cadenas_en_estructuras()
    assert len(cadenas) >= 20, f"solo {len(cadenas)} cadenas: el barrido dejó de ver el módulo"
    assert any("%" in s for _, s in cadenas), "no está viendo las unidades"
