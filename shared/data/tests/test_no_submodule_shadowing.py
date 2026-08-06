"""Ningún nombre exportado por ``shared.data`` puede tapar a un submódulo suyo.

La capa de datos tiene una colisión estructural: cada conector vive en
``shared/data/<x>_client.py`` y expone una instancia llamada ``<x>_client``. Si el
``__init__`` reexporta la instancia, el nombre queda ocupado por el objeto y el submódulo
se vuelve inalcanzable por atributo — ``from shared.data import bcrd_client`` y hasta
``import shared.data.bcrd_client as m`` devuelven la INSTANCIA, porque el binding del
``from … import`` del ``__init__`` pisa el atributo que el propio import del submódulo dejó
en el paquete.

No es teórico: costó tres rodeos con ``sys.modules[…]`` en los tests de social_dev antes de
que alguien lo nombrara. El síntoma aparece lejos de la causa (un ``monkeypatch.setattr``
que falla con "no attribute"), así que el guard vive acá, en el contrato del paquete.

Regla: ``shared.data`` exporta el CONTRATO (tipos + lineage); las instancias se importan de
su submódulo. Si hace falta reexportar algo nuevo, que no se llame como un submódulo.
"""
import pkgutil
from types import ModuleType

import shared.data


def test_no_attribute_of_the_package_shadows_a_submodule():
    """Se mira el NAMESPACE real, no ``__all__``: la sombra la crea el import del
    ``__init__``, aunque quien la agregue se olvide de listarla en ``__all__``."""
    shadowed = []
    for info in pkgutil.iter_modules(shared.data.__path__):
        attr = getattr(shared.data, info.name, None)
        if attr is not None and not isinstance(attr, ModuleType):
            shadowed.append(f"{info.name} → {type(attr).__name__}")
    assert not shadowed, (
        "estos atributos de shared.data tapan a un submódulo homónimo: "
        f"{sorted(shadowed)}. Importe la instancia desde su submódulo "
        "(from shared.data.<x>_client import <x>_client) en vez de reexportarla."
    )


def test_all_matches_what_the_package_actually_exports():
    """``__all__`` no debe mentir sobre la superficie pública del paquete."""
    for name in shared.data.__all__:
        assert hasattr(shared.data, name), f"{name} está en __all__ pero no se exporta"


def test_client_submodules_are_reachable_as_modules():
    """El caso concreto que se rompía: llegar al MÓDULO para parchearlo en un test."""
    import shared.data.bcrd_client as bcrd_mod
    import shared.data.one_client as one_mod

    assert hasattr(bcrd_mod, "fetch_bcrd_variable"), "se obtuvo la instancia, no el módulo"
    assert hasattr(one_mod, "__path__") or hasattr(one_mod, "__file__")
