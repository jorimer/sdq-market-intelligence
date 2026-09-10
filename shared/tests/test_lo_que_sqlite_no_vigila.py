"""Restricciones que PostgreSQL aplica y SQLite ignora, vigiladas desde SQLite.

**El día que las dos fallaron juntas.** El 2026-09-06 el boletín regional no se podía generar
—`POST /boletin-regional/generate` daba 500 en 0,38 s— y el sync de SECMCA llevaba un día
entero sin entrar ni una fila. Dos causas distintas, una sola raíz:

  · `reporttype` es un ENUM de PostgreSQL y le faltaba el valor `boletin_regional`. El tipo se
    había registrado en treinta superficies y en ninguna migración.
  · `rb_country_aggregates.metric` era `VARCHAR(60)` y SECMCA genera claves de hasta 104.

Las dos pasaron los 8.666 tests EN VERDE, porque la batería corre sobre SQLite y SQLite **no
aplica el largo de un VARCHAR ni los valores de un Enum** (los materializa como un CHECK por
tabla, recreado solo al crear la tabla). Es una clase entera de restricciones sobre la que
todos los tests son ciegos a la vez, así que la lección escrita no alcanza: hace falta leer el
código y las migraciones, que es lo que hacen estos guards.
"""
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]
VERSIONES = RAIZ / "infrastructure" / "alembic" / "versions"


def _texto_de_las_migraciones() -> str:
    archivos = list(VERSIONES.glob("*.py"))
    assert len(archivos) >= 20, (
        f"solo se encontraron {len(archivos)} migraciones en {VERSIONES}: el barrido se "
        "quedó ciego y los guards de abajo pasarían sin mirar nada")
    return "\n".join(f.read_text(encoding="utf-8") for f in archivos)


def _valores_del_enum(nombre: str) -> set:
    """Los valores que la clase Python declara para un enum persistido."""
    from modules.banking_score.models import models

    return {m.value for m in getattr(models, nombre)}


def test_el_barrido_de_migraciones_ENCUENTRA_algo():
    """Si el glob deja de encontrar migraciones, todo lo de abajo pasa sin comprobar nada."""
    texto = _texto_de_las_migraciones()
    assert "ADD VALUE" in texto, "ninguna migración agrega valores de enum: el lector falló"


@pytest.mark.parametrize("valor", sorted(_valores_del_enum("ReportType")))
def test_todo_tipo_de_informe_existe_TAMBIEN_en_el_enum_de_postgres(valor):
    """Un tipo nuevo se registra en todas sus superficies, y la BASE es una de ellas.

    Sin esto, el tipo existe en Python, la aplicación lo acepta, y el INSERT lo rechaza en
    producción con un 500 que ocurre ANTES de cualquier trabajo: ni siquiera queda una fila
    con estado de error para investigar.
    """
    texto = _texto_de_las_migraciones()
    creado_de_origen = re.search(
        r"(?s)sa\.Enum\((.{0,400}?)name=[\"']reporttype[\"']", texto)
    en_creacion = bool(creado_de_origen and f"'{valor}'" in creado_de_origen.group(1))
    agregado = re.search(
        rf"ALTER TYPE reporttype ADD VALUE[^\n]*['\"]{re.escape(valor)}['\"]", texto)
    assert en_creacion or agregado, (
        f"«{valor}» está en ReportType y ninguna migración lo agrega al enum de PostgreSQL. "
        "En SQLite el INSERT pasa; en producción devuelve 500 antes de hacer nada")


