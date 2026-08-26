"""El aseo de los directorios de salida.

Es la única tarea del sistema que BORRA archivos, así que los tests pesan más que de
costumbre: cada guard se prueba por el lado que importa —que NO borre— y no solo por el que
funciona.
"""
import time

import pytest

from shared.operations.aseo import (EXTENSIONES, RETENCION_DIAS, AseoError, archivos_protegidos,
                                    barrer, directorios_declarados, run_aseo)

DIA = 86400


@pytest.fixture()
def salida(tmp_path):
    """Un `data/charts` de mentira, con archivos de edades distintas."""
    d = tmp_path / "data" / "charts"
    d.mkdir(parents=True)
    ahora = time.time()

    def _crear(nombre, dias, contenido=b"x" * 1024):
        f = d / nombre
        f.write_bytes(contenido)
        import os
        os.utime(f, (ahora - dias * DIA, ahora - dias * DIA))
        return f

    return d, _crear, ahora


class TestNoBarreLoQueNoDECLARO:
    def test_un_directorio_fuera_de_la_raiz_de_datos_LEVANTA(self, tmp_path):
        otro = tmp_path / "documentos" / "cliente"
        otro.mkdir(parents=True)
        with pytest.raises(AseoError, match="no cae bajo"):
            barrer(str(otro), "charts")

    def test_una_ruta_demasiado_ARRIBA_levanta(self):
        """Un error de ruta en una tarea de aseo no se recupera."""
        with pytest.raises(AseoError):
            barrer("/", "charts")

    def test_una_clase_sin_retencion_declarada_LEVANTA(self, salida):
        d, _, _ = salida
        with pytest.raises(AseoError, match="sin retención declarada"):
            barrer(str(d), "lo_que_sea")

    def test_un_directorio_inexistente_LEVANTA(self, tmp_path):
        with pytest.raises(AseoError, match="no es un directorio"):
            barrer(str(tmp_path / "data" / "no_existe"), "charts")

    def test_retencion_CERO_levanta(self, salida):
        """Una ventana de cero borraría la salida de la corrida en curso."""
        d, _, _ = salida
        with pytest.raises(AseoError, match="retención de 0 días"):
            barrer(str(d), "charts", dias=0)


class TestSoloBarreLoDeclarado:
    def test_respeta_la_ventana_de_retencion(self, salida):
        d, crear, ahora = salida
        crear("viejo.png", 30)
        crear("nuevo.png", 1)
        b = barrer(str(d), "charts", ahora=ahora)
        assert b.borrados == 1
        assert (d / "nuevo.png").exists() and not (d / "viejo.png").exists()

    def test_NO_toca_extensiones_que_no_declaró(self, salida):
        """Si alguien deja un `.csv` de trabajo ahí, el aseo no lo toca. Una tarea que borra
        «todo lo viejo» borra lo que no sabía que había."""
        d, crear, ahora = salida
        crear("viejo.png", 30)
        crear("trabajo.csv", 300)
        crear("base.sqlite", 300)
        b = barrer(str(d), "charts", ahora=ahora)
        assert b.borrados == 1
        assert (d / "trabajo.csv").exists() and (d / "base.sqlite").exists()

    def test_la_lista_de_extensiones_es_BLANCA_por_clase(self):
        assert ".png" in EXTENSIONES["charts"] and ".pdf" not in EXTENSIONES["charts"]
        assert ".pdf" in EXTENSIONES["reports"]

    def test_no_entra_en_subdirectorios(self, salida):
        d, crear, ahora = salida
        sub = d / "subcarpeta"
        sub.mkdir()
        f = sub / "viejo.png"
        f.write_bytes(b"x")
        import os
        os.utime(f, (ahora - 300 * DIA, ahora - 300 * DIA))
        barrer(str(d), "charts", ahora=ahora)
        assert f.exists()

    def test_las_retenciones_son_CONSTANTES_a_la_vista(self):
        assert RETENCION_DIAS["charts"] == 7
        assert RETENCION_DIAS["reports"] == 90


