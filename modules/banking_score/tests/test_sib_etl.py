"""Tests for the ported SIB ETL data client (real-data extraction).

Covers the entity catalog, the settings-driven client factory, and the ETL
field mapping (SIB API records → BankingData fields). Network calls are never
made — we exercise the pure mapping and the factory with patched config.
"""
import pytest

from modules.banking_score.external import sib_data_client as etl
from modules.banking_score.external.sib_data_client import SIBDataClient
from modules.banking_score.models.models import BankingData


def test_entity_catalog_integrity():
    assert len(etl.SIB_ENTITY_CODES) >= 30
    for short, info in etl.SIB_ENTITY_CODES.items():
        assert info["sib_code"], f"{short} sin sib_code"
        assert info["tipo_entidad"] in {"BM", "AAP", "BAC", "CC"}, info["tipo_entidad"]
        assert info["nombre_sib"]


def test_corporaciones_credito_covered():
    """Corporaciones de crédito (CC) are in the catalog and fetch candidates."""
    cc = {k: v for k, v in etl.SIB_ENTITY_CODES.items() if v["tipo_entidad"] == "CC"}
    # Reidco is a (now-exited) corporación de crédito, catalogued for historical data.
    assert set(cc) == {"Monumental", "Nordestana", "Oficorp", "Reidco"}
    assert "CC" in SIBDataClient.SIB_TIPO_ENTIDAD_CANDIDATES


def test_client_none_without_key(monkeypatch):
    monkeypatch.setattr(etl, "_resolve_sib_config", lambda: ("", "https://x", "", ""))
    assert etl.get_sib_data_client(force_new=True) is None


def test_client_built_with_key(monkeypatch):
    monkeypatch.setattr(
        etl, "_resolve_sib_config",
        lambda: ("a-key", "https://apis.sb.gob.do/estadisticas/v2", "", ""),
    )
    client = etl.get_sib_data_client(force_new=True)
    assert client is not None
    assert client.api_key == "a-key"
    assert client.use_proxy is False


def test_client_uses_proxy_when_configured(monkeypatch):
    monkeypatch.setattr(
        etl, "_resolve_sib_config",
        lambda: ("k", "https://b", "https://w.workers.dev", "secret"),
    )
    client = etl.get_sib_data_client(force_new=True)
    assert client.use_proxy is True


def test_mapping_keys_are_model_columns():
    """The ETL must only emit fields the BankingData model has."""
    cols = {c.name for c in BankingData.__table__.columns}
    out = SIBDataClient(api_key="x")._map_to_sdq_fields(
        {"income": [], "balance": [], "solvency": [], "indicators": []}
    )
    assert set(out) <= cols


def test_mapping_extracts_real_values():
    client = SIBDataClient(api_key="x")
    period_data = {
        "balance": [
            {"conceptoNivel1": "Activos", "conceptoNivel2": "Cartera de créditos", "valor": 1000.0},
            {"conceptoNivel1": "Pasivos", "conceptoNivel2": "Obligaciones con el público", "valor": 700.0},
            {"conceptoNivel1": "Patrimonio", "conceptoNivel2": "Patrimonio neto", "valor": 200.0},
        ],
        "solvency": [
            {"componente": "PATRIMONIO TECNICO AJUSTADO", "valor": 800.0},
            {"componente": "CAPITAL PRIMARIO", "valor": 600.0},
        ],
        "indicators": [
            {"indicador": "ACTIVOS NETOS TOTALES", "valor": 5000.0},
        ],
        "income": [],
    }
    out = client._map_to_sdq_fields(period_data)
    assert out["cartera_bruta"] == 1000.0
    assert out["depositos_totales"] == 700.0
    assert out["patrimonio_tecnico"] == 800.0
    assert out["capital_primario"] == 600.0
    assert out["activos_totales"] == 5000.0
    # Fields the SIB API never provides stay None.
    assert out["suma_top10"] is None
    assert out["castigos"] is None


def test_extract_banking_data_unknown_entity():
    client = SIBDataClient(api_key="x")
    # Unknown short name is rejected before any network call.
    with pytest.raises(ValueError):
        client.extract_banking_data("NoSuchBank")
