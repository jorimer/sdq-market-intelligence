"""Tests del manifiesto de exposición — la pieza que hace la API auto-extensible.

Lo que se protege acá es la promesa de la decisión de amplitud: una serie nueva se
publica SOLA (nadie edita la capa API), y la cuarentena es una condición calculada que
se levanta sola cuando deja de aplicar. Y la contraparte: fail-closed — ante licencia
ausente, sector no publicado o readiness caída, no se sirve.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dataclasses import replace

from shared.data_api.manifest import (
    Q_LICENSE_RESTRICTS,
    Q_LOW_READINESS,
    Q_NO_LICENSE,
    Q_NO_READER,
    Q_NOT_ACTIVATED,
    build_manifest,
)
from shared.database.base import Base
from shared.products.contract import CanonicalSeries, SeriesObservation
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.registry import CatalogEntry


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[ProductActivation.__table__, ProductReadiness.__table__]
    )
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class FakeProduct:
    """Producto de prueba que implementa el par opcional del contrato."""

    sector_key = "banking"

    def __init__(self, series, *, with_reader=True):
        self._series = series
        self._with_reader = with_reader
        if with_reader:
            self.series_observations = self._read

    def canonical_series(self):
        return self._series

    def _read(self, code, *, start=None, end=None, as_of=None, limit=None):
        return [SeriesObservation(period="2025", value=1.0)]


def _series(code="roa", license_="datos oficiales SIB — uso público con cita", n_obs=40):
    return CanonicalSeries(
        code=code, label="Rentabilidad sobre activos", unit="%", frequency="quarterly",
        source="SIB", license=license_, period_first="2015-Q1", period_latest="2025-Q1",
        n_obs=n_obs,
    )


@pytest.fixture()
def wire(monkeypatch):
    """Cablea un catálogo de UN sector con el producto que le pasemos."""

    def _wire(product, sector_key="banking"):
        entry = CatalogEntry(sector_key, "Banca de prueba", "banking_score", "SIB")
        monkeypatch.setattr("shared.data_api.manifest.PRODUCT_CATALOG", [entry])
        monkeypatch.setattr("shared.data_api.manifest.is_implemented", lambda k: True)
        monkeypatch.setattr("shared.data_api.manifest.get_product", lambda k, d=None: product)

    return _wire


def _publish(db, sector_key="banking", tier="pulse", readiness=0.9):
    db.add(ProductActivation(sector_key=sector_key, tier=tier, is_active=True))
    db.add(ProductReadiness(sector_key=sector_key, tier=tier, readiness=readiness))
    db.commit()


# ─── La promesa: lo nuevo se publica solo ─────────────────────────────


def test_a_new_series_is_published_without_touching_the_api_layer(db, wire):
    """El test que sostiene la decisión de auto-extensión: agregar una serie al
    producto la hace aparecer en el manifiesto, sin registrar nada ni editar rutas."""
    _publish(db)
    product = FakeProduct([_series("roa")])
    wire(product)
    assert [a.code for a in build_manifest(db).exposed_assets()] == ["roa"]

    # El módulo cablea una serie más — nadie toca shared/data_api.
    product._series = [_series("roa"), _series("nim")]
    assert sorted(a.code for a in build_manifest(db).exposed_assets()) == ["nim", "roa"]


def test_asset_key_is_namespaced_by_sector_and_kind(db, wire):
    _publish(db)
    wire(FakeProduct([_series("roa")]))
    asset = build_manifest(db).assets[0]
    assert asset.key == "banking:series:roa" and asset.kind == "series"


# ─── Cuarentena: calculada, no curada ─────────────────────────────────


def test_series_without_license_is_quarantined(db, wire):
    """Fail-closed: no se redistribuye lo que no consta que se pueda redistribuir."""
    _publish(db)
    wire(FakeProduct([_series(license_=None)]))
    asset = build_manifest(db).assets[0]
    assert not asset.exposed and Q_NO_LICENSE in asset.quarantine


def test_blank_license_counts_as_missing(db, wire):
    _publish(db)
    wire(FakeProduct([_series(license_="   ")]))
    assert Q_NO_LICENSE in build_manifest(db).assets[0].quarantine


def test_unactivated_sector_is_quarantined(db, wire):
    wire(FakeProduct([_series()]))          # sin _publish
    asset = build_manifest(db).assets[0]
    assert not asset.exposed and Q_NOT_ACTIVATED in asset.quarantine


def test_activated_but_readiness_below_threshold_is_quarantined(db, wire):
    _publish(db, readiness=0.10)            # umbral pulse = 0.75
    wire(FakeProduct([_series()]))
    asset = build_manifest(db).assets[0]
    assert not asset.exposed and Q_LOW_READINESS in asset.quarantine


def test_descriptor_without_reader_is_quarantined(db, wire):
    """Una serie que el catálogo anuncia y nadie puede leer es peor que no anunciarla."""
    _publish(db)
    wire(FakeProduct([_series()], with_reader=False))
    asset = build_manifest(db).assets[0]
    assert not asset.exposed and Q_NO_READER in asset.quarantine


def test_quarantine_lifts_by_itself_when_the_condition_stops_applying(db, wire):
    """Nadie tiene que acordarse de aprobar nada — ese era el punto de la decisión."""
    wire(FakeProduct([_series()]))
    assert not build_manifest(db).assets[0].exposed      # sector sin publicar
    _publish(db)                                         # se publica el sector
    assert build_manifest(db).assets[0].exposed          # se libera sola


def test_all_reasons_accumulate(db, wire):
    wire(FakeProduct([_series(license_=None)], with_reader=False))
    reasons = build_manifest(db).assets[0].quarantine
    assert set(reasons) == {Q_NO_LICENSE, Q_NO_READER, Q_NOT_ACTIVATED}


def test_without_db_everything_is_quarantined(wire):
    """Sin sesión no se puede verificar publicación: fail-closed, no fail-open."""
    wire(FakeProduct([_series()]))
    assert build_manifest(None).exposed_assets() == ()


# ─── Robustez y rotulado ──────────────────────────────────────────────


def test_thin_history_is_labeled_not_hidden(db, wire):
    _publish(db)
    wire(FakeProduct([_series(n_obs=3)]))
    asset = build_manifest(db).assets[0]
    assert asset.stability == "thin" and asset.exposed


def test_product_that_does_not_implement_the_contract_contributes_nothing(db, wire):
    class Bare:
        sector_key = "banking"

    _publish(db)
    wire(Bare())
    assert build_manifest(db).assets == ()      # brecha honesta, no error


def test_a_failing_product_does_not_take_down_the_manifest(db, wire):
    class Explosive:
        sector_key = "banking"

        def canonical_series(self):
            raise RuntimeError("tabla ausente")

        def series_observations(self, *a, **k):
            return []

    _publish(db)
    wire(Explosive())
    assert build_manifest(db).assets == ()      # degrada ese eje, no el registro


def test_summary_counts_exposed_and_reasons(db, wire):
    _publish(db)
    wire(FakeProduct([_series("roa"), _series("nim", license_=None)]))
    summary = build_manifest(db).summary
    assert summary["total"] == 2 and summary["exposed"] == 1
    assert summary["quarantine_reasons"][Q_NO_LICENSE] == 1


# ─── Redistribución vs cálculo propio ─────────────────────────────────
# Doctrina del dueño: "calculamos, no revendemos la misma info". El eje que decide no es
# la fuente sino QUÉ se sirve.

_ITU = "CC BY-NC-SA 3.0 IGO (ITU)"
_ODBL = "https://opendatacommons.org/licenses/odbl/"


def test_verbatim_series_from_a_non_commercial_source_is_quarantined(db, wire):
    """ITU es no-comercial: reexportar su serie tal cual a un cliente que paga es
    justamente lo que la licencia no permite."""
    _publish(db)
    wire(FakeProduct([_series("mobile_subs", license_=_ITU)]))
    asset = build_manifest(db).assets[0]
    assert not asset.exposed and Q_LICENSE_RESTRICTS in asset.quarantine


def test_a_derived_asset_over_the_same_source_is_served(db, wire):
    """El índice calculado sobre ese insumo es obra propia: no se retiene."""
    _publish(db)
    s = _series("telecom_index", license_=_ITU)
    wire(FakeProduct([replace(s, derivation="derived")]))
    assert build_manifest(db).assets[0].exposed


def test_odbl_share_alike_is_also_caught_verbatim(db, wire):
    _publish(db)
    wire(FakeProduct([_series("primas", license_=_ODBL)]))
    assert Q_LICENSE_RESTRICTS in build_manifest(db).assets[0].quarantine


def test_permissive_sources_stay_exposed_verbatim(db, wire):
    """El BCRD publica para uso público con cita: la serie sale, con su atribución."""
    _publish(db)
    wire(FakeProduct([_series("gdp_growth",
                              license_="datos oficiales BCRD — uso público con cita")]))
    assert build_manifest(db).assets[0].exposed


def test_world_bank_cc_by_is_not_treated_as_restrictive(db, wire):
    """CC-BY (sin NC ni SA) permite redistribuir citando: no debe caer en el filtro."""
    _publish(db)
    wire(FakeProduct([_series("wgi_rule_of_law",
                              license_="World Bank Open Data (CC-BY 4.0)")]))
    assert build_manifest(db).assets[0].exposed


def test_default_derivation_is_the_conservative_one(db, wire):
    """Un producto que no declara nada se trata como verbatim (lo más restrictivo)."""
    _publish(db)
    wire(FakeProduct([_series("x", license_=_ITU)]))
    assert build_manifest(db).assets[0].derivation == "verbatim"
