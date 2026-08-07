"""Tests de la marca de frescura compartida (shared.indices.freshness)."""


def test_marca_el_rezago_en_paneles_anuales():
    """Caso real del ISF: Autoseguro con estados de 2020 junto a 33 aseguradoras de 2024."""
    from shared.indices.freshness import annotate_freshness
    filas = [{"period": "2024"}, {"period": "2020"}, {"period": "2023"}]
    corte = annotate_freshness(filas)
    assert corte == "2024"
    assert filas[0]["stale"] is False and filas[0]["periods_behind"] == 0
    assert filas[1]["stale"] is True and filas[1]["periods_behind"] == 4
    assert filas[2]["periods_behind"] == 1
    assert {f["period_unit"] for f in filas} == {"años"}


def test_marca_el_rezago_en_paneles_mensuales():
    """Caso real del ISARS: SeNaSa y SEMMA en 2026-03 contra 2026-04 del resto."""
    from shared.indices.freshness import annotate_freshness
    filas = [{"period": "2026-04"}, {"period": "2026-03"}, {"period": "2025-12"}]
    corte = annotate_freshness(filas)
    assert corte == "2026-04"
    assert filas[1]["periods_behind"] == 1 and filas[1]["period_unit"] == "meses"
    assert filas[2]["periods_behind"] == 4  # cruza el cambio de año


def test_panel_al_dia_no_marca_nada():
    """Las 7 AFP reportan el mismo corte: nadie queda marcado."""
    from shared.indices.freshness import annotate_freshness
    filas = [{"period": "2026-05"} for _ in range(7)]
    assert annotate_freshness(filas) == "2026-05"
    assert all(f["stale"] is False and f["periods_behind"] == 0 for f in filas)


def test_periodo_irreconocible_queda_en_none_no_en_cero():
    """Sin período legible no se puede afirmar que está al día: None, no False/0."""
    from shared.indices.freshness import annotate_freshness
    filas = [{"period": "2024"}, {"period": None}, {"period": "—"}]
    annotate_freshness(filas)
    for f in filas[1:]:
        assert f["stale"] is None and f["periods_behind"] is None


def test_no_mezcla_unidades_para_inventar_un_atraso():
    """Un panel con años y meses mide cada fila contra el corte de SU unidad.

    Restar "2024" contra "2026-04" daría un atraso inventado, y un número inventado es peor
    que no marcar nada.
    """
    from shared.indices.freshness import annotate_freshness
    filas = [{"period": "2026-04"}, {"period": "2026-03"}, {"period": "2024"}, {"period": "2023"}]
    annotate_freshness(filas)
    assert filas[1]["periods_behind"] == 1 and filas[1]["period_unit"] == "meses"
    assert filas[2]["periods_behind"] == 0 and filas[2]["period_unit"] == "años"
    assert filas[3]["periods_behind"] == 1


def test_panel_vacio_no_revienta():
    from shared.indices.freshness import annotate_freshness
    assert annotate_freshness([]) is None
