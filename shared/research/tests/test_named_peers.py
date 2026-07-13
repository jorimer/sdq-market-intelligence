"""Tests de PARES NOMBRADOS en el research (roadmap #3): la evidencia y la tabla
comparativa dejan de ser un percentil anónimo y nombran a los competidores con su dato.
Payloads sintéticos con la forma real de cada motor (banca: peer_block.named_peers;
pension/insurance: peers + rating).
"""
import shared.research.data_pull as dp
import shared.research.deep_report as dr


def _banking_payload():
    return {
        "scoring_result": {"overall_score": 61.2, "rating_tier": "SDQ-BBB",
                           "sub_components": {"solidez": 60.0}},
        "peer_block": {
            "metric_label": "activos", "cr5": 70.0, "cr10": 88.0, "hhi": 1200.0,
            "named_peers": {
                "entity_type": "banca_multiple", "n_system": 42, "n_type": 18,
                "rows": [
                    {"name": "Banco Popular", "type": "banca_multiple", "score": 84.3,
                     "tier": "SDQ-AA", "rank": 1, "rank_in_type": 1, "is_subject": False},
                    {"name": "BHD", "type": "banca_multiple", "score": 82.1,
                     "tier": "SDQ-AA", "rank": 2, "rank_in_type": 2, "is_subject": False},
                    {"name": "Banco Lafise", "type": "banca_multiple", "score": 61.2,
                     "tier": "SDQ-BBB", "rank": 30, "rank_in_type": 14, "is_subject": True},
                ],
            },
        },
    }


def test_banking_summary_names_position_and_peers():
    evs = dp._banking_summary("Banco Lafise", _banking_payload(), "2025-12", "SIB · BCRD")
    t = " || ".join(e.text for e in evs)
    assert "Posición nombrada: 30 de 42 en el sistema; 14 de 18 entre banca_multiple" in t
    assert "Banco Popular (84.3, SDQ-AA)" in t and "BHD (82.1, SDQ-AA)" in t
    # el sujeto no se lista como par de sí mismo
    assert "Banco Lafise (61.2" not in t


def test_banking_summary_without_named_peers_unchanged():
    payload = {"scoring_result": {"overall_score": 61.2, "rating_tier": "SDQ-BBB"},
               "peer_block": {"metric_label": "activos", "cr5": 70.0, "cr10": 88.0, "hhi": 1200.0}}
    evs = dp._banking_summary("Banco Lafise", payload, "2025-12", "SIB · BCRD")
    t = " || ".join(e.text for e in evs)
    assert "Posición nombrada" not in t and "Pares del sistema" not in t
    assert "CR5 70.0" in t  # la evidencia previa sigue intacta


def _pension_payload():
    return {
        "has_data": True,
        "rating": {"slug": "afp-crecer", "name": "AFP Crecer", "overall_score": 64.0,
                   "band": "Adecuada", "dimensions": []},
        "peers": [
            {"slug": "afp-popular", "name": "AFP Popular", "overall_score": 78.0, "band": "Fuerte"},
            {"slug": "afp-crecer", "name": "AFP Crecer", "overall_score": 64.0, "band": "Adecuada"},
            {"slug": "afp-reservas", "name": "AFP Reservas", "overall_score": 71.5, "band": "Adecuada"},
        ],
    }


def test_pension_named_form_ranks_peers():
    evs = dp._pension_summary("AFP Crecer", _pension_payload(), "2026-05", "SIPEN")
    t = " || ".join(e.text for e in evs)
    assert "ISA 64.0/100" in t
    assert "Posición nombrada: 3 de 3 en el sistema" in t
    assert "AFP Popular (78.0)" in t and "AFP Reservas (71.5)" in t
    assert "AFP Crecer (64.0)" not in t  # el sujeto no se lista como par


def test_tables_banking_named_peers():
    tables = dr._tables_from_payload(_banking_payload())
    titles = [t for t, _ in tables]
    assert any("Posición vs pares nombrados" in t for t in titles)
    _, body = next((t, b) for t, b in tables if "pares nombrados" in t)
    assert body[0] == ["Pos.", "Entidad", "Tipo", "Score", "Rating"]
    # el sujeto va marcado; los pares con su score/tier reales
    flat = str(body)
    assert "Banco Lafise ◀" in flat and "Banco Popular" in flat and "84.3" in flat


def test_tables_pension_ranking():
    tables = dr._tables_from_payload(_pension_payload())
    _, body = next((t, b) for t, b in tables if "Ranking nombrado" in t)
    assert body[0] == ["Pos.", "Entidad", "Score", "Banda"]
    # ordenado por score desc y sujeto marcado
    assert body[1][1] == "AFP Popular" and body[1][0] == "1"
    assert body[3][1] == "AFP Crecer ◀" and body[3][0] == "3"


def test_tables_no_peers_no_fabrication():
    # sin named_peers ni peers → solo la tabla de concentración (si viene), nada fabricado
    tables = dr._tables_from_payload({"peer_block": {"cr5": 70.0, "cr10": 88.0,
                                                     "hhi": 1200.0, "metric_label": "activos"}})
    assert len(tables) == 1 and "Concentración" in tables[0][0]
    assert dr._tables_from_payload({}) == []
