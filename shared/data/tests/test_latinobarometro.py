"""El conector habla con un servicio NO documentado, así que los tests son el contrato.

Cada uno de acá corresponde a una forma en que ese servicio puede cambiar sin avisar. El más
importante no es que el cálculo dé bien: es que cuando el país NO fue encuestado el servicio
devuelve la tabla de los dieciocho países juntos, con éxito y sin marca, y publicar eso como
cifra dominicana sería el peor error posible de esta plataforma.
"""
import pytest

from shared.data.latinobarometro import (BASE_MAXIMA_DE_UN_PAIS, CATEGORIAS_CONFIA,
                                         LatinobarometroUnavailable, RONDAS,
                                         parse_confianza)


def _respuesta(rotulo="Dominican Republic", base=984, frecuencias=None, success=True):
    """La forma real de la respuesta, recortada a lo que el parser mira."""
    frecuencias = frecuencias or {1: 37, 2: 182, 3: 349, 4: 416, -1: 7, -2: 9}
    return {
        "success": success,
        "samplestext": rotulo,
        "footerTable": rotulo,
        "resultado": {"tables": [{
            "rows": [{"valorCat": c, "frecuenciasN": [n], "porcentaje": [n / 10.0]}
                     for c, n in frecuencias.items()],
            "baseSinMissing": [base],
        }]},
    }


class TestElGuardDelAmbito:
    def test_el_ano_sin_el_pais_se_OMITE_en_vez_de_publicarse(self):
        """El caso real: antes de 2004 el país no entra en la encuesta y el servicio cae al
        agregado regional con éxito. Devolver ese número como dominicano sería atribuirle al
        país la opinión de dieciocho."""
        assert parse_confianza(_respuesta(rotulo="", base=22018)) is None

    def test_un_rotulo_de_OTRO_pais_tampoco_pasa(self):
        assert parse_confianza(_respuesta(rotulo="Costa Rica")) is None

    def test_el_rotulo_vale_en_los_DOS_idiomas_del_emisor(self):
        """El mismo servicio devolvió «República Dominicana» para 2010 y «Dominican Republic»
        para 2024. Aceptar uno solo perdería la mitad de la serie en silencio."""
        for rotulo in ("Dominican Republic", "República Dominicana", "REPUBLICA DOMINICANA"):
            assert parse_confianza(_respuesta(rotulo=rotulo)) is not None, rotulo

    def test_una_base_de_pais_imposible_LEVANTA_aunque_el_rotulo_diga_el_pais(self):
        """El segundo cinturón. Si el emisor algún día rotula bien y agrega igual, el tamaño
        de la base lo delata."""
        with pytest.raises(LatinobarometroUnavailable, match="agregó ámbitos"):
            parse_confianza(_respuesta(base=BASE_MAXIMA_DE_UN_PAIS + 1))


class TestLaMagnitud:
    def test_suma_las_dos_primeras_sobre_la_base_SIN_no_respuesta(self):
        """37 + 182 = 219 sobre 984 = 22,26%, que es lo que reproduce la línea base legal de
        22,2 para 2010. Sobre el total de 1.000 daría 21,9% y ya no cerraría igual."""
        assert parse_confianza(_respuesta()) == 22.26

    def test_las_categorias_de_confianza_son_las_dos_primeras(self):
        """Si alguien las cambia, cambia el indicador. Queda fijado acá."""
        assert CATEGORIAS_CONFIA == (1, 2)

    def test_si_falta_una_categoria_sustantiva_LEVANTA(self):
        """Una escala de tres puntos no es la misma magnitud que una de cuatro, y el
        porcentaje seguiría saliendo sin que nada avise."""
        with pytest.raises(LatinobarometroUnavailable, match="escala del emisor cambió"):
            parse_confianza(_respuesta(frecuencias={1: 37, 2: 182, 3: 349, -1: 7}))

    def test_sin_base_sin_no_respuesta_LEVANTA(self):
        with pytest.raises(LatinobarometroUnavailable, match="base sin no-respuesta"):
            parse_confianza(_respuesta(base=0))

    def test_una_fila_ilegible_LEVANTA_en_vez_de_saltarse(self):
        """Saltarse una fila cambiaría la base implícita y el porcentaje saldría igual de
        plausible."""
        mala = _respuesta()
        mala["resultado"]["tables"][0]["rows"][0] = {"valorCat": 1, "frecuenciasN": []}
        with pytest.raises(LatinobarometroUnavailable, match="fila ilegible"):
            parse_confianza(mala)

    def test_una_respuesta_sin_exito_no_se_interpreta(self):
        assert parse_confianza(_respuesta(success=False)) is None


class TestElMapaDeRondas:
    def test_las_rondas_no_son_correlativas_y_por_eso_se_declaran(self):
        """2013 es la ronda 573 y 2015 es la 1539: entre dos años consecutivos de la encuesta
        hay casi mil identificadores. Inferir el año del id daría cualquier cosa."""
        assert RONDAS[573] == 2013 and RONDAS[1539] == 2015

    def test_no_hay_dos_rondas_para_el_mismo_ano(self):
        anios = list(RONDAS.values())
        assert len(anios) == len(set(anios))

    def test_estan_los_anos_que_la_ley_necesita(self):
        """La línea base y los tres cortes con meta. Si el emisor deja de cubrir alguno, este
        test lo dice antes que el informe."""
        for anio in (2010, 2015, 2020):
            assert anio in RONDAS.values(), anio
