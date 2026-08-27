"""Un 4xx de la SIB no se reintenta: el resultado sería idéntico y cuesta minutos.

**El caso, del 2026-08-27.** Una sonda a un período viejo hizo que la SIB respondiera
`400 — "Se introdujo un tipo de entidad incorrecto"`. El cliente lo registró correctamente
como *not retryable*… y el bucle de paginación lo reintentó **tres veces más**, con 5, 10 y
15 segundos de espera, por página y por tipo de entidad.

Resultado medido: la petición tardaba **más de cuatro minutos** en morir, Sentry recibió unos
sesenta avisos idénticos, y el error final decía «TRUNCADO tras reintentos» sobre algo que
nunca iba a funcionar.

**La causa.** `_get_with_retry` devolvía `None` para dos cosas OPUESTAS: «se cayó, probá de
nuevo» y «está mal pedido, nunca va a andar». El bucle solo veía `None` y no podía
distinguirlas. Es el mismo defecto que el techo de tiempo indistinguible de la degradación del
servicio: **dos causas que exigen respuestas opuestas no pueden compartir un valor de
retorno.**

El fallo transitorio SIGUE reintentándose — eso no se toca, y tiene su propio test acá: una
truncación silenciosa ya dejó `hhi_ingresos` en N/D a mitad de período.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from modules.banking_score.external.sib_data_client import RECHAZO_PERMANENTE, SIBDataClient


class _Cliente(SIBDataClient):
    """Cliente con la capa de red y las esperas sustituidas por contadores."""

    def __init__(self, respuestas: List[Any]):
        super().__init__(api_key="x")
        self._respuestas = list(respuestas)
        self.intentos = 0
        self.dormido = 0.0

    def _get_with_retry(self, httpx, url, params, endpoint, page):  # type: ignore[override]
        self.intentos += 1
        return self._respuestas.pop(0) if self._respuestas else None

    def _sleep(self, segundos):  # type: ignore[override]
        self.dormido += float(segundos)

    def _check_connectivity(self):  # type: ignore[override]
        return {"reachable": True}


def _paginar(cliente: _Cliente, **kw) -> List[Dict]:
    import httpx as _httpx
    return cliente._paginate(_httpx, "estados/situacion/eic", {}, **kw) \
        if hasattr(cliente, "_paginate") else []


@pytest.fixture()
def metodo_de_paginacion():
    """El nombre del método que pagina, resuelto del propio cliente.

    Se resuelve en vez de escribirse: si mañana se renombra, este test tiene que fallar por
    no encontrarlo —y decirlo— en lugar de pasar en verde sin haber ejercitado nada.
    """
    candidatos = [n for n in dir(SIBDataClient)
                  if "pagin" in n.lower() and callable(getattr(SIBDataClient, n))]
    assert candidatos, "no se encontró el método de paginación del cliente"
    return candidatos[0]


def test_un_RECHAZO_no_se_reintenta_ni_una_vez(metodo_de_paginacion):
    """La afirmación entera: una sola llamada, cero esperas."""
    import httpx

    c = _Cliente([RECHAZO_PERMANENTE])
    getattr(c, metodo_de_paginacion)(httpx, "estados/situacion/eic", {})
    assert c.intentos == 1, "reintentó un error que nunca va a cambiar"
    assert c.dormido == 0.0, "durmió esperando a que un 400 dejara de ser un 400"


def test_un_fallo_TRANSITORIO_sí_se_reintenta(metodo_de_paginacion):
    """El contrapeso, y no es decorativo: una truncación silenciosa ya dejó `hhi_ingresos`
    en N/D a mitad de período. Sin este caso, «no reintentar» se podría implementar de más."""
    import httpx

    c = _Cliente([None, None, None, None])
    getattr(c, metodo_de_paginacion)(httpx, "estados/situacion/eic", {})
    assert c.intentos > 1, "un fallo transitorio tiene que reintentarse"
    assert c.dormido > 0.0


def test_el_rechazo_y_el_fallo_transitorio_son_valores_DISTINTOS():
    """Si volvieran a colapsar en `None`, el bucle no podría distinguirlos — que es
    exactamente el defecto que este archivo cierra."""
    assert RECHAZO_PERMANENTE is not None
