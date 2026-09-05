"""T-PS-4 · Integridad permanente del corpus canónico del BCRD (§4 del spec).

Las siete aserciones del spec verifican propiedades de `mm_series` en un despliegue con el
corpus ingerido, y CI no tiene ese corpus: correr la ingesta acá pediría red y modelo. Un
test que se limite a lo que hay en una base vacía pasa siempre y no protege de nada — es el
mismo agujero que un `@parametrize` sin casos.

Por eso el contrato se congela en un MANIFIESTO (`manifiesto_persistencia_canonica.json`),
generado de una corrida real y comiteado. El manifiesto no es un espejo del dato: es la
lista de lo que cada entrada canónica DEBE producir, con el mínimo de observaciones que ya
alcanzó. Eso lo vuelve verificable sin base y estable en el tiempo:

* si alguien agrega una entrada canónica con puente y no corre la ingesta, falta en el
  manifiesto y el test lo dice;
* si un cambio del extractor renombra una serie, el código del manifiesto deja de coincidir;
* si una lectura se trunca, `min_obs` baja — y `min_obs` no puede bajar, porque el BCRD no
  retira historia. Ese es el defecto que más veces apareció en este corpus.

Lo que el manifiesto NO congela: el número exacto de observaciones, que crece cada mes. Un
test que lo fijara fallaría solo, todos los meses, y se terminaría desactivando.
"""
import json
import re
from pathlib import Path

import pytest

from modules.macro_monitor import service
from shared.data.bcrd_excel import canonical
from shared.data.series_cadence import DESDE_ESPANOL, cadencia_de_periodo

MANIFIESTO = json.loads(
    (Path(__file__).parent / "manifiesto_persistencia_canonica.json").read_text())
SERIES = MANIFIESTO["series"]

#: Las entradas SIN puente, con el motivo por el que no lo tienen. La lista es explícita y
#: exhaustiva a propósito: el spec pedía «una lista de excepciones con motivo», y meterlas a
#: todas bajo una excusa genérica dejaría sin cubrir a un tercio del registro — que no es una
#: excepción, es un agujero. Cada motivo dice por qué la elección es de un ANALISTA y no algo
#: que el código pueda decidir.
SIN_PUENTE = {
    "inflacion_interanual":
        "no es una columna del archivo: el IPC publica el índice y su variación MENSUAL, y "
        "la interanual la computa la plataforma. Un puente apuntaría a una serie que el "
        "emisor no publica.",
    "pib_sectores_origen":
        "no es UNA serie sino una familia de 326: el archivo publica cinco cuadros (nivel, "
        "volumen encadenado, tasas, incidencia y ponderación) por cada actividad. Elegir un "
        "sufijo sería elegir un sector.",
    "pib_nominal_gasto":
        "el archivo publica niveles y ponderaciones en dos cuadros por hoja, y cuál es la "
        "serie canónica —¿el PIB total, el consumo, la formación de capital?— depende del "
        "uso. Sin esa decisión tomada, un puente inventaría una.",
    "balanza_pagos_mbp6":
        "57 series jerárquicas; el titular sería la cuenta corriente, pero la entrada "
        "canónica nombra la BALANZA entera, que no es una serie sino el cuadro.",
    "balanza_pagos_mbp5":
        "mismo motivo que el MBP6 —54 series jerárquicas y ninguna que sea «la» balanza— y "
        "encima descontinuada: su propia nota manda usarla solo antes de 2010, así que un "
        "puente tendría que declarar además el tramo.",
    "pii_mbp6":
        "el cuadro cruza activos y pasivos por instrumento y sector con seis conceptos por "
        "año (saldo de apertura, cuatro flujos y saldo de cierre): 780 series. La posición "
        "NETA, que sería el titular, el BCRD no la publica como fila.",
    "pii_mbp5":
        "mismo cruce de activos y pasivos por instrumento y sector que el MBP6 —576 "
        "series— y descontinuada desde 2013: la entrada existe para el tramo histórico, no "
        "para citar una serie.",
    "agregados_monetarios":
        "M1, M2 y M3 son tres series distintas y la entrada nombra al conjunto. Un puente "
        "obligaría a elegir un agregado y la elección depende de qué se esté midiendo.",
    "base_monetaria":
        "restringida y amplia son dos definiciones, las dos oficiales y las dos publicadas. "
        "Elegir una en el registro escondería la otra.",
    "tipo_cambio":
        "siete cortes (diario, mensual, trimestral, anual y sus versiones de fin de "
        "período) y compra/venta en cada uno: catorce series. Cuál es «el» tipo de cambio "
        "depende de para qué.",
    "tasa_ocupacion":
        "el archivo publica dos tramos anuales y uno semestral, con un quiebre de encuesta "
        "en el medio; la serie canónica exige antes la decisión de empalme.",
    "tasa_desocupacion":
        "ídem ocupación, y además dos definiciones (abierta y ampliada) que no son "
        "intercambiables.",
    "llegada_turistas":
        "el archivo publica varios cortes de años como hojas separadas y falta "
        "consolidarlos; hasta entonces no hay UNA serie que citar.",
}

