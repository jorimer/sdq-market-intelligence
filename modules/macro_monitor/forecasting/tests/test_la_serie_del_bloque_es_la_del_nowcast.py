"""El bloque del BVAR y el nowcast tienen que puntuarse contra LA MISMA serie del PIB.

Si divergen, los dos motores se comparan contra observados distintos y sus errores dejan de
ser comparables — pero la tabla de desempeño los pone uno debajo del otro igual, y nadie se
entera. Es la forma que toma acá «dos declaraciones del mismo hecho se desincronizan».

`panel.PIB_CODE` es una constante escrita; el bloque resuelve la suya por el registro
canónico. Este archivo cruza las dos.
"""
from shared.data.bcrd_excel import canonical

from modules.macro_monitor.forecasting import bloque
from shared.data import medida_de_pronostico as med
from modules.macro_monitor.forecasting import panel as panel_mod


def test_el_registro_canonico_resuelve_pib_real_al_codigo_QUE_USA_EL_NOWCAST():
    """El único candidato del corpus tiene que ser el mismo código que el nowcast pide."""
    entrada = next(e for e in canonical.registry() if e.key == "pib_real")
    resuelto = canonical.codigo_de(entrada, [panel_mod.PIB_CODE])
    assert resuelto == panel_mod.PIB_CODE, (
        f"el bloque resolvería «pib_real» a {resuelto!r} y el nowcast puntúa contra "
        f"{panel_mod.PIB_CODE!r}: dos motores midiendo contra series distintas, publicados "
        "en la misma tabla")


def test_el_bloque_declara_que_el_PIB_entra_como_variacion_INTERANUAL():
    """El punto que sale del BVAR no es el nivel del índice **ni** su variación trimestral:
    el PIB entra al bloque como interanual. Puntuarlo contra el nivel da un error del tamaño
    del índice; contra la variación trimestral, del tamaño de la estacionalidad —que en esta
    serie, que es la ORIGINAL sin desestacionalizar, vale 5,80 pp de amplitud—."""
    assert bloque.medida_del_punto("pib_real") == med.YOY_PCT


def test_toda_variable_del_bloque_tiene_medida_en_LOS_DOS_vocabularios():
    """Hay dos mapas sobre `Variable.transformacion` y contestan preguntas distintas:
    `MEDIDA_DEL_PUNTO` dice cómo realizar el observado para puntuar, `MEDIDA_POR_TRANSFORMACION`
    qué clase de crecimiento expresa el número para saber qué se puede restar de qué.

    Se comprueban JUNTOS: una transformación nueva que entre a uno y no al otro rompe en
    silencio del lado que se olvidó, y son casi homónimos — el modo exacto en que dos
    declaraciones del mismo hecho se desincronizan.
    """
    sin_punto = [v.nombre for v in bloque.BLOQUE if bloque.medida_del_punto(v.nombre) is None]
    assert not sin_punto, (
        f"sin medida DEL PUNTO (el ledger no sabría contra qué puntuar): {sin_punto}. "
        f"`MEDIDA_DEL_PUNTO` cubre {sorted(bloque.MEDIDA_DEL_PUNTO)}")
    sin_clase = [v.transformacion for v in bloque.BLOQUE
                 if v.transformacion not in bloque.MEDIDA_POR_TRANSFORMACION]
    assert not sin_clase, (
        f"sin clase de CRECIMIENTO (la reconciliación sectorial no sabría si se puede "
        f"restar): {sin_clase}")


def test_el_puente_entre_los_dos_vocabularios_no_inventa_una_clase_para_un_NIVEL():
    """Un nivel no es un crecimiento, y de la medida sola no se puede deducir si la serie que
    recorre es a su vez una tasa. La respuesta es `None` y quien llama se niega: suponerlo es
    el defecto que la reconciliación existe para vetar."""
    assert panel_mod.clase_de_crecimiento(med.YOY_PCT) == panel_mod.INTERANUAL
    assert panel_mod.clase_de_crecimiento(med.DLOG_PCT) == panel_mod.TRIMESTRAL
    assert panel_mod.clase_de_crecimiento(med.LEVEL) is None
    assert panel_mod.clase_de_crecimiento("") is None
