"""Cross-cutting data layer — connectors with lineage and license gating.

Every axis ingests external data through these clients (mixed-source: each
declares ``mode="live"|"fixture"`` behind one interface).  Records carry a
:class:`~shared.data.lineage.Lineage` stamp so any emitted figure is traceable.

El paquete exporta el CONTRATO (tipos + lineage), no las instancias de cliente:
cada conector vive en el submódulo homónimo y de ahí se importa
(``from shared.data.bcrd_client import bcrd_client``), que es como lo hace todo
el código. Reexportar la instancia acá TAPA al submódulo del mismo nombre —
``from shared.data import bcrd_client`` devolvía el objeto y no el módulo, y
``import shared.data.bcrd_client as m`` también, porque el binding del ``from …
import`` pisa el atributo que el import del submódulo dejó en el paquete. El
guard de :mod:`shared.data.tests.test_no_submodule_shadowing` lo mantiene así.
"""
from shared.data.base_client import (
    FixtureBackedClient,
    LicenseError,
    Mode,
    Record,
    SourceClient,
    check_license_for,
)
from shared.data.lineage import Lineage
from shared.data.outcomes import LabeledOutcome

__all__ = [
    "SourceClient",
    "FixtureBackedClient",
    "Record",
    "Mode",
    "LicenseError",
    "check_license_for",
    "Lineage",
    "LabeledOutcome",
]
