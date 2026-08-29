"""Paridad de DECLARACIONES entre el Deep Dive trimestral y la Revisión Anual.

**Por qué existe este archivo.** El producto anual lo construí sin comparar su contexto ni su
documento contra los del trimestral, y el resultado fue una serie de huecos que aparecieron de
a uno, cada uno costando una generación real:

  * el NIVEL DE REFERENCIA de cada indicador — el modelo lo ponía de memoria y el guard
    vetaba el informe entero (dos veces el 2026-08-27);
  * el SCORE de cada indicador — viajaba en la trayectoria y el balance lo tiraba;
  * la NOTA de capital redundante — el trimestral la imprime y el anual publicaba dos filas
    con el número idéntico sin explicar por qué;
  * el balance POR DIMENSIÓN — el trimestral imprime los cinco sub-componentes y el anual
    decía «el score cedió 6,02 puntos» sin poder decir por cuál.

El patrón tiene nombre en este repo —«un guard existe en un motor y falta en el otro»— pero
acá es del lado del DATO. Estos tests fijan la paridad para que el próximo hueco falle en CI
en vez de en un PDF que ya se mandó.
"""
from __future__ import annotations

from modules.banking_score.reports.pdf_generator import (_nota_de_capital_del_balance,
                                                         _nota_de_capital_redundante)
from modules.banking_score.reports.revision_anual import (_balance, _balance_por_dimension,
                                                          _reconciliacion_publica)

#: Serie REAL de Bonao 2025, tomada de la trayectoria publicada en su Deep Dive de diciembre.
SUB_REAL = {
    "solidez": [{"period_end": "2024-12-31", "score": 75.32},
                {"period_end": "2025-12-31", "score": 67.99}],
    "calidad": [{"period_end": "2024-12-31", "score": 77.54},
                {"period_end": "2025-12-31", "score": 72.15}],
    "eficiencia": [{"period_end": "2024-12-31", "score": 19.24},
                   {"period_end": "2025-12-31", "score": 11.43}],
    "liquidez": [{"period_end": "2024-12-31", "score": 61.49},
                 {"period_end": "2025-12-31", "score": 57.21}],
    "diversificacion": [{"period_end": "2024-12-31", "score": 21.91},
                        {"period_end": "2025-12-31", "score": 22.75}],
}
CORTES = ["2024-12-31", "2025-12-31"]


def test_la_descomposicion_RECONCILIA_con_el_cambio_del_score():
    """El test que vale por todos: un comité SUMA la columna.

    Con los datos reales de Bonao el score cedió 6,02 puntos, y los aportes por dimensión
    tienen que dar eso mismo. Si no reconcilia, la tabla contradice su propio titular.
    """
    rec = _reconciliacion_publica(SUB_REAL, CORTES, "aap", -6.02)
    assert rec["suma_de_aportes"] == -6.02
    assert rec["reconcilia"] is True


def test_declara_el_centesimo_del_redondeo_en_vez_de_esconderlo():
    """Las filas redondeadas suman −6,03 y el titular dice −6,02. Esconder esa diferencia es
    peor que declararla: el lector que sume a mano va a encontrarla igual."""
    rec = _reconciliacion_publica(SUB_REAL, CORTES, "aap", -6.02)
    assert rec["suma_de_las_filas_redondeadas"] == -6.03
    assert "redondeadas" in rec["nota"]


def test_el_aporte_pondera_por_el_PESO_y_no_es_el_delta_suelto():
    """Eficiencia cae MÁS que Solidez (−7,81 vs −7,33) y aporta MENOS, porque pesa 13 % contra
    38 %. Servir el delta suelto obliga al modelo a multiplicar, y multiplicar es lo que hace
    mal — por eso la doctrina manda computarlo."""
    filas = {f["dimension"]: f for f in _balance_por_dimension(SUB_REAL, CORTES, "aap")}
    assert filas["eficiencia"]["cambio"] < filas["solidez"]["cambio"]
    assert filas["eficiencia"]["aporte_al_cambio"] > filas["solidez"]["aporte_al_cambio"]


def test_ordena_de_la_que_mas_DESTRUYO_a_la_que_mas_aporto():
    filas = _balance_por_dimension(SUB_REAL, CORTES, "aap")
    assert [f["dimension"] for f in filas][0] == "solidez"
    assert [f["dimension"] for f in filas][-1] == "diversificacion"