_TRES = ("pib_real", "imae_indice", "ipc_general")


def _con_puente():
    return [e for e in canonical.registry() if e.excel_series_suffix]


# ── Aserción 1 · cada entrada con puente resuelve a una serie persistida ──────────────
def test_toda_entrada_con_puente_esta_en_el_manifiesto():
    faltan = [e.key for e in _con_puente() if e.key not in SERIES]
    assert not faltan, (
        f"entradas canónicas con puente que nunca se vieron persistidas: {faltan}. "
        "Si la entrada es nueva, correr la ingesta y regenerar el manifiesto; si el puente "
        "cambió, el que está mal es el manifiesto o el sufijo.")


@pytest.mark.parametrize("entrada", _con_puente(), ids=lambda e: e.key)
def test_el_puente_construye_el_codigo_del_manifiesto(entrada):
    """El sufijo tiene que seguir apuntando a la misma serie. Un renombrado del extractor
    que no pase por acá deja la entrada canónica apuntando al vacío."""
    code = SERIES[entrada.key]["code"]
    assert code.endswith(entrada.excel_series_suffix), (
        f"«{entrada.key}» declara el sufijo {entrada.excel_series_suffix!r} y la serie "
        f"persistida es {code}")


def test_el_puente_identifica_dentro_de_su_archivo_y_no_en_todo_el_corpus():
    """`serie_original_indice` existe en el PIB y en el IMAE; `quintil_3` en el IPC por
    quintiles y en el costo de la canasta. Resolver el sufijo globalmente devuelve la serie
    equivocada — por eso `canonical.codigo_de` acota por el archivo de la entrada."""
    todos = [d["code"] for d in SERIES.values()]
    ambiguos = [e.key for e in _con_puente()
                if sum(1 for c in todos if c.endswith(e.excel_series_suffix)) > 1]
    assert ambiguos, ("si ya no hay sufijos compartidos, este test perdió su motivo: "
                      "revisar si `codigo_de` sigue haciendo falta")
    for e in _con_puente():
        assert canonical.codigo_de(e, todos) == SERIES[e.key]["code"], (
            f"`codigo_de` no resuelve «{e.key}» a su serie")


# ── Aserción 2 · las entradas sin puente están declaradas, con motivo ────────────────
def test_las_entradas_sin_puente_estan_declaradas_una_por_una():
    reales = {e.key for e in canonical.registry() if not e.excel_series_suffix}
    assert reales == set(SIN_PUENTE), (
        f"sin declarar: {sorted(reales - set(SIN_PUENTE))} · "
        f"declaradas de más: {sorted(set(SIN_PUENTE) - reales)}")


@pytest.mark.parametrize("clave", sorted(SIN_PUENTE))
def test_cada_excepcion_explica_por_que(clave):
    motivo = SIN_PUENTE[clave]
    assert len(motivo) > 60, f"«{clave}» no explica nada: {motivo!r}"


# ── Aserciones 3 y 4 · cadencia presente, y coincidente con el canónico ──────────────
@pytest.mark.parametrize("entrada", _con_puente(), ids=lambda e: e.key)
def test_la_cadencia_persistida_coincide_con_la_declarada(entrada):
    persistida = SERIES[entrada.key]["cadencia"]
    assert persistida not in (None, "", "unknown", "mixta"), (
        f"«{entrada.key}» quedó sin cadencia resoluble: {persistida!r}")
    declarada = DESDE_ESPANOL.get((entrada.frequency or "").lower())
    assert declarada == persistida, (
        f"«{entrada.key}» se declara {entrada.frequency!r} ({declarada}) y sus períodos "
        f"dicen {persistida}")


# ── Aserción 5 · ninguna serie mezcla formas de período ─────────────────────────────
def test_ninguna_serie_mezcla_formas_de_periodo():
    mezcladas = [k for k, d in SERIES.items() if d["cadencia"] == "mixta"]
    assert not mezcladas, (
        f"series con períodos de más de una forma —el eje temporal se leyó mal—: {mezcladas}")


@pytest.mark.parametrize("clave", sorted(SERIES))
def test_el_primer_periodo_tiene_la_forma_de_su_cadencia(clave):
    d = SERIES[clave]
    assert cadencia_de_periodo(d["primero"]) == d["cadencia"]


# ── Aserción 6 · continuidad ────────────────────────────────────────────────────────
@pytest.mark.parametrize("clave", _TRES)
def test_las_tres_series_del_modelo_no_tienen_huecos(clave):
    """Un hueco de un trimestre en el medio es invisible al ojo y fatal para un modelo con
    rezagos. Se verifica en test, no en revisión visual."""
    assert clave in SERIES, f"«{clave}» no está en el manifiesto"
    assert SERIES[clave]["huecos"] == 0, (
        f"«{clave}» tiene {SERIES[clave]['huecos']} período(s) faltantes en el medio")


