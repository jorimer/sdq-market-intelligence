"""Los TRES bloques de amplitud del Deep Dive en la muestra curada, y su aritmética.

Por qué existe este archivo. El Deep Dive real adjunta al `scoring_result` tres bloques que
se sirven como TABLA —entorno macro, sensibilidades, soporte/techo soberano—; la muestra no
los traía. El efecto no fue un fallo: dos secciones salían narradas y SIN la tabla que la
prosa interpreta, y la de Entorno Operativo no salía en absoluto —el motor la retira cuando
no hay telón macro—. El nivel se veía peor de lo que es en la única pieza que se usa para
vender, y ningún test se puso rojo. Es el mismo defecto que tuvo el mapa sectorial.

Y la muestra tiene una obligación que el informe real no tiene: sus cifras se escriben a
mano, así que son el único sitio del producto donde una relación puede quedar en desacuerdo
con sus términos. Acá se exige que cada relación —dirección y magnitud de un factor macro,
umbral e impacto de una sensibilidad, etiqueta sistémica y lectura del soporte— sea la que
computan las reglas REALES, y que la prosa curada no cite ninguna cifra que su tabla no
traiga: esa prosa no pasa por el motor, así que el guard numérico nunca la juzga.
"""

import re
from datetime import date

import pytest

from shared.contracts.macro_sector import (ADVERSO, classify_factor, factor_doctrine,
                                           factor_reading)
from shared.products import ProductTier
from modules.banking_score import products as P
from modules.banking_score.products import (SAMPLE_ENTORNO_MACRO as MACRO,
                                            SAMPLE_SENSIBILIDADES as SENS,
                                            SAMPLE_SOPORTE_SOBERANO as SOPORTE)
from modules.banking_score.reports import pdf_generator as PDF
from modules.banking_score.scoring.engine import calculate_deterministic_score
from modules.banking_score.scoring.indicator_detail import INDICATOR_META, _band
from modules.banking_score.scoring.sensitivity import (_CURVES, _fmt_raw, _next_edge_down,
                                                       _next_edge_up)
from modules.banking_score.scoring.support import (STATE_OWNED, compose_support_overlay,
                                                   systemic_label)
from modules.banking_score.scoring.weights import get_sub_component_weights

_PESOS = get_sub_component_weights(None)


def _cifras(texto: str) -> list:
    return re.findall(r"\d+(?:\.\d+)?", texto)


def _respaldo(*valores) -> set:
    """Las FORMAS en que una cifra de la tabla puede aparecer en la prosa."""
    out = set()
    for v in valores:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        out |= {f"{abs(v):.2f}", f"{abs(v):.1f}", f"{abs(v):g}", f"{abs(v):.0f}"}
    return out


