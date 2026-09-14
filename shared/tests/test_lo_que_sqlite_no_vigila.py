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


# ── Toda clave que se escribe en `app_setting` ENTRA en su columna ───────────────
#
# El 2026-09-10 Postgres rechazó tres veces en 40 minutos el MISMO marcador de dedup de una
# alerta de banca: `alert_sent:banking:<uuid>:umbral:crecimiento_anomalo:<uuid>` son 119
# caracteres y `app_setting.key` es `VARCHAR(100)`. La notificación ya estaba comprometida,
# el marcador no, así que cada barrido volvía a avisar lo mismo al mismo cliente — el ruido
# que el módulo de alertas declara como su modo de falla dominante. Los tests de dedup
# estaban en verde porque usaban un sujeto VACÍO y porque SQLite no aplica el largo.


def test_el_marcador_de_una_alerta_de_banca_ENTRA_en_app_setting():
    """La clave real, con la regla más larga que hoy dispara y dos UUID de 36 caracteres."""
    from shared.alerts import entrega
    from shared.alerts.reglas import rule_umbral
    from shared.settings.models import AppSetting

    tope = AppSetting.__table__.c.key.type.length
    assert tope, "la columna `app_setting.key` dejó de declarar un largo"

    evento = rule_umbral(
        sector_key="banking", subject="aea314c5-876a-404d-8446-523c7b0d9869",
        sujeto_label="Banco X", periodo="2026-Q2", metrica="crecimiento_anomalo",
        metrica_label="Crecimiento de activos", valor=140.0, umbral=100.0,
        direccion="por_encima", severidad="alta", basis="b", frescura=True)
    assert evento is not None
    clave = entrega.DEDUP._key(entrega._clave(evento, "b696e0a3-e90b-4072-a83a-7bb5386dcd0e"))
    assert len(clave) <= tope, (
        f"el marcador de dedup mide {len(clave)} y `app_setting.key` admite {tope}. En "
        f"PostgreSQL el INSERT falla DESPUÉS de crear la notificación y el cliente recibe la "
        f"misma alerta en cada barrido. La clave es: {clave!r}")


# La clave de una alerta es solo el caso que reventó. El guard de abajo lee TODA escritura en
# `app_setting` —de cualquier módulo, y también de `scripts/`, que escribe en la misma base—
# y exige una de tres cosas: que la clave sea un literal que entra, que pase por
# `clave_acotada` (que la acota por construcción), o que figure abajo con el motivo por el
# que igual está acotada. Lo que queda afuera: las escrituras por SQL crudo (migraciones), que
# no construyen un `AppSetting`.

_CARPETAS_CON_ESCRITORES = ("shared", "modules", "app", "scripts")

#: Escrituras cuya clave no se resuelve leyendo un solo módulo. Cada entrada nombra QUÉ la
#: acota; si deja de hacer falta (el lector ya la resuelve, o la escritura desapareció), el
#: guard lo exige quitar, para que la lista no se vuelva un permiso heredado.
ACOTADAS_FUERA_DEL_MODULO = {
    "shared/alerts/observaciones.py::guardar":
        "recibe claves armadas por `observaciones.clave`, que pasa por `clave_acotada` "
        "(lo mide `test_la_clave_de_una_observacion_ENTRA_aunque_sus_partes_no`)",
}

_ACOTADA = object()


class _Opaca(str):
    """Una clave que el lector no pudo resolver; el texto dice por qué."""


def _modulo_de(ruta: pathlib.Path) -> str:
    return ".".join(ruta.relative_to(RAIZ).with_suffix("").parts)


def _es_archivo_de_test(ruta: pathlib.Path) -> bool:
    return ("tests" in ruta.parts or ruta.name.startswith("test_")
            or ruta.name == "conftest.py")


