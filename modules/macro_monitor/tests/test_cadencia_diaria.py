"""La cadencia diaria, de punta a punta: se deriva, se ordena y se sirve."""
import pytest

from modules.macro_monitor.service import _infer_frequency, period_end_date, period_start_date
from shared.data.series_cadence import CADENCIAS, DIARIA, cadencia_de_periodo


def test_un_periodo_con_dia_es_diario():
    assert cadencia_de_periodo("2026-03-07") == DIARIA
    assert DIARIA in CADENCIAS


@pytest.mark.parametrize("period,esperado", [
    ("2026", "annual"), ("2026-Q1", "quarterly"), ("2026-03", "monthly"),
])
def test_las_otras_tres_no_se_mueven(period, esperado):
    assert cadencia_de_periodo(period) == esperado


def test_el_ordenamiento_cronologico_entiende_el_dia():
    """Sin esto, una serie diaria se ordena por texto y la Data API la sirve mal."""
    assert period_start_date("2026-03-07").isoformat() == "2026-03-07"
    assert period_end_date("2026-03-07").isoformat() == "2026-03-07"
    assert period_end_date("2026-03-07") < period_end_date("2026-03-08")
    # y un día cae DENTRO de su mes
    assert period_start_date("2026-03") <= period_start_date("2026-03-07")
    assert period_end_date("2026-03-07") <= period_end_date("2026-03")


def test_una_serie_de_dias_se_infiere_diaria():
    assert _infer_frequency(["2026-03-07", "2026-03-08", "2026-03-09"]) == "daily"


def test_un_dia_invalido_no_se_acepta():
    assert period_end_date("2026-02-31") is None
    assert cadencia_de_periodo("2026-13-01") == "unknown"
