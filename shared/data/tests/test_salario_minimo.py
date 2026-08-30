"""El salario mínimo del MHE: mensual, por tamaño de empresa y área — y con su vejez visible.

Por qué esta fuente y no otra. El Comité Nacional de Salarios lo fija por resolución y el
portal del Ministerio de Trabajo lo publica como noticias, sin dataset; CEPALSTAT tiene API
pero su índice de indicadores devuelve 404. El Ministerio de Hacienda y Economía publica la
serie 2000-2025 completa en el portal nacional de datos abiertos.

Lo que estos tests fijan son las tres formas en que este archivo puede leerse mal en
silencio: la CODIFICACIÓN (latin-1; en UTF-8 la columna «TAMAÑO EMPRESA» deja de existir), el
SEPARADOR DE MILES (la coma de «27,989» leída como decimal convierte veintiocho mil pesos en
veintiocho) y la VEJEZ (una serie escalonada repite su valor hasta el próximo ajuste, así que
una categoría abandonada se ve idéntica a una vigente).
"""
import pytest

from shared.data.salario_minimo import (
    SalarioMinimoUnavailable,
    parse_salario_minimo,
)

_CABECERA = "SECTOR;TAMAÑO EMPRESA;AREAS;MES;AÑO;SALARIO MINIMO;\n"


def _csv(filas: str) -> bytes:
    return (_CABECERA + filas).encode("latin-1")


def _meses(anio, valor, meses=("Enero", "Febrero", "Marzo"), tam="Empresa grande",
           area="Empresas del sector no sectorizado"):
    return "".join(f"Sector privado;{tam};{area};{m};{anio};{valor};\n" for m in meses)


class TestElFormatoSeLeeBien:
    def test_la_coma_es_separador_de_MILES_y_no_decimal(self):
        """«27,989» son veintiocho mil pesos. Leído como decimal daría 27,99 — un salario
        mínimo de veintiocho pesos, que ningún control de rango detectaría como absurdo si
        el resto de la serie también se leyera mal."""
        s = parse_salario_minimo(_csv(_meses(2025, "27,989", ("Enero",))))[0]
        assert s.puntos == [("2025-01", 27989.0)]

    def test_la_codificacion_latin1_conserva_la_columna_con_eñe(self):
        """En UTF-8 «TAMAÑO EMPRESA» se rompe y la columna deja de encontrarse."""
        s = parse_salario_minimo(_csv(_meses(2024, "24,990", ("Enero",))))[0]
        assert s.tamano == "Empresa grande"

    def test_el_periodo_sale_del_MES_en_castellano(self):
        s = parse_salario_minimo(_csv(_meses(2024, "1,000", ("Enero", "Septiembre", "Diciembre"))))[0]
        assert [p for p, _ in s.puntos] == ["2024-01", "2024-09", "2024-12"]

    def test_la_serie_viene_ORDENADA_aunque_el_csv_no_lo_esté(self):
        filas = _meses(2025, "2,000", ("Enero",)) + _meses(2024, "1,000", ("Diciembre",))
        s = parse_salario_minimo(_csv(filas))[0]
        assert [p for p, _ in s.puntos] == ["2024-12", "2025-01"]


class TestLaVejezDeUnaSerieESCALONADA:
    """Una serie que repite su valor no dice si está estable o abandonada."""

    def test_el_ultimo_cambio_es_la_fecha_del_ESCALON_no_la_del_ultimo_punto(self):
        # Fiel al caso real: la serie SÍ se ajustó en 2006-07 y desde entonces repite.
        filas = (_meses(2006, "2,490", ("Mayo", "Junio"))
                 + _meses(2006, "3,600", ("Julio", "Agosto"))
                 + _meses(2025, "3,600", ("Enero", "Febrero")))
        s = parse_salario_minimo(_csv(filas))[0]
        assert s.puntos[-1][0] == "2025-02"      # el último punto es reciente…
        assert s.ultimo_cambio == "2006-07"      # …pero el último AJUSTE tiene 19 años

    def test_una_serie_que_nunca_cambio_lo_DICE_con_None(self):
        s = parse_salario_minimo(_csv(_meses(2024, "1,000", ("Enero", "Febrero"))))[0]
        assert s.ultimo_cambio is None

    def test_los_escalones_son_solo_los_meses_de_AJUSTE(self):
        filas = (_meses(2024, "10,000", ("Enero", "Febrero", "Marzo"))
                 + _meses(2024, "12,000", ("Abril", "Mayo")))
        s = parse_salario_minimo(_csv(filas))[0]
        assert s.escalones == [("2024-01", 10000.0), ("2024-04", 12000.0)]


class TestUnCambioDeLayoutSE_DECLARA:
    def test_sin_las_columnas_esperadas_falla_y_dice_cuales(self):
        with pytest.raises(SalarioMinimoUnavailable, match="faltan columnas"):
            parse_salario_minimo(b"OTRA;COSA;\nx;y;\n")

    def test_un_csv_vacio_no_devuelve_una_lista_vacia_en_silencio(self):
        with pytest.raises(SalarioMinimoUnavailable, match="vino vacío"):
            parse_salario_minimo(b"")

    def test_si_los_meses_dejan_de_reconocerse_lo_DICE(self):
        """Sin esto, un cambio a meses en inglés dejaría cero series y nadie se enteraría."""
        with pytest.raises(SalarioMinimoUnavailable, match="ninguna serie"):
            parse_salario_minimo(_csv(_meses(2024, "1,000", ("January", "February"))))

    def test_un_monto_ilegible_se_SALTA_sin_romper_la_serie(self):
        filas = _meses(2024, "1,000", ("Enero",)) + _meses(2024, "n/d", ("Febrero",))
        s = parse_salario_minimo(_csv(filas))[0]
        assert s.puntos == [("2024-01", 1000.0)]


def test_cada_combinacion_de_tamaño_y_area_es_su_propia_serie():
    """«Empresa grande» vale distinto en hotelería que fuera de ella: si colapsaran, un
    valor pisaría al otro y la serie mezclaría dos regímenes salariales."""
    filas = (_meses(2025, "27,989", ("Enero",))
             + _meses(2025, "16,800", ("Enero",), area="Hoteles, bares y restaurantes"))
    series = parse_salario_minimo(_csv(filas))
    assert len(series) == 2
    assert {s.puntos[0][1] for s in series} == {27989.0, 16800.0}
