"""El CNSS renombra el CSV cada mes y DEJA el anterior en pie: una URL fija no falla, envejece.

Es la falla más cara que puede tener un conector, porque no avisa. Cuando se detectó, la URL
fijada devolvía 200 y una serie hasta 2026-03 mientras el emisor publicaba 2026-05.
"""
import shared.data.sisalril_client as sc


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _pagina(*nombres):
    enlaces = "".join(
        f'<a href="https://cnss.gob.do/wp-content/uploads/2023/06/{n}">x</a>' for n in nombres)
    return f"<html><body>{enlaces}</body></html>"


def test_resuelve_el_csv_que_el_emisor_publica_hoy(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(
        _pagina("SFS_Afiliacion-por-Regimen_2007_Mayo-2026.csv")))
    url, procedencia = sc.resolver_csv_vigente()
    assert procedencia == "indice"
    assert url.endswith("Mayo-2026.csv")


def test_el_mes_en_mayusculas_tambien_se_reconoce(monkeypatch):
    """El emisor alterna «MARZO» y «Mayo»: comparar sensible al caso perdería la mitad."""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(
        _pagina("SFS_AFILIACION-POR-REGIMEN_2007_MARZO-2026-.csv")))
    assert sc.resolver_csv_vigente()[1] == "indice"


def test_si_el_indice_no_responde_el_respaldo_se_DECLARA(monkeypatch):
    """Un respaldo silencioso es cómo un fallback se vuelve permanente. Ya pasó acá con los
    «promedios del sistema», que quedaron años sirviendo constantes."""
    def _cae(*a, **k):
        raise ConnectionError("503")

    monkeypatch.setattr("requests.get", _cae)
    url, procedencia = sc.resolver_csv_vigente()
    assert procedencia == "respaldo"
    assert url == sc._SFS_CSV_RESPALDO


def test_una_pagina_sin_el_archivo_no_inventa_una_url(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(_pagina("RC_Recaudos_SFS.csv")))
    assert sc.resolver_csv_vigente()[1] == "respaldo"
