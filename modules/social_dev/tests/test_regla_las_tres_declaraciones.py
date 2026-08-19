"""REGLA: una serie nacional se declara en TRES lugares o no llega al consumidor.

Agregar una serie nacional al panel exige tocar tres sitios, cada uno con su razón:

    social_sync.WDI_NACIONALES_FUERA_DEL_INDICE   qué se DESCARGA y con qué unidad
    products._FUERA_DEL_INDICE                    qué se PUBLICA al Data Registry
    shared/doctrine/social.yaml → variable_scopes qué ALCANCE tiene

Ninguna omisión levanta un error. Faltando la segunda, el dato se guarda y nadie lo ve.
Faltando la tercera, la señal cae al default `per_subject` y el proveedor del eje de leyes
la RECHAZA — el indicador desaparece del informe sin aviso, que es el modo de fallar que
este repo ya pagó caro con la pobreza extrema de `cibao_norte` publicada como nacional.

Este test no impide la duplicación —hay razones para que los tres existan por separado—;
impide la DERIVA, que es lo que de verdad hace daño.
"""
import pathlib

import pytest

from modules.social_dev.products import SocialDevProduct
from modules.social_dev.social_sync import WDI_NACIONALES_FUERA_DEL_INDICE

_RAIZ = pathlib.Path(__file__).resolve().parents[3]


def _alcances():
    """Se lee por el mismo camino que el código de producción, no con un cargador propio:
    un test que parsea la doctrina a su manera puede pasar mientras el producto falla."""
    from shared.registry.builders import axis_variable_scopes
    from modules.social_dev.products import DOCTRINE_AXIS
    return axis_variable_scopes(DOCTRINE_AXIS)


def _publicadas():
    return set(SocialDevProduct._FUERA_DEL_INDICE)


@pytest.mark.parametrize("tema", sorted(t for t, _ in WDI_NACIONALES_FUERA_DEL_INDICE.values()))
def test_lo_que_se_descarga_se_PUBLICA(tema):
    assert tema in _publicadas(), (
        f"«{tema}» se descarga en la sync y no está en `_FUERA_DEL_INDICE`: el dato se "
        f"guarda en la base y NADIE lo ve. No falla — desaparece.")


@pytest.mark.parametrize("tema", sorted(_publicadas()))
def test_TODO_lo_que_se_publica_DECLARA_su_alcance(tema):
    """Sobre `_FUERA_DEL_INDICE` entero y no solo sobre lo que baja del WDI.

    El glob importa: la primera versión de este test recorría el catálogo de descargas, así
    que las series DERIVADAS —las que computamos nosotros, como los conteos regionales— no
    quedaban cubiertas. Justo las que más lo necesitan, porque nadie externo las valida."""
    alc = _alcances()
    assert tema in alc, (
        f"«{tema}» no declara alcance en la doctrina: cae al default `per_subject` y el "
        f"proveedor del eje de leyes la rechaza. El indicador desaparece del informe — y una "
        f"señal PUBLICADA no puede descansar en una omisión, porque el lector no distingue "
        f"«se decidió por sujeto» de «nadie lo pensó».")
    assert alc[tema] in ("national", "per_subject")


@pytest.mark.parametrize("tema", sorted(t for t, _ in WDI_NACIONALES_FUERA_DEL_INDICE.values()))
def test_lo_que_baja_del_WDI_es_NACIONAL(tema):
    """Son series de PAÍS del Banco Mundial: una que quedara en `per_subject` sería rechazada
    por el proveedor del eje de leyes y el indicador desaparecería sin aviso."""
    assert _alcances().get(tema) == "national"


def test_ninguna_serie_nacional_pondera_en_el_indice():
    """Peso 0 es lo que hace que agregar series al registro NO mueva la cobertura del eje
    social, que es un producto en producción. Sin esto, cada serie nueva le cambia la
    métrica a un eje que no pidió nada."""
    import inspect
    fuente = inspect.getsource(SocialDevProduct._senales_fuera_del_indice)
    assert "weight=0.0" in fuente, "las señales fuera del índice van con peso 0"
