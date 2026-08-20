"""No se acusa sin evidencia, y no se confunde «no hay rastro» con «no se hizo».

Es el guard más importante del módulo. El destinatario del informe suele ser el órgano al que
la obligación le corresponde: afirmarle al Congreso que su comisión nunca se constituyó, sin
haber consultado los expedientes de Cámara y Senado, es refutable con un solo documento.
"""
import pytest

from modules.law_intel.obligaciones import (ACUSATORIOS, ESTADOS, Obligacion, _validar,
                                            cargar_obligaciones, por_producto, resumen)
from modules.law_intel.registro import ExpedienteInvalido

EXPEDIENTE = "end_2030"


def ob(**kw):
    base = dict(id="x", articulo=1, deber="d", deudor={"tipo": "organo", "nombre": "n"},
                estado="cumplida")
    return Obligacion(**{**base, **kw})


class TestNoAcusarSinEvidencia:
    @pytest.mark.parametrize("estado", sorted(ACUSATORIOS))
    def test_todo_estado_acusatorio_exige_evidencia(self, estado):
        with pytest.raises(ExpedienteInvalido, match="no trae evidencia"):
            _validar([ob(estado=estado)])

    @pytest.mark.parametrize("estado", sorted(ACUSATORIOS))
    def test_con_evidencia_pasa(self, estado):
        _validar([ob(estado=estado, evidencia="Decreto 134-14 del 2014-04-09")])

    def test_evidencia_en_blanco_no_cuenta(self):
        with pytest.raises(ExpedienteInvalido):
            _validar([ob(estado="incumplida", evidencia="   ")])

    def test_sin_registro_publico_no_exige_evidencia(self):
        """Es la salida honesta: se puede declarar la ausencia de rastro sin probarla."""
        _validar([ob(estado="sin_registro_publico")])


class TestLaFraseQueSalePublicada:
    def test_sin_registro_no_afirma_incumplimiento(self):
        f = ob(articulo=51, estado="sin_registro_publico").frase_publicable()
        assert "No se afirma incumplimiento" in f
        assert "incumpl" in f.lower()      # la palabra aparece solo para negarla
        assert not f.startswith("Artículo 51: hay evidencia")

    def test_el_objeto_marca_lo_que_falta_verificar(self):
        assert ob(estado="sin_registro_publico").requiere_verificacion_antes_de_publicar
        assert not ob(estado="incumplida", evidencia="x").requiere_verificacion_antes_de_publicar

    def test_no_exigible_se_explica_por_su_diseño(self):
        f = ob(articulo=36, estado="no_exigible",
               deudor={"tipo": "indeterminado", "nombre": "las fuerzas"}).frase_publicable()
        assert "no tiene deudor determinado" in f


class TestExigibilidad:
    def test_deudor_indeterminado_no_es_exigible(self):
        """Una obligación cuyo sujeto pasivo son «las fuerzas políticas, económicas y
        sociales» es inexigible por construcción: no hay a quién requerir."""
        o = ob(estado="no_exigible", deudor={"tipo": "indeterminado", "nombre": "las fuerzas"})
        assert not o.exigible

    def test_organo_con_estado_normal_si_es_exigible(self):
        assert ob(estado="incumplida", evidencia="x").exigible

    def test_tipo_de_deudor_invalido_no_carga(self):
        with pytest.raises(ExpedienteInvalido, match="deudor"):
            _validar([ob(deudor={"tipo": "persona", "nombre": "n"})])