def test_los_pesos_se_RENORMALIZAN_sobre_lo_presente():
    """Si falta una dimensión, acreditarle su peso a las demás es fabricar el dato que no
    está. Es la misma regla del motor, y sin ella los aportes no sumarían el cambio real."""
    parcial = {k: v for k, v in SUB_REAL.items() if k != "diversificacion"}
    filas = _balance_por_dimension(parcial, CORTES, "aap")
    assert abs(sum(f["peso"] for f in filas) - 1.0) < 1e-6


def test_la_nota_de_capital_del_anual_es_LA_MISMA_del_trimestral():
    """No dos textos parecidos: el mismo. Dos redacciones del mismo hecho divergen, y ya nos
    pasó con las etiquetas de tipo de entidad."""
    del_trimestral = _nota_de_capital_redundante(
        {"solvencia": {"raw": 23.26}, "leverage": {"raw": 23.26}})
    del_anual = _nota_de_capital_del_balance(
        [{"indicador": "solvencia", "cierre": 23.26},
         {"indicador": "leverage", "cierre": 23.26}])
    assert del_anual == del_trimestral
    assert del_anual is not None


def test_la_nota_NO_sale_cuando_los_dos_ratios_difieren():
    assert _nota_de_capital_del_balance(
        [{"indicador": "solvencia", "cierre": 23.26},
         {"indicador": "leverage", "cierre": 19.10}]) is None


def test_el_balance_por_indicador_lleva_referencia_Y_score():
    """Los dos huecos que costaron informes, fijados juntos: sin la referencia el guard veta,
    sin el score la tabla no deja ver qué mueve la calificación."""
    indicadores = {"cobertura_provisiones": [
        {"period_end": "2024-12-31", "raw": 147.82, "score": 66.6},
        {"period_end": "2025-12-31", "raw": 108.36, "score": 52.9}]}
    fila = _balance(indicadores, CORTES)[0]
    assert fila["nivel_de_referencia"] == 100.0
    assert (fila["score_apertura"], fila["score_cierre"]) == (66.6, 52.9)


# ── El PANEL en los dos cortes ─────────────────────────────────────────

#: Claves REALES del benchmark (`INDICATOR_TO_BENCHMARK`), no inventadas: mi primera fixture
#: usó `cobertura_avg` y el lector devolvió `{}` — el test habría pasado sin haber medido nada
#: si solo hubiese afirmado ausencias.
_BENCH_AP = {"sector_averages": {"coverage_ratio": 160.0},
             "peer_groups": {"aap": {"coverage_ratio_avg": 150.0, "label": "AAyP", "n": 9}}}
_BENCH_CI = {"sector_averages": {"coverage_ratio": 155.0},
             "peer_groups": {"aap": {"coverage_ratio_avg": 148.0, "label": "AAyP", "n": 9}}}
_IND = {"cobertura_provisiones": [
    {"period_end": "2024-12-31", "raw": 147.82, "score": 66.6},
    {"period_end": "2025-12-31", "raw": 108.36, "score": 52.9}]}


def _fila_con_panel():
    return _balance(_IND, CORTES, bench_apertura=_BENCH_AP, bench_cierre=_BENCH_CI,
                    tipo="aap")[0]


def test_cada_brecha_se_mide_contra_la_referencia_de_SU_MISMO_corte():
    """Comparar el cierre contra la mediana de apertura mezclaría el movimiento de la entidad
    con el del sistema. Medida a cada lado, la estacionalidad se cancela."""
    f = _fila_con_panel()
    assert f["brecha_vs_sistema_apertura"] == round(147.82 - 160.0, 4)
    assert f["brecha_vs_sistema_cierre"] == round(108.36 - 155.0, 4)


def test_dice_si_la_brecha_se_AMPLIO_o_se_cerró():
    """La pregunta del año, y una RELACIÓN: se computa y el modelo la copia. Sin esto, «cayó
    39 puntos» se lee como catástrofe propia aunque el sistema hubiera caído lo mismo."""
    f = _fila_con_panel()
    assert f["brecha_vs_su_tipo_como_se_movio"]["veredicto"] == "se amplió"
    # Estaba 2 puntos bajo su tipo y cerró 40 abajo: la separación creció ~37.
    assert f["brecha_vs_su_tipo_como_se_movio"]["cambio_de_la_brecha"] > 37


