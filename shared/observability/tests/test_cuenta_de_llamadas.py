"""La cuenta de llamadas al modelo: el importe y lo que NO se pudo convertir, juntos.

**Por qué un total no puede ser un float pelado.** ``estimate_cost`` cae a la tarifa Sonnet
para cualquier modelo fuera de ``PRICING_PER_MTOK``, y devuelve un número con la misma cara
que una medición. Una suma que la absorbe en silencio publica una suposición como si fuera
una cifra. Acá se comprueba que el importe viaja SIEMPRE con cuántas llamadas lo produjeron y
cuántas salieron de una tarifa supuesta.
"""
import asyncio

import pytest

from shared.observability.llm_ledger import (
    PURPOSE_ROUTING,
    contar_llamadas,
    record_call,
)

_TARIFADO = "claude-sonnet-4-6"
_SIN_TARIFA = "un-modelo-que-no-esta-en-la-tabla"


def _llamada(model=_TARIFADO, costo=0.01, hit=False):
    record_call(purpose=PURPOSE_ROUTING, model=model, cost_usd=costo, cache_hit=hit)


def test_el_importe_viaja_con_el_conteo_que_lo_produjo():
    with contar_llamadas() as c:
        _llamada(costo=0.01)
        _llamada(costo=0.02)
    assert c.costo_usd == pytest.approx(0.03)
    assert c.llamadas == 2
    assert c.costo_es_exacto


def test_una_tarifa_SUPUESTA_no_se_absorbe_en_el_total():
    """El importe sigue siendo el mejor que tenemos; lo que no puede es callar su origen."""
    with contar_llamadas() as c:
        _llamada(model=_TARIFADO, costo=0.01)
        _llamada(model=_SIN_TARIFA, costo=0.05)
    assert c.llamadas_sin_tarifa == 1
    assert not c.costo_es_exacto, (
        "el total se presenta como exacto incluyendo una llamada costeada con una tarifa "
        "que no es la del modelo")
    assert c.costo_usd == pytest.approx(0.06), "y sin embargo el importe no se descarta"


def test_un_cero_MEDIDO_se_distingue_de_un_cero_por_no_haber_medido():
    """Cero llamadas y cero costo es un hecho; el conteo al lado es lo que lo dice."""
    with contar_llamadas() as c:
        pass
    assert (c.costo_usd, c.llamadas) == (0.0, 0)


def test_un_HIT_de_cache_cuesta_cero_de_verdad_y_se_cuenta_aparte():
    with contar_llamadas() as c:
        _llamada(model=_SIN_TARIFA, costo=0.0, hit=True)
    assert c.hits_de_cache == 1
    # Un HIT no paga tarifa, así que no ensucia la exactitud del importe.
    assert c.llamadas_sin_tarifa == 0 and c.costo_es_exacto


def test_dos_cuentas_ANIDADAS_ven_las_mismas_llamadas_y_no_se_pisan():
    with contar_llamadas() as fuera:
        _llamada(costo=0.01)
        with contar_llamadas() as dentro:
            _llamada(costo=0.02)
        _llamada(costo=0.04)
    assert dentro.costo_usd == pytest.approx(0.02)
    assert fuera.costo_usd == pytest.approx(0.07)


def test_una_llamada_fuera_del_bloque_NO_entra():
    with contar_llamadas() as c:
        _llamada(costo=0.01)
    _llamada(costo=99.0)
    assert c.costo_usd == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_las_ramas_de_un_gather_suman_a_la_MISMA_cuenta():
    """Un `contextvar` se COPIA por tarea: si la cuenta fuera un valor inmutable, cada rama
    sumaría a su propia copia y el total del tramo saldría en cero sin que nada fallara."""
    async def rama(costo):
        await asyncio.sleep(0)
        _llamada(costo=costo)

    with contar_llamadas() as c:
        await asyncio.gather(rama(0.01), rama(0.02), rama(0.03))
    assert c.llamadas == 3
    assert c.costo_usd == pytest.approx(0.06)