class TestExpedienteReal:
    def test_carga(self):
        obs = cargar_obligaciones(EXPEDIENTE)
        assert len(obs) >= 6
        assert all(o.estado in ESTADOS for o in obs)

    def test_el_hallazgo_central_se_cuenta_no_se_afirma(self):
        """«Ningún control tiene consecuencia asignada» deja de ser prosa y pasa a ser un
        conteo que alguien puede refutar fila por fila."""
        r = resumen(EXPEDIENTE)
        assert r["sin_consecuencia_asignada"]["n"] == r["total"]
        assert "frenos que nadie está obligado a pisar" in \
            r["sin_consecuencia_asignada"]["lectura"]

    def test_el_pacto_fiscal_queda_como_no_exigible(self):
        o = next(x for x in cargar_obligaciones(EXPEDIENTE) if x.id == "art-36-pacto-fiscal")
        assert o.estado == "no_exigible" and not o.exigible
        assert "inexigible POR CONSTRUCCIÓN" in (o.nota_de_diseño or "")

    def test_la_comision_bicameral_queda_marcada_para_verificar(self):
        """Es el destinatario del informe: la afirmación negativa no puede salir sin comprobar."""
        o = next(x for x in cargar_obligaciones(EXPEDIENTE) if x.id == "art-51-comision-bicameral")
        assert o.estado == "sin_registro_publico"
        assert o.requiere_verificacion_antes_de_publicar
        assert "BLOQUEANTE" in (o.evidencia or "")

    def test_el_contraste_reportar_vs_revisar(self):
        """13 cumplimientos de reportar (art. 41), cero de revisar (art. 42)."""
        obs = {o.id: o for o in cargar_obligaciones(EXPEDIENTE)}
        assert obs["art-41-informe-anual"].estado == "cumplida"
        assert obs["art-42-informe-mediano-plazo"].estado == "incumplida"
        assert obs["art-42-informe-mediano-plazo"].evidencia

    def test_resuelve_quien_debe_producir_cada_cosa(self):
        """Es lo que vuelve accionable la sección de brechas."""
        p = por_producto(EXPEDIENTE)
        assert "estudios_independientes" in p
        arts = {o.articulo for o in p["estudios_independientes"]}
        assert {42, 44} <= arts, "los estudios independientes los mandan los arts. 42 y 44"


class TestNingunaObligacionQUEDASinDeclararSuAlcance:
    """O declara qué buscar en la base normativa, o declara POR QUÉ no se puede.

    Sin esta regla, «no hay consulta» es indistinguible de «nadie lo pensó» — la misma
    ambigüedad que el expediente existe para no producir. Es la doctrina de declarar la brecha
    aplicada a las obligaciones: una ausencia sin motivo no es una decisión.
    """

    def test_cada_obligacion_declara_una_cosa_o_la_otra(self):
        from modules.law_intel.obligaciones import cargar_obligaciones

        mudas = [o.articulo for o in cargar_obligaciones("end_2030")
                 if not o.verificacion_normativa and not (o.sin_consulta_normativa or "").strip()]
        assert not mudas, (
            f"los artículos {mudas} no declaran consulta ni motivo: quien lea el expediente no "
            f"puede distinguir «no se puede verificar» de «nadie lo miró»")

    def test_no_se_declaran_las_DOS(self):
        """Declarar consulta y motivo a la vez sería una contradicción escrita: o se puede
        comprobar contra la base normativa o no."""
        from modules.law_intel.obligaciones import cargar_obligaciones

        ambas = [o.articulo for o in cargar_obligaciones("end_2030")
                 if o.verificacion_normativa and (o.sin_consulta_normativa or "").strip()]
        assert not ambas, f"los artículos {ambas} declaran consulta Y motivo de ausencia"

    def test_la_FUENTE_que_haria_falta_queda_nombrada_cuando_existe(self):
        """El 50 y el 51 son actos del Congreso: constan, pero en expedientes de Cámara y
        Senado. Nombrar la fuente que falta convierte una brecha en un pendiente accionable —
        distinto de un informe, que NUNCA va a dejar rastro en la Gaceta."""
        from modules.law_intel.obligaciones import cargar_obligaciones

        por_art = {o.articulo: (o.sin_consulta_normativa or "") for o in
                   cargar_obligaciones("end_2030")}
        for art in (50, 51):
            assert "Cámara y Senado" in por_art[art], (
                f"el art-{art} no nombra la fuente que haría falta")
