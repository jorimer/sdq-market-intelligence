"""La §4 tiene contexto propio, y los conteos de mercado dicen qué cuentan.

Dos defectos del Deep Dive de MAPFRE-BHD:

* «un mercado de 26 operadores activos» era FALSO. La serie `sis.aseguradoras.activas_max` es
  el MÁXIMO ENTRE RAMOS de cuántas compañías operan en un ramo — 26 es el ramo más concurrido,
  no el mercado. El panel tiene 35 con ISF. Bajo el nombre `aseguradoras_activas`, el modelo lo
  leyó como tamaño de mercado y derivó «la cola restante, 22 operadores».
* La sección Alerta Temprana usaba el MISMO template y el MISMO contexto que la evaluación de
  solidez, así que repetía el análisis y hasta el encabezado de la §1.
"""
import inspect

from modules.insurance_intel.ai_context import market_pulse_context


class TestConteosDeMercado:
    def _ctx(self):
        return market_pulse_context({
            "period": "2026-03", "latest_year": "2025", "active_insurers": 26, "n_ramos": 11,
            "total_premiums_rd": 1.5e11, "top4_concentration_pct": 87.1,
            "mix": [{"label": "Incendio y Aliados", "amount": 4e10, "pct": 26.0},
                    {"label": "Salud", "amount": 3.6e10, "pct": 23.8},
                    {"label": "Vehículos de Motor", "amount": 3.3e10, "pct": 21.9},
                    {"label": "Vida Colectiva", "amount": 2.3e10, "pct": 15.4}],
        })

    def test_la_clave_dice_que_es_un_maximo_POR_RAMO(self):
        ctx = self._ctx()
        assert ctx["max_aseguradoras_en_un_mismo_ramo"] == 26
        assert "aseguradoras_activas" not in ctx, (
            "el nombre viejo invita a leerlo como tamaño de mercado")

    def test_el_tamano_real_del_mercado_viaja_con_su_propio_nombre(self):
        """Sin una cifra correcta disponible, el modelo toma la que haya."""
        n = self._ctx()["aseguradoras_autorizadas_sis"]
        assert n is None or n > 26

    def test_la_concentracion_sigue_nombrando_su_poblacion(self):
        ctx = self._ctx()
        assert ctx["concentracion_top4_ramos_pct"] == 87.1
        assert ctx["concentracion_top4_ramos_nombres"][0] == "Incendio y Aliados"

    def test_la_tabla_del_pdf_rotula_el_maximo_por_ramo(self):
        from modules.insurance_intel.products import _pulse_table
        _, rows = _pulse_table({"active_insurers": 26, "latest_year": "2025",
                                "total_premiums_rd": 1.5e11})
        etiquetas = [r[0] for r in rows]
        assert any("un mismo ramo" in e for e in etiquetas)
        assert "Aseguradoras activas" not in etiquetas


class TestAlertaTemprana:
    def test_la_seccion_no_reusa_el_contexto_de_la_evaluacion(self):
        from modules.insurance_intel.products import InsuranceProduct
        src = inspect.getsource(InsuranceProduct.narratives)
        i = src.index('section == "early_warning"')
        j = src.index('ctx = insurance_entity_context', i)
        assert "insurance_early_warning_context" in src[i:j], (
            "la §4 volvió a caer al contexto de la §1: publicará el mismo análisis")

    def test_el_contexto_trae_la_trayectoria_y_prohibe_repetir(self):
        from modules.insurance_intel.ai_context import insurance_early_warning_context
        rating = {"slug": "x", "name": "X", "overall_score": 71.1, "coverage": 1.0,
                  "dimensions": [{"key": "liquidez", "label": "Liquidez", "score": 42.7,
                                  "weight": 0.15, "present": True},
                                 {"key": "escala", "label": "Escala", "score": 95.5,
                                  "weight": 0.15, "present": True}]}
        ctx = insurance_early_warning_context(None, "x", rating, [rating])
        # Sin DB la trayectoria se declara ausente, nunca se inventa ni revienta la sección.
        assert ctx["trayectoria"]["disponible"] is False
        assert ctx["dimension_mas_debil"]["dimension"] == "Liquidez"
        enf = ctx["enfoque"]
        assert "NO la repitas" in enf and "TRAYECTORIA" in enf

    def test_la_regla_de_sin_senal_viaja_cuando_hay_trayectoria(self):
        """«Sin señal» ≠ «estable»: el modelo no debe intercambiarlas."""
        from modules.insurance_intel.ai_context import insurance_early_warning_context
        from modules.insurance_intel.ai_context import REGLA_TENDENCIA
        assert "NO significa estable" in REGLA_TENDENCIA
        assert "regla_tendencia" in inspect.getsource(insurance_early_warning_context)


def test_la_ventana_del_ciclo_se_declara():
    """Dos combined ratios de la misma compañía en un documento —2024 y ciclo 2020-2024—
    parecen una contradicción si no se nombra la ventana al citarlos.

    Se afirma sobre el VALOR de la constante, no sobre el código: un literal partido por ancho
    de línea deja de existir como frase en el fuente aunque el valor sea correcto (la primera
    versión de este test falló justamente por eso).
    """
    from modules.insurance_intel.ai_context import REGLA_TENDENCIA, VENTANA_DEL_CICLO
    assert "no el último ejercicio" in VENTANA_DEL_CICLO
    assert "rango de años" in VENTANA_DEL_CICLO
    assert "NO significa estable" in REGLA_TENDENCIA
