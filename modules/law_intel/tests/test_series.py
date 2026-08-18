

def test_el_periodo_de_la_senal_manda_sobre_el_del_eje(monkeypatch):
    """No todas las variables de un eje se actualizan a la vez. La razón de ocupación
    femenina/masculina traía 2025 mientras el eje social iba por 2024, y el proveedor
    estampaba el del eje: servía el valor de un año con el rótulo de otro. Para un semáforo
    que juzga contra la meta de un año concreto, eso es la cifra equivocada."""
    from types import SimpleNamespace

    import modules.law_intel.series as mod
    from shared.registry.signals import NATIONAL, REAL, VariableSignal

    eje = SimpleNamespace(
        sector_key="social_dev", period="2024",
        signals=(
            VariableSignal(key="al_dia", label="al día", state=REAL, value=1.0,
                           period="2025", scope=NATIONAL),
            VariableSignal(key="sin_propio", label="sin propio", state=REAL, value=2.0,
                           scope=NATIONAL),
        ))
    import shared.registry.service as svc
    monkeypatch.setattr(svc, "build_data_registry",
                        lambda db: SimpleNamespace(axes=(eje,)))
    leer = mod.proveedor_registro(None)
    assert leer("social_dev:al_dia") == [("2025", 1.0)]
    assert leer("social_dev:sin_propio") == [("2024", 2.0)]


def test_el_proveedor_RECHAZA_una_senal_que_no_sea_nacional(monkeypatch):
    """Todo indicador de una ley nacional fija una meta para el PAÍS. Una variable medida
    por sujeto publica el valor de UN sujeto —el registro sirve el de la primera región—,
    y contrastarlo contra la meta del país es comparar cosas distintas.

    Pasó de verdad y llegó a producción: la pobreza extrema de `cibao_norte` (2,0%) se
    publicó como cifra nacional, y con ella «la meta de 2030, alcanzada seis años antes».

    Se rechaza en vez de promediar las diez regiones: sin ponderar por población, ese
    promedio tampoco es la cifra del país — sería inventar el dato que falta.
    """
    from types import SimpleNamespace

    import modules.law_intel.series as mod
    import shared.registry.service as svc
    from shared.registry.signals import NATIONAL, PER_SUBJECT, REAL, VariableSignal

    eje = SimpleNamespace(sector_key="social_dev", period="2024", signals=(
        VariableSignal(key="pais", label="país", state=REAL, value=1.0, scope=NATIONAL),
        VariableSignal(key="por_region", label="región", state=REAL, value=2.0,
                       scope=PER_SUBJECT),
    ))
    monkeypatch.setattr(svc, "build_data_registry", lambda db: SimpleNamespace(axes=(eje,)))
    leer = mod.proveedor_registro(None)
    assert leer("social_dev:pais") == [("2024", 1.0)]
    assert leer("social_dev:por_region") == [], "una variable por sujeto no mide al país"


def test_hay_UNA_sola_implementacion_del_proveedor_de_series():
    """Había dos: la de `series.py` y una copia dentro del router. La copia se quedó sin los
    dos guards que la otra fue ganando —el rechazo de señales que no son de alcance
    NACIONAL y la preferencia del período de la señal sobre el del eje— y era ÉSA la que
    corría, porque es la que alimenta la ruta que decide las promociones.

    Es el patrón que este repo ya sufrió cinco veces: un guard presente en un motor y
    ausente en el gemelo. La lección escrita no alcanzó ninguna de las veces; lo que
    funciona es leer el código y exigir la regla.
    """
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[1]
    culpables = []
    for archivo in raiz.rglob("*.py"):
        if archivo.name == "series.py" or "/tests/" in str(archivo):
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            # Una función que construye un índice desde `build_data_registry` y devuelve un
            # lector por código de serie es, por definición, otro proveedor.
            if isinstance(n, ast.FunctionDef) and "proveedor" in n.name.lower():
                cuerpo = ast.dump(n)
                if "build_data_registry" in cuerpo:
                    culpables.append(f"{archivo.name}:{n.name}")
    assert not culpables, (
        f"estas funciones duplican el proveedor de series: {culpables}. Usá "
        "`modules.law_intel.series.proveedor_registro` — una copia hereda los guards del "
        "día que se copió y no los que vengan después."
    )
