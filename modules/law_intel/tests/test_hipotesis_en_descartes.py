"""Una hipótesis escondida en la prosa de un motivo es un indicador que nadie vuelve a mirar.

Este guard sale de tres casos reales del expediente END 2030, y dos de ellos eran indicadores
MEDIBLES que estuvieron meses descartados:

  4.1  el motivo decía que el emisor había reemplazado la serie y que la ley se fijó sobre la
       vieja. Nadie lo comprobó. Era el CONCEPTO: la ley titula «dióxido de carbono» un total
       de gases de efecto invernadero. Entró por oráculo con Δ 1,1%.
  3.20 el motivo decía que «productos agropecuarios» nombraba una agrupación arancelaria.
       Tampoco era eso: era una SUMA inválida —dos cuotas con denominadores distintos—.
       Entró con Δ 2,4%.
  3.24 el motivo decía que «producción» nombraba un subconjunto del crédito. Se trajo la
       fuente que el propio motivo pedía y NO cierra. Ahí la hipótesis sí sobrevivió, y por
       eso ahora está declarada en vez de contada.

La regla que queda: un motivo puede explicar, pero si explica con una causa que nadie midió,
la causa se declara en un campo y no en la prosa. Declarada, es una lista de trabajo;
enterrada en el motivo, es un indicador perdido.
"""
import pytest

from modules.law_intel.bindings import (Binding, cargar_bindings, hipotesis_abiertas,
                                        motivos_con_hipotesis_sin_declarar)

E = "end_2030"


class TestElGuard:
    def test_ningun_descarte_esconde_una_hipotesis_en_su_motivo(self):
        sueltas = motivos_con_hipotesis_sin_declarar(E)
        assert not sueltas, (
            "estos motivos EXPLICAN la brecha con una causa que nadie midió y no la declaran "
            f"en `hipotesis_sin_comprobar`: {sueltas}. O se mide, o se declara — dejarla en "
            "la prosa es como el 4.1 y el 3.20 pasaron meses descartados siendo medibles.")

    def test_el_guard_detecta_una_hipotesis_sin_declarar(self):
        """Sin esto, un guard que nunca encuentra nada es indistinguible de uno que no mira."""
        b = Binding(indicador="x", serie="s", fuente="wdi", mejor="mayor", estado="descartado",
                    motivo_descarte="Da otro número; la base de la ley parece ser otra cosa.")
        from modules.law_intel import bindings as B
        assert B._MARCAS_DE_HIPOTESIS.search(b.motivo_descarte or "")

    def test_una_CITA_del_emisor_no_cuenta_como_hipotesis_nuestra(self):
        """Los ocho descartes del PEFA transcriben la lengua hedgeada del propio anexo —«se
        podría cubrir RAZONABLEMENTE»—. Eso es evidencia sobre qué dijo el emisor, no una
        suposición nuestra, y confundirlas convertiría el guard en ruido."""
        from modules.law_intel import bindings as B
        citado = 'El anexo dice: «se podría cubrir RAZONABLEMENTE» y se descarta por eso.'
        assert not B._MARCAS_DE_HIPOTESIS.search(B._CITAS.sub(" ", citado))
        assert B._MARCAS_DE_HIPOTESIS.search(citado), "sin quitar la cita sí hay marca"


class TestLaLista:
    def test_las_hipotesis_declaradas_traen_texto(self):
        abiertas = hipotesis_abiertas(E)
        assert abiertas, "el barrido quedó vacío: dejó de listar algo"
        for h in abiertas:
            assert len(h["hipotesis"]) > 60, (
                f"{h['indicador']}: la hipótesis tiene que decir QUÉ se supone y qué la "
                f"comprobaría; una línea suelta no es reabrible.")

    def test_solo_los_descartes_declaran_hipotesis(self):
        """Un binding VERIFICADO con una hipótesis abierta sería una cifra publicada sobre una
        suposición. Si la duda sigue viva, el campo correcto es `nota_comparabilidad`, que
        frena la promoción."""
        for b in cargar_bindings(E).values():
            if (b.hipotesis_sin_comprobar or "").strip():
                assert b.estado == "descartado", (
                    f"{b.indicador}: estado '{b.estado}' con una hipótesis sin comprobar.")

    def test_el_3_24_declara_la_suya_y_su_motivo_ya_no_la_cuenta(self):
        """El caso que sobrevivió a que le trajeran su fuente: la hipótesis pasó del relato al
        campo, y el motivo pasó a decir qué se midió.

        ══ REESCRITO 2026-08-24 ══ Exigía la cadena literal «2026-08-22», o sea la fecha de
        UNA corrida. Eso ata el test a que nadie vuelva a medir: el día que se recomputó, se
        puso rojo por haberse hecho el trabajo. La fecha se sigue pidiendo —un motivo sin
        fechar no se puede auditar— pero por su FORMA.

        Y se agrega lo que este caso enseñó, que es más fuerte que la fecha: el motivo tiene
        que nombrar el CAMINO con el que se computó. Este motivo estuvo suspendido porque
        citaba ocho cifras que nadie podía rehacer, y un motivo irreproducible no es
        evidencia — se lee como caso cerrado y no lo es.
        """
        import re

        b = cargar_bindings(E)["3.24"]
        assert (b.hipotesis_sin_comprobar or "").strip()
        motivo = b.motivo_descarte or ""
        assert re.search(r"20\d\d-\d\d-\d\d", motivo), (
            "el motivo tiene que fechar la comprobación que se hizo")
        assert "bcrd_prestamos_destino" in motivo, (
            "el motivo tiene que nombrar el módulo con el que se puede REHACER el cómputo; "
            "sin eso son cifras transcritas y el motivo vuelve a ser una afirmación")

    @pytest.mark.parametrize("ind", ["4.1", "3.20"])
    def test_los_dos_que_se_recuperaron_ya_no_son_descartes(self, ind):
        """El contrapeso de todo lo anterior: si volvieran a descartarse, la lección se perdió."""
        b = cargar_bindings(E)[ind]
        assert b.cuenta, f"{ind} volvió a no contar: {b.estado}"
