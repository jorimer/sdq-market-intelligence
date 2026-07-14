"""Tests del conector DGII de contribuyentes por subclase (§B).

Valida: agregación por subclase con split por tipo de persona y descarte de no-activos;
el crosswalk vertical (códigos exactos y prefijo); y el parseo del Excel de muestra
(cifras + fecha de corte). Las cifras del fixture son chicas y conocidas para aserción exacta.
"""
from datetime import date

import pytest

from shared.data.dgii_rnc_client import (
    CAVEAT,
    VERTICALS,
    DGIIRncClient,
    SubclaseContrib,
    Vertical,
    aggregate_rows,
)

_HEADER = ("Actividad Económica 1", "Subclase", "Tipo de persona", "Estatus", "Cantidad")


def _rows(*tuples):
    # (subclase, tipo, estatus, cantidad) → fila completa en el orden de _HEADER
    return [("X", sub, tipo, est, cant) for sub, tipo, est, cant in tuples]


def test_aggregate_por_subclase_split_y_descarta_no_activos():
    rows = _rows(
        ("552118-Comida Rapida", "Física", "Activo", 3),
        ("552118-Comida Rapida", "Jurídica", "Activo", 2),
        ("552118-Comida Rapida", "Física", "Suspendido", 99),   # NO cuenta
        ("011111-Arroz", "Física", "Activo", 10),
    )
    out = {a.subclase: a for a in aggregate_rows(_HEADER, rows)}
    assert out["552118"] == SubclaseContrib("552118", "Comida Rapida", 5, 3, 2)
    assert out["011111"].activos == 10
    assert "552118" in out and out["552118"].activos_juridica == 2


def test_aggregate_ignora_subclase_vacia_y_suma_cantidades_texto():
    rows = _rows(
        ("552113-Pizzerias", "Jurídica", "Activo", "1"),   # cantidad como texto
        (None, "Física", "Activo", 5),                     # subclase vacía → ignora
    )
    out = {a.subclase: a for a in aggregate_rows(_HEADER, rows)}
    assert out["552113"].activos == 1
    assert len(out) == 1


def test_vertical_matches_codes_y_prefijo():
    comida = next(v for v in VERTICALS if v.key == "comida_rapida")
    assert comida.matches("552118") and comida.matches("552113")
    assert not comida.matches("552210")
    assert comida.code_label == "552118+552113"

    rbc = next(v for v in VERTICALS if v.key == "restaurantes_bares_cantinas")
    assert rbc.matches("552210") and rbc.matches("552118")
    assert not rbc.matches("551101")
    assert rbc.code_label == "552xxx"


def test_fixture_agrega_y_lee_corte():
    corte, rows, lineage = DGIIRncClient(mode="fixture").fetch_aggregates()
    by = {r.subclase: r for r in rows}
    assert corte == date(2026, 3, 15)                      # de la hoja 'Notas'
    # comida rápida = 552118 (5) + 552113 (1) = 6; el Suspendido (99) quedó fuera
    assert by["552118"].activos == 5
    assert by["552113"].activos == 1
    assert "011111" in by                                  # guarda TODAS las subclases
    assert lineage.source == "DGII" and lineage.note == CAVEAT
    assert lineage.published_at == corte


def test_fetch_serie_temporal_no_soportado():
    with pytest.raises(NotImplementedError):
        DGIIRncClient(mode="fixture").fetch()
