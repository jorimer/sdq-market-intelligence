"""La serie del Registro Único de trámites.

Ninguno de estos tests toca la red: el catálogo se simula. Un test que llame al portal del
Estado en cada corrida de CI es exactamente lo que este repositorio ya pagó una vez.
"""
import datetime as dt

import pytest

from modules.social_dev import tramites_sync as sync
from modules.social_dev.tramites_sync import (MINIMO_PLAUSIBLE, TEMA_CON_TIEMPO, TEMA_PCT,
                                              TEMA_TOTAL, TEMAS, TramitesSyncError,
                                              periodo_de, run_tramites)
from shared.data.gobdo_tramites import Tiempo, Tramite


def _tramite(con_tiempo=False, sigla="INS"):
    t = Tiempo(valor=5, unidad="dia", laborables=True,
               texto_original="5 días laborables") if con_tiempo else None
    return Tramite(slug="x", nombre="Un trámite", institucion="Instituto",
                   institucion_sigla=sigla, area="Salud", canales=("en_linea",),
                   costo_declarado=True, visitas=1, actualizado=None, tiempo=t)


class TestElPeriodoEsElMESdeLaLectura:
    def test_formato_YYYY_MM(self):
        assert periodo_de(dt.date(2026, 8, 25)) == "2026-08"
        assert periodo_de(dt.date(2026, 12, 1)) == "2026-12"

    def test_el_AÑO_sigue_saliendo_de_los_primeros_cuatro(self):
        """El semáforo y la proyección del eje de leyes extraen el año así."""
        assert periodo_de(dt.date(2026, 8, 25))[:4] == "2026"

    def test_dos_lecturas_del_mismo_mes_comparten_periodo(self):
        """Y dos de meses distintos NO: es lo que deja ver si la cifra se mueve."""
        assert periodo_de(dt.date(2026, 8, 1)) == periodo_de(dt.date(2026, 8, 31))
        assert periodo_de(dt.date(2026, 8, 31)) != periodo_de(dt.date(2026, 9, 1))


class TestUnCatalogoQueNoSeLeyoNoPersisteCERO:
    def test_por_debajo_del_minimo_plausible_LEVANTA(self, monkeypatch):
        """Un cero persistido diría que el Estado dejó de publicar trámites."""
        monkeypatch.setattr(sync, "SessionLocal", lambda: pytest.fail("no debe tocar la base"))
        import shared.data.gobdo_tramites as g
        monkeypatch.setattr(g, "fetch", lambda **k: [_tramite() for _ in range(5)])
        with pytest.raises(TramitesSyncError, match="mínimo plausible"):
            run_tramites()

    def test_el_minimo_es_una_CONSTANTE_a_la_vista(self):
        assert MINIMO_PLAUSIBLE == 200

    def test_una_MUESTRA_no_persiste(self, monkeypatch):
        """Un porcentaje sobre 30 trámites no es el porcentaje del catálogo."""
        monkeypatch.setattr(sync, "SessionLocal", lambda: pytest.fail("no debe tocar la base"))
        import shared.data.gobdo_tramites as g
        monkeypatch.setattr(g, "fetch", lambda **k: [_tramite() for _ in range(30)])
        r = run_tramites(limite=30)
        assert r["persistido"] is False and r["motivo"] == "muestra"