class _LectorDeClaves:
    """Resuelve la expresión `key=` de un `AppSetting(...)` dentro de UN módulo.

    Sigue asignaciones locales, parámetros hasta sus llamadas en el mismo módulo, funciones
    del mismo módulo hasta sus `return`, y constantes del módulo (o importadas de otro). No
    adivina: lo que no puede seguir lo devuelve como `_Opaca` con el motivo.
    """

    def __init__(self, texto: str, modulo: str, importar: bool = True) -> None:
        import ast

        self.arbol = ast.parse(texto)
        self.modulo = modulo
        self.importar = importar
        self.padres = {}
        for nodo in ast.walk(self.arbol):
            for hijo in ast.iter_child_nodes(nodo):
                self.padres[hijo] = nodo

    # ── dónde está cada cosa ──
    def funcion_de(self, nodo):
        import ast

        while nodo in self.padres:
            nodo = self.padres[nodo]
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return nodo
        return None

    def funciones(self, nombre):
        import ast

        return [n for n in ast.walk(self.arbol)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nombre]

    def escrituras(self):
        """`[(funcion, expr)]` de todo `AppSetting(key=...)` del módulo."""
        import ast

        salida = []
        for n in ast.walk(self.arbol):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            nombre = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if nombre != "AppSetting":
                continue
            expr = next((k.value for k in n.keywords if k.arg == "key"),
                        n.args[0] if n.args else None)
            fn = self.funcion_de(n)
            salida.append((fn.name if fn else "<módulo>", expr, fn))
        return salida

    # ── resolución ──
    def resolver(self, expr, fn, profundidad=0):
        import ast

        if profundidad > 6:
            return [_Opaca("cadena de resolución demasiado larga")]
        if expr is None:
            return [_Opaca("`AppSetting(...)` sin clave explícita")]
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return [expr.value]
        if isinstance(expr, ast.Call):
            return self._resolver_llamada(expr, profundidad)
        if isinstance(expr, ast.Name):
            return self._resolver_nombre(expr.id, fn, profundidad)
        return [_Opaca(f"expresión no resoluble: {ast.unparse(expr)}")]

    def _resolver_llamada(self, llamada, profundidad):
        import ast

        f = llamada.func
        nombre = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        if nombre == "clave_acotada":
            return [_ACOTADA]
        definiciones = self.funciones(nombre) if nombre else []
        if not definiciones:
            return [_Opaca(f"llamada a una función de otro módulo: {ast.unparse(llamada)}")]
        salida = []
        for d in definiciones:
            retornos = [r.value for r in ast.walk(d) if isinstance(r, ast.Return)]
            if not retornos:
                salida.append(_Opaca(f"`{nombre}` no devuelve nada"))
            for r in retornos:
                salida.extend(self.resolver(r, d, profundidad + 1))
        return salida

    def _resolver_nombre(self, nombre, fn, profundidad):
        import ast

        if fn is not None:
            asignaciones = [a.value for a in ast.walk(fn)
                            if isinstance(a, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == nombre
                                    for t in a.targets)]
            if asignaciones:
                return [v for a in asignaciones for v in self.resolver(a, fn, profundidad + 1)]
            parametros = [a.arg for a in fn.args.posonlyargs + fn.args.args]
            if nombre in parametros or nombre in [a.arg for a in fn.args.kwonlyargs]:
                return self._resolver_parametro(fn, nombre, profundidad)
        return self._resolver_constante(nombre, fn)

    def _resolver_parametro(self, fn, nombre, profundidad):
        import ast

        posicionales = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        es_metodo = bool(posicionales) and posicionales[0] in ("self", "cls")
        salida = []
        for n in ast.walk(self.arbol):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            llamada = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if llamada != fn.name:
                continue
            arg = next((k.value for k in n.keywords if k.arg == nombre), None)
            if arg is None and nombre in posicionales:
                i = posicionales.index(nombre) - (1 if es_metodo and isinstance(f, ast.Attribute)
                                                  else 0)
                arg = n.args[i] if 0 <= i < len(n.args) else None
            if arg is None:
                salida.append(_Opaca(f"llamada a `{fn.name}` sin `{nombre}` legible"))
                continue
            salida.extend(self.resolver(arg, self.funcion_de(n), profundidad + 1))
        return salida or [_Opaca(f"`{nombre}` es parámetro de `{fn.name}` y nadie la llama "
                                 "en este módulo")]

    def _resolver_constante(self, nombre, fn=None):
        """Literal del módulo, o constante importada —a nivel de módulo o dentro de la
        función, que es como varios módulos traen las claves de `shared.contracts`—."""
        import ast
        import importlib

        for n in self.arbol.body:
            destino = (n.targets if isinstance(n, ast.Assign)
                       else [n.target] if isinstance(n, ast.AnnAssign) else [])
            if (any(isinstance(t, ast.Name) and t.id == nombre for t in destino)
                    and isinstance(getattr(n, "value", None), ast.Constant)
                    and isinstance(n.value.value, str)):
                return [n.value.value]
        importaciones = [n for n in self.arbol.body if isinstance(n, ast.ImportFrom)]
        if fn is not None:
            importaciones += [n for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)]
        for n in importaciones:
            alias = next((a for a in n.names if (a.asname or a.name) == nombre), None)
            if alias is None:
                continue
            if not self.importar or n.level or not n.module:
                return [_Opaca(f"`{nombre}` viene de un import que el lector no sigue")]
            valor = getattr(importlib.import_module(n.module), alias.name, None)
            if isinstance(valor, str):
                return [valor]
        return [_Opaca(f"`{nombre}` no es un literal del módulo")]


