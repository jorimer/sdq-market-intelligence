"""Re-etiquetado retroactivo de acciones a Perfil SDQ (spec §9)."""
import pytest

from modules.banking_score.scoring.acciones_por_eje import transicion


class TestTransicion:

    def test_expresa_el_movimiento_de_banda(self):
        assert transicion("Competitiva", "Rezagada") == "Competitiva → Rezagada"

    def test_sin_movimiento_lo_dice_en_vez_de_callar(self):
        """«Sólida (sin cambio)» y «sin dato» son afirmaciones distintas."""
        assert transicion("Sólida", "Sólida") == "Sólida (sin cambio)"

    def test_una_banda_ausente_NO_se_lee_como_sin_cambio(self):
        """Si el período anterior no tiene el eje calculado, no hay transición que afirmar."""
        assert transicion(None, "Sólida") is None
        assert transicion("Sólida", None) is None
        assert transicion(None, None) is None


class TestReetiquetadoRetroactivo:
    """La acción se DESDOBLA: un símbolo único no traduce a una etiqueta nueva."""

    def test_los_dos_ejes_pueden_moverse_en_sentidos_OPUESTOS(self):
        """Es lo que el tier único no podía expresar — los promediaba en un movimiento."""
        assert transicion("Rezagada", "Competitiva") == "Rezagada → Competitiva"
        assert transicion("Sólida", "Adecuada") == "Sólida → Adecuada"

    def test_el_delta_declara_la_brecha_en_vez_de_asumir_cero(self):
        from modules.banking_score.scoring.acciones_por_eje import _delta
        assert _delta(50.0, 62.5) == 12.5
        assert _delta(None, 62.5) is None
        assert _delta(50.0, None) is None

    def test_la_operacion_tiene_la_firma_del_runner(self):
        """Un runner con la firma equivocada pasa los 3 gates y revienta en producción."""
        import inspect

        from modules.banking_score.operations import _run_reetiquetar_acciones
        assert list(inspect.signature(_run_reetiquetar_acciones).parameters) == [
            "params", "user_id", "set_phase"]


def test_las_acciones_NUEVAS_nacen_con_los_ejes():
    """Sin esto, cada período nuevo volvería a necesitar el re-etiquetado retroactivo."""
    import inspect

    from modules.banking_score.scoring import batch
    src = inspect.getsource(batch.detect_rating_action)
    for campo in ("banda_ejecucion_previa", "banda_ejecucion_nueva",
                  "banda_resiliencia_previa", "banda_resiliencia_nueva",
                  "ejecucion_delta", "resiliencia_delta"):
        assert campo in src, f"detect_rating_action no puebla {campo}"


def test_el_modelo_declara_las_columnas_por_eje():
    from modules.banking_score.models.models import RatingAction
    cols = {c.name for c in RatingAction.__table__.columns}
    assert {"banda_ejecucion_previa", "banda_ejecucion_nueva",
            "banda_resiliencia_previa", "banda_resiliencia_nueva",
            "ejecucion_delta", "resiliencia_delta"} <= cols
    # La notación vieja SIGUE en la tabla: es linaje del dato, no superficie.
    assert {"previous_tier", "new_tier"} <= cols


class TestDedupAcciones:
    """Los duplicados no son historia: son la misma acción recalculada 19 veces."""

    def test_por_defecto_SIMULA_y_no_borra(self):
        """Un borrado en producción se mira antes de correrlo."""
        import inspect

        from modules.banking_score.scoring.dedup_acciones import deduplicar
        assert inspect.signature(deduplicar).parameters["ejecutar"].default is False

    def test_la_operacion_exige_ejecutar_explicito(self):
        import inspect

        from modules.banking_score import operations
        src = inspect.getsource(operations._run_dedup_acciones)
        assert 'get("ejecutar")' in src, "la operación borra sin exigir confirmación"

    def test_la_firma_del_runner_es_la_del_repo(self):
        import inspect

        from modules.banking_score.operations import _run_dedup_acciones
        assert list(inspect.signature(_run_dedup_acciones).parameters) == [
            "params", "user_id", "set_phase"]


def test_detect_rating_action_ACTUALIZA_en_vez_de_insertar_siempre():
    """La causa raíz de los 35.621 duplicados: se insertaba en cada rescore."""
    import inspect

    from modules.banking_score.scoring import batch
    src = inspect.getsource(batch.detect_rating_action)
    assert "RatingAction.bank_id == bank_id" in src, "no busca la acción existente"
    assert "if action is None:" in src, "no distingue crear de actualizar"


def test_el_serializador_expone_los_dos_ejes():
    """Regresión: el re-etiquetado quedó en la base y no se veía por la API."""
    import inspect

    from modules.banking_score.api import router_reports
    src = inspect.getsource(router_reports._action_to_dict)
    for campo in ("banda_ejecucion_previa", "banda_resiliencia_nueva",
                  "transicion_ejecucion", "transicion_resiliencia"):
        assert f'"{campo}"' in src, f"_action_to_dict no expone {campo}"
