"""El empalme de las tasas: cuatro archivos, una serie, y lo que se puede afirmar de él.

El BCRD publica la tasa activa y la pasiva en CUATRO archivos por período —hasta 2007,
2008-2012, 2013-2016 y 2017 en adelante— y el registro canónico solo declaraba el vigente.
La serie empezaba en 2017 y el bloque del BVAR se quedaba sin la crisis de 2003, que es el
episodio de estrés más informativo que tiene el país: la tasa activa pasó de 20% a 27,5% y
volvió a 15% en tres años.

**Ninguno de los tramos solapa con el siguiente**, así que el empalme se DOCUMENTA y no se
mide contra un período común — igual que la balanza de pagos MBP5/MBP6. Lo que sí se puede
medir, y este archivo fija, es que los saltos de empalme caen dentro de lo que la serie hace
normalmente, y que el spread activa−pasiva nunca se invierte.

Estos tests NO bajan archivos: corren sobre el registro y sobre una serie sembrada. Lo que
vigilan es que las declaraciones del registro sigan siendo coherentes entre sí.
"""
import pytest

from shared.data.bcrd_excel import canonical

_TRAMOS_ACTIVA = ["tasa_activa_1998_2007", "tasa_activa_2008_2012",
                  "tasa_activa_2013_2016", "tasa_activa"]
_TRAMOS_PASIVA = ["tasa_pasiva_1998_2007", "tasa_pasiva_2008_2012",
                  "tasa_pasiva_2013_2016", "tasa_pasiva"]


def _entrada(clave):
    return next(e for e in canonical.registry() if e.key == clave)


@pytest.mark.parametrize("clave", _TRAMOS_ACTIVA + _TRAMOS_PASIVA)
def test_los_cuatro_tramos_de_cada_tasa_estan_en_el_registro(clave):
    assert _entrada(clave)


@pytest.mark.parametrize("clave", _TRAMOS_ACTIVA[:-1] + _TRAMOS_PASIVA[:-1])
def test_cada_tramo_historico_se_escribe(clave):
    """De nada sirve declararlos si no entran a `mm_series`: la serie seguiría empezando
    en 2017."""
    assert _entrada(clave).source_file in canonical.PERSISTIBLES_VERIFICADOS


@pytest.mark.parametrize("clave", _TRAMOS_ACTIVA[:-1] + _TRAMOS_PASIVA[:-1])
def test_cada_tramo_declara_a_qué_serie_apunta(clave):
    """Sin puente, un tramo es un archivo suelto: nadie sabe cuál de sus columnas es la que
    se empalma."""
    assert _entrada(clave).excel_series_suffix


@pytest.mark.parametrize("clave", _TRAMOS_ACTIVA[:-1] + _TRAMOS_PASIVA[:-1])
def test_los_tramos_son_archivos_DISTINTOS(clave):
    archivos = [_entrada(k).source_file for k in _TRAMOS_ACTIVA + _TRAMOS_PASIVA]
    assert len(set(archivos)) == len(archivos), f"dos tramos apuntan al mismo archivo: {archivos}"


def test_el_empalme_esta_declarado_donde_viaja_al_cliente():
    """La nota va por PREFIJO de código de serie, que es lo que la Data API sirve. Un
    empalme que solo esté explicado en un comentario del código no llega a quien lo cita."""
    for prefijo in ("bcrd.xls.taap_activa.", "bcrd.xls.taap_pasiva."):
        assert prefijo in canonical.SERIES_NOTES, f"falta la nota de {prefijo}"
        nota = canonical.SERIES_NOTES[prefijo]
        assert "empalme" in nota.lower()
        assert "no solapa" in nota.lower() or "ninguno solapa" in nota.lower()


def test_la_nota_dice_que_el_empalme_NO_se_midio_contra_un_periodo_comun():
    """Es la diferencia entre «lo verificamos» y «lo contrastamos». Decir la primera cuando
    corresponde la segunda es exactamente lo que la doctrina prohíbe."""
    nota = canonical.SERIES_NOTES["bcrd.xls.taap_activa."]
    assert "documenta" in nota.lower() and "no se mide" in nota.lower()


def test_la_nota_trae_los_numeros_que_sostienen_la_afirmacion():
    """Una nota que diga «el empalme es bueno» sin las cifras no es verificable por quien la
    lee, que es el punto de publicarla."""
    nota = canonical.SERIES_NOTES["bcrd.xls.taap_activa."]
    for cifra in ("0,62", "2,24", "0,49", "343"):
        assert cifra in nota, f"la nota no trae {cifra}"