# ── Entorno Operativo ────────────────────────────────────────────────────────────────
class TestElEntornoMacroDeLaMuestraSeClasificaSolo:
    """La señal («Favorable»/«Neutral») es una RELACIÓN entre el valor y los umbrales de la
    doctrina. Escrita a mano, sobrevive a que la doctrina se recalibre: la tabla seguiría
    diciendo «Favorable» al lado de un valor que los umbrales nuevos llaman adverso."""

    def test_cada_factor_esta_declarado_en_la_doctrina(self):
        for f in MACRO["factors"]:
            assert factor_doctrine(f["key"]) is not None, (
                f"«{f['key']}» no existe en shared/doctrine/macro_sector.yaml: la muestra "
                "inventaría un factor que el producto real nunca emite")

    @pytest.mark.parametrize("campo", ["label", "unit"])
    def test_la_etiqueta_y_la_unidad_salen_de_la_doctrina(self, campo):
        for f in MACRO["factors"]:
            assert f[campo] == factor_doctrine(f["key"])[campo]

    def test_la_direccion_y_la_magnitud_las_COMPUTA_la_doctrina(self):
        for f in MACRO["factors"]:
            esperado = classify_factor(f["value"], factor_doctrine(f["key"]))
            assert (f["direction"], f["magnitude"]) == esperado, (
                f"{f['key']}: la señal de la muestra no es la que dan los umbrales")

    def test_la_lectura_tiene_el_FORMATO_que_emite_el_productor(self):
        """Un nivel se lee «5.75 %» y una variación «+7.2% interanual». Con el formato
        equivocado la muestra enseña una tabla que el producto real no produce."""
        for f in MACRO["factors"]:
            assert f["reading"] == factor_reading(f["value"], factor_doctrine(f["key"]))

    def test_ningun_factor_es_ADVERSO(self):
        """La prosa curada dice «telón favorable con matices». Un factor adverso en la tabla
        dejaría al documento contradiciéndose con su propia sección."""
        adversos = [f["key"] for f in MACRO["factors"] if f["direction"] == ADVERSO]
        assert not adversos, f"la prosa no describe un telón adverso: {adversos}"

    def test_la_prosa_nombra_las_magnitudes_que_la_tabla_TRAE(self):
        """La prosa curada nombra cinco magnitudes macro. Cada una tiene que estar en la
        tabla: nombrar una que no está es citar un dato que el lector no puede ver."""
        texto = P.SAMPLE_NARRATIVES["entorno_operativo"].lower()
        claves = {f["key"] for f in MACRO["factors"]}
        for nombrada, clave in (("actividad económica", "activity"),
                                ("inflación", "inflation"),
                                ("tasa de política", "policy_rate"),
                                ("tipo de cambio", "fx_depreciation"),
                                ("reservas internacionales", "reserves")):
            assert nombrada in texto, f"la prosa dejó de nombrar «{nombrada}»"
            assert clave in claves, f"la prosa nombra «{nombrada}» y la tabla no lo trae"

    def test_la_prosa_curada_no_cita_cifras_que_la_tabla_no_traiga(self):
        respaldo = _respaldo(*[f["value"] for f in MACRO["factors"]])
        huerfanas = [c for c in _cifras(P.SAMPLE_NARRATIVES["entorno_operativo"])
                     if c not in respaldo]
        assert not huerfanas, f"cifras sin respaldo en la tabla macro: {huerfanas}"

    def test_el_periodo_del_telon_no_es_POSTERIOR_al_corte(self):
        """El producto real omite el telón macro cuando su período supera el corte —un
        informe «al 31-dic-2024» no puede describir el entorno de 2026—. La muestra no
        puede enseñar lo que el producto se niega a emitir."""
        assert MACRO["period"] <= P.SAMPLE_PERIOD[:7]


# ── Sensibilidades ───────────────────────────────────────────────────────────────────
def _filas():
    for lado, signo in (("palancas_alza", +1), ("riesgos_baja", -1)):
        for fila in SENS[lado]:
            yield lado, signo, fila


def _n_indicadores_del_sub(sub: str) -> int:
    return sum(1 for k in P.SAMPLE_SCORING["indicators"]
               if INDICATOR_META.get(k, {}).get("sub") == sub)