def _escrituras_en_app_setting():
    """`[(sitio, claves_resueltas)]` de toda escritura en `app_setting` del código."""
    salida = []
    for carpeta in _CARPETAS_CON_ESCRITORES:
        for ruta in sorted((RAIZ / carpeta).rglob("*.py")):
            if _es_archivo_de_test(ruta):
                continue
            texto = ruta.read_text(encoding="utf-8")
            if "AppSetting(" not in texto:
                continue
            # Se importa el módulo del que viene una constante, nunca el archivo leído: un
            # script de `scripts/` no se ejecuta por ser barrido.
            lector = _LectorDeClaves(texto, _modulo_de(ruta))
            for nombre_fn, expr, fn in lector.escrituras():
                sitio = f"{ruta.relative_to(RAIZ).as_posix()}::{nombre_fn}"
                salida.append((sitio, lector.resolver(expr, fn)))
    return salida


def test_el_lector_de_claves_NO_dice_que_si_a_todo():
    """Un lector que resuelve todo como «entra» pasaría en verde sin mirar. Se le da la forma
    exacta del defecto —una clave armada con un f-string sobre un parámetro— y tiene que
    declararla opaca; y la misma escritura acotada, aceptarla."""
    roto = ("def _key(op):\n    return f'op_status:{op}'\n"
            "def escribir(db, op):\n    db.add(AppSetting(key=_key(op)))\n")
    sano = ("def _key(op):\n    return clave_acotada('op_status', op)\n"
            "def escribir(db, op):\n    db.add(AppSetting(key=_key(op)))\n")
    literal = ("CLAVE = 'x' * 1\nK = 'reporte'\n"
               "def escribir(db):\n    db.add(AppSetting(key=K))\n")
    for texto, esperado in ((roto, _Opaca), (sano, type(_ACOTADA)), (literal, str)):
        lector = _LectorDeClaves(texto, "sintetico", importar=False)
        (_, expr, fn), = lector.escrituras()
        (resuelta,) = lector.resolver(expr, fn)
        assert type(resuelta) is esperado, (texto, resuelta)


