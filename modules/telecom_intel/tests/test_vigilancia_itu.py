"""La sonda que vigila si la UIT volvió a dejar entrar.

**El hueco que cierra, medido en producción el 2026-08-23.** `itu-telecom-sync` está en
`phase: error` desde el 2026-07-19 con `403 Forbidden` de `api.datahub.itu.int` — el mismo
corte que la UIT confirmó por escrito el 2026-08-18 (ciberataques contra sus API, acceso
externo restringido, sin fecha de restablecimiento). El dato servido sigue siendo correcto:
2024 es el último anual que la UIT publica. Lo que estaba roto no era la cifra sino el
REINTENTO: la operación es anual y su `next_run_at` cae en **2027-06-28**. Si la UIT reabre
la semana que viene, el eje se queda diez meses sin enterarse.

**Lo que hace peligrosa a una sonda es lo mismo que en la de INDOTEL:** que confunda «miré y
sigue cerrado» con «no pude mirar». Un fallo de red reportado como «sigue restringido» es
peor que no tener sonda, porque produce una confirmación falsa que nadie va a revisar. Por
eso son TRES estados y no un booleano.
"""
import httpx
import pytest

from shared.data.itu_client import (ABIERTO, INDETERMINADO, RESTRINGIDO,
                                    sonda_datahub)


class _Resp:
    def __init__(self, status):
        self.status_code = status


def _con_respuesta(monkeypatch, status):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(status))
    return sonda_datahub()


def _sin_red(monkeypatch, exc):
    def _boom(*_a, **_k):
        raise exc
    monkeypatch.setattr("httpx.get", _boom)
    return sonda_datahub()


class TestLosTresEstados:

    def test_un_200_es_que_el_acceso_volvio(self, monkeypatch):
        r = _con_respuesta(monkeypatch, 200)
        assert r["estado"] == ABIERTO and r["http"] == 200

    @pytest.mark.parametrize("status", [401, 403])
    def test_el_emisor_negando_el_acceso_es_RESTRINGIDO(self, monkeypatch, status):
        r = _con_respuesta(monkeypatch, status)
        assert r["estado"] == RESTRINGIDO and r["http"] == status

    def test_no_poder_llegar_NO_es_sigue_cerrado(self, monkeypatch):
        """El error que hace inútil a una sonda: reportar la propia falla como hallazgo."""
        r = _sin_red(monkeypatch, httpx.ConnectError("no resuelve"))
        assert r["estado"] == INDETERMINADO
        assert r["http"] is None

    def test_una_respuesta_rara_tampoco_concluye(self, monkeypatch):
        """Un 500 del emisor o un portal de captura no son «sigue cerrado» ni «volvió»."""
        r = _con_respuesta(monkeypatch, 502)
        assert r["estado"] == INDETERMINADO and r["http"] == 502

    def test_la_sonda_nunca_levanta(self, monkeypatch):
        """Una sonda que rompe la operación deja de correr, y entonces no vigila nada."""
        assert _sin_red(monkeypatch, RuntimeError("cualquier cosa"))["estado"] == INDETERMINADO


class TestLaOperacionEstaRegistrada:

    def test_existe_y_su_cadencia_no_es_la_del_sync(self):
        """El sync es anual porque el DATO es anual; la sonda vigila el ACCESO, que puede
        volver cualquier día. Igualar las cadencias reabriría el hueco de diez meses."""
        import modules.telecom_intel.operations  # noqa: F401 — registra las operaciones
        from shared.operations import OPERATIONS

        sonda, sync = OPERATIONS.get("itu-vigilancia"), OPERATIONS.get("itu-telecom-sync")
        assert sonda is not None, f"no se registró la sonda: {sorted(OPERATIONS)}"
        assert sync is not None
        assert sonda.default_interval_hours < sync.default_interval_hours

    def test_la_sonda_no_ingiere_nada(self):
        """Propone y no promueve: re-cablear la fuente vigente es decisión del dueño."""
        import inspect

        from modules.telecom_intel.operations import _run_vigilancia_itu

        cuerpo = inspect.getsource(_run_vigilancia_itu)
        assert "create_suggestion" in cuerpo
        assert "compute_and_persist" not in cuerpo and "_write_score" not in cuerpo
