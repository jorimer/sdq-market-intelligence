"""El saldo agotado se reporta UNA vez por operación, no una vez por sección.

**Por qué existe este archivo.** El crédito de la organización estuvo agotado cinco semanas
y produjo 961 eventos de Sentry en siete días. El volumen NO venía de reintentos (el
reintento de sección ya excluye los 400 por diseño): venía de que cada sección degradada
loguea a ``ERROR`` y la integración de logging convierte todo ``ERROR`` en evento. Un Deep
Dive fanea 6 secciones × 2-4 llamadas, así que una sola generación sin saldo emitía decenas
de eventos idénticos — y sepultaba debajo las incidencias reales.

Lo que se acalla es SOLO el saldo agotado, que es determinista y de organización. Un error
del modelo conserva su ``ERROR`` intacto: confundir las dos cosas volvería a esconder
justamente lo que hay que ver.
"""
import logging

import anthropic
import httpx
import pytest

from shared.llm import failures
from shared.llm.failures import is_credit_exhausted, report_api_failure


def _error(mensaje: str) -> anthropic.BadRequestError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": mensaje}}
    return anthropic.BadRequestError(f"Error code: 400 - {body}",
                                     response=httpx.Response(400, request=req), body=body)


_SIN_CREDITO = ("Your credit balance is too low to access the Anthropic API. "
                "Please go to Plans & Billing to upgrade or purchase credits.")


@pytest.fixture(autouse=True)
def _limpiar():
    """La ventana vive en un módulo: sin limpiar, un test hereda el reporte de otro."""
    failures._last_credit_log.clear()
    yield
    failures._last_credit_log.clear()


@pytest.fixture()
def log(caplog):
    caplog.set_level(logging.WARNING, logger="test.credito")
    return logging.getLogger("test.credito")


def _niveles(caplog):
    return [r.levelno for r in caplog.records]


def test_reconoce_el_saldo_agotado():
    assert is_credit_exhausted(_error(_SIN_CREDITO))


def test_no_confunde_otro_400_con_saldo():
    """Comparte ``type`` con cualquier ``invalid_request_error``: si el reconocedor fuera
    laxo, acallaría errores de prompt que sí hay que ver."""
    assert not is_credit_exhausted(_error("max_tokens: must be greater than 0"))


def test_un_error_cualquiera_no_es_saldo():
    assert not is_credit_exhausted(ValueError("cualquier cosa"))


def test_el_saldo_abre_UN_evento_y_el_resto_baja_a_warning(log, caplog):
    """El caso de producción: seis secciones fallando dentro de la misma operación."""
    for _ in range(6):
        report_api_failure(log, _error(_SIN_CREDITO), label="cerebro")

    niveles = _niveles(caplog)
    assert niveles.count(logging.ERROR) == 1, f"esperaba 1 evento, hubo {niveles.count(logging.ERROR)}"
    assert niveles.count(logging.WARNING) == 5
    assert "AGOTADO" in caplog.records[0].getMessage()


def test_un_error_del_modelo_conserva_su_error(log, caplog):
    """No se acalla lo que no es saldo: eran las incidencias reales sepultadas."""
    for _ in range(3):
        report_api_failure(log, _error("max_tokens: must be greater than 0"), label="cerebro")
    assert _niveles(caplog).count(logging.ERROR) == 3


def test_cada_operacion_reporta_la_suya(log, caplog):
    """La ventana es POR operación: si fuera global, la primera en fallar acallaría a las
    demás y el operador no vería a quién le está pasando."""
    from shared.observability.llm_ledger import attributed_to

    for op in ("informe-diario", "rescore"):
        with attributed_to("operacion", op):
            report_api_failure(log, _error(_SIN_CREDITO), label="cerebro")
            report_api_failure(log, _error(_SIN_CREDITO), label="cerebro")

    assert _niveles(caplog).count(logging.ERROR) == 2
    assert _niveles(caplog).count(logging.WARNING) == 2


def test_pasada_la_ventana_vuelve_a_alertar(log, caplog, monkeypatch):
    """Un agotamiento NUEVO tiene que volver a abrir evento; si no, se acalla para siempre."""
    report_api_failure(log, _error(_SIN_CREDITO), label="cerebro")
    for k in failures._last_credit_log:
        failures._last_credit_log[k] -= failures._CREDIT_LOG_WINDOW_SECONDS + 1
    report_api_failure(log, _error(_SIN_CREDITO), label="cerebro")
    assert _niveles(caplog).count(logging.ERROR) == 2


def test_reporta_aunque_la_maquina_recien_arranque(log, caplog, monkeypatch):
    """Regresión: el primer reporte no puede depender del UPTIME de la máquina.

    La ventana usaba un centinela 0.0 y preguntaba ``ahora - 0.0 > 3600``. El origen de
    ``time.monotonic()`` es arbitrario —en Linux cuenta desde el arranque—, así que en un
    runner con menos de una hora encendido el PRIMER reporte caía a WARNING: ningún evento,
    y el silencio se lee como que no hay problema. Pasaba en local (uptime largo) y fallaba
    en CI. Se fija un monotonic chico para reproducir esa máquina.
    """
    monkeypatch.setattr(failures.time, "monotonic", lambda: 12.0)
    report_api_failure(log, _error(_SIN_CREDITO), label="cerebro")
    assert _niveles(caplog).count(logging.ERROR) == 1, (
        "el primer saldo agotado no abrió evento: la ventana depende del uptime")