def test_toda_clave_escrita_en_app_setting_ENTRA_en_su_columna():
    from shared.settings.models import AppSetting

    tope = AppSetting.__table__.c.key.type.length
    assert tope, "la columna `app_setting.key` dejó de declarar un largo"

    escrituras = _escrituras_en_app_setting()
    literales = [c for _, cs in escrituras for c in cs if type(c) is str]
    assert len(escrituras) >= 25 and len(literales) >= 25, (
        f"solo se leyeron {len(escrituras)} escrituras y {len(literales)} claves literales: "
        "el barrido se quedó ciego y este guard pasaría sin medir")
    assert any(c is _ACOTADA for _, cs in escrituras for c in cs), (
        "ninguna escritura pasa por `clave_acotada`: o el dedup dejó de usarla o el lector falló")

    largas = sorted({(sitio, c) for sitio, cs in escrituras for c in cs
                     if type(c) is str and len(c) > tope})
    assert not largas, (
        f"`app_setting.key` admite {tope} caracteres y estas claves literales no entran "
        f"(SQLite las acepta; PostgreSQL rechaza el INSERT): {largas}")

    opacas = {sitio: sorted({str(c) for c in cs if isinstance(c, _Opaca)})
              for sitio, cs in escrituras}
    opacas = {s: m for s, m in opacas.items() if m}
    sin_declarar = {s: m for s, m in opacas.items() if s not in ACOTADAS_FUERA_DEL_MODULO}
    assert not sin_declarar, (
        "estas escrituras en `app_setting` arman una clave que no se puede acotar leyendo el "
        "código. Pasala por `shared.settings.models.clave_acotada` (acota por construcción "
        "sin cambiar las claves que ya entran), o declarala en ACOTADAS_FUERA_DEL_MODULO con "
        f"lo que la acota: {sin_declarar}")
    sobrantes = set(ACOTADAS_FUERA_DEL_MODULO) - set(opacas)
    assert not sobrantes, (
        f"ACOTADAS_FUERA_DEL_MODULO declara sitios que ya no hace falta declarar: {sobrantes}")


def test_la_clave_de_una_observacion_ENTRA_aunque_sus_partes_no():
    """La contraparte de la entrada declarada en ACOTADAS_FUERA_DEL_MODULO: la observación
    lleva eje, sujeto (un UUID) y métrica (`publicacion:<clave de informe>`), ninguno acotado."""
    from shared.alerts import observaciones
    from shared.settings.models import AppSetting

    tope = AppSetting.__table__.c.key.type.length
    corta = observaciones.clave("banking", "", "validacion_stale")
    assert corta == "alert_obs:banking::validacion_stale"   # lo persistido conserva su forma
    larga = observaciones.clave("banking_year_review", "aea314c5-876a-404d-8446-523c7b0d9869",
                                "publicacion:" + "x" * 200)
    assert len(larga) <= tope, len(larga)


def test_todo_buzon_de_dedup_ACOTA_su_clave():
    """El marcador de un `Dedup` lleva lo que el consumidor le pase —UUIDs, nombres de regla,
    claves de informe—, así que ningún largo de entrada puede producir una clave que no entre.
    Se instancian los prefijos REALES del código, no uno de ejemplo."""
    import ast

    from shared.notifications.dedup import Dedup
    from shared.settings.models import AppSetting

    tope = AppSetting.__table__.c.key.type.length
    prefijos = set()
    for carpeta in _CARPETAS_CON_ESCRITORES:
        for ruta in (RAIZ / carpeta).rglob("*.py"):
            if _es_archivo_de_test(ruta) or "Dedup(" not in ruta.read_text(encoding="utf-8"):
                continue
            for n in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
                if (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Dedup"
                        and n.args and isinstance(n.args[0], ast.Constant)):
                    prefijos.add(n.args[0].value)
    assert len(prefijos) >= 4, f"solo se encontraron {prefijos}: el barrido se quedó ciego"

    for prefijo in sorted(prefijos):
        buzon = Dedup(prefijo)
        for largo in (1, 60, 89, 90, 1000):
            clave = buzon._key("x" * largo)
            assert len(clave) <= tope, (prefijo, largo, len(clave))
        # Lo que ya entraba conserva su forma: los marcadores persistidos siguen valiendo.
        assert buzon._key("corta") == f"{prefijo}:corta"


