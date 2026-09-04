"""Ningún cliente de banca sale a la red sin que la licencia lo permita.

**El defecto que lo obligó.** Los cuatro conectores de la Superintendencia de Bancos
declaraban su licencia (T-BR-1) pero ninguno la CONSULTABA: no heredaban del contrato de
`shared.data.base_client`, así que `check_license()` nunca corría. La declaración era
decorativa — el atributo existía para el gate estático y no tenía ningún efecto sobre el
dato. Un boletín público que atribuye a la SB se apoya en que esa declaración signifique
algo.

**Por qué el test mide lo que mide.** No alcanza con comprobar que se levanta
`LicenseError`: hay que comprobar que se levanta ANTES del egress. Un gate que corre
después de la descarga no protege de nada — el dato ya salió del emisor y ya está en
nuestro disco. Por eso cada caso sabotea la capa de red para que CUALQUIER llamada sea un
fallo ruidoso y distinto de `LicenseError`: si el orden se invierte algún día, el test no
se pone verde, se pone rojo con otro error.
"""
import pytest

from modules.banking_score.external import (
    fiduciaria_pdf_client,
    sib_data_client,
    sib_historical_client,
    simbad_client,
)
from shared.data import LicenseError


class _LaRedNoDebioOcurrir(AssertionError):
    """Se levanta si el conector llegó a la capa de red pese a la licencia negada."""


@pytest.fixture
def red_saboteada(monkeypatch):
    """Cualquier egress explota con un error que NO es LicenseError."""
    def _boom(*_a, **_kw):
        raise _LaRedNoDebioOcurrir("el conector salió a la red con la licencia negada")

    import httpx
    import urllib.request
    for mod, attr in ((httpx, "get"), (httpx, "post"), (httpx, "stream"),
                      (urllib.request, "urlopen")):
        monkeypatch.setattr(mod, attr, _boom)
    return _boom


def test_sib_data_client_frena_en_los_tres_puntos_de_egress(monkeypatch, red_saboteada):
    """Las tres rutas de red de la clase son independientes: ninguna llama a las otras."""
    cliente = sib_data_client.SIBDataClient(api_key="x")
    monkeypatch.setattr(cliente, "license_ok", False)

    with pytest.raises(LicenseError):
        cliente.check_connectivity()
    with pytest.raises(LicenseError):
        cliente._discover_working_tipo_codes()
    # `_get_with_retry` y no `_get`: `api/router_data.py` lo llama directo con su propio
    # httpx, salteándose `_get`. Es el único bypass del archivo.
    with pytest.raises(LicenseError):
        cliente._get_with_retry(None, "http://x", {}, "endpoint", 1)


@pytest.mark.parametrize("modulo,funcion,args", [
    (sib_historical_client, "download_to_temp", ("https://sb.gob.do/media/x.csv",)),
    (simbad_client, "_post_chart_data", (35, ["a"], [])),
    (fiduciaria_pdf_client, "discover_pdfs", ("fiduciaria-bhd",)),
    (fiduciaria_pdf_client, "download_pdf", ("https://www.sb.gob.do/x.pdf",)),
])
def test_los_modulos_de_funciones_frenan_antes_del_egress(
    monkeypatch, red_saboteada, modulo, funcion, args
):
    """Tres de los cuatro conectores no tienen clase: el gate es la función libre."""
    monkeypatch.setattr(modulo, "LICENSE_OK", False)
    with pytest.raises(LicenseError):
        getattr(modulo, funcion)(*args)


def test_el_sabotaje_de_red_REALMENTE_muerde(red_saboteada):
    """Si el saboteador no funcionara, los tests de arriba pasarían sin probar el orden.

    Con la licencia en regla, la misma llamada tiene que llegar a la red y explotar con
    `_LaRedNoDebioOcurrir` — que es la prueba de que el egress estaba a un paso.
    """
    with pytest.raises(_LaRedNoDebioOcurrir):
        sib_historical_client.download_to_temp("https://sb.gob.do/media/x.csv")
