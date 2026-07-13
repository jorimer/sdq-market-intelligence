"""Tests for the SIS audited-financials page discovery — offline, synthetic HTML.

``discover_audited_urls`` scrapes the transparencia page for the per-year audited
workbooks. The HTTP layer is stubbed (requests.get) and fed inline HTML, per the
DGA-connector pattern: valid links, .xlsx-over-.xls preference, no links, malformed
HTML and an HTTP error. No network.
"""
import pytest

from modules.insurance_intel.financials_sync import discover_audited_urls


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            import requests  # type: ignore[import-untyped]
            raise requests.HTTPError(f"{self._status} error")


def _stub(monkeypatch, text="", status=200):
    import requests  # type: ignore[import-untyped]
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Resp(text, status))


def test_discovers_year_links(monkeypatch):
    _stub(monkeypatch, """
      <a href="https://sis.gob.do/wp/Estados-Financieros-Auditados-por-cia-2023.xlsx">2023</a>
      <a href="https://sis.gob.do/wp/Estados-Financieros-Auditados-por-cia-2024.xlsx">2024</a>
      <a href="https://sis.gob.do/wp/otro-informe-2024.pdf">no</a>
    """)
    urls = discover_audited_urls()
    assert set(urls) == {"2023", "2024"}
    assert urls["2024"].endswith("Estados-Financieros-Auditados-por-cia-2024.xlsx")


def test_prefers_xlsx_over_xls_for_same_year(monkeypatch):
    _stub(monkeypatch, """
      <a href="https://sis.gob.do/wp/Estados-Financieros-Auditados-por-cia-2022.xls">a</a>
      <a href="https://sis.gob.do/wp/Estados-Financieros-Auditados-por-cia-2022.xlsx">b</a>
      <a href="https://sis.gob.do/wp/Estados-Financieros-Auditados-por-cia-2021.xls">c</a>
    """)
    urls = discover_audited_urls()
    assert urls["2022"].endswith(".xlsx")   # .xlsx wins when both exist
    assert urls["2021"].endswith(".xls")    # .xls kept when it's all there is


def test_no_matching_links_returns_empty(monkeypatch):
    _stub(monkeypatch, '<a href="https://sis.gob.do/wp/memoria-anual-2024.pdf">x</a>')
    assert discover_audited_urls() == {}


def test_malformed_html_returns_empty_not_crash(monkeypatch):
    _stub(monkeypatch, "<html><a href='sin-comillas-dobles.xlsx <div>>>> {rot" )
    assert discover_audited_urls() == {}


def test_http_error_propagates(monkeypatch):
    import requests  # type: ignore[import-untyped]
    _stub(monkeypatch, "", status=503)
    with pytest.raises(requests.HTTPError):
        discover_audited_urls()
