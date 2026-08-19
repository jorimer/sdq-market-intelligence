"""La sonda que convierte «telecom está congelado» en algo que el sistema vigila.

El boletín público de INDOTEL se congeló en 2022-Q1 y el IDT pasó a servirse de ITU DataHub.
Eso es una DECISIÓN, no una brecha — pero sin vigilancia hay que volver a tomarla a mano cada
vez que alguien pregunta si INDOTEL volvió, y la respuesta de la última vez no queda escrita
en ningún lado que el sistema lea.

Lo que estos tests fijan es lo que hace peligrosa a una sonda: que confunda «miré y no hay»
con «no pude mirar». Un fallo de red que se reporte como «sigue congelado» es peor que no
tener sonda, porque produce una confirmación falsa.
"""
from shared.data.indotel_client import LATEST_PERIOD, _periodo_de_nombre


def test_el_periodo_sale_del_nombre_del_boletin():
    assert _periodo_de_nombre(
        "indicadores-estadisticos-trimestrales-enero-marzo-2022-res-026-21-web.xlsx"
    ) == "2022-Q1"
    assert _periodo_de_nombre("boletin_octubre_diciembre_2024.xlsx") == "2024-Q4"
    assert _periodo_de_nombre("abril-junio-2023-indicadores.xlsx") == "2023-Q2"


def test_un_archivo_que_no_declara_trimestre_no_inventa_periodo():
    assert _periodo_de_nombre("memoria-institucional-2024.pdf") is None
    assert _periodo_de_nombre("cualquier-cosa.xlsx") is None


def _sonda(monkeypatch, html_por_pagina, status=200):
    """Sonda contra páginas simuladas, sin red."""
    import httpx

    from shared.data import indotel_client as mod

    class _Resp:
        def __init__(self, texto):
            self.status_code = status
            self.text = texto

    def _get(url, **_kw):
        if url not in html_por_pagina:
            raise httpx.ConnectError("no resuelve")
        return _Resp(html_por_pagina[url])

    monkeypatch.setattr(mod.httpx if hasattr(mod, "httpx") else httpx, "get", _get,
                        raising=False)
    monkeypatch.setattr("httpx.get", _get)
    return mod.descubrir_boletin_mas_reciente()


_PAGINA = "https://indotel.gob.do/estadisticas/indicadores-estadisticos-trimestrales/"
_PAGINA2 = "https://indotel.gob.do/estadisticas/"


def test_detecta_un_boletin_mas_nuevo_que_el_conocido(monkeypatch):
    html = ('<a href="https://indotel.gob.do/x/boletin-abril-junio-2025-web.xlsx">Q2 2025</a>')
    out = _sonda(monkeypatch, {_PAGINA: html, _PAGINA2: ""})
    assert out["periodo"] == "2025-Q2"
    assert out["hay_mas_nuevo"] is True
    assert out["conocido"] == LATEST_PERIOD


def test_paginas_leidas_y_sin_boletines_es_evidencia_de_que_sigue_congelado(monkeypatch):
    out = _sonda(monkeypatch, {_PAGINA: "<p>sin documentos</p>", _PAGINA2: "<p>nada</p>"})
    assert out["hay_mas_nuevo"] is False
    assert out["paginas_ok"] == 2, "hay que poder distinguir «miré» de «no pude mirar»"


def test_si_no_se_pudo_leer_ninguna_pagina_NO_afirma_que_sigue_congelado(monkeypatch):
    """El caso peligroso: una caída de red que se reporte como confirmación."""
    out = _sonda(monkeypatch, {})
    assert out["hay_mas_nuevo"] is False
    assert out["paginas_ok"] == 0, (
        "Con cero páginas leídas, el `hay_mas_nuevo=False` NO es evidencia — la operación "
        "lo declara explícitamente en su `lectura`.")


def test_un_boletin_mas_VIEJO_que_el_conocido_no_dispara_nada(monkeypatch):
    html = '<a href="https://indotel.gob.do/x/enero-marzo-2021.xlsx">viejo</a>'
    out = _sonda(monkeypatch, {_PAGINA: html, _PAGINA2: ""})
    assert out["periodo"] == "2021-Q1"
    assert out["hay_mas_nuevo"] is False