class TestLasSensibilidadesCierranSolas:
    def test_la_linea_base_es_el_PROPIO_score_de_la_muestra(self):
        """Si la base no es el score que el informe imprime, cada Δ de la tabla se mide
        contra un número que no aparece en ninguna otra página."""
        assert SENS["baseline_overall"] == P.SAMPLE_SCORING["overall_score"]
        assert SENS["baseline_overall"] == calculate_deterministic_score(
            P.SAMPLE_SCORING["sub_components"], _PESOS)

    def test_cada_fila_apunta_a_un_indicador_REAL_de_la_muestra(self):
        for _, _, f in _filas():
            assert f["indicador"] in P.SAMPLE_SCORING["indicators"], (
                f"«{f['indicador']}» no es un indicador de la muestra")
            ind = P.SAMPLE_SCORING["indicators"][f["indicador"]]
            assert f["raw_actual"] == pytest.approx(ind["raw"])
            assert f["score_actual"] == pytest.approx(ind["score"])

    def test_la_etiqueta_y_la_dimension_salen_del_catalogo_del_MOTOR(self):
        for _, _, f in _filas():
            meta = INDICATOR_META[f["indicador"]]
            assert f["label"] == meta["label"]
            assert f["sub"] == meta["sub"]

    def test_las_bandas_las_COMPUTA_la_regla_del_motor(self):
        for lado, _, f in _filas():
            assert f["banda_actual"] == _band(f["score_actual"])
            borde = (_next_edge_up if lado == "palancas_alza" else _next_edge_down)(
                f["score_actual"])
            assert borde is not None, f"{f['indicador']} no tiene frontera de ese lado"
            exacto = borde + (0.01 if lado == "palancas_alza" else -0.01)
            assert f["score_objetivo"] == pytest.approx(round(exacto, 0))
            # OJO: la banda objetivo es la del score EXACTO, no la del redondeado. A la
            # baja, 69,99 es «moderado» y 70,0 es «adecuado» — leer el redondeado
            # invertiría la fila y diría que deteriorarse conserva la banda.
            assert f["banda_objetivo"] == _band(exacto)

    def test_el_umbral_recorre_el_MISMO_tramo_que_la_curva_real(self):
        """El umbral no se estima a ojo: mueve el valor crudo el mismo trecho que la curva
        real del indicador recorre entre el score actual y el objetivo."""
        for lado, _, f in _filas():
            clave = f["indicador"]
            curva = _CURVES[clave]
            borde = (_next_edge_up if lado == "palancas_alza" else _next_edge_down)(
                f["score_actual"])
            exacto = borde + (0.01 if lado == "palancas_alza" else -0.01)
            tramo = (curva.to_raw(exacto, f["raw_actual"], None)
                     - curva.to_raw(f["score_actual"], f["raw_actual"], None))
            assert f["umbral_raw"] == pytest.approx(round(f["raw_actual"] + tramo, 2))
            assert f["umbral_fmt"] == _fmt_raw(clave, f["umbral_raw"])

    def test_el_umbral_cae_del_lado_que_la_fila_AFIRMA(self):
        """La prueba que atrapa la fila absurda: una palanca cuyo umbral empeora el
        indicador («para subir, baje el ROE a 12,75%») es lo primero que un comprador con
        la metodología en la mano encuentra."""
        for lado, _, f in _filas():
            mejora = _CURVES[f["indicador"]].direction == "higher"
            sube = f["umbral_raw"] > f["raw_actual"]
            assert sube == (mejora if lado == "palancas_alza" else not mejora), (
                f"{f['indicador']} en {lado}: el umbral va para el lado contrario")

    def test_el_impacto_se_RECOMPUTA_con_la_agregacion_real(self):
        """Δ Score sale de mover el sub-componente y volver a puntuar con los pesos reales,
        no de una regla de tres escrita al lado."""
        for _, _, f in _filas():
            borde_up = _next_edge_up(f["score_actual"])
            arriba = f["banda_objetivo"] in ("fuerte",) and borde_up is not None and \
                f["score_objetivo"] > f["score_actual"]
            borde = borde_up if arriba else _next_edge_down(f["score_actual"])
            exacto = borde + (0.01 if arriba else -0.01)
            subs = dict(P.SAMPLE_SCORING["sub_components"])
            subs[f["sub"]] += (exacto - f["score_actual"]) / _n_indicadores_del_sub(f["sub"])
            esperado = round(calculate_deterministic_score(subs, _PESOS)
                             - SENS["baseline_overall"], 2)
            assert f["delta_overall"] == pytest.approx(esperado, abs=0.005), (
                f"{f['indicador']}: el impacto no coincide con el recomputo")

    def test_el_signo_del_impacto_coincide_con_el_lado(self):
        for lado, signo, f in _filas():
            assert f["delta_overall"] * signo > 0, f"{f['indicador']} en {lado}"

    def test_estan_ordenadas_por_impacto_y_no_pasan_de_tres(self):
        """El motor devuelve `top=3` por lado, ordenadas. Una muestra con seis filas o
        desordenada enseña una tabla que el producto real no emite."""
        alza = [f["delta_overall"] for f in SENS["palancas_alza"]]
        baja = [f["delta_overall"] for f in SENS["riesgos_baja"]]
        assert len(alza) <= 3 and len(baja) <= 3
        assert alza == sorted(alza, reverse=True)
        assert baja == sorted(baja)

    def test_la_prosa_curada_no_cita_cifras_que_la_tabla_no_traiga(self):
        """La sección de Recomendación es la que lleva esta tabla debajo."""
        respaldo = set()
        for _, _, f in _filas():
            respaldo |= _respaldo(f["raw_actual"], f["score_actual"], f["umbral_raw"],
                                  f["score_objetivo"], f["delta_overall"])
        respaldo |= _respaldo(SENS["baseline_overall"],
                              *P.SAMPLE_SCORING["sub_components"].values())
        huerfanas = [c for c in _cifras(P.SAMPLE_NARRATIVES["recommendation"])
                     if c not in respaldo]
        assert not huerfanas, f"cifras sin respaldo en las sensibilidades: {huerfanas}"


