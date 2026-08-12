"""Suprimir una dimensión no puede MEJORAR el score, y los límites se declaran.

Revisión actuarial externa (2026-08-12), tres observaciones sobre el cierre anterior:

1. «A un fronting le va mejor precisamente por no poder medirlo.» Al suprimir siniestralidad
   y resultado técnico, el ISF renormalizaba sobre las dimensiones restantes y Angloamericana
   pasaba de 35,9 a 55,2. Renormalizar equivale a SUPONER que las suprimidas valen el promedio
   de las demás — para un dato ausente es una suposición neutra; para una métrica que NO APLICA
   no tiene con qué sostenerse.
2. Ponderar por exposición concentra el peso en el último ejercicio (hasta 58% en el panel).
3. Los cortes salen de n=3 y n=1: acotados por los datos, no determinados por ellos.
"""
from modules.insurance_intel.scoring.isf import score_insurers
from modules.insurance_intel.scoring.perfil_sdq import (
    ANCLAJE_POR_TIPO, LIMITE_PONDERACION, calcular_ejes, metricas_del_ciclo,
)

_BASE = dict(primas_devengadas=1000.0, gastos_operativos=350.0, productos_inversion=50.0,
             activos_totales=3.0e9, indice_solvencia=1.8, indice_liquidez=1.4,
             siniestros_incurridos=1200.0)


def _fin(slug, cedidas):
    return {"slug": slug, "name": slug.title(), "period": "2024", **_BASE,
            "primas_cedidas": cedidas}


class TestSuprimirNoPremia:
    def test_la_fronting_no_recibe_score(self):
        """El caso de Angloamericana: 35,9 → 55,2 al suprimir. Ahora no hay score que subir."""
        panel = [_fin("fronting", 880.0), _fin("normal", 300.0),
                 _fin("otra", 250.0), _fin("otra2", 200.0)]
        por = {r["slug"]: r for r in score_insurers(panel)}
        assert por["fronting"]["overall_score"] is None
        assert "cede 88%" in por["fronting"]["score_no_publicable"]
        # …y la que sí es medible conserva su score.
        assert por["normal"]["overall_score"] is not None
        assert por["normal"]["score_no_publicable"] is None

    def test_las_dimensiones_medibles_se_siguen_publicando(self):
        """No se oculta lo que SÍ se midió: se retira el compuesto, no el detalle."""
        r = next(x for x in score_insurers([_fin("fronting", 880.0), _fin("n1", 300.0),
                                            _fin("n2", 250.0)]) if x["slug"] == "fronting")
        por_key = {d["key"]: d for d in r["dimensions"]}
        assert por_key["solvencia"]["score"] is not None
        assert por_key["escala"]["score"] is not None
        assert por_key["siniestralidad"]["score"] is None

    def test_un_dato_AUSENTE_sigue_renormalizando(self):
        """La regla distingue «falta el dato» de «la métrica no aplica». Para el primero,
        suponer el promedio de las presentes sigue siendo una suposición neutra."""
        sin_escala = {k: v for k, v in _fin("x", 300.0).items() if k != "activos_totales"}
        panel = [sin_escala, _fin("y", 300.0), _fin("z", 250.0)]
        r = next(x for x in score_insurers(panel) if x["slug"] == "x")
        assert r["overall_score"] is not None
        assert r["score_no_publicable"] is None


class TestPesoDelUltimoEjercicio:
    def _ciclo(self, primas):
        ej = {str(2020 + i): {"loss": 0.6, "exp": 0.3, "cesion": 0.3, "inversion": 0.0,
                              "primas": p} for i, p in enumerate(primas)}
        return metricas_del_ciclo(ej)

    def test_se_publica_cuanto_pesa_el_ultimo_ano(self):
        """Un «promedio de ciclo» que en la práctica es casi un año tiene que decirlo."""
        c = self._ciclo([10.0, 20.0, 40.0, 100.0, 400.0])
        assert c["peso_ultimo_ejercicio"] > 0.6
        plano = self._ciclo([100.0] * 5)
        assert abs(plano["peso_ultimo_ejercicio"] - 0.2) < 0.01

    def test_el_eje_lo_expone_junto_al_limite_declarado(self):
        ejes = calcular_ejes(self._ciclo([10.0, 20.0, 40.0, 100.0, 400.0]), 1.8, 1.4)
        assert ejes["peso_ultimo_ejercicio"] is not None
        assert "contracción" in ejes["limite_ponderacion"]

    def test_el_limite_declara_que_NO_es_evaluable(self):
        """Con n=1 no se corrige nada; se dice. Afirmar sobre el VALOR, no sobre el código."""
        assert "No es evaluable con este panel" in LIMITE_PONDERACION
        assert "sentido contrario" in LIMITE_PONDERACION


class TestUmbralesAcotadosNoDeterminados:
    def test_la_metodologia_declara_el_n_de_cada_corte(self):
        t = ANCLAJE_POR_TIPO.lower()
        assert "acotados por los datos" in t and "no determinados" in t
        assert "tres observaciones" in t and "una" in t

    def test_la_metodologia_explica_por_que_no_se_renormaliza(self):
        t = ANCLAJE_POR_TIPO.lower()
        assert "renormalizar" in t
        assert "beneficiada" in t and "no ser medible" in t
