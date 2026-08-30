"""Un fallo de una operación LARGA tiene que quedar diagnosticable sin acceso al servidor.

El caso. El 2026-08-30 el backfill del cubo de créditos murió a los 106 minutos, en el
trimestre 19 de 22. Lo único que quedó en el estado fue «Ocurrió un error durante la
sincronización. El detalle quedó en los registros (logs)» — y esos logs viven en Railway.
Sin acceso al servidor, dos horas y media de trabajo terminaron en un fallo sobre el que no
se podía formular ni una hipótesis: ni el tipo de excepción, ni dónde murió.

La intención original era buena y se conserva: un stacktrace no va delante del operador, así
que el mensaje amable sigue siendo lo que la pantalla muestra. Lo que cambia es que la firma
técnica —tipo, mensaje acotado y FASE— se persiste en el resultado, que es donde alguien la
va a buscar cuando pregunte «¿por qué falló?».
"""

from modules.banking_score.sib_sync import _firma_tecnica, _friendly_error


class TestLaFirmaTecnica:
    def test_conserva_el_TIPO_de_excepcion(self):
        """Sin el tipo no se puede ni empezar: un MemoryError y un error de driver piden
        cosas distintas y el mensaje amable es el mismo para los dos."""
        f = _firma_tecnica(MemoryError("out of memory"), "carteras 2025-09 (19/22)")
        assert f["excepcion"] == "MemoryError"

    def test_conserva_la_FASE_en_que_murio(self):
        f = _firma_tecnica(ValueError("x"), "carteras 2025-09 (19/22)")
        assert f["fase_al_fallar"] == "carteras 2025-09 (19/22)"

    def test_trunca_el_detalle_porque_el_estado_se_sirve_por_API(self):
        """Un error de driver puede traer una consulta entera."""
        f = _firma_tecnica(ValueError("x" * 5000), None)
        assert len(f["detalle"]) == 300

    def test_una_excepcion_sin_mensaje_deja_None_y_no_cadena_vacia(self):
        """Una cadena vacía se lee como «no hubo detalle»; None dice «no lo trajo»."""
        assert _firma_tecnica(MemoryError(), None)["detalle"] is None

    def test_sin_fase_conocida_lo_dice_con_None(self):
        assert _firma_tecnica(ValueError("x"), None)["fase_al_fallar"] is None


class TestElMensajeAmableNoCambia:
    """La firma técnica se AGREGA; no reemplaza lo que el operador lee."""

    def test_los_errores_reconocidos_siguen_traduciendose(self):
        assert "Tiempo de espera" in _friendly_error(TimeoutError("connection timed out"))
        assert "Credenciales" in _friendly_error(RuntimeError("401 unauthorized"))

    def test_un_error_desconocido_sigue_diciendo_algo_legible(self):
        m = _friendly_error(MemoryError("out of memory"))
        assert "error" in m.lower() and "MemoryError" not in m
