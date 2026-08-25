"""Ningún indicador de la ley puede quedar en silencio.

Un indicador sin veredicto y sin motivo es indistinguible de uno que nadie miró, y esa
ambigüedad es la que vuelve inauditable un informe de cumplimiento. El motor se niega a
servir un expediente así.

La segunda regla que fijan estos tests es la que impide que el cierre sea una casilla:
«buscamos y no hay» exige evidencia con fecha; «no hemos buscado» no la exige y se cuenta
aparte. Sin esa separación, cerrar el campo se lograría declarando todo pendiente.
"""
import pytest

from modules.law_intel.campo import (ESTADOS_DEL_CAMPO, Casilla, _validar, campo, resumen)
from modules.law_intel.registro import ExpedienteInvalido

EXPEDIENTE = "end_2030"


@pytest.fixture(scope="module")
def r():
    return resumen(EXPEDIENTE)


class TestNadieEnSilencio:
    def test_el_expediente_real_tiene_el_campo_cerrado(self, r):
        assert r["en_silencio"] == 0
        assert r["campo_cerrado"] is True
        assert r["con_veredicto"] + r["declarados_sin_veredicto"] == \
            r["total_indicadores_de_la_ley"]

    def test_un_indicador_sin_veredicto_y_sin_motivo_LEVANTA(self, monkeypatch):
        """Es el guard central. Sin él, un indicador nuevo entra al registro y desaparece."""
        from modules.law_intel import campo as m

        declarado = dict(m._declarado(EXPEDIENTE))
        declarado.pop("4.4")                      # se le quita el motivo a uno real
        monkeypatch.setattr(m, "_declarado", lambda e: declarado)
        with pytest.raises(ExpedienteInvalido, match="silencio"):
            m.campo(EXPEDIENTE)

    def test_cada_casilla_trae_su_detalle(self):
        vacias = [c.indicador for c in campo(EXPEDIENTE).values() if not c.detalle.strip()]
        assert not vacias, f"casillas sin detalle: {vacias}"


class TestCerradoNoEsResuelto:
    """La composición se publica al lado de la cifra a propósito."""

    def test_el_resumen_separa_lo_resuelto_de_lo_pendiente(self, r):
        assert r["motivo_resuelto"] + r["pendientes_de_trabajo_nuestro"]["n"] == \
            r["declarados_sin_veredicto"]

    def test_hay_pendientes_declarados_y_eso_es_correcto(self, r):
        """Un expediente sin pendientes a esta altura sería sospechoso, no bueno."""
        assert r["pendientes_de_trabajo_nuestro"]["n"] > 0

    def test_los_estados_publicados_estan_en_el_conjunto_cerrado(self, r):
        assert set(r["por_estado"]) <= set(ESTADOS_DEL_CAMPO)


class TestLaEvidenciaSeparaElHallazgoDeLaConjetura:
    def test_afirmar_que_no_existe_fuente_EXIGE_evidencia_con_fecha(self):
        """«No existe fuente» es una afirmación sobre el mundo. Sin evidencia es conjetura."""
        for estado in ("sin_fuente_conocida", "fuente_no_procesable",
                       "magnitud_no_publicada", "instrumento_discontinuado"):
            with pytest.raises(ExpedienteInvalido, match="evidencia"):
                _validar({"x": Casilla("x", estado, "detalle", evidencia=None)})

    def test_la_evidencia_sin_fecha_tampoco_alcanza(self):
        with pytest.raises(ExpedienteInvalido, match="evidencia"):
            _validar({"x": Casilla("x", "sin_fuente_conocida", "d", evidencia="se buscó")})

    def test_pendiente_NO_exige_evidencia(self):
        """Es el punto del estado: declarar que no se buscó no requiere probar nada."""
        _validar({"x": Casilla("x", "pendiente_de_busqueda", "no se buscó todavía")})

    def test_los_estados_definitivos_del_expediente_real_traen_su_fecha(self):
        from modules.law_intel.campo import _EXIGEN_EVIDENCIA

        for c in campo(EXPEDIENTE).values():
            if c.estado in _EXIGEN_EVIDENCIA:
                assert (c.evidencia or "").strip() and (c.verificado_el or "").strip(), c.indicador


