"""Invariantes del registro canónico del panel LatAm+Caribe del IRMP."""
from shared.data.latam_peers import (
    PEERS,
    fips_to_iso2,
    iso3_by_iso2,
    names,
    peer,
    regions,
)


def test_panel_is_24_with_unique_codes():
    assert len(PEERS) == 24
    assert len({p.iso2 for p in PEERS}) == 24    # iso2 únicos
    assert len({p.iso3 for p in PEERS}) == 24    # iso3 únicos
    assert len({p.fips for p in PEERS}) == 24    # FIPS únicos (clave para GDELT)


def test_focused_regional_set_present_and_mapped():
    i3 = iso3_by_iso2()
    assert i3["DO"] == "DOM" and i3["CR"] == "CRI" and i3["GT"] == "GTM"
    assert fips_to_iso2()["DR"] == "DO"          # FIPS ≠ ISO2 para RD
    assert names()["DO"] == "República Dominicana"
    assert regions()["DO"] == "Caribe" and regions()["CR"] == "Centroamérica"


def test_every_peer_has_name_and_region():
    for p in PEERS:
        assert peer(p.iso2) is p
        assert p.name and p.region
