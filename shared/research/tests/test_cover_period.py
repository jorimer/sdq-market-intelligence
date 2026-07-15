"""Regresión del Hallazgo 1 del piloto P4-P6: el 'Período' de portada del entregable debe ser
la fecha MÁS RECIENTE entre todos los motores convocados, no la del primero de la lista
(`live[0]`), que era un artefacto del orden de iteración de `pulls`."""
from shared.research.data_pull import EnginePull
from shared.research.deep_report import _latest_period, _period_key


def _pull(period, sk="macro", label="Sistema"):
    return EnginePull(sector_key=sk, entity_label=label, period=period,
                      source=f"Fuente · {sk}", payload={}, ok=True)


# ─── normalización/parseo de período (formatos mixtos) ─────────────────
def test_period_key_orders_mixed_formats():
    # ISO más nuevo que año-solo del año anterior.
    assert _period_key("2026-06-30") > _period_key("2025")
    # trimestre vs ISO del mismo año: Q1 (ene-mar) es más viejo que junio.
    assert _period_key("2026-Q1") < _period_key("2026-06-30")
    # una comparación de string ingenua ordenaría MAL este par ('2026-Q1' > '2026-06-30'
    # lexicográficamente, porque 'Q' > '0'); el parseo numérico lo corrige.
    assert "2026-Q1" > "2026-06-30"           # el bug que se está evitando
    assert _period_key("2026-Q1") < _period_key("2026-06-30")   # ya bien ordenado
    # trimestre tardío gana a uno temprano; año-mes se ubica bien.
    assert _period_key("2026-Q4") > _period_key("2026-Q1")
    assert _period_key("2026-06") > _period_key("2026-03")
    # el formato T (trimestre en español) también parsea.
    assert _period_key("2026-T2") > _period_key("2026-Q1")


def test_period_key_unparseable_sinks_to_bottom():
    assert _period_key(None) == (-1, -1, -1)
    assert _period_key("") == (-1, -1, -1)
    assert _period_key("sin fecha") == (-1, -1, -1)
    # y por tanto nunca gana el 'más reciente' frente a un período válido.
    assert _period_key("2020") > _period_key("basura")


# ─── selección del período de portada ──────────────────────────────────
def test_latest_period_picks_most_recent_not_first():
    # el motor MÁS NUEVO está de último en la lista (orden entidades→axes→context):
    # antes la portada tomaba live[0] ('2025-12-31'); ahora toma el más reciente.
    live = [_pull("2025-12-31", "macro"), _pull("2026-06-30", "monetary_policy")]
    assert _latest_period(live) == "2026-06-30"
    # y también si el más nuevo está primero (no debe romperse al revés).
    live_rev = [_pull("2026-06-30", "monetary_policy"), _pull("2025-12-31", "macro")]
    assert _latest_period(live_rev) == "2026-06-30"


def test_latest_period_mixed_formats_in_one_list():
    # los 3 formatos mezclados en una sola lista `live`: año, ISO y trimestre.
    live = [_pull("2025", "esg"), _pull("2026-Q1", "macro"), _pull("2026-06-30", "monetary_policy")]
    assert _latest_period(live) == "2026-06-30"
    # sin la fecha ISO, gana el trimestre sobre el año-solo.
    live2 = [_pull("2025", "esg"), _pull("2026-Q1", "macro")]
    assert _latest_period(live2) == "2026-Q1"


def test_latest_period_all_none_returns_none():
    assert _latest_period([_pull(None), _pull(None)]) is None
    assert _latest_period([]) is None