def test_acercarse_a_la_referencia_DESDE_ARRIBA_tambien_es_converger():
    """El signo se mide sobre el VALOR ABSOLUTO: si no, una entidad que deja de estar
    excepcionalmente bien figuraría como que «se separó», que es lo contrario de lo que pasó."""
    from modules.banking_score.reports.revision_anual import _como_se_movio_la_brecha
    assert _como_se_movio_la_brecha(40.0, 10.0, 0.5)["veredicto"] == "se redujo"
    assert _como_se_movio_la_brecha(-40.0, -10.0, 0.5)["veredicto"] == "se redujo"


def test_un_movimiento_INMATERIAL_de_la_brecha_no_se_narra_como_cambio():
    from modules.banking_score.reports.revision_anual import _como_se_movio_la_brecha
    assert _como_se_movio_la_brecha(10.0, 10.2, 0.5)["veredicto"] == "estable"


def test_la_referencia_NOMBRA_su_poblacion():
    """«El SUJETO viaja con el número»: `sistema` y `su_tipo` son poblaciones distintas y el
    modelo reatribuye al sujeto más cercano si no se las nombra."""
    f = _fila_con_panel()
    assert f["panel_cierre"]["su_tipo_label"] == "AAyP"
    assert f["panel_cierre"]["su_tipo_n"] == 9
    assert "sistema" in f["panel_cierre"] and "su_tipo" in f["panel_cierre"]


def test_sin_panel_la_fila_NO_inventa_una_brecha():
    """Un benchmark ausente es `None`, nunca cero: una brecha de 0.0 se lee como «está
    exactamente en la referencia», que es una afirmación y no un hueco."""
    f = _balance(_IND, CORTES)[0]
    assert "brecha_vs_sistema_cierre" not in f
    assert "panel_cierre" not in f


# ── Las OTRAS 46 entidades: las que no integran el sistema ─────────────

_BENCH_ROA = {"sector_averages": {"roa": 1.40},
              "peer_groups": {"cambiaria": {"roa_avg": 2.10, "label": "Agentes de cambio",
                                            "n": 42},
                              "aap": {"roa_avg": 0.90, "label": "AAyP", "n": 10}}}
_IND_ROA = {"roa": [{"period_end": "2024-12-31", "raw": 0.71, "score": 30.0},
                    {"period_end": "2025-12-31", "raw": 0.33, "score": 13.3}]}


def _fila_roa(tipo):
    return _balance(_IND_ROA, CORTES, bench_apertura=_BENCH_ROA,
                    bench_cierre=_BENCH_ROA, tipo=tipo)[0]


def test_una_CAMBIARIA_no_se_compara_contra_el_sistema():
    """46 de las 89 entidades del universo —42 cambiarias y 4 fiduciarias— NO integran el
    agregado del sistema: no captan depósitos ni tienen libro de crédito, y el módulo de
    benchmarks las excluye a propósito.

    Y sin embargo comparten claves con el benchmark: `roa` y `roe` las cambiarias, más
    `cost_to_income` las fiduciarias. Sin esta guarda se publicaría «el ROA de este agente de
    cambio está 1,07 puntos bajo el sistema», comparándolo contra bancos. Es la MAYORÍA del
    universo, no un borde — y yo lo verifiqué recién porque el dueño preguntó «¿y las otras
    entidades?», no porque se me hubiera ocurrido.
    """
    f = _fila_roa("cambiaria")
    # El orden importa: comprobar la ausencia PRIMERO. Al revés, el acceso revienta con
    # KeyError antes de poder evaluar el `or` — el test falla por su propia redacción y no
    # por el código, que es una forma barata de perder media hora.
    assert f.get("brecha_vs_sistema_cierre") is None
    assert "sistema" not in (f["panel_cierre"] or {})


def test_y_el_motivo_se_DECLARA_en_vez_de_desaparecer():
    """Una referencia que se omite en silencio se lee como que no existe. La verdad es que
    existe y NO APLICA, que es distinto — y es lo que el lector necesita saber."""
    f = _fila_roa("cambiaria")
    assert "no integra el agregado" in f["panel_cierre"]["sistema_no_aplica"]


def test_pero_SÍ_contra_su_propio_grupo():
    """Los grupos de pares cubren todos los tipos justamente para que cualquier entidad
    encuentre el suyo. Quitarle también esa referencia la dejaría sin ninguna."""
    f = _fila_roa("cambiaria")
    assert f["panel_cierre"]["su_tipo_label"] == "Agentes de cambio"
    assert f["brecha_vs_su_tipo_cierre"] == round(0.33 - 2.10, 4)