class TestLoQuePersiste:
    def _correr(self, monkeypatch, tramites, force=False):
        import shared.data.gobdo_tramites as g
        monkeypatch.setattr(g, "fetch", lambda **k: tramites)
        escrito = {}

        class _DB:
            def query(self, *a, **k):
                return self

            def filter_by(self, **k):
                self._k = k
                return self

            def all(self):
                return []

            def first(self):
                return None

            def add(self, fila):
                escrito[fila.theme] = fila

            def commit(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(sync, "SessionLocal", lambda: _DB())
        return run_tramites(force=force), escrito

    def test_persiste_los_TRES_temas(self, monkeypatch):
        catalogo = [_tramite(True)] * 3 + [_tramite()] * 707
        r, escrito = self._correr(monkeypatch, catalogo)
        assert r["persistido"] is True
        assert set(escrito) == set(TEMAS)
        assert escrito[TEMA_TOTAL].value == 710.0
        assert escrito[TEMA_CON_TIEMPO].value == 3.0
        assert escrito[TEMA_PCT].value == 0.4

    def test_la_clave_del_PORCENTAJE_nombra_su_denominador(self):
        """Acá conviven dos poblaciones y `pct_con_tiempo` a secas se reatribuye."""
        assert "_sobre_los_catalogados" in TEMA_PCT

    def test_cada_tema_lleva_su_UNIDAD(self, monkeypatch):
        _, escrito = self._correr(monkeypatch, [_tramite(True)] + [_tramite()] * 709)
        assert escrito[TEMA_TOTAL].unit == "trámites"
        assert escrito[TEMA_PCT].unit == "% de los catalogados"

    def test_el_alcance_persistido_es_NACIONAL(self, monkeypatch):
        """Son conteos del Estado entero, no de una institución."""
        _, escrito = self._correr(monkeypatch, [_tramite(True)] + [_tramite()] * 709)
        assert all(f.disaggregation == "nacional" for f in escrito.values())
        assert all(f.entity_key is None or f.entity_key == "nacional"
                   for f in escrito.values())


def test_los_tres_temas_declaran_su_alcance_en_la_DOCTRINA():
    """Sin alcance declarado caen a `per_subject` y un consumidor leería «710 trámites»
    como el número de UNA entidad — la misma falla que publicó la pobreza de una región
    como cifra del país."""
    from shared.registry.builders import axis_variable_scopes
    scopes = axis_variable_scopes("social")
    for tema in TEMAS:
        assert scopes.get(tema) == "national", f"«{tema}» no declara alcance nacional"


def test_los_tres_temas_estan_en_el_REGISTRO_del_producto():
    """Un tema que se persiste y no se publica queda invisible para el eje de leyes."""
    from modules.social_dev.products import SocialDevProduct
    fuera = SocialDevProduct._FUERA_DEL_INDICE
    for tema in TEMAS:
        assert tema in fuera, f"«{tema}» se persiste y no llega al Data Registry"


class TestLaAGENDAmensual:
    """La operación se auto-agenda al desplegar. Que quede bien declarada importa: una
    cadencia mal puesta o un parámetro obligatorio la dejan fuera del scheduler sin avisar."""

    def _op(self):
        import modules.social_dev.operations  # noqa: F401 — registra al importar
        from shared.operations.service import OPERATIONS
        return OPERATIONS["tramites-registro-unico"]

    def test_la_operacion_esta_registrada(self):
        assert self._op().name == "tramites-registro-unico"

    def test_la_cadencia_es_MENSUAL(self):
        assert self._op().default_interval_hours == 730     # ~30 días

    def test_NO_lleva_anclaje_de_calendario(self):
        """El anclaje alinea con el calendario de publicación de una fuente —un trimestre
        que cierra y se publica 45 días después—. Este catálogo es un estado continuo: no
        tiene calendario, y un ancla trimestral lo desfasaría."""
        assert self._op().anclaje is None

    def test_se_AUTO_AGENDA_y_no_queda_bajo_demanda(self):
        """Con `needs_params` o cadencia <= 0 el scheduler la ignora en silencio."""
        from shared.operations.service import is_on_demand
        op = self._op()
        assert not op.needs_params
        assert is_on_demand(op) is False

    def test_la_descripcion_nombra_la_OBLIGACION_que_sigue(self):
        """Una operación que no dice para qué existe se apaga el día que estorbe."""
        d = self._op().description
        assert "167-21" in d and "142-2024" in d

    def test_la_tarea_del_worker_existe_con_su_nombre(self):
        from modules.social_dev.tasks import tramites_registro_unico_task
        assert tramites_registro_unico_task.name == "social.tramites_registro_unico"