# ── Soporte y techo soberano ─────────────────────────────────────────────────────────
class TestElSoporteSoberanoCierraSolo:
    def test_se_ARMA_con_la_misma_composicion_que_el_producto_real(self):
        """No se transcribe: la etiqueta sistémica y la lectura del soporte son relaciones
        y las computa `compose_support_overlay`, la misma que usa el Deep Dive con DB."""
        assert SOPORTE == compose_support_overlay(
            state_owned=P.SAMPLE_NAME in STATE_OWNED,
            activos_share=SOPORTE["systemic"]["activos_share"],
            depositos_share=SOPORTE["systemic"]["depositos_share"],
            rank_activos=SOPORTE["systemic"]["rank_activos"],
            sovereign=SOPORTE["sovereign"],
            standalone_score=P.SAMPLE_SCORING["overall_score"],
            standalone_tier=P.SAMPLE_SCORING["banda_resiliencia"])

    def test_la_etiqueta_sistemica_es_la_del_RANK_declarado(self):
        assert SOPORTE["systemic"]["label"] == systemic_label(
            SOPORTE["systemic"]["rank_activos"])
        assert SOPORTE["systemic"]["is_systemic"] is True

    def test_el_standalone_es_el_de_la_MUESTRA(self):
        """Una tabla que declare otro score que la portada rompe el documento en dos."""
        assert SOPORTE["standalone"] == {"score": P.SAMPLE_SCORING["overall_score"],
                                         "tier": P.SAMPLE_SCORING["banda_resiliencia"]}

    def test_la_cuota_es_coherente_con_la_CONCENTRACION_de_la_muestra(self):
        """La misma muestra publica el CR5 y el CR10 en la sección comparativa. Una cuota
        que no quepa dentro de ellos es una resta de una página a la otra."""
        cuota = SOPORTE["systemic"]["activos_share"]
        rank = SOPORTE["systemic"]["rank_activos"]
        cr5, cr10 = P.SAMPLE_PEER["cr5"], P.SAMPLE_PEER["cr10"]
        assert cuota <= cr5 / rank, (
            f"un top-{rank} no puede pesar más que el promedio de los {rank} mayores")
        assert cuota >= (cr10 - cr5) / 5, (
            f"un top-{rank} no puede pesar menos que el promedio de los puestos 6 a 10")
        assert SOPORTE["systemic"]["depositos_share"] < cuota

    def test_el_techo_soberano_es_el_ancla_DECLARADA_de_RD(self):
        """El techo no es una cifra sintética: es el ancla soberana declarada. Si la
        doctrina la mueve, la prosa curada que la nombra queda mintiendo — por eso se
        exige que el rating de la tabla esté escrito en el texto."""
        from modules.banking_score.scoring.support import sovereign_at
        assert SOPORTE["sovereign"] == sovereign_at(
            date.fromisoformat(P.SAMPLE_PERIOD)), (
            "el techo de la muestra no es el ancla declarada vista desde su corte")
        assert SOPORTE["sovereign"]["rating"] in P.SAMPLE_NARRATIVES["soporte_soberano"]
        assert SOPORTE["sovereign"]["agency"] in P.SAMPLE_NARRATIVES["soporte_soberano"]

    def test_la_prosa_curada_no_cita_cifras_que_la_tabla_no_traiga(self):
        respaldo = _respaldo(SOPORTE["systemic"]["activos_share"],
                             SOPORTE["systemic"]["depositos_share"],
                             SOPORTE["systemic"]["rank_activos"],
                             SOPORTE["sovereign"]["score"],
                             SOPORTE["standalone"]["score"])
        # 100 es la BASE de la escala («80.3/100»), y la tabla la imprime así en sus dos
        # filas de score. No es una cifra medida sobre la entidad.
        respaldo |= _respaldo(100)
        huerfanas = [c for c in _cifras(P.SAMPLE_NARRATIVES["soporte_soberano"])
                     if c not in respaldo]
        assert not huerfanas, f"cifras sin respaldo en el soporte: {huerfanas}"


