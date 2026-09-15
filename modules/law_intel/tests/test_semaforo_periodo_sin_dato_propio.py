"""Un período de la ley sin dato propio se DECLARA indeterminado, no se juzga con el de otro año.

**El caso (prod, 2026-09-15).** El semáforo de la Ley 1-12 al corte 2025 emitía 46 veredictos de
cumplimiento, y 21 juzgaban la meta de 2025 con la observación más reciente disponible: 2024, 2023
y hasta 2019. `evaluar()` tomaba `obs[-1]` sin mirar su período. «2.7 alcanza la meta de 2025» se
afirmaba con el dato de 2024: una afirmación sobre un período que ningún dato cubre.

**La regla (decisión del dueño, estricta).** Si la observación más reciente es de un año ANTERIOR
al de la meta que vence, el veredicto es `indeterminado`: la observación, su período y la
distancia viajan a la vista, y no cuenta como cumple ni como no cumple. Declarar la brecha, nunca
rellenarla con el dato de otro año.
"""
import pytest

from modules.law_intel.bindings import Binding
from modules.law_intel.registro import Indicador
from modules.law_intel.scoring.semaforo import VEREDICTOS, evaluar, resumen, tabla

VERIF = dict(serie="s", fuente="one", estado="verificado")


def ind(**kw):
    base = dict(id="2.7", eje=2, nombre="Índice de ejemplo", escala="numerica",
                base_valor=0.3, metas={"2020": 0.40, "2025": 0.44, "2030": 0.50})
    return Indicador(**{**base, **kw})


def _b(mejor="mayor"):
    return Binding(indicador="2.7", mejor=mejor, **VERIF)


class TestUnPeriodoSinDatoPropio:
    def test_el_dato_de_2024_no_juzga_la_meta_de_2025(self):
        v = evaluar(ind(), _b(), [("2023", 0.36), ("2024", 0.39)], corte="2025")
        assert v.veredicto == "indeterminado"
        assert v.cumple is None, "un período sin dato propio no cumple ni incumple"

    def test_la_observacion_y_la_distancia_VIAJAN_aunque_no_se_juzgue(self):
        v = evaluar(ind(), _b(), [("2023", 0.36), ("2024", 0.39)], corte="2025")
        assert v.meta_periodo == "2025" and v.meta == 0.44
        assert v.observado == 0.39 and v.periodo_observado == "2024"
        assert v.distancia == pytest.approx(0.05)
        assert "2025" in (v.motivo or "") and "2024" in (v.motivo or "")

    def test_un_dato_del_MISMO_anio_de_la_meta_si_juzga(self):
        v = evaluar(ind(), _b(), [("2024", 0.39), ("2025", 0.45)], corte="2025")
        assert v.veredicto == "alcanzada" and v.cumple is True

    def test_un_periodo_sub_anual_del_anio_de_la_meta_juzga(self):
        """«2025-Q4» y «2025-12» son del año de la meta: se compara el AÑO, no la cadena."""
        v = evaluar(ind(), _b(), [("2024-12", 0.39), ("2025-06", 0.45)], corte="2025")
        assert v.veredicto == "alcanzada"

    def test_un_sub_anual_del_anio_ANTERIOR_no_juzga(self):
        v = evaluar(ind(), _b(), [("2024-06", 0.38), ("2024-12", 0.39)], corte="2025")
        assert v.veredicto == "indeterminado"

    def test_un_UMBRAL_sin_dato_del_periodo_tambien_es_indeterminado(self):
        i = ind(escala="umbral", metas={"2025": "< 4"})
        v = evaluar(i, _b("menor"), [("2024", 5.97)], corte="2025")
        assert v.veredicto == "indeterminado"
        assert v.distancia is None, "un umbral sigue sin admitir distancia"

    def test_un_ROTULADO_sin_dato_del_periodo_tambien(self):
        i = ind(escala="redactada", metas={"2025": "Matemáticas : 63.0"})
        v = evaluar(i, _b("menor"), [("2019", 97.84)], corte="2025")
        assert v.veredicto == "indeterminado"
        assert "Matemáticas" in (v.motivo or ""), "el sujeto sigue viajando con el número"


class TestElEstadoEstaRegistradoEnTodasSusSuperficies:
    def test_esta_en_el_vocabulario_publicado(self):
        assert "indeterminado" in VEREDICTOS

    def test_el_resumen_lo_saca_del_denominador_de_evaluados(self):
        vs = [evaluar(ind(), _b(), [("2024", 0.39)], "2025"),
              evaluar(ind(id="2.8"), Binding(indicador="2.8", mejor="mayor", **VERIF),
                      [("2025", 0.45)], "2025")]
        r = resumen(vs)
        assert r["total"] == 2 and r["evaluados"] == 1
        assert r["por_veredicto"].get("indeterminado") == 1

    def test_la_tabla_de_evidencia_no_lo_lista_como_logro_ni_incumplimiento(self):
        i = ind()
        filas = tabla([evaluar(i, _b(), [("2024", 0.39)], "2025")], [i])
        assert filas == []

    def test_los_fines_lo_cuentan_como_sin_veredicto(self):
        from modules.law_intel.scoring.fines import ALCANZAN, NO_ALCANZAN, SIN_VEREDICTO

        assert "indeterminado" in SIN_VEREDICTO
        assert "indeterminado" not in ALCANZAN and "indeterminado" not in NO_ALCANZAN

    def test_el_modelo_recibe_como_se_lee(self):
        """Sin la glosa, el redactor ve `indeterminado` al lado de una meta y un valor y hace
        la comparación que el motor se negó a hacer."""
        from modules.law_intel.ai_context import law_ai_context
        from modules.law_intel.scoring.semaforo import GLOSA_INDETERMINADO

        voc = law_ai_context("end_2030", "2025")["vocabulario_obligatorio"]
        assert voc["indeterminado"] == GLOSA_INDETERMINADO

    def test_todo_veredicto_del_vocabulario_tiene_su_lugar_en_los_fines(self):
        """Un estado nuevo que no entra a ninguna lista de `fines` desaparece del juicio del fin."""
        from modules.law_intel.scoring.fines import ALCANZAN, NO_ALCANZAN, SIN_VEREDICTO

        sin_lugar = set(VEREDICTOS) - set(ALCANZAN) - set(NO_ALCANZAN) - set(SIN_VEREDICTO)
        assert not sin_lugar, f"veredictos sin lugar en fines.py: {sorted(sin_lugar)}"
