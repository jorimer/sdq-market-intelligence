"""Áreas protegidas (ONE) — indicador 4.2 de la END.

Las filas son REALES, del conjunto del portal nacional: dos niveles anidados, un rótulo que
es grupo y subcategoría a la vez, y las erratas del emisor («Mamiferso», «Reservsa»).
"""
import pytest

from shared.data.one_areas_protegidas import (BANDA_PCT, ESTRUCTURA, GRUPOS,
                                              AreasProtegidasError, leer_filas,
                                              razon_terrestre, superficies_de)

#: 2007 completo, tal cual viene: 19 filas, seis grupos con sus subcategorías debajo.
FILAS_2007 = [
    ["Áreas de protección estricta", "8", "201", "35263", "2007"],
    ["Reservas Científicas ", "6", "180", "0", "2007"],
    ["Santuarios de Mamiferso Marinos", "2", "21", "35263", "2007"],
    ["Reserva Biológica", "0", "0", "0", "2007"],
    ["Parques Nacionales ", "19", "6863", "1486", "2007"],
    ["Parque Nacionales", "17", "6862", "1231", "2007"],
    ["Parques Nacionales Submarinos", "2", "1", "255", "2007"],
    ["Monumentos Naturales", "19", "504", "7", "2007"],
    ["Monumentos Naturales ", "17", "470", "7", "2007"],
    ["Refugios de Vida Silvestre", "2", "34", "0", "2007"],
    ["Áreas de Manejo de Habitat/ Especies", "14", "257", "161", "2007"],
    ["Refugios de Vida Silvestre", "14", "257", "161", "2007"],
    ["Santuario Marino", "0", "0", "0", "2007"],
    ["Reservsa Naturales", "15", "1620", "0", "2007"],
    ["Reservas Forestales", "15", "1620", "0", "2007"],
    ["Paisajes Protegidos", "12", "297", "46", "2007"],
    ["Vía Panorámica ", "9", "191", "12", "2007"],
    ["Áreas Naturales de Recreo", "3", "106", "33", "2007"],
    ["Corredor Ecológico", "0", "0", "0", "2007"],
]

#: 2012: el emisor NO cuadra consigo mismo en la marina del primer grupo (43.459 contra
#: 0 + 32.897 + 0). Es real y se declara; el año no se tira.
FILAS_2012 = [[f[0], f[1], f[2], f[3], "2012"] for f in FILAS_2007]
FILAS_2012[0] = ["Áreas de protección estricta", "14", "201", "43459", "2012"]


def test_suma_solo_los_SEIS_grupos_y_no_las_diecinueve_filas():
    """Sumarlas todas cuenta cada superficie dos veces: 19.484 en vez de 9.742."""
    s = superficies_de(FILAS_2007)[0]
    assert s.terrestre_km2 == pytest.approx(9742.0)
    todas = sum(float(f[2]) for f in FILAS_2007)
    assert todas == pytest.approx(19484.0), "el doble conteo es real, no hipotético"


def test_los_grupos_NO_se_eligen_por_su_rotulo():
    """«Monumentos Naturales» es grupo Y subcategoría —una lleva espacio final— y «Refugios
    de Vida Silvestre» aparece bajo dos grupos. Normalizar los rótulos las vuelve
    indistinguibles, así que la decisión es posicional y la respalda `ESTRUCTURA`."""
    assert ESTRUCTURA[7] == ESTRUCTURA[8] == "MONUMENTOS NATURALES"
    assert ESTRUCTURA.count("REFUGIOS DE VIDA SILVESTRE") == 2
    assert len(GRUPOS) == 6


def test_una_estructura_DISTINTA_levanta_en_vez_de_sumar_al_lado():
    """Es lo que hace legítimo leer por posición: si el emisor agrega o reordena una
    categoría, esto para en vez de servir una serie creíble."""
    rotas = [list(f) for f in FILAS_2007]
    rotas.insert(3, ["Categoría nueva del emisor", "1", "99", "0", "2007"])
    with pytest.raises(AreasProtegidasError, match="estructura"):
        superficies_de(rotas)


def test_el_desajuste_del_EMISOR_se_declara_y_no_tira_el_ano():
    """Un primer intento identificaba los grupos POR la identidad y se saltaba en silencio
    los que no cerraban: 2021 daba 3.037 km² donde van 11.896. Servir algo plausible es
    peor que fallar."""
    s = superficies_de(FILAS_2012)[0]
    assert s.terrestre_km2 == pytest.approx(9742.0), "el año se lee igual"
    assert any("marina" in d for d in s.desajustes)
    assert not any("terrestre" in d for d in s.desajustes)


def test_un_ano_que_SI_cuadra_no_declara_desajustes():
    assert superficies_de(FILAS_2007)[0].desajustes == ()


class TestLaRazon:
    def test_reproduce_la_LINEA_BASE_de_la_ley(self):
        """La ley fija 24,4% para 2009 y el cuadro da 11.684 km² sobre 48.198 = 24,24%."""
        from shared.data.one_areas_protegidas import Superficie

        s = Superficie(anio=2009, terrestre_km2=11684.0, marina_km2=48032.0)
        pct = razon_terrestre(s, 48198.02)
        assert pct == pytest.approx(24.24, abs=0.02)
        assert abs(pct - 24.4) / 24.4 * 100 < 2.0, "cierra el oráculo"

    def test_meter_lo_MARINO_no_reproduce_nada(self):
        """El informe del Estado deja abierto si la razón incluye lo marino. El oráculo lo
        decide sin que haya que opinar: con lo marino la razón se va a un dígito."""
        from shared.data.one_areas_protegidas import Superficie

        s = Superficie(anio=2009, terrestre_km2=11684.0, marina_km2=48032.0)
        solo_terrestre = razon_terrestre(s, 48198.02)
        con_marino = (s.terrestre_km2 + s.marina_km2) / (48198.02 + 269000) * 100
        d_terrestre = abs(solo_terrestre - 24.4) / 24.4 * 100
        d_marino = abs(con_marino - 24.4) / 24.4 * 100
        # 0,7% contra 22,8%: una entra en la tolerancia del oráculo (2,0%) y la otra se va
        # a diez veces esa distancia. No hace falta interpretar el informe del emisor.
        assert d_terrestre < 2.0 < d_marino
        assert d_marino / d_terrestre > 10

    def test_sin_denominador_LEVANTA(self):
        from shared.data.one_areas_protegidas import Superficie

        with pytest.raises(AreasProtegidasError, match="área terrestre"):
            razon_terrestre(Superficie(2009, 11684.0, 0.0), 0.0)

    def test_la_banda_ataja_un_denominador_en_otra_UNIDAD(self):
        """Si alguien pasara el área en hectáreas, la razón se iría a la décima parte."""
        from shared.data.one_areas_protegidas import Superficie

        with pytest.raises(AreasProtegidasError, match="fuera de la banda"):
            razon_terrestre(Superficie(2009, 11684.0, 0.0), 48198.02 * 100)
        assert BANDA_PCT == (1.0, 60.0)


def test_el_csv_se_lee_con_su_ENCODING_y_sin_cabecera():
    texto = ("Categoría y subcategoría;Cantidad;Superficie Terrestre;Superficie Marina;Año\n"
             + "\n".join(";".join(f) for f in FILAS_2007))
    filas = leer_filas(texto)
    assert len(filas) == 19 and filas[0][0].startswith("Áreas")