# ── La procedencia entra en TODA tabla que la guarda, medida contra quien la ESCRIBE ──────
#
# Tercera vez de la misma familia en diez días: `rb_country_aggregates.metric` (#1160),
# `sector_observations.license` (MIVHED, 278 > 200) y `insurance_series.license` (#1169,
# SISALRIL 245 > 160, dos syncs de prod sin persistir desde el 2026-09-02). Cada arreglo
# vigiló SU tabla, y la siguiente reventó en otra. Este guard no nombra tablas: toma TODO
# modelo con `period` y `source`/`license`, busca los módulos que lo escriben por lo que el
# código HACE —`Modelo(` o `.source =`/`.license =`— y mide contra la columna:
#
#   · los conectores de `shared.data` que importan esos módulos, y los de los módulos que
#     importan a un escritor (el `service` que recibe las filas armadas por su `*_sync`);
#   · los literales y constantes que aparecen en el lado derecho de la escritura.
#
# Medir contra el conector MÁS largo del catálogo es demasiado estricto (un ONE de 82 no
# escribe `ti_flows`); medir solo lo que efectivamente escribe es lo que dice si PostgreSQL
# rechaza el INSERT. También veta RECORTAR la procedencia en la escritura (`licencia[:120]`):
# eso no cura la truncación, la vuelve silenciosa y publica una licencia mutilada.
#
# Lo que queda afuera: procedencia armada fuera de `shared.data` y de los literales del
# escritor (un parámetro que viaja más de un salto), y escrituras por SQL crudo.

_CAMPOS_DE_PROCEDENCIA = ("source", "license")
_NOMBRE_DE_CONSTANTE = {
    "source": re.compile(r"(?i)(^|_)(source|fuente)(_|$)"),
    "license": re.compile(r"(?i)(^|_)(license|licen[cs]e|licencia)(_|$)"),
}

#: Tablas con procedencia que HOY no tienen escritor en el código. Cada entrada dice por qué;
#: si aparece un escritor, el guard exige quitarla para que la mida.
SIN_ESCRITOR_EN_EL_CODIGO = {
    "esg_indicators": "el módulo ESG solo la BORRA (`api/router.py`, reset); nada la llena",
}


def _tablas_con_procedencia():
    """`{clase: tabla}` de todo modelo mapeado con `period` y `source` o `license`."""
    import app.main  # noqa: F401 — registra los modelos de todos los módulos
    from shared.database.base import Base

    salida = {}
    for mapper in Base.registry.mappers:
        cols = mapper.local_table.c
        if "period" in cols and any(c in cols for c in _CAMPOS_DE_PROCEDENCIA):
            salida[mapper.class_.__name__] = mapper.local_table
    return salida


def _nombre_llamado(llamada):
    f = llamada.func
    return f.id if hasattr(f, "id") else getattr(f, "attr", None)