# ── Registro: los tres llegan al Deep Dive, y a NINGÚN otro nivel ────────────────────
class TestLosTresLleganAlDeepDiveYSeIMPRIMEN:
    def test_el_snapshot_del_deep_dive_trae_los_tres_bloques(self):
        sr = P.BankingProduct().sample_snapshot(ProductTier.deep_dive).payload["scoring_result"]
        for clave in ("entorno_macro", "sensibilidades", "soporte_soberano"):
            assert sr.get(clave), f"la muestra del Deep Dive no trae «{clave}»"

    def test_el_INSIGHT_no_los_recibe(self):
        """Son amplitud exclusiva del Deep Dive: regalarlos en el Insight borra en la
        muestra lo que separa un nivel del otro."""
        sr = P.BankingProduct().sample_snapshot(ProductTier.insight).payload["scoring_result"]
        for clave in ("entorno_macro", "sensibilidades", "soporte_soberano",
                      # El mapa entra en la lista porque se coló: la muestra lo adjuntaba a
                      # los dos niveles nombrados y su TABLA salía impresa en el PDF del
                      # Insight, sin la sección que la interpreta. El producto real lo gatea.
                      "mapa_sectorial"):
            assert clave not in sr

    def test_las_secciones_que_los_interpretan_son_del_DEEP_DIVE(self):
        for sec in ("entorno_operativo", "soporte_soberano"):
            assert sec in P._DEEP_DIVE_SECTIONS
            assert sec not in P._INSIGHT_SECTIONS

    def test_el_motor_ya_no_RETIRA_la_seccion_de_entorno_operativo(self):
        """La sección se retira cuando el snapshot no trae telón macro. Sin este dato la
        muestra salía con una sección menos y ningún test se ponía rojo."""
        sr = P.BankingProduct().sample_snapshot(ProductTier.deep_dive).payload["scoring_result"]
        assert sr.get("entorno_macro"), (
            "sin `entorno_macro`, `narratives()` saca «entorno_operativo» de la lista")

    @pytest.mark.parametrize("constructor,bloque", [
        ("_build_macro_table", "entorno_macro"),
        ("_build_sensitivity_table", "sensibilidades"),
        ("_build_support_table", "soporte_soberano"),
    ])
    def test_cada_bloque_produce_una_tabla_NO_vacia(self, constructor, bloque):
        """Los tres constructores devuelven `[]` sin datos —opt-in silencioso—, que es
        exactamente cómo la muestra salía narrada y sin tabla."""
        sr = P.BankingProduct().sample_snapshot(ProductTier.deep_dive).payload["scoring_result"]
        assert getattr(PDF, constructor)(sr[bloque], PDF._get_styles())


def test_el_barrido_encontro_algo():
    """Toda aserción de ausencia lleva al lado la prueba de que había dónde mirar."""
    assert MACRO["factors"], "la muestra no tiene factores macro"
    assert SENS["palancas_alza"] and SENS["riesgos_baja"], "la muestra no tiene filas"
    assert SOPORTE["systemic"] and SOPORTE["sovereign"], "la muestra no tiene soporte"
