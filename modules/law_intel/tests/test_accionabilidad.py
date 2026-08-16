"""La recomendación se construye de campos: no hay dónde alojar una opinión de política.

Es la restricción que sostiene vender un producto «independiente» a una parte interesada. Si
la recomendación tuviera texto libre, la frontera dependería de quién redacta cada informe.
"""
import dataclasses

import pytest

from modules.law_intel.obligaciones import Obligacion, cargar_obligaciones
from modules.law_intel.registro import cargar
from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.scoring.accionabilidad import Recomendacion, recomendaciones, resumen
from modules.law_intel.scoring.brecha import Brecha, brechas

EXPEDIENTE = "end_2030"


def ob(**kw):
    base = dict(id="x", articulo=42, deber="Elaborar el Informe de Mediano Plazo",
                deudor={"tipo": "organo", "nombre": "Órgano rector"},
                estado="incumplida", evidencia="ninguno publicado",
                produce=["informe"], habilita_exigir=["amparo_de_cumplimiento"])
    return Obligacion(**{**base, **kw})


class TestNoHayDondePonerPolitica:
    def test_la_recomendacion_no_tiene_campo_de_texto_libre(self):
        """El guard estructural: si mañana alguien agrega un campo `comentario`, este test cae."""
        campos = {f.name for f in dataclasses.fields(Recomendacion)}
        libres = campos - {"clase", "que_falta", "base_legal", "deudor", "instrumentos",
                           "desbloquea", "indicadores", "estado_obligacion",
                           "verificacion_pendiente"}
        assert not libres, f"campo nuevo sin revisar la frontera política: {libres}"

    def test_la_frase_se_arma_de_los_campos(self):
        r = recomendaciones([], [ob()])[0]
        f = r.frase()
        assert "artículo 42" in f
        assert "Órgano rector" in f
        assert "amparo_de_cumplimiento" in f


class TestFuerzaDelReclamo:
    def test_lo_incumplido_con_evidencia_va_primero(self):
        """No pide nada nuevo: exige lo ya mandado. Es el reclamo más difícil de contestar."""
        recs = recomendaciones([], [
            ob(id="a", articulo=44, estado="pendiente_no_vencida", evidencia=None),
            ob(id="b", articulo=42, estado="incumplida", evidencia="ninguno publicado")])
        assert recs[0].base_legal == "artículo 42"

    def test_sin_registro_publico_no_afirma_incumplimiento(self):
        r = recomendaciones([], [ob(articulo=51, estado="sin_registro_publico",
                                    evidencia=None)])[0]
        assert r.verificacion_pendiente
        assert "No se afirma incumplimiento" in r.frase()

    def test_lo_cumplido_no_genera_recomendacion(self):
        assert recomendaciones([], [ob(estado="cumplida", evidencia="13 informes")]) == []

    def test_lo_no_exigible_tampoco(self):
        """El Pacto Fiscal no tiene deudor determinado: no hay a quién recomendarle nada."""
        o = ob(estado="no_exigible", evidencia=None,
               deudor={"tipo": "indeterminado", "nombre": "las fuerzas"})
        assert recomendaciones([], [o]) == []


class TestLoNuestroSeDeclaraComoNuestro:
    def test_las_brechas_de_la_plataforma_no_se_le_imputan_al_estado(self):
        bs = [Brecha("1.1", "n", 1, "sin_binding", "sdq"),
              Brecha("1.2", "n", 1, "binding_sin_verificar", "sdq", serie_candidata="s")]
        recs = recomendaciones(bs, [])
        assert all(r.clase == "interna" for r in recs)
        assert all("no del Estado" in r.frase() for r in recs)

    def test_separa_verificar_de_identificar(self):
        bs = [Brecha("1.1", "n", 1, "sin_binding", "sdq"),
              Brecha("1.2", "n", 1, "binding_sin_verificar", "sdq", serie_candidata="s")]
        qs = {r.que_falta.split()[0] for r in recomendaciones(bs, [])}
        assert qs == {"Verificar", "Identificar"}


def test_sobre_el_expediente_real():
    e = cargar(EXPEDIENTE)
    br = brechas(e.numerados, cargar_bindings(EXPEDIENTE))
    recs = recomendaciones(br, cargar_obligaciones(EXPEDIENTE))
    r = resumen(recs)
    assert r["total"] > 0
    assert set(r["por_clase"]) <= {"publicacion", "dato", "interna"}
    # El art. 51 es el destinatario del informe: su recomendación debe salir marcada.
    assert "artículo 51" in (r["con_verificacion_pendiente"] or [])
    assert "nunca la política" in str(r["alcance"])


def test_el_desbloqueo_no_se_infla_con_las_de_publicacion():
    """Una obligación incumplida no «desbloquea indicadores»: son cosas distintas y sumarlas
    haría parecer que exigir un informe rinde cobertura que no rinde."""
    recs = recomendaciones([], [ob()])
    assert all(r.desbloquea == 0 for r in recs if r.clase == "publicacion")


class TestLaListaSoloTraeLoAccionable:
    def test_lo_ya_cumplido_tarde_no_es_una_accion(self):
        """El art. 54 se cumplió con 21 meses de retraso: es evidencia del expediente, no algo
        que se pueda exigir hoy. Mezclarlo con lo pendiente le quita fuerza a la lista."""
        o = ob(articulo=54, estado="cumplida_tarde", evidencia="Decreto 134-14, 21 meses tarde")
        assert recomendaciones([], [o]) == []

    def test_una_recomendacion_sin_base_legal_no_dice_None(self):
        r = Recomendacion(clase="dato", que_falta="El indicador 3.9 no tiene fuente admisible",
                          base_legal=None, deudor=None, instrumentos=[], desbloquea=1,
                          indicadores=["3.9"])
        assert "None" not in r.frase()
        assert r.frase().startswith("El indicador 3.9")