def test_una_entidad_del_sistema_sigue_teniendo_las_DOS_referencias():
    f = _fila_roa("aap")
    assert f["brecha_vs_sistema_cierre"] == round(0.33 - 1.40, 4)
    assert f["brecha_vs_su_tipo_cierre"] == round(0.33 - 0.90, 4)
    assert f["panel_cierre"]["sistema_label"]


def test_los_tipos_del_universo_estan_TODOS_contemplados():
    """Barrido con su prueba negativa: cada tipo que existe cae de un lado o del otro, y
    ninguno queda en un limbo donde el comportamiento no esté decidido."""
    from modules.banking_score.models.models import BankType
    from modules.banking_score.scoring.benchmarks import SISTEMA_TIPOS

    tipos = {t.value for t in BankType}
    assert len(tipos) >= 6, "el barrido no encontró los tipos de entidad"
    dentro = tipos & set(SISTEMA_TIPOS)
    fuera = tipos - set(SISTEMA_TIPOS)
    assert dentro and fuera, "si todos cayeran del mismo lado, esta guarda no probaría nada"
    for tipo in sorted(fuera):
        assert "sistema" not in (_fila_roa(tipo)["panel_cierre"] or {}), (
            f"'{tipo}' no integra el sistema y se le sirvió la referencia del sistema.")


class TestLaFrescuraSignificaLoMismoEnLosDos:
    """Los dos productos van en el MISMO paquete al cliente: si `freshness_days` no mide lo
    mismo en ambos, los dos documentos se contradicen sobre qué tan al día está el dato.

    El caso: el anual la medía contra el 31 de diciembre del año cerrado —una propiedad del
    CALENDARIO, que crece sola cada día— mientras el trimestral la medía contra la
    observación más nueva del panel. Una revisión externa de dos informes reales de la misma
    entidad lo señaló como contradicción, y tenía razón. Que el informe hable de SU corte y no
    del último dato es otra cosa, y la resuelve `report_sections._frescura_md` anclando al
    corte; esto fija qué MIDE el campo.

    Se lee con `ast` y no buscando texto: `data_signals` tiene un early return que también
    asigna `freshness_days`, así que un `.index()` encuentra ESE y el test pasa con el código
    viejo. Pasó — este test no tuvo dientes hasta que se comprobó contra la versión anterior.
    """

    @staticmethod
    def _expresiones_de_frescura(clase):
        """Cada expresión asignada a `freshness_days` en `data_signals`, como fuente."""
        import ast
        import inspect
        import textwrap
        arbol = ast.parse(textwrap.dedent(inspect.getsource(clase.data_signals)))
        # Un nivel de indirección: el trimestral pasa `freshness_days=freshness` y calcula
        # `freshness` una línea antes. Sin resolver el nombre, el test miraría la variable en
        # vez de su definición y aprobaría cualquier cosa.
        asignaciones = {t.id: ast.unparse(nodo.value)
                        for nodo in ast.walk(arbol) if isinstance(nodo, ast.Assign)
                        for t in nodo.targets if isinstance(t, ast.Name)}
        out = []
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            for kw in nodo.keywords:
                if kw.arg != "freshness_days":
                    continue
                expr = ast.unparse(kw.value)
                out.append(asignaciones.get(expr, expr) if isinstance(kw.value, ast.Name)
                           else expr)
        return out

    def _productos(self):
        from modules.banking_score.products import BankingProduct
        from modules.banking_score.products_year_review import BankingYearReviewProduct
        return (BankingProduct, BankingYearReviewProduct)

    def test_la_frescura_sale_del_maximo_periodo_del_panel(self):
        for clase in self._productos():
            reales = [e for e in self._expresiones_de_frescura(clase) if e != "None"]
            assert reales, f"{clase.__name__}: no asigna ninguna frescura real"
            for expr in reales:
                assert "period_end" in expr or "ultima_obs" in expr or "latest" in expr, (
                    f"{clase.__name__}: la frescura sale de `{expr}`, que no es la observación "
                    f"más nueva del panel; si cada producto usa otra referencia, los dos "
                    f"informes de un mismo paquete se contradicen")

    def test_la_frescura_no_se_computa_contra_una_fecha_de_CALENDARIO(self):
        for clase in self._productos():
            for expr in self._expresiones_de_frescura(clase):
                assert "12, 31" not in expr, (
                    f"{clase.__name__}: la frescura se mide contra `{expr}` — eso es una "
                    f"propiedad del calendario, no del dato: crece sola aunque el panel no "
                    f"cambie, y da un número distinto del que publica el otro producto")