class _LectorDeProcedencia:
    """Lo que UN módulo escribe como procedencia de un modelo, leído del AST."""

    def __init__(self, ruta: pathlib.Path, texto: str) -> None:
        import ast

        self.ruta = ruta
        self.arbol = ast.parse(texto)
        self.constantes = {
            t.id: n.value.value
            for n in self.arbol.body if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            for t in n.targets if isinstance(t, ast.Name)}

    def escrituras(self, modelo: str, menciona_modelo: bool):
        """`[(campo, expr)]`: `Modelo(campo=...)`, `Lineage(campo=...)` y `x.campo = ...`.

        La asignación por atributo solo cuenta en módulos que nombran el modelo: `x.source =`
        es genérico y sin esa condición el barrido le atribuiría escrituras de otras tablas.
        """
        import ast

        salida = []
        construye = False
        for n in ast.walk(self.arbol):
            if isinstance(n, ast.Call) and _nombre_llamado(n) in (modelo, "Lineage"):
                construye |= _nombre_llamado(n) == modelo
                salida += [(k.arg, k.value) for k in n.keywords
                           if k.arg in _CAMPOS_DE_PROCEDENCIA]
            elif isinstance(n, ast.Assign) and menciona_modelo:
                salida += [(t.attr, n.value) for t in n.targets
                           if isinstance(t, ast.Attribute) and t.attr in _CAMPOS_DE_PROCEDENCIA]
        return construye, salida

    def conectores_importados(self, campos):
        """`[(origen, campo, valor)]` de lo que el módulo importa de `shared.data`."""
        import ast
        import importlib
        import types

        salida = []
        for n in ast.walk(self.arbol):
            if not (isinstance(n, ast.ImportFrom) and n.module
                    and n.module.startswith("shared.data")):
                continue
            mod = importlib.import_module(n.module)
            for alias in n.names:
                obj = getattr(mod, alias.name, None)
                # Funciones y submódulos no declaran procedencia; clases, instancias
                # (`sipen_client`) y constantes (`SOURCE`, `LICENSE`) sí.
                if isinstance(obj, types.ModuleType) or (
                        callable(obj) and not isinstance(obj, type)):
                    continue
                for campo in campos:
                    if isinstance(obj, str):
                        if _NOMBRE_DE_CONSTANTE[campo].search(alias.name):
                            salida.append((f"{n.module}.{alias.name}", campo, obj))
                    else:
                        valor = getattr(obj, campo, None)
                        if isinstance(valor, str) and valor:
                            salida.append((f"{n.module}.{alias.name}", campo, valor))
        return salida

    def literales(self, campo, expr):
        """Literales y constantes del módulo en el lado derecho, y si la escritura RECORTA."""
        import ast

        valores, recorta = [], False
        for n in ast.walk(expr):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value:
                valores.append(n.value)
            elif isinstance(n, ast.Name) and n.id in self.constantes:
                valores.append(self.constantes[n.id])
            elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice):
                recorta = True
        return valores, recorta


def _procedencia_por_tabla():
    """`{tabla: {"columnas", "escritores", "medidas", "recortes"}}` de todo el código."""
    import ast

    tablas = _tablas_con_procedencia()
    archivos = []
    for carpeta in _CARPETAS_CON_ESCRITORES:
        for ruta in sorted((RAIZ / carpeta).rglob("*.py")):
            if not _es_archivo_de_test(ruta) and "models" not in ruta.parts:
                archivos.append((ruta, ruta.read_text(encoding="utf-8")))

    # Quién importa a quién, para seguir un salto: el `service` que persiste lo que arma su
    # `*_sync` no importa el conector; lo importa el que lo llama.
    importadores = {}
    for ruta, texto in archivos:
        for n in ast.walk(ast.parse(texto)):
            if isinstance(n, ast.ImportFrom) and n.module:
                importadores.setdefault(n.module, set()).add(ruta)
    textos = dict(archivos)

    salida = {}
    for modelo, tabla in sorted(tablas.items()):
        campos_tabla = [c for c in _CAMPOS_DE_PROCEDENCIA if c in tabla.c]
        info = {"columnas": {c: getattr(tabla.c[c].type, "length", None) for c in campos_tabla},
                "escritores": [], "medidas": [], "recortes": []}
        for ruta, texto in archivos:
            if modelo not in texto:
                continue
            lector = _LectorDeProcedencia(ruta, texto)
            construye, escrituras = lector.escrituras(modelo, menciona_modelo=True)
            asigna = any(isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr in campos_tabla for t in n.targets)
                for n in ast.walk(lector.arbol))
            if not (construye or asigna):
                continue
            sitio = ruta.relative_to(RAIZ).as_posix()
            campos = sorted({c for c, _ in escrituras if c in campos_tabla})
            info["escritores"].append(sitio)
            for campo, expr in escrituras:
                if campo not in campos_tabla:
                    continue
                valores, recorta = lector.literales(campo, expr)
                info["medidas"] += [(f"{sitio} (literal)", campo, v) for v in valores]
                if recorta:
                    info["recortes"].append(f"{sitio}: {campo} = {ast.unparse(expr)}")
            info["medidas"] += lector.conectores_importados(campos)
            modulo = _modulo_de(ruta)
            for otro in importadores.get(modulo, ()):
                info["medidas"] += _LectorDeProcedencia(otro, textos[otro]) \
                    .conectores_importados(campos)
        salida[tabla.name] = info
    return salida


