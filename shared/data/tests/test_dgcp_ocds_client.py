"""Obra pública adjudicada por mes (DGCP, OCDS): qué cuenta como obra, adjudicación y monto.

Releases sintéticos con la FORMA medida en la fuente real el 2026-09-14: la categoría viene en
`tender.mainProcurementCategory`, el monto NUNCA en `awards[].value` sino en `contracts[].value`
colgado por `awardID`, y la unidad de compra en `parties` con rol `procuringEntity`.
"""
from datetime import date

import pytest

from shared.data import dgcp_ocds_client as dg


def _release(ocid, *, categoria="works", modalidad="Comparación de Precios", awards=(),
             contratos=(), unidad="DO-UC-100"):
    return {
        "ocid": ocid,
        "tender": {"mainProcurementCategory": categoria, "procurementMethodDetails": modalidad},
        "parties": [{"roles": ["procuringEntity"], "identifier": {"id": unidad}, "name": "X"}],
        "awards": [{"id": a[0], "date": a[1], "status": a[2]} for a in awards],
        "contracts": [{"awardID": c[0], "value": {"amount": c[1], "currency": "DOP"}}
                      for c in contratos],
    }


def test_solo_cuenta_la_CATEGORIA_obra_y_nunca_la_modalidad():
    """Una obra grande va por Licitación Pública y un bien puede ir por Comparación de Precios:
    la modalidad no dice qué se compró."""
    releases = [
        _release("obra-grande", modalidad="Licitación Pública Nacional",
                 awards=[("a1", "2026-06-10", "active")], contratos=[("a1", 900_000_000)]),
        _release("bien-menor", categoria="goods", modalidad="Comparación de Precios",
                 awards=[("b1", "2026-06-11", "active")], contratos=[("b1", 7_000)]),
    ]
    s = dg.agregar(releases, "2026-06")
    # El monto dice CUÁL entró: con un corte por modalidad saldría el bien y no la obra.
    assert s[dg.SERIE_OBRAS]["2026-06"] == 1
    assert s[dg.SERIE_MONTO]["2026-06"] == 900_000_000


def test_una_adjudicacion_CANCELADA_o_pendiente_no_es_obra_adjudicada():
    releases = [_release("a", awards=[("a1", "2026-06-10", "cancelled"),
                                      ("a2", "2026-06-12", "pending"),
                                      ("a3", "2026-06-15", "active")])]
    assert dg.agregar(releases, "2026-06")[dg.SERIE_OBRAS]["2026-06"] == 1


def test_el_monto_sale_del_CONTRATO_de_cada_adjudicacion():
    releases = [_release("a", awards=[("a1", "2026-06-10", "active")],
                         contratos=[("a1", 1_000_000), ("a1", 500_000), ("otra", 9_999_999)])]
    s = dg.agregar(releases, "2026-06")
    assert s[dg.SERIE_MONTO]["2026-06"] == 1_500_000


def test_adjudicaciones_SIN_contrato_con_monto_dejan_el_monto_en_None_no_en_cero():
    releases = [_release("a", awards=[("a1", "2026-05-10", "active")]),
                _release("b", awards=[("b1", "2026-06-10", "active")], contratos=[("b1", 10)])]
    s = dg.agregar(releases, "2026-06")
    assert s[dg.SERIE_MONTO]["2026-05"] is None
    assert s[dg.SERIE_MONTO]["2026-06"] == 10


def test_un_mes_sin_ninguna_adjudicacion_es_un_CERO_medido():
    releases = [_release("a", awards=[("a1", "2026-04-10", "active")], contratos=[("a1", 5)]),
                _release("b", awards=[("b1", "2026-06-10", "active")], contratos=[("b1", 7)])]
    s = dg.agregar(releases, "2026-06")
    assert s[dg.SERIE_OBRAS]["2026-05"] == 0 and s[dg.SERIE_MONTO]["2026-05"] == 0


def test_el_sector_electrico_se_identifica_por_la_UNIDAD_de_compra_y_no_por_el_nombre():
    """«Corporación de Acueducto» contiene «cued»: un patrón la metía en el sector eléctrico. Cada
    una en un mes distinto, para que el conteo diga CUÁL entró y no solo cuántas."""
    releases = [
        _release("edesur", unidad="DO-UC-815", awards=[("a1", "2026-06-10", "active")]),
        _release("acueducto", unidad="DO-UC-999", awards=[("b1", "2026-05-11", "active")]),
    ]
    releases[1]["parties"][0]["name"] = "Corporación de Acueducto y Alcantarillado de Santiago"
    s = dg.agregar(releases, "2026-06")
    assert s[dg.SERIE_OBRAS]["2026-05"] == 1 and s[dg.SERIE_OBRAS]["2026-06"] == 1
    assert s[dg.SERIE_OBRAS_ELECTRICAS]["2026-06"] == 1
    assert s[dg.SERIE_OBRAS_ELECTRICAS]["2026-05"] == 0, "el acueducto entró al sector eléctrico"


def test_un_proceso_que_aparece_en_DOS_archivos_se_cuenta_una_vez():
    r = _release("a", awards=[("a1", "2026-06-10", "active")])
    assert dg.agregar([r, r], "2026-06")[dg.SERIE_OBRAS]["2026-06"] == 1


def test_los_meses_POSTERIORES_al_publicable_no_se_leen():
    releases = [_release("a", awards=[("a1", "2026-06-10", "active"), ("a2", "2026-08-02", "active")])]
    s = dg.agregar(releases, "2026-07")
    assert "2026-08" not in s[dg.SERIE_OBRAS]


@pytest.mark.parametrize("recuperado, esperado", [
    (date(2026, 9, 7), "2026-07"),    # agosto terminó hace 7 días: todavía se registra
    (date(2026, 9, 30), "2026-08"),   # agosto terminó hace 30 días
    (date(2026, 1, 15), "2025-11"),   # cruza el año
])
def test_el_ultimo_mes_publicable_respeta_el_margen_de_registro(recuperado, esperado):
    assert dg.ultimo_mes_publicable(recuperado) == esperado
