"""El bloque del BVAR y el nowcast tienen que puntuarse contra LA MISMA serie del PIB.

Si divergen, los dos motores se comparan contra observados distintos y sus errores dejan de
ser comparables — pero la tabla de desempeño los pone uno debajo del otro igual, y nadie se
entera. Es la forma que toma acá «dos declaraciones del mismo hecho se desincronizan».

`panel.PIB_CODE` es una constante escrita; el bloque resuelve la suya por el registro
canónico. Este archivo cruza las dos.
"""
from shared.data.bcrd_excel import canonical

from modules.macro_monitor.forecasting import bloque
from modules.macro_monitor.forecasting import medida as med
from modules.macro_monitor.forecasting import panel as panel_mod


def test_el_registro_canonico_resuelve_pib_real_al_codigo_QUE_USA_EL_NOWCAST():
    """El único candidato del corpus tiene que ser el mismo código que el nowcast pide."""
    entrada = next(e for e in canonical.registry() if e.key == "pib_real")
    resuelto = canonical.codigo_de(entrada, [panel_mod.PIB_CODE])
    assert resuelto == panel_mod.PIB_CODE, (
        f"el bloque resolvería «pib_real» a {resuelto!r} y el nowcast puntúa contra "
        f"{panel_mod.PIB_CODE!r}: dos motores midiendo contra series distintas, publicados "
        "en la misma tabla")


def test_el_bloque_declara_que_el_PIB_entra_como_TASA():
    """El punto que sale del BVAR es una variación logarítmica ×100, no el nivel del índice.
    La medida del ledger sale de esta declaración y no de una constante paralela."""
    assert bloque.medida_de_variable("pib_real") == med.DLOG_PCT


def test_toda_variable_del_bloque_tiene_medida_en_el_vocabulario_del_ledger():
    """Un mapa incompleto devolvería `None` y la emisión se caería —o peor, escribiría sin
    declarar— el día que alguien agregue una transformación nueva."""
    faltan = [v.nombre for v in bloque.BLOQUE if bloque.medida_de_variable(v.nombre) is None]
    assert not faltan, (
        f"estas variables del bloque no tienen medida declarada para el ledger: {faltan}. "
        f"`MEDIDA_DE_TRANSFORMACION` cubre {sorted(bloque.MEDIDA_DE_TRANSFORMACION)}")
