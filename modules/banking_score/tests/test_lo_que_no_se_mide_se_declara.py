"""Dos ausencias que el informe publicaba mal: una en silencio y otra como número imposible.

Salieron del Deep Dive de Banco Múltiple Caribe Internacional al 2026-06-30 —el corte cuyo
cubo de crédito la Superintendencia todavía no publicó—.
"""

from datetime import date

import pytest

from modules.banking_score.scoring import sensitivity as sens


# ── 1. El umbral que no puede existir ──────────────────────────────

class TestUnUmbralFueraDelDominioNoEsUnRiesgo:
    """«Exposición inmobiliaria · actual 11.46 · umbral -5.02%».

    La tabla invierte la curva y publicaba el resultado sin preguntarse si ese valor puede
    existir. Una exposición es una porción de la cartera: no puede ser negativa. Lo que ese
    número decía es que la banda NO ES ALCANZABLE por ese indicador, y esa fila no es un
    riesgo — es ruido que además desplaza a un riesgo real de una tabla que muestra tres.
    """

    def test_una_porcion_de_cartera_no_puede_ser_negativa(self):
        assert not sens.umbral_alcanzable("exposicion_re", -5.02)
        assert not sens.umbral_alcanzable("morosidad", -0.1)
        assert not sens.umbral_alcanzable("concentracion_top10", 101.0)

    def test_lo_que_SÍ_puede_ser_negativo_sigue_pasando(self):
        """El contra-caso. Una cota inferior aplicada a todo borraría escenarios reales:
        el patrimonio puede ser negativo, y este repo ya tuvo un defecto por suponer que no.
        """
        for clave in ("roa", "roe", "margen_financiero", "patrimonio_activos",
                      "solvencia", "tier1_ratio", "leverage"):
            assert sens.umbral_alcanzable(clave, -3.0), clave

    def test_el_valor_actual_de_CADA_indicador_esta_en_su_dominio(self):
        """Barrido con prueba negativa: si el dominio declarado excluyera un valor que el
        panel produce de verdad, la tabla perdería filas legítimas en silencio."""
        reales = {"exposicion_re": 11.46, "morosidad": 3.56, "concentracion_top10": 34.90,
                  "cobertura_provisiones": 113.34, "castigos_pct": 3.68, "ltd": 85.22,
                  "liquidez_inmediata": 30.30, "liquidez_ajustada": 46.58,
                  "pct_cartera_a": 96.29, "migracion": 5.09, "hhi_ingresos": 4677.0,
                  "hhi_sectorial": 2222.0, "cost_to_income": 43.92, "roa": 0.37,
                  "roe": 5.61, "margen_financiero": 7.27, "solvencia": 13.09,
                  "tier1_ratio": 10.42, "leverage": 9.56, "patrimonio_activos": 6.55}
        assert set(reales) == set(sens._CURVES), (
            "el barrido dejó indicadores afuera: agregá su valor real o quitá su curva")
        for clave, v in reales.items():
            assert sens.umbral_alcanzable(clave, v), f"{clave}={v} quedó fuera de su dominio"

    def test_TODO_indicador_con_curva_declara_su_dominio(self):
        """Estructural: un indicador nuevo no puede entrar sin declararlo, o volvería a
        publicar umbrales imposibles sin que nada falle."""
        faltan = set(sens._CURVES) - set(sens.DOMINIO_DEL_INDICADOR)
        assert not faltan, f"sin dominio declarado: {sorted(faltan)}"

    def test_la_tabla_DESCARTA_la_fila_del_umbral_imposible(self):
        """De comportamiento: se arma la tabla y se mira si la fila salió."""
        ind = {"exposicion_re": {"raw": 11.46, "score": 81.0, "available": True},
               "morosidad": {"raw": 3.56, "score": 64.4, "available": True}}
        t = sens.sensitivity_table(ind, "banca_multiple")
        claves = [f["indicador"] for f in t["riesgos_baja"]]
        assert "exposicion_re" not in claves, (
            f"publica un umbral fuera del dominio: {t['riesgos_baja']}")


# ── 2. La ausencia del mapa NO se inventaría ───────────────────

class TestLaAusenciaDelMapaNOseInventaria:
    """Hubo una versión que ponía en el lugar de la sección un párrafo explicando el hueco.

    Dejaba en el índice del documento un título —«Mapa Sectorial del Crédito»— cuyo contenido
    entero era «esto no lo tenemos». El dueño lo revirtió el 2026-08-31: un lector de un
    informe de calificación no lee eso como rigor, lo lee como producto incompleto. Lo que no
    se puede afirmar no se menciona.

    Lo que SÍ se conserva —y este test lo exige— es que la sección se siga descartando: narrar
    un contexto vacío produce una sección hueca y `full_rating` falla cerrado ante una
    degradada. Y la afirmación de MÉTODO, una sola vez, en Limitaciones.
    """

    @pytest.mark.parametrize("ruta", ["informes", "productos"])
    def test_la_seccion_se_descarta_y_NO_se_reemplaza_por_un_parrafo(self, ruta):
        import ast
        import inspect
        if ruta == "informes":
            from modules.banking_score.reports import narrative as mod
            fn_name = "generate_report_narratives"
        else:
            from modules.banking_score import products_year_review as mod
            fn_name = "narratives"
        fn = next(n for n in ast.walk(ast.parse(inspect.getsource(mod)))
                  if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                  and n.name == fn_name)
        src = ast.unparse(fn)
        assert "mapa_sectorial" in src, f"la ruta de {ruta} dejó de filtrar la sección sin dato"
        assert "_no_publicado" not in src, (
            f"la ruta de {ruta} volvió a poner un párrafo en el lugar de la sección ausente")

    def test_la_afirmacion_de_METODO_sigue_estando_una_vez(self):
        from modules.banking_score.products import _LIMITATIONS_TEXT
        assert "se renormalizan sobre lo efectivamente medido" in _LIMITATIONS_TEXT

    def test_la_COBERTURA_no_anuncia_huecos(self):
        """La frase terminaba en «lo no cubierto se declara como rúbrica o brecha — nunca se
        fabrica»: cierta, y le anunciaba al comprador que tenemos huecos.

        Se leen los LITERALES vía `ast` y no el fuente en crudo: la primera versión de este
        test buscaba la frase en el texto del módulo y fallaba por el COMENTARIO que explica
        justamente este cambio. Es el mismo modo de falla que ya se documentó hoy — un test
        que se satisface con su propia documentación, acá en la dirección contraria.
        """
        import ast
        import inspect

        from shared.products import report_sections
        literales = [n.value for n in ast.walk(ast.parse(inspect.getsource(report_sections)))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any("rúbrica o brecha" in t for t in literales), (
            "la cobertura volvió a anunciarle al comprador que tenemos huecos")
        assert any("se construye sobre dato" in t for t in literales)
