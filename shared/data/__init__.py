"""Cross-cutting data layer — connectors with lineage and license gating.

Every axis ingests external data through these clients (mixed-source: each
declares ``mode="live"|"fixture"`` behind one interface).  Records carry a
:class:`~shared.data.lineage.Lineage` stamp so any emitted figure is traceable.
"""
from shared.data.base_client import (
    FixtureBackedClient,
    LicenseError,
    Mode,
    Record,
    SourceClient,
)
from shared.data.bcrd_client import bcrd_client
from shared.data.dga_client import dga_client
from shared.data.dgii_client import dgii_client
from shared.data.hacienda_client import hacienda_client
from shared.data.lineage import Lineage
from shared.data.one_client import one_client
from shared.data.outcomes import LabeledOutcome
from shared.data.sib_client import sib_client

__all__ = [
    "SourceClient",
    "FixtureBackedClient",
    "Record",
    "Mode",
    "LicenseError",
    "Lineage",
    "LabeledOutcome",
    "sib_client",
    "bcrd_client",
    "one_client",
    "dgii_client",
    "dga_client",
    "hacienda_client",
]
