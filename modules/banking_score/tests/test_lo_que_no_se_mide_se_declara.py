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


# ── 2. La ausencia del mapa, declarada ─────────────────────────────

class TestLaAusenciaDelMapaSeDECLARA:
    """El informe de 2026-06-30 simplemente no traía la sección. La lectura que quedaba era
    la peor: que la entidad evaluada carece de algo, cuando lo que faltaba era un trimestre
    que la fuente no publicó."""

    def test_los_dos_motivos_son_DISTINTOS(self):
        from modules.banking_score.reports import mapa_sectorial as m
        assert m.MOTIVO_FUENTE_SIN_PUBLICAR != m.MOTIVO_ENTIDAD_SIN_DESGLOSE
        assert "Superintendencia" in m.MOTIVO_FUENTE_SIN_PUBLICAR
        assert "esta entidad" in m.MOTIVO_ENTIDAD_SIN_DESGLOSE.lower()

    def test_sin_celdas_del_corte_la_culpa_es_de_la_FUENTE(self, monkeypatch):
        from modules.banking_score.reports import mapa_sectorial as m
        monkeypatch.setattr(m, "_celdas", lambda db, corte: [])
        assert m.motivo_sin_mapa(None, date(2026, 6, 30), object()) == (
            m.MOTIVO_FUENTE_SIN_PUBLICAR)

    def test_con_celdas_pero_no_de_la_entidad_el_hueco_es_de_la_ENTIDAD(self, monkeypatch):
        """Confundirlos haría que un trimestre sin publicar se leyera como una
        característica del banco evaluado."""
        from modules.banking_score.reports import mapa_sectorial as m
        monkeypatch.setattr(m, "_celdas", lambda db, corte: [object()])
        assert m.motivo_sin_mapa(None, date(2026, 3, 31), object()) == (
            m.MOTIVO_ENTIDAD_SIN_DESGLOSE)

    def test_el_mapa_del_SISTEMA_no_habla_de_ninguna_entidad(self, monkeypatch):
        from modules.banking_score.reports import mapa_sectorial as m
        monkeypatch.setattr(m, "_celdas", lambda db, corte: [])
        motivo = m.motivo_sin_mapa(None, date(2026, 6, 30), None)
        assert motivo == m.MOTIVO_SISTEMA_SIN_PUBLICAR
        assert "entidad" not in motivo.lower()

    @pytest.mark.parametrize("ruta", ["informes", "productos"])
    def test_las_DOS_rutas_colocan_el_motivo_como_texto_de_la_seccion(self, ruta):
        """El gate gemelo: el filtro que descarta la sección vive en las dos rutas, así que
        la declaración tiene que vivir en las dos o el informe de una saldrá mudo."""
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
        # Se exige la LLAMADA a update con los motivos, no la mención del nombre: un test
        # que buscara el string pasaría en verde contra el código roto, porque el comentario
        # que explica el arreglo menciona el nombre.
        updates = [n for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "update"
                   and any(isinstance(a, ast.Name) and "motivo" in a.id for a in n.args)]
        assert updates, (
            f"la ruta de {ruta} descarta la sección sin colocar el motivo: el informe queda "
            "mudo sobre por qué falta el mapa")


class TestLaSeccionDeclaradaVaEnSuLUGAR:
    """El PDF numera las secciones por el orden del dict. Anexar la declarada al final dejó
    «10. Mapa Sectorial del Crédito» DESPUÉS de la Recomendación en el informe real de
    2026-06-30: un documento que se vende no puede tener el índice desordenado porque faltó
    un dato."""

    @pytest.mark.parametrize("ruta", ["informes", "productos"])
    def test_el_retorno_respeta_el_orden_declarado(self, ruta):
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
        # El último `return` tiene que ser una comprensión de dict guiada por el orden
        # original, no el dict crudo al que se le anexó.
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value]
        assert any(isinstance(r.value, ast.DictComp) for r in returns), (
            f"la ruta de {ruta} devuelve el dict tal cual: la sección declarada queda al "
            "final y el índice del documento sale desordenado")
