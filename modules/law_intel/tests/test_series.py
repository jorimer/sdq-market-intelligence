

def test_el_periodo_de_la_senal_manda_sobre_el_del_eje(monkeypatch):
    """No todas las variables de un eje se actualizan a la vez. La razón de ocupación
    femenina/masculina traía 2025 mientras el eje social iba por 2024, y el proveedor
    estampaba el del eje: servía el valor de un año con el rótulo de otro. Para un semáforo
    que juzga contra la meta de un año concreto, eso es la cifra equivocada."""
    from types import SimpleNamespace

    import modules.law_intel.series as mod
    from shared.registry.signals import REAL, VariableSignal

    eje = SimpleNamespace(
        sector_key="social_dev", period="2024",
        signals=(
            VariableSignal(key="al_dia", label="al día", state=REAL, value=1.0,
                           period="2025"),
            VariableSignal(key="sin_propio", label="sin propio", state=REAL, value=2.0),
        ))
    import shared.registry.service as svc
    monkeypatch.setattr(svc, "build_data_registry",
                        lambda db: SimpleNamespace(axes=(eje,)))
    leer = mod.proveedor_registro(None)
    assert leer("social_dev:al_dia") == [("2025", 1.0)]
    assert leer("social_dev:sin_propio") == [("2024", 2.0)]