def _no_entran(procedencia, topes=None):
    """`[texto]` de cada valor que no entra en su columna (con *topes* se simula un largo)."""
    salida = set()
    for nombre, info in procedencia.items():
        for origen, campo, valor in info["medidas"]:
            tope = (topes or {}).get(f"{nombre}.{campo}", info["columnas"].get(campo))
            if tope is not None and len(valor) > tope:
                salida.add((f"{nombre}.{campo}", f"{origen}: {len(valor)} > {tope}"))
    return sorted(salida)


def test_el_barrido_de_procedencia_ENCUENTRA_escritores_en_cada_tabla():
    """Un barrido ciego pasa en verde: toda tabla con procedencia tiene que tener escritor y
    algo MEDIDO en cada campo que se escribe, salvo las declaradas sin escritor."""
    procedencia = _procedencia_por_tabla()
    assert len(procedencia) >= 10, (
        f"solo {len(procedencia)} tablas con `period` y procedencia: el registro de modelos "
        f"no se cargó entero: {sorted(procedencia)}")

    ciegas = {n for n, i in procedencia.items() if not i["escritores"] or not i["medidas"]}
    sin_declarar = ciegas - set(SIN_ESCRITOR_EN_EL_CODIGO)
    assert not sin_declarar, (
        "el barrido no encontró escritores o no midió nada en estas tablas. O el lector se "
        "quedó ciego, o la tabla no tiene escritor y va a SIN_ESCRITOR_EN_EL_CODIGO con el "
        f"motivo: { {n: procedencia[n]['escritores'] for n in sorted(sin_declarar)} }")
    sobrantes = set(SIN_ESCRITOR_EN_EL_CODIGO) - ciegas
    assert not sobrantes, (
        f"SIN_ESCRITOR_EN_EL_CODIGO declara tablas que ya tienen escritor medido: {sobrantes}")

    # Los escritores que ya reventaron en prod tienen que estar a la vista, o el lector
    # cambió de forma sin que nadie lo note.
    seguros = {o for o, _, _ in procedencia["insurance_series"]["medidas"]}
    for esperado in ("SISClient", "SISALRILClient", "SISALRILARSClient", "SISSolvencyClient"):
        assert any(o.endswith(f".{esperado}") for o in seguros), (esperado, sorted(seguros))


def test_el_guard_de_procedencia_NO_dice_que_si_a_todo():
    """Se acorta una columna que hoy entra: el guard tiene que nombrarla."""
    procedencia = _procedencia_por_tabla()
    assert not [f for f, _ in _no_entran(procedencia) if f.startswith("ti_partner_chapters")]
    simulado = _no_entran(procedencia, topes={"ti_partner_chapters.license": 10})
    assert any(f == "ti_partner_chapters.license" for f, _ in simulado), simulado


def test_la_procedencia_ENTRA_en_toda_tabla_que_la_guarda():
    procedencia = _procedencia_por_tabla()
    no_entran = _no_entran(procedencia)
    assert not no_entran, (
        "estos escritores guardan procedencia más larga que su columna. En SQLite el INSERT "
        "pasa; en PostgreSQL el sync entero falla con StringDataRightTruncation y la consola "
        "sigue mostrando el `last_result` de la corrida buena anterior. `license` va a TEXT y "
        f"`source` a String(120), con migración `batch_alter_table`: {no_entran}")


def test_ninguna_escritura_RECORTA_la_procedencia():
    """`licencia[:120]` no cura la truncación: la vuelve silenciosa y publica una licencia
    mutilada como si fuera la del emisor. Se agranda la columna; la cadena viaja entera."""
    recortes = [r for info in _procedencia_por_tabla().values() for r in info["recortes"]]
    assert not recortes, recortes

