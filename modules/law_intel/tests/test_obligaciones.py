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

    def test_la_comision_bicameral_declara_el_alcance_de_su_fuente(self):
        """Era el caso marcado como BLOQUEANTE y la comprobación lo dio vuelta.

        Se verificó contra el registro del Congreso y resultó que una comisión bicameral SÍ
        examina el Presupuesto: la afirmación negativa que iba a publicarse era refutable con
        el propio archivo del obligado, que es justo lo que la marca advertía.

        La regla que queda no es la palabra «BLOQUEANTE» —eso era el recordatorio— sino la
        durable: el destinatario del informe es el propio Congreso, así que **la evidencia
        tiene que viajar con el alcance de la fuente que la sostiene**. Sin eso, un lector
        entiende que la lectura cubre los catorce años de la ley y cubre un período
        legislativo.
        """
        o = next(x for x in cargar_obligaciones(EXPEDIENTE) if x.id == "art-51-comision-bicameral")
        # Ya no es `sin_registro_publico`: se comprobó y pasó a `parcial`. Lo que NO cambia
        # —y es lo que este test fija— es que la afirmación viaja con el alcance de la fuente
        # que la sostiene, y que la consulta llevaba control positivo.
        assert o.afirma_incumplimiento, "acusa: sin evidencia el motor no la habría admitido"
        assert (o.evidencia or "").strip()
        assert "período legislativo vigente" in (o.evidencia or "")
        assert (o.verificacion_congresual or {}).get("control_positivo")

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

    def test_la_FUENTE_que_haria_falta_queda_nombrada_O_conectada(self):
        """El 50 y el 51 son actos del Congreso, que constan en sus expedientes.

        La regla original pedía NOMBRAR la fuente faltante, porque nombrarla convierte una
        brecha en un pendiente accionable. Los dos pendientes se cerraron: la fuente está
        conectada. La regla sobrevive con la disyunción, que es lo que siempre quiso decir —
        o se sabe qué falta, o se sabe contra qué se comprueba. Lo que nunca se admite es que
        no diga ninguna de las dos.
        """
        from modules.law_intel.obligaciones import cargar_obligaciones

        por_art = {o.articulo: o for o in cargar_obligaciones("end_2030")}
        for art in (50, 51):
            o = por_art[art]
            nombrada = "Cámara y Senado" in (o.sin_consulta_normativa or "")
            conectada = bool(o.verificacion_congresual)
            assert nombrada or conectada, (
                f"el art-{art} no nombra la fuente que haría falta ni declara contra qué "
                f"registro se comprueba")


def test_REGLA_todo_campo_de_una_obligacion_LLEGA_o_se_declara_interno():
    """ESTRUCTURAL: un campo que existe y no se sirve es indistinguible de uno que no existe.

    Pasó tres veces en un día: `scope` en el registro, y `verificacion_normativa` y
    `sin_consulta_normativa` acá — declarados en el expediente, invisibles para cualquier
    consumidor. El motivo de por qué una obligación no se puede verificar es exactamente el
    tipo de cosa que el informe necesita y que se perdía en el serializador.

    No exige servir todo: exige DECIDIR. Lo que no se sirve se nombra abajo con su razón.
    """
    import ast
    import inspect
    import textwrap
    from dataclasses import fields

    from modules.law_intel.api import router
    from modules.law_intel.obligaciones import Obligacion

    #: Campos que a propósito NO se sirven, con el motivo.
    INTERNOS = {
        "nota_de_diseño",  # comentario de mantenimiento del expediente, no del informe
    }

    fuente = textwrap.dedent(inspect.getsource(router.obligaciones_))
    servidos = {n.value for n in ast.walk(ast.parse(fuente))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    faltan = [f.name for f in fields(Obligacion)
              if f.name not in servidos and f.name not in INTERNOS]
    assert not faltan, (
        f"estos campos de `Obligacion` no llegan al consumidor ni se declaran internos: "
        f"{faltan}. Un campo que existe y no se sirve es indistinguible de uno que no existe.")
