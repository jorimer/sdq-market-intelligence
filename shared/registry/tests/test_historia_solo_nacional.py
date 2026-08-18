"""La SERIE del registro: qué la puede llevar y qué pasa cuando falta.

La historia se agregó porque sin ella el eje de evaluación de leyes solo sabía decir
NIVEL. Con una sola observación el semáforo se niega —bien— a emitir tendencia, así que
«retrocede» y «no alcanzará» no existían para ningún indicador, aunque el dato estuviera
en la misma tabla que ya leíamos. La ley pide juzgar avance.

El riesgo que introduce es peor que el que resuelve, si no se acota: un punto suelto de
alcance equivocado se compara contra una meta y produce una distancia errada; una SERIE de
alcance equivocado afirma una DIRECCIÓN —«mejora», «retrocede»— y el consumidor que la lee
no tiene forma de sospechar que es una región y no el país.
"""
from shared.registry.signals import NATIONAL, PER_SUBJECT, REAL, VariableSignal


def _sig(**kw):
    base = dict(key="women_senate", label="Mujeres en el Senado", state=REAL)
    return VariableSignal(**{**base, **kw})


def test_por_defecto_una_senal_no_tiene_historia():
    """Vacía NO significa «no existe la serie»: significa que este eje publica un punto.
    La diferencia importa porque el consumidor que la lee vacía no debe concluir que el
    Estado no publica el dato."""
    assert _sig().history == ()


def test_la_ultima_observacion_de_la_historia_ES_el_valor():
    """Son la misma verdad dicha dos veces. El día que difieran gana la que el consumidor
    mire primero, y no hay forma de saber cuál es."""
    s = _sig(scope=NATIONAL, value=12.5, period="2024",
             history=(("2020", 12.5), ("2024", 12.5)))
    assert s.history[-1] == (s.period, s.value)


class TestUnaSerieDeAlcanceEquivocadoAfirmaUnaDIRECCION:
    def test_el_consumidor_no_recibe_la_historia_de_una_senal_por_sujeto(self, monkeypatch):
        """La red que de verdad protege está en el consumidor, no en el constructor: aunque
        un eje futuro adjunte historia a una señal por-sujeto por descuido, el proveedor del
        eje de leyes la rechaza entera —señal y serie— antes de que llegue al semáforo."""
        from types import SimpleNamespace

        import modules.law_intel.series as mod
        import shared.registry.service as svc

        eje = SimpleNamespace(sector_key="social_dev", period="2024", signals=(
            _sig(key="pobreza_regional", scope=PER_SUBJECT, value=2.0, period="2024",
                 history=(("2010", 8.0), ("2024", 2.0))),
            _sig(key="women_senate", scope=NATIONAL, value=12.5, period="2024",
                 history=(("2010", 9.4), ("2020", 12.5), ("2024", 12.5))),
        ))
        monkeypatch.setattr(svc, "build_data_registry",
                            lambda db: SimpleNamespace(axes=(eje,)))
        leer = mod.proveedor_registro(None)
        assert leer("social_dev:pobreza_regional") == []
        assert leer("social_dev:women_senate") == [
            ("2010", 9.4), ("2020", 12.5), ("2024", 12.5)]

    def test_sin_historia_el_proveedor_sigue_sirviendo_el_punto(self, monkeypatch):
        """La historia es un añadido, no un requisito: las variables que vienen del panel
        del IDM se arman con un solo período y tienen que seguir midiendo nivel."""
        from types import SimpleNamespace

        import modules.law_intel.series as mod
        import shared.registry.service as svc

        eje = SimpleNamespace(sector_key="social_dev", period="2024", signals=(
            _sig(key="life_expectancy", scope=NATIONAL, value=73.868),))
        monkeypatch.setattr(svc, "build_data_registry",
                            lambda db: SimpleNamespace(axes=(eje,)))
        assert mod.proveedor_registro(None)("social_dev:life_expectancy") == [
            ("2024", 73.868)]

    def test_el_alcance_por_sujeto_sigue_siendo_el_default(self):
        """Un eje nuevo que no declara alcance NO debe caer en «nacional» por omisión."""
        assert _sig().scope == PER_SUBJECT
