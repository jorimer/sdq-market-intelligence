"""Period & number normalization — the messy primitives the corpus throws at us."""
from shared.data.bcrd_excel.periods import (
    coerce_num,
    format_period,
    parse_month,
    parse_quarter,
    parse_year,
)


def test_parse_month_variants():
    assert parse_month("Enero") == 1
    assert parse_month("septiembre") == 9
    assert parse_month("Setiembre") == 9  # BCRD spelling
    assert parse_month("Dic.") == 12      # abbreviated with dot
    assert parse_month("DICIEMBRE ") == 12
    assert parse_month("Promedio 2007") is None
    assert parse_month(None) is None


def test_parse_year_variants():
    assert parse_year(1982) == 1982
    assert parse_year(1982.0) == 1982     # xlrd floats
    assert parse_year("1982") == 1982
    assert parse_year("Promedio 2007") == 2007
    assert parse_year("hola") is None
    assert parse_year(12) is None         # not a plausible year


def test_parse_quarter_variants():
    assert parse_quarter("E-M") == 1   # BCRD month-range quarters
    assert parse_quarter("A-J") == 2
    assert parse_quarter("J-S") == 3
    assert parse_quarter("O-D") == 4
    assert parse_quarter("Ene-Mar") == 1
    assert parse_quarter("III") == 3
    assert parse_quarter("T2") == 2
    assert parse_quarter("Q4") == 4
    assert parse_quarter("Enero") is None  # a month is not a quarter
    assert parse_quarter(None) is None


def test_format_period():
    assert format_period(2007, 5) == "2007-05"
    assert format_period(2007, None) == "2007"
    assert format_period(2007, 12) == "2007-12"
    assert format_period(2007, None, 2) == "2007-Q2"   # quarterly
    assert format_period(2007, 5, 2) == "2007-05"       # month wins if both given


def test_coerce_num_mixed_types_and_missing():
    assert coerce_num(312.7) == 312.7
    assert coerce_num("255") == 255.0      # string-typed numbers
    assert coerce_num("-381.1") == -381.1
    assert coerce_num("-") is None         # dash = missing, never 0
    assert coerce_num("n.d.") is None
    assert coerce_num("") is None
    assert coerce_num(None) is None
    assert coerce_num("1,234.5") == 1234.5  # en grouping
    assert coerce_num("1.234,5") == 1234.5  # es-DO grouping
