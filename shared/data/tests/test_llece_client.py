"""El cliente del LLECE sirve NIVELES y nunca puntajes, y eso no es una omisión.

La Ley 1-12 fija sus metas de puntaje en la escala de SERCE 2006 (media regional 500) y el
LLECE publica desde TERCE 2013 con media 700. Un puntaje moderno leído contra una meta de la
ley la supera por unos doscientos puntos sin que el país haya cambiado de desempeño: el ERCE
2019 da 643,95 en lectura de 6to contra una meta de «> 557» para 2030.

Exponer el puntaje acá dejaría el arma cargada — cualquier consumidor futuro lo ataría a una
meta y publicaría un cumplimiento falso. Los NIVELES sí son comparables de 2006 a 2019 y por
eso son lo único que sale.
"""
import pytest

from shared.data.llece_client import (LLECEUnavailable, parse_bajo_nivel_ii,
                                      niveles_disponibles)

CABECERA = ("Estudio,pais,materia,grado,ERCE_nivel_1,ERCE_nivel_2,ERCE_nivel_3,ERCE_nivel_4,"
            "ERCE_puntaje_promedio,TERCE_nivel_1,TERCE_nivel_2,TERCE_nivel_3,TERCE_nivel_4,"
            "TERCE_puntaje_promedio\n")
# Fila REAL de República Dominicana, matemáticas de 6to grado.
RD_MAT6 = ("ERCE_2019,do,Matematicas,6,0.8117,0.1667,0.0195,0.0021,635.88,"
           "0.8253,0.1597,0.0136,0.0014,630.44\n")


def test_sirve_el_porcentaje_EN_O_POR_DEBAJO_del_nivel_II():
    """Es la suma de los niveles I y II — la magnitud exacta que el 2.17 de la ley fija."""
    obs = dict(parse_bajo_nivel_ii(CABECERA + RD_MAT6, "Matematicas", "6"))
    assert obs["2019"] == pytest.approx(97.84, abs=0.01)
    assert obs["2013"] == pytest.approx(98.50, abs=0.01)


def test_el_periodo_es_el_ANO_DE_APLICACION_de_cada_estudio():
    """Rotularlo con el año del archivo o el de publicación fecharía mal la observación, y el
    semáforo juzga contra la meta de un año concreto."""
    assert sorted(dict(parse_bajo_nivel_ii(CABECERA + RD_MAT6, "Matematicas", "6"))) == \
        ["2013", "2019"]


def test_NO_expone_el_puntaje():
    """El módulo entero no debe ofrecer una vía para sacar el puntaje: es lo que impide que
    alguien lo ate a una meta escrita en otra escala."""
    import shared.data.llece_client as mod

    publicas = [n for n in dir(mod) if not n.startswith("_")]
    assert not [n for n in publicas if "puntaje" in n.lower() or "score" in n.lower()]


def test_si_los_niveles_no_suman_UNO_se_omite_la_observacion():
    """Habría una categoría fuera de la partición y el porcentaje mediría otra cosa. Declarar
    eso vale más que servir el número."""
    rota = ("ERCE_2019,do,Matematicas,6,0.50,0.10,0.05,0.05,635.88,"
            "0.8253,0.1597,0.0136,0.0014,630.44\n")
    obs = dict(parse_bajo_nivel_ii(CABECERA + rota, "Matematicas", "6"))
    assert "2019" not in obs, "una partición incompleta no produce dato"
    assert "2013" in obs, "la otra observación, que sí suma 1, se conserva"


def test_una_materia_ausente_NO_se_confunde_con_ausencia_de_dato():
    """«Esta tabla no lo trae» y «el dato no existe» son cosas distintas."""
    with pytest.raises(LLECEUnavailable) as e:
        parse_bajo_nivel_ii(CABECERA + RD_MAT6, "Ciencias", "3")
    assert "no se puede afirmar que el dato no exista" in str(e.value)


def test_el_diagnostico_dice_que_trae_la_tabla():
    assert niveles_disponibles(CABECERA + RD_MAT6) == {"Matematicas": ["6"]}