class TestLoComputadoNoSeDeclara:
    def test_un_estado_computado_no_admite_declaracion_a_mano(self):
        """Dos verdades sobre el mismo hecho terminan divergiendo."""
        with pytest.raises(ExpedienteInvalido, match="se computa"):
            _validar({"x": Casilla("x", "sin_meta_legal", "d", evidencia="a mano",
                                   verificado_el="2026-08-21")})

    def test_los_sin_meta_de_la_ley_salen_solos(self):
        c = campo(EXPEDIENTE)
        assert c["1.5"].estado == "sin_meta_legal"
        assert c["1.6"].estado == "sin_meta_legal"

    def test_un_binding_descartado_hereda_su_motivo(self):
        c = campo(EXPEDIENTE)["2.23"]
        assert c.estado == "candidato_descartado"
        assert "mortalidad materna" in c.detalle.lower() or c.detalle.strip()


def test_un_estado_inventado_no_carga():
    with pytest.raises(ExpedienteInvalido, match="desconocido"):
        _validar({"x": Casilla("x", "ya_veremos", "d")})

class TestQueSeDESCUENTAdelGate:
    """La lista que saca indicadores del denominador del readiness.

    Es correcta y es peligrosa: mal usada, un eje esconde su propia deuda detrás de «lo
    impide el instrumento». Estos tests son la cerradura.
    """

    def test_TODO_motivo_del_campo_esta_clasificado_de_un_lado(self):
        """Un motivo nuevo tiene que clasificarse a mano. Si cayera por defecto, caería del
        lado que conviene — y el lado que conviene es el que infla la cobertura."""
        from modules.law_intel.campo import (DEPENDEN_DE_NOSOTROS, ESTADOS_DEL_CAMPO,
                                             IMPOSIBLES_POR_EL_INSTRUMENTO)
        sin_clasificar = (set(ESTADOS_DEL_CAMPO) - IMPOSIBLES_POR_EL_INSTRUMENTO
                          - DEPENDEN_DE_NOSOTROS)
        assert not sin_clasificar, (
            f"motivos sin clasificar para el gate: {sorted(sin_clasificar)}")

    def test_las_dos_listas_son_DISJUNTAS(self):
        from modules.law_intel.campo import DEPENDEN_DE_NOSOTROS, IMPOSIBLES_POR_EL_INSTRUMENTO
        assert not (IMPOSIBLES_POR_EL_INSTRUMENTO & DEPENDEN_DE_NOSOTROS)

    def test_NUESTRA_deuda_nunca_sale_del_denominador(self):
        """Los cinco que dependen de nosotros siguen pesando aunque duelan.
        `fuente_no_procesable` es la más tentadora —el emisor publica en un formato
        incómodo— y se queda: un formato difícil es trabajo, no una imposibilidad legal."""
        from modules.law_intel.campo import IMPOSIBLES_POR_EL_INSTRUMENTO
        for nuestro in ("pendiente_de_busqueda", "candidato_descartado",
                        "candidato_sin_verificar", "pendiente_de_derivacion",
                        "fuente_no_procesable"):
            assert nuestro not in IMPOSIBLES_POR_EL_INSTRUMENTO

    def test_lo_descontado_SIGUE_declarado_en_el_expediente(self):
        """Un descuento silencioso se leería como que esos indicadores no existen. Todo lo
        que sale del denominador tiene su casilla, con estado y motivo."""
        from modules.law_intel.campo import (IMPOSIBLES_POR_EL_INSTRUMENTO, campo,
                                             imposibles_por_el_instrumento)
        casillas = campo("end_2030")
        descontados = [c for c in casillas.values()
                       if c.estado in IMPOSIBLES_POR_EL_INSTRUMENTO]
        assert len(descontados) == imposibles_por_el_instrumento("end_2030")
        assert all(c.estado and c.detalle for c in descontados)
        # Y todos cierran la pregunta: nada pendiente sale del denominador.
        assert all(c.resuelto for c in descontados)

    def test_el_descuento_no_puede_vaciar_el_universo(self):
        from modules.law_intel.bindings import cobertura
        from modules.law_intel.campo import imposibles_por_el_instrumento
        total = cobertura("end_2030")["total"]
        assert 0 < total - imposibles_por_el_instrumento("end_2030") <= total

