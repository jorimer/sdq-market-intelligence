"""Tests for the READ-ONLY SIPEN discovery analysers (offline, no network).

Only the pure HTML parsers are covered here; the live orchestrator (``sipen_discovery``)
does network I/O against SIPEN from Railway and is marked ``pragma: no cover``.
"""
from modules.pension_intel.sipen_discovery import (
    descarga_files,
    download_labels,
    section_links,
    summarize_periods,
)

# A fragment shaped like a SIPEN estados-financieros year page: timestamped /descarga/
# files with a "_YYYY_MM_" period stamp, plus an audited annual file with only a year.
_YEAR_PAGE = """
<a href="https://sipen.gob.do/descarga/afp-popular-2026_2026_05_1781.pdf">Mayo</a>
<a href="https://sipen.gob.do/descarga/afp-popular-2026_2026_04_1777.pdf">Abril</a>
<a href="https://sipen.gob.do/descarga/estados-auditados-popular-2010_9931.pdf">2010</a>
<a href="https://sipen.gob.do/descarga/afp-popular-2026_2026_05_1781.pdf">dup</a>
"""

_PREVISIONAL = """
<a href="https://sipen.gob.do/descarga/rent_178.xlsx"
   aria-label="Descargar documento Rentabilidad">x</a>
<a href="https://sipen.gob.do/descarga/vc_179.xlsx"
   aria-label="Descargar documento Valor Cuota">x</a>
<a href="https://sipen.gob.do/descarga/cart_180.xlsx"
   aria-label="Descargar documento Cartera">x</a>
"""

_PARENT = """
<a href="/estadisticas/estados-financieros-afp/estados-financieros">Interinos</a>
<a href="/estadisticas/estados-financieros-afp/estados-financieros-auditados">Auditados</a>
<a href="https://sipen.gob.do/estadisticas/estados-financieros-afp/accionistas">Accionistas</a>
<a href="/otra-cosa">no</a>
"""


def test_descarga_files_dedupes_and_detects_periods():
    files = descarga_files(_YEAR_PAGE)
    urls = [f["url"] for f in files]
    assert len(urls) == len(set(urls)) == 3  # the dup collapses
    by_url = {f["url"].rsplit("/", 1)[-1]: f for f in files}
    assert by_url["afp-popular-2026_2026_05_1781.pdf"]["period"] == "2026-05"
    # audited annual file: no _MM_ stamp → falls back to bare year.
    assert by_url["estados-auditados-popular-2010_9931.pdf"]["period"] == "2010"
    assert all(f["ext"] == "pdf" for f in files)


def test_download_labels_reads_aria_titles():
    labels = download_labels(_PREVISIONAL)
    assert labels == ["Rentabilidad", "Valor Cuota", "Cartera"]


def test_section_links_filters_and_absolutizes():
    links = section_links(_PARENT, "/estados-financieros-afp/")
    assert "https://sipen.gob.do/estadisticas/estados-financieros-afp/estados-financieros" in links
    assert "https://sipen.gob.do/estadisticas/estados-financieros-afp/estados-financieros-auditados" in links
    assert "https://sipen.gob.do/estadisticas/estados-financieros-afp/accionistas" in links
    assert all("otra-cosa" not in u for u in links)  # unrelated href excluded


def test_summarize_periods_spans_min_to_max():
    s = summarize_periods(descarga_files(_YEAR_PAGE))
    assert s["n_files"] == 3
    assert s["earliest"] == "2010"
    assert s["latest"] == "2026-05"
    assert "2026-04" in s["periods"]