#: Series cuya DISCONTINUIDAD no es un defecto de lectura sino la forma del dato. Cada una
#: con su motivo: una lista sin motivos se llena por inercia y deja de proteger.
#:
#: La prueba de que una entrada pertenece acá no es que tenga huecos —eso lo tiene también
#: una serie mal leída— sino que el hueco corresponda a un HECHO que no ocurrió. Un mes sin
#: subasta no tiene tasa de subasta; un mes sin publicación de un índice mensual sí debería
#: tener índice, y ése sigue siendo un defecto.
DISCONTINUAS_POR_NATURALEZA = {
    "curva_pesos_mas_de_dos_anos": (
        "La curva soberana en pesos sale de SUBASTAS, no de un calendario. El Banco Central "
        "coloca el plazo largo cuando lo necesita, no todos los meses, y el cuadro deja el "
        "mes en blanco —o anota un 0 con el monto vacío— cuando no hubo colocación. Un mes "
        "sin subasta no tiene tasa de subasta: el hueco ES el dato. Rellenarlo con el mes "
        "anterior inventaría una colocación que no existió, y es justo lo que "
        "`rf_de_la_curva` evita al tomar las últimas lecturas VIVAS en vez de la última "
        "casilla del calendario."),
    "curva_pesos_de_1_a_2_anos": (
        "Mismo cuadro y mismo motivo, y más marcado: el tramo de uno a dos años es el que "
        "menos se subasta de los seis, así que su serie es la más rala. Se conserva porque "
        "con el término largo da la PENDIENTE de la curva."),
}


def test_ninguna_serie_canonica_tiene_huecos():
    """La continuidad sigue siendo la regla; la excepción se nombra y se justifica."""
    con_huecos = {k: d["huecos"] for k, d in SERIES.items()
                  if d["huecos"] and k not in DISCONTINUAS_POR_NATURALEZA}
    assert not con_huecos, f"series con huecos internos: {con_huecos}"


def test_toda_serie_declarada_DISCONTINUA_lo_es_de_verdad():
    """Una excepción para una serie que resultó continua es una excepción de más: quedaría
    tapando el día que esa serie SÍ desarrolle un hueco de lectura."""
    for clave in DISCONTINUAS_POR_NATURALEZA:
        assert clave in SERIES, f"«{clave}» declarada discontinua y no está en el manifiesto"
        assert SERIES[clave]["huecos"] > 0, (
            f"«{clave}» está declarada discontinua por naturaleza y no tiene huecos: sacala "
            "de la lista para que el guard vuelva a cubrirla")


def test_toda_excepcion_de_continuidad_explica_POR_QUE_el_hueco_es_el_dato():
    for clave, motivo in DISCONTINUAS_POR_NATURALEZA.items():
        assert len(motivo) > 150, f"«{clave}» excepcionada sin explicar la naturaleza del dato"
        assert "subasta" in motivo.lower() or "no ocurrió" in motivo.lower(), (
            f"«{clave}»: el motivo tiene que decir qué HECHO no ocurrió en el mes vacío, no "
            "solo que la serie es rala")


def test_el_pib_real_alcanza_para_el_bvar():
    """El número que decide si el motor de proyección procede como está especificado."""
    assert SERIES["pib_real"]["min_obs"] >= 60, (
        f"`pib_real` tiene {SERIES['pib_real']['min_obs']} trimestres: por debajo de 60 el "
        "BVAR del spec de proyección hay que replantearlo")


# ── Aserción 7 · ningún valor pasa de no-nulo a nulo ────────────────────────────────
def test_el_guard_de_nulos_sigue_en_la_frontera_de_escritura():
    """La aserción se verifica de verdad en `test_upsert_dedupe.py`, que ejercita el upsert
    entre corridas. Acá se fija que la GUARDA siga existiendo: es una línea de tres palabras
    dentro de una rama de asignaciones, y quitarla no rompe ningún test de forma."""
    import ast
    import inspect

    fuente = inspect.getsource(service._upsert_records)
    arbol = ast.parse(fuente.lstrip())
    guardas = [n for n in ast.walk(arbol)
               if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
               and isinstance(n.test.ops[0], ast.IsNot)
               and isinstance(n.test.comparators[0], ast.Constant)
               and n.test.comparators[0].value is None]
    assert guardas, (
        "`_upsert_records` ya no protege el valor persistido de un nulo posterior: "
        "desapareció el `if r.value is not None`. Ver §2.2.1 del spec.")


def test_la_ingesta_poda_lo_que_dejo_de_escribir():
    """La otra mitad del arrastre: que el upsert no borre está bien, pero entonces alguien
    tiene que llevarse los códigos que el extractor dejó de producir. Lo hace la propia
    sincronización, con sus frenos — ver `test_poda_en_la_ingesta.py`."""
    import inspect

    assert "podar" in inspect.signature(service.ingest_canonical).parameters
    from modules.macro_monitor import operations
    assert "podar=True" in inspect.getsource(operations), (
        "la operación programada dejó de podar: el arrastre vuelve a acumularse en silencio")
