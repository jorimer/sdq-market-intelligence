"""La cadencia se ancla al CALENDARIO de publicación, no al reloj.

Caso real: `dga-trade-sync` corrió el 2026-06-27 —tres días antes de que cerrara 2026-Q2— y
`next_run_at = ahora + 2160h` lo mandó al 2026-09-25. La DGA publicó Q2 en el medio y el
sistema sirvió Q1 en informes fechados en agosto, casi tres meses tarde y sin declararlo.
"""
from datetime import datetime, timedelta

from shared.operations.calendario import (
    REINTENTO_DIAS, REZAGO_PUBLICACION_DIAS, proximo_disparo,
)


class TestTrimestral:
    def test_el_caso_que_lo_motivo(self):
        """27-jun con intervalo de 90 días: la relativa da septiembre, la anclada agosto."""
        ahora = datetime(2026, 6, 27)
        anclada = proximo_disparo("trimestral", ahora, 2160)
        relativa = ahora + timedelta(hours=2160)
        assert anclada < relativa
        assert anclada.month == 8 and anclada.year == 2026
        assert relativa.month == 9

    def test_apunta_al_cierre_del_trimestre_mas_el_rezago(self):
        # Q1 cierra el 31-mar; con 45 días de rezago, mediados de mayo.
        d = proximo_disparo("trimestral", datetime(2026, 2, 10), 2160)
        assert d == datetime(2026, 3, 31) + timedelta(days=REZAGO_PUBLICACION_DIAS["trimestral"])

    def test_si_VAMOS_ATRASADOS_reintenta_pronto(self):
        """El caso real: 20-ago, Q2 ya publicado y el sistema con Q1 cargado. Sin esto se
        espera a noviembre y se pierde el trimestre entero — que es lo que pasó."""
        ahora = datetime(2026, 8, 20)
        atrasado = proximo_disparo("trimestral", ahora, 2160, ultimo_periodo_visto="2026-Q1")
        al_dia = proximo_disparo("trimestral", ahora, 2160, ultimo_periodo_visto="2026-Q2")
        assert atrasado == ahora + timedelta(days=REINTENTO_DIAS)
        assert al_dia.month == 11          # al día: al próximo cierre + rezago
        assert atrasado < al_dia

    def test_sin_saber_que_tenemos_no_se_inventa_un_atraso(self):
        """La función no puede adivinar si falta un período: sin el dato, no lo afirma."""
        d = proximo_disparo("trimestral", datetime(2026, 8, 20), 2160)
        assert d == datetime(2026, 11, 14)

    def test_periodo_esperado_es_el_ultimo_ya_publicable(self):
        from shared.operations.calendario import periodo_esperado
        assert periodo_esperado("trimestral", datetime(2026, 8, 20)) == "2026-Q2"
        assert periodo_esperado("trimestral", datetime(2026, 7, 10)) == "2026-Q1"

    def test_diciembre_no_desborda_de_año(self):
        d = proximo_disparo("trimestral", datetime(2026, 11, 5), 2160)
        assert d == datetime(2026, 12, 31) + timedelta(days=45)


class TestAnual:
    def test_apunta_al_cierre_del_año(self):
        d = proximo_disparo("anual", datetime(2026, 3, 1), 8760)
        assert d == datetime(2026, 12, 31) + timedelta(days=REZAGO_PUBLICACION_DIAS["anual"])

    def test_pasado_el_rezago_salta_al_año_siguiente(self):
        d = proximo_disparo("anual", datetime(2026, 4, 5), 8760)
        assert d.year in (2026, 2027)
        assert d > datetime(2026, 4, 5)


class TestSinAnclaje:
    def test_conserva_la_cadencia_relativa(self):
        """Un feed continuo (macro diario, caché tibia) se agenda bien por intervalo."""
        ahora = datetime(2026, 5, 5, 10, 0)
        assert proximo_disparo(None, ahora, 24) == ahora + timedelta(hours=24)
        assert proximo_disparo("mensual", ahora, 720) == ahora + timedelta(hours=720)


def test_las_operaciones_de_comercio_estan_ancladas():
    """Las dos que se desfasaron. Si alguien las vuelve a dejar relativas, esto lo dice."""
    import modules.trade_intel.operations  # noqa: F401 — registra las operaciones
    from shared.operations.service import OPERATIONS

    for name in ("dga-trade-sync", "dga-partners-sync"):
        assert OPERATIONS[name].anclaje == "trimestral", name


def test_el_scheduler_usa_el_ancla_al_reprogramar():
    """Contrato: si `run_due_schedules` vuelve a `now + interval`, la cadencia se desfasa
    otra vez sin que ningún test unitario lo note."""
    import inspect

    from shared.operations import service
    src = inspect.getsource(service.run_due_schedules)
    assert "proximo_disparo" in src
    assert "next_run_at=now + timedelta(hours=interval)" not in src


def test_la_operacion_de_comercio_sabe_que_periodo_tiene():
    """Sin esta lectura el scheduler no puede distinguir «al día» de «nos falta un período»,
    y una corrida que no encuentra dato pierde el trimestre entero."""
    import modules.trade_intel.operations  # noqa: F401
    from shared.operations.service import OPERATIONS

    for name in ("dga-trade-sync", "dga-partners-sync"):
        assert callable(OPERATIONS[name].periodo_actual), name


def test_la_lectura_del_periodo_nunca_rompe_la_agenda():
    """Si la tabla no existe o la consulta falla, se agenda igual (sin el atajo de reintento)."""
    from modules.trade_intel.operations import _periodo_cargado

    class _DbRoto:
        def query(self, *a, **k):
            raise RuntimeError("sin tabla")

    assert _periodo_cargado(_DbRoto()) is None
