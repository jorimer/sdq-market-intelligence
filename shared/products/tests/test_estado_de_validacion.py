"""REGLA ESTRUCTURAL: ningún eje del catálogo calla su estado de validación.

**El caso.** Siete de los dieciséis ejes no tenían backtest y el catálogo no decía por qué.
«Sin validación» se leía como una tarea pendiente, cuando en cinco de ellos es una
imposibilidad de diseño: el índice tiene UN solo sujeto —el país— y un Gini o un IC de rango
necesitan un corte transversal que ordenar. Con esa distinción invisible, la pregunta «¿por
qué este eje no está validado?» se contestaba con un encogimiento de hombros en cada reunión,
y un eje que calla su falta de validación es peor que uno que la declara: el silencio se lee
como que sí la tiene.

**La regla.** Todo eje de `PRODUCT_CATALOG` declara `ESTADO_BACKTEST` en su clase de
producto, y la declaración tiene que ser verificable:

1. Si dice tener motor, el motor tiene que EXISTIR en `shared.validation.frescura.MOTORES`.
   Es el cruce entre los dos registros: un producto no puede reclamar una validación que
   nadie registró.
2. Si dice NO tenerlo, tiene que declarar un obstáculo de la lista cerrada y explicarlo.
   «Pendiente» no es un obstáculo.
3. Si el obstáculo es `dato_pendiente`, tiene que nombrar QUÉ dato falta. Sin eso, la brecha
   no se puede cerrar ni presupuestar.

El estado declara hechos de DISEÑO, no el veredicto de la última corrida: si concluye o no
lo dice el reporte, que se recalcula. Poner el veredicto acá lo congelaría — el defecto que
abrió este plan.
"""
import pytest

from shared.products.contract import OBSTACULOS_BACKTEST


def _ejes():
    import app.main  # noqa: F401 — auto-registra productos y motores reales
    from shared.products.registry import PRODUCT_CATALOG, get_product

    return [(e.sector_key, get_product(e.sector_key, None)) for e in PRODUCT_CATALOG]


def _estado(producto):
    return getattr(type(producto), "ESTADO_BACKTEST", None)


def test_los_dieciseis_ejes_declaran_su_estado_de_validacion():
    sin_declarar = [k for k, p in _ejes() if p is None or _estado(p) is None]
    assert not sin_declarar, (
        f"Estos ejes del catálogo no declaran `ESTADO_BACKTEST`: {sin_declarar}. "
        "Un eje que calla su falta de validación se lee como si la tuviera."
    )


def test_el_que_dice_tener_motor_lo_tiene_registrado_de_verdad():
    """Cruce entre los dos registros: producto ↔ motor de validación."""
    from shared.validation.frescura import MOTORES

    mentiras = []
    for clave, p in _ejes():
        est = _estado(p)
        if est and est.tiene_motor:
            if not est.eje_motor:
                mentiras.append(f"{clave}: dice tener motor y no nombra cuál (`eje_motor`)")
            elif est.eje_motor not in MOTORES:
                mentiras.append(f"{clave}: declara el motor '{est.eje_motor}', que no está "
                                f"registrado en shared.validation.frescura")
    assert not mentiras, "\n  ".join(["Productos que reclaman una validación inexistente:"]
                                     + mentiras)


def test_el_que_no_tiene_motor_declara_un_obstaculo_de_la_lista_cerrada():
    fallos = []
    for clave, p in _ejes():
        est = _estado(p)
        if est and not est.tiene_motor:
            if est.obstaculo not in OBSTACULOS_BACKTEST:
                fallos.append(f"{clave}: obstáculo '{est.obstaculo}' no es uno de "
                              f"{list(OBSTACULOS_BACKTEST)}")
    assert not fallos, "\n  ".join(["Ejes sin motor y sin obstáculo declarado:"] + fallos)


def test_el_motivo_explica_en_vez_de_rotular():
    """Un motivo de tres palabras es un rótulo, y un rótulo no se puede discutir."""
    cortos = [f"{k} ({len((_estado(p).motivo or '').split())} palabras)"
              for k, p in _ejes() if _estado(p) and len((_estado(p).motivo or "").split()) < 12]
    assert not cortos, f"Motivos que no explican: {cortos}"


def test_dato_pendiente_nombra_el_dato_que_falta():
    """Una brecha sin nombre no se puede cerrar ni presupuestar."""
    anonimas = [k for k, p in _ejes()
                if (e := _estado(p)) and e.obstaculo == "dato_pendiente"
                and not (e.dato_que_falta or "").strip()]
    assert not anonimas, f"Ejes con dato pendiente y sin nombrarlo: {anonimas}"


def test_el_estado_no_congela_el_veredicto_de_la_ultima_corrida():
    """El estado declara diseño; si concluye o no lo dice el reporte, que se recalcula.

    Un `EstadoBacktest` que dijera «concluyente» sería exactamente el artefacto que este
    plan vino a eliminar: una afirmación de validación que sobrevive al cambio de su dato.
    """
    from dataclasses import fields

    from shared.products.contract import EstadoBacktest

    nombres = {f.name for f in fields(EstadoBacktest)}
    assert "conclusive" not in nombres and "concluyente" not in nombres
    assert "gini" not in nombres and "ic" not in nombres


@pytest.mark.parametrize("clave_esperada", ["tourism", "free_zones", "energy",
                                            "construction", "telecom", "law"])
def test_los_ejes_sin_backtest_del_catalogo_siguen_declarando(clave_esperada):
    """Fija el triaje de la Fase 4: estos seis no tienen motor y dicen por qué.

    Si alguno gana un motor, este test falla y obliga a actualizar el triaje en vez de
    dejar la lista vieja conviviendo con la realidad nueva.
    """
    est = dict(_ejes())[clave_esperada]
    e = _estado(est)
    assert e is not None and e.tiene_motor is False
    assert e.obstaculo in OBSTACULOS_BACKTEST