def test_las_claves_de_los_conectores_ENTRAN_en_su_columna():
    """El largo de un VARCHAR no lo aplica SQLite. Se mide contra lo que el conector produce.

    Se leen los fixtures, que son capturas del emisor real: es la única forma de saber cuánto
    mide de verdad la clave más larga sin ir a la red.
    """
    import json

    from modules.regional_banking.models.models import CountryBankingAggregate

    tope = CountryBankingAggregate.__table__.c.metric.type.length
    assert tope, "la columna `metric` dejó de declarar un largo"

    fx = json.loads((RAIZ / "shared" / "data" / "fixtures" / "secmca.json")
                    .read_text(encoding="utf-8"))
    claves = {f"{clave}::{etiqueta}"
              for iso, bloque in fx.items() if not iso.startswith("_")
              for clave, filas in (bloque.get("cuadros") or {}).items()
              for _corte, etiqueta, _v in filas}
    assert len(claves) >= 20, (
        f"solo se derivaron {len(claves)} claves del fixture de SECMCA: el lector se quedó "
        "ciego y este guard pasaría sin medir")
    peor = max(claves, key=len)
    assert len(peor) <= tope, (
        f"la clave más larga de SECMCA mide {len(peor)} y la columna admite {tope}. En "
        f"PostgreSQL el sync entero falla con «value too long»; en SQLite entra sin ruido. "
        f"La clave es: {peor!r}")


# ── La PROCEDENCIA de un conector entra en la columna que la guarda ──────────────
#
# El 2026-09-10 el primer sync del feed mensual del MIVHED reventó en producción con
# `StringDataRightTruncation`: la licencia que declara el conector son 278 caracteres y la
# columna era `VARCHAR(200)`. Los 9.769 tests estaban en verde, porque SQLite no aplica el
# largo de un VARCHAR. Es la MISMA familia que el caso de `rb_country_aggregates.metric` de
# arriba, y que se repita es la prueba de que la lección escrita no alcanza: hace falta un
# lector que mida lo que los conectores producen contra lo que la columna acepta.
#
# Se miden los conectores REALES —no un fixture—, porque el valor problemático es un atributo
# de clase que cualquiera puede alargar al corregir una licencia mal declarada, que es
# exactamente como esto va a volver a pasar.


def _procedencia_de_los_conectores():
    """`[(clase, campo, largo)]` de `source` y `license` de todo conector de shared/data."""
    import importlib
    import inspect
    import pkgutil

    import shared.data as paquete

    salida = []
    for m in pkgutil.iter_modules(paquete.__path__):
        try:
            mod = importlib.import_module(f"shared.data.{m.name}")
        except Exception:  # noqa: BLE001 — un conector que no importa no aporta al barrido
            continue
        for nombre, obj in inspect.getmembers(mod, inspect.isclass):
            for campo in ("source", "license"):
                valor = getattr(obj, campo, None)
                if isinstance(valor, str) and valor:
                    salida.append((nombre, campo, len(valor)))
    return salida


def test_el_barrido_de_conectores_ENCUENTRA_procedencia():
    """Sin esto, el guard de abajo pasaría en verde sin medir nada."""
    filas = _procedencia_de_los_conectores()
    clases = {c for c, _, _ in filas}
    assert len(clases) >= 20, f"solo se leyeron {len(clases)} conectores: el barrido falló"
    assert any(campo == "license" for _, campo, _ in filas)


def test_la_procedencia_ENTRA_en_sector_observations():
    """La tabla de observaciones es TRANSVERSAL: recibe la procedencia de cualquier eje, así
    que tiene que aceptar la del conector más largo del catálogo, no la del que la estrenó."""
    from shared.observations.models import SectorObservation

    filas = _procedencia_de_los_conectores()
    for campo in ("source", "license"):
        col = SectorObservation.__table__.c[campo]
        tope = getattr(col.type, "length", None)
        if tope is None:
            continue  # TEXT: sin cota, nada que verificar
        peor = max(((n, largo) for n, c, largo in filas if c == campo),
                   key=lambda x: x[1], default=None)
        assert peor is not None
        assert peor[1] <= tope, (
            f"`sector_observations.{campo}` acepta {tope} caracteres y {peor[0]} declara "
            f"{peor[1]}. En SQLite el INSERT pasa; en PostgreSQL revienta con "
            f"StringDataRightTruncation y el feed no persiste nada.")

