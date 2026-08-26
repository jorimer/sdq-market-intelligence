"""El expediente de la Ley 167-21, y lo que prueba del motor.

Es el primer instrumento de una clase distinta: **una ley de OBLIGACIONES, no de metas.** La
END fija 90 indicadores con valores a alcanzar; ésta no fija ninguno. Si el motor lo sirve
sin forzarlo, el seam aguanta por el otro lado.
"""
import pytest

from modules.law_intel.bindings import cargar_bindings, cobertura
from modules.law_intel.campo import resumen as campo
from modules.law_intel.obligaciones import EXIGEN_CONTEO, cargar_obligaciones
from modules.law_intel.obligaciones import resumen as resumen_obligaciones
from modules.law_intel.registro import cargar, expedientes

EID = "ley_167_21"


def test_el_expediente_esta_en_el_catalogo():
    assert EID in expedientes()


class TestUnaLeySinMETAS:
    def test_la_ley_no_fija_ninguna_meta_numerica(self):
        """Registrar un 100% sería ponerle a la ley una cifra que no escribió."""
        e = cargar(EID)
        assert len(e.numerados) == 1
        ind = e.numerados[0]
        assert ind.escala == "redactada"
        assert all(not isinstance(v, (int, float)) for v in ind.metas.values())

    def test_no_declara_horizonte_de_vigencia(self):
        """La ley no vence. Poner una fecha haría que el motor proyecte contra un plazo
        que nadie fijó."""
        assert cargar(EID).meta.get("vigencia_hasta") is None

    def test_el_indicador_unico_NO_produce_veredicto_y_lo_declara(self):
        c = campo(EID)
        assert c["campo_cerrado"] is True
        assert c["en_silencio"] == 0
        # El motor COMPUTA el estado desde la escala y no admite que se declare a mano:
        # tener dos verdades sobre el mismo hecho es el defecto que persigue.
        assert c["por_estado"] == {"meta_no_interpretable": 1}

    def test_el_motivo_es_del_INSTRUMENTO_y_no_deuda_nuestra(self):
        """El numerador se mide; el denominador —cuántos procedimientos existen— no lo
        publica nadie."""
        from modules.law_intel.campo import RESPONSABLE_POR_MOTIVO
        assert RESPONSABLE_POR_MOTIVO["meta_no_interpretable"] == "instrumento"


class TestLoQueEstaLeyTIENEyLaENDno:
    def test_el_articulo_40_le_pone_CONSECUENCIA_a_la_obligacion_central(self):
        """En la END, `consecuencia: null` en los siete mecanismos era el hallazgo. Acá el
        art. 40 vuelve inexigible el trámite no registrado, que es la consecuencia más
        fuerte que puede tener una obligación de publicar."""
        obs = {o.id: o for o in cargar_obligaciones(EID)}
        art39 = obs["art-39-publicar-procedimientos"]
        assert art39.consecuencia and "40" in art39.consecuencia
        assert "no es exigible" in art39.consecuencia.lower()

    def test_NO_todas_las_obligaciones_tienen_consecuencia(self):
        """El contraste se publica con su cifra, no como adjetivo."""
        r = resumen_obligaciones(EID)
        assert r["sin_consecuencia_asignada"]["n"] < r["total"]


class TestElDeudorUNIVERSO:
    def test_la_ley_introduce_un_deudor_que_la_END_no_tenia(self):
        """«Todos los entes y órganos» está determinado y son cientos: de un universo hay
        que decir cuántos de cuántos, no «incumplió»."""
        tipos = {o.deudor.get("tipo") for o in cargar_obligaciones(EID)}
        assert "universo" in tipos
        assert "universo" in EXIGEN_CONTEO

    def test_acusar_a_un_universo_sin_cifra_LEVANTA(self):
        """El guard con dientes: una afirmación global se refuta con una sola institución
        que sí cumplió, y se lleva puesto el informe."""
        from modules.law_intel.obligaciones import Obligacion, _validar
        from modules.law_intel.registro import ExpedienteInvalido
        o = Obligacion(
            id="x", articulo=39, deber="publicar",
            deudor={"tipo": "universo", "nombre": "Todos los entes"},
            periodicidad="continua", plazo={"tipo": "desde_vigencia", "vence": "2022-02-05"},
            consecuencia=None, estado="parcial",
            evidencia="Varias instituciones no publicaron sus procedimientos.")
        with pytest.raises(ExpedienteInvalido, match="cuántos de cuántos"):
            _validar([o])

    def test_con_la_cifra_en_la_evidencia_PASA(self):
        from modules.law_intel.obligaciones import Obligacion, _validar
        o = Obligacion(
            id="x", articulo=39, deber="publicar",
            deudor={"tipo": "universo", "nombre": "Todos los entes"},
            periodicidad="continua", plazo={"tipo": "desde_vigencia", "vence": "2022-02-05"},
            consecuencia=None, estado="parcial",
            evidencia="710 trámites de 91 instituciones publicados al 2026-08-25.")
        _validar([o])           # no levanta


class TestElRangoDeLaNORMAnoSeConfunde:
    def test_el_indicador_NO_lleva_binding_y_esa_es_la_decision(self):
        """Se ató primero y era un error: el campo computa el motivo desde la escala y el
        binding habría declarado otro para el mismo indicador. La serie entra por la
        obligación del art. 39, no por acá."""
        assert cargar_bindings(EID) == {}
        obs = {o.id: o for o in cargar_obligaciones(EID)}
        art39 = obs["art-39-publicar-procedimientos"]
        assert "catalogo_de_tramites" in art39.produce
        # El enlace que sí corresponde: la serie SIGUE la obligación, no mide un indicador.
        assert art39.serie_de_seguimiento == "social_dev:tramites_catalogados"

    def test_el_expediente_NO_le_atribuye_a_la_ley_el_tiempo_de_respuesta(self):
        """Lo exige la Resolución 142-2024 del MAP, no la Ley 167-21. Atribuirle a la ley
        una exigencia que puso una resolución es refutable leyendo la ley."""
        import pathlib
        raiz = pathlib.Path(__file__).resolve().parents[1] / "expedientes" / EID
        texto = " ".join(p.read_text(encoding="utf-8") for p in raiz.iterdir() if p.is_file())
        assert "142-2024" in texto, "el expediente no nombra la resolución que sí lo exige"
        # La obligación del tiempo NO cuelga de un artículo de la ley.
        for o in cargar_obligaciones(EID):
            assert "tiempo de respuesta" not in (o.deber or "").lower(), (
                f"la obligación {o.id} le atribuye a la ley el tiempo de respuesta")