class TestLoPROTEGIDOnoSeBorraNunca:
    def test_un_archivo_referenciado_sobrevive_aunque_sea_el_mas_viejo(self, salida):
        """Se protege por REFERENCIA, no por antigüedad: la edad no dice nada sobre si
        alguien lo necesita. Medido en dev: de 2 informes, 1 dependía del archivo."""
        d, crear, ahora = salida
        f = crear("informe_legacy.png", 500)
        otro = crear("basura.png", 500)
        b = barrer(str(d), "charts", protegidos={str(f.resolve())}, ahora=ahora)
        assert f.exists() and not otro.exists()
        assert b.protegidos_por_referencia == 1
        assert b.borrados == 1

    def test_sin_sesion_de_base_NO_barre_a_ciegas(self):
        """Un «no hay protegidos» falso es exactamente cómo se borra lo que hacía falta."""
        with pytest.raises(AseoError, match="barrer a ciegas"):
            archivos_protegidos(None)

    def test_protege_solo_los_informes_SIN_blob(self):
        """El que tiene blob se regenera del store durable; el que no, solo vive en disco."""
        class _Q:
            def __init__(self, filas):
                self._f = filas

            def filter(self, *a, **k):
                return self

            def all(self):
                return self._f

        class _DB:
            def query(self, *a, **k):
                return _Q([("/tmp/data/reports/solo_en_disco.pdf",)])

        prot = archivos_protegidos(_DB())
        assert any("solo_en_disco.pdf" in p for p in prot)


class TestElSIMULACROnoBorra:
    def test_cuenta_sin_borrar(self, salida):
        d, crear, ahora = salida
        crear("viejo.png", 30)
        b = barrer(str(d), "charts", simulacro=True, ahora=ahora)
        assert b.borrados == 1 and b.simulacro is True
        assert (d / "viejo.png").exists(), "el simulacro borró de verdad"

    def test_el_simulacro_reporta_los_MISMOS_bytes_que_el_barrido(self, salida):
        d, crear, ahora = salida
        crear("viejo.png", 30, b"y" * 4096)
        seco = barrer(str(d), "charts", simulacro=True, ahora=ahora)
        real = barrer(str(d), "charts", ahora=ahora)
        assert seco.bytes_liberados == real.bytes_liberados == 4096


class TestLaOPERACIONdelConsole:
    def _op(self):
        import shared.operations.operaciones_de_aseo  # noqa: F401
        from shared.operations.service import OPERATIONS
        return OPERATIONS["aseo-directorios-de-salida"]

    def test_esta_registrada_y_es_SEMANAL(self):
        assert self._op().default_interval_hours == 168

    def test_se_AUTO_AGENDA(self):
        from shared.operations.service import is_on_demand
        assert is_on_demand(self._op()) is False

    def test_la_descripcion_dice_QUE_protege(self):
        """Una tarea que borra tiene que decir qué NO borra, o nadie la deja encendida."""
        d = self._op().description
        assert "PROTEGIDOS" in d and "file_blob" in d
        assert "simulacro" in d

    def test_los_directorios_salen_de_la_CONFIGURACION(self):
        dd = directorios_declarados()
        assert set(dd) == {"charts", "reports"}
        assert all(v for v in dd.values())


def test_run_aseo_no_revienta_si_un_directorio_no_existe(tmp_path, monkeypatch):
    """En una instalación nueva `data/reports` puede no existir todavía."""
    d = tmp_path / "data" / "charts"
    d.mkdir(parents=True)
    monkeypatch.setattr("shared.operations.aseo.directorios_declarados",
                        lambda: {"charts": str(d), "reports": str(tmp_path / "data" / "nada")})

    class _DB:
        def query(self, *a, **k):
            class _Q:
                def filter(self, *a, **k):
                    return self

                def all(self):
                    return []
            return _Q()

    r = run_aseo(simulacro=True, db=_DB())
    assert [x["clase"] for x in r["por_directorio"]] == ["charts"]
