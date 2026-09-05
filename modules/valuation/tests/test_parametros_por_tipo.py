"""La Superintendencia supervisa cuatro clases de entidad y el modelo las trataba igual.

Beta de bancos cotizados latinoamericanos y retención del 60 % para las cuatro. Los datos
—SIMBAD, cierres 2019-2025, 145 entidad-año— dicen que no son lo mismo, y dicen HASTA DÓNDE:

* la **retención** está MEDIDA y las separa con claridad: 0,75 / 0,74 / 0,76 y **0,99** las
  asociaciones, que son mutuales y no tienen accionistas a quienes pagar dividendos;
* la **dispersión de ROE** sostiene el ORDEN en los extremos —asociaciones las menos dispersas
  los seis de seis años, banca múltiple la más dispersa cinco de seis— y **no** sostiene un
  orden fino de cuatro: los dos del medio se cruzan y las corporaciones de crédito son tres
  entidades.

Por eso la beta se abre en TRES grupos, no cuatro. Y el tamaño del salto entre bandas es
RÚBRICA declarada: dispersión de ROE es riesgo total, beta es riesgo sistemático, y sin
entidades dominicanas cotizadas no hay forma de medirlo.
"""
import pytest

from modules.valuation.engine import por_tipo as pt


def test_las_ASOCIACIONES_tienen_la_beta_mas_baja():
    """Lo mejor sostenido de la tabla: las menos dispersas los seis de seis años."""
    aap = pt.beta_de("aap")
    for otro in ("banca_multiple", "banco_ahorro_credito", "corporacion_credito"):
        assert aap[1] < pt.beta_de(otro)[1], f"aap no queda por debajo de {otro}"


def test_la_banca_multiple_conserva_la_banda_ORIGINAL():
    """Es la clase que se parece a los comparables latinoamericanos de donde sale la beta.
    Moverla sería cambiar el ancla sin evidencia nueva."""
    assert pt.beta_de("banca_multiple") == (0.85, 1.15)


def test_las_corporaciones_COMPARTEN_banda_y_el_motivo_es_falta_de_MUESTRA():
    """No se midió que se parezcan: son tres entidades y su dispersión es ruido. Que la
    razón sea la muestra y no una medición tiene que estar escrito, o en seis meses alguien
    lee la banda compartida como un hallazgo."""
    assert pt.beta_de("corporacion_credito") == pt.beta_de("banco_ahorro_credito")
    ev = pt.BETA_EVIDENCIA_POR_TIPO["corporacion_credito"]
    assert "TRES entidades" in ev and "falta de muestra" in ev


def test_la_retencion_de_las_ASOCIACIONES_es_casi_uno_y_dice_POR_QUE():
    """0,99 no es un artefacto: son mutuales. Y el modelo les aplicaba 0,60."""
    assert pt.retencion_de("aap") == pytest.approx(0.99)
    ev = pt.RETENCION_EVIDENCIA_POR_TIPO["aap"]
    assert "MUTUALES" in ev and "dividendos" in ev


def test_las_otras_tres_retenciones_son_PARECIDAS_entre_si():
    """El contraejemplo de la afirmación de arriba: si las cuatro fueran distintas, el 0,99
    no sería un hallazgo sobre las mutuales sino ruido de medición."""
    otras = [pt.retencion_de(t) for t in
             ("banca_multiple", "banco_ahorro_credito", "corporacion_credito")]
    assert max(otras) - min(otras) < 0.05, f"las otras tres no son parecidas: {otras}"
    assert pt.retencion_de("aap") - max(otras) > 0.20, "el salto de las mutuales se perdió"


def test_un_tipo_DESCONOCIDO_cae_al_defecto_y_lo_DECLARA():
    """Un tipo que no se reconoce no puede elegir parámetros en silencio: cambia el valor."""
    assert pt.beta_de("banco_de_marte") == pt.beta_de(pt.TIPO_POR_DEFECTO)
    assert pt.retencion_de(None) == pt.retencion_de(pt.TIPO_POR_DEFECTO)
    ev = pt.evidencia_de("banco_de_marte")
    assert "NO RECONOCIDO" in ev and "banco_de_marte" in ev


def test_TODO_tipo_conocido_trae_su_evidencia():
    """Un parámetro que cambia el valor y no dice de dónde sale es un número inventado con
    buena presentación."""
    for t in pt.BETA_POR_TIPO:
        assert len(pt.BETA_EVIDENCIA_POR_TIPO[t]) > 100, f"{t}: beta sin evidencia"
        assert len(pt.RETENCION_EVIDENCIA_POR_TIPO[t]) > 40, f"{t}: retención sin evidencia"
        assert t in pt.RETENCION_POR_TIPO


def test_las_bandas_son_TRES_y_no_cuatro():
    """La evidencia sostiene tres grupos. Abrir cuatro daría una precisión que la dispersión
    de tres entidades no puede respaldar."""
    assert len(set(pt.BETA_POR_TIPO.values())) == 3, (
        f"hay {len(set(pt.BETA_POR_TIPO.values()))} bandas distintas y la evidencia "
        "sostiene tres")
