"""El cableado de la proyección, en sus TRES puntos — y ninguno es `_evidence_state`.

`SubQuestion` y `VariableSignal` son clases distintas en paquetes distintos. Para que una
señal proyectada llegue a anclar una sub-pregunta, su metadato tiene que viajar por tres
lugares: el pasaje del registro, la `Evidence` que se construye de él, y el orquestador, que
es el único que puede ESCRIBIR en la `SubQuestion`.

`_evidence_state` clasifica —recibe un `Dict` y devuelve un `str`—, así que ahí va el ESTADO
pero no puede ir la meta: no tiene la `SubQuestion` a mano ni forma de escribirle. Confundir
las dos cosas manda a implementar algo imposible en ese punto.
"""
from shared.knowledge.ingest import registry_passages
from shared.registry.signals import (
    PROJECTED,
    REAL,
    AxisRegistry,
    DataRegistry,
    ProjectionMeta,
    VariableSignal,
)
from shared.research.models import Evidence, SubQuestion, _evidence_state
from shared.data.medida_de_pronostico import DLOG_PCT


def _meta():
    return ProjectionMeta(
        model_id="m.v1", target_series="s", horizon="2026-Q4", as_of="2026-08-31",
        revision=0, point=3.9, measure=DLOG_PCT, intervals=((0.80, 3.1, 4.7),),
        backtest_id="m.v1|s|2026-Q4",
        oos_error=0.6, error_metric="rmse", n_oos=16, n_oos_overlapping=False,
        interval_coverage=((0.80, 0.78, 16),))


# ── Punto 0 · la clasificación del estado (que SÍ va en `_evidence_state`) ───────────
def test_un_pasaje_de_registro_proyectado_se_clasifica_projected():
    r = {"kind": "registry", "meta": {"state": PROJECTED}}
    assert _evidence_state(r) == PROJECTED


def test_un_pasaje_de_registro_real_sigue_siendo_real():
    assert _evidence_state({"kind": "registry", "meta": {"state": REAL}}) == REAL


# ── Punto 1 · el pasaje del registro propaga la meta ────────────────────────────────
class _Reg:
    def __init__(self, axes):
        self.axes = axes


def test_el_pasaje_del_registro_lleva_la_proyeccion(monkeypatch):
    señal = VariableSignal(key="pib", label="PIB", state=PROJECTED, weight=1.0,
                           projection=_meta())
    eje = AxisRegistry(sector_key="macro", display_name="Macro", source="BCRD",
                       implemented=True, signals=(señal,))
    monkeypatch.setattr("shared.registry.service.build_data_registry",
                        lambda db: DataRegistry(generated_at="x", axes=(eje,)))
    pasajes = [p for p in registry_passages(db=object()) if p.meta.get("variable") == "pib"]
    assert pasajes, "el registro no produjo el pasaje de la variable"
    assert pasajes[0].meta["state"] == PROJECTED
    assert pasajes[0].meta.get("projection") is not None, (
        "el pasaje no lleva la meta de proyección: sin ella la evidencia no la puede tomar")


# ── Punto 2 · la Evidence la toma del pasaje ────────────────────────────────────────
def test_la_evidencia_toma_la_proyeccion_del_pasaje():
    e = Evidence.from_passage({
        "text": "t", "source": "s", "kind": "registry", "score": 1.0,
        "meta": {"state": PROJECTED, "projection": _meta()},
    })
    assert e.state == PROJECTED
    assert e.projection is not None


def test_una_evidencia_sin_proyeccion_no_inventa_el_campo():
    e = Evidence.from_passage({"text": "t", "source": "s", "kind": "registry", "score": 1.0,
                               "meta": {"state": REAL}})
    assert e.projection is None


# ── Punto 3 · el orquestador escribe en la SubQuestion ──────────────────────────────
def test_el_orquestador_marca_la_subpregunta_como_proyectada():
    from shared.research import orchestrator

    ev = Evidence(text="t", source="s", kind="registry", state=PROJECTED, score=1.0,
                  projection=_meta())
    sq = SubQuestion(text="¿cuánto crecerá?")
    orchestrator._aplicar_evidencia_proyectada(sq, [ev])
    assert sq.state == PROJECTED
    assert sq.projection is not None
    assert sq.anchored is True


def test_si_hay_evidencia_real_esa_manda_sobre_la_proyectada():
    """Un dato real siempre le gana a un pronóstico: la proyección es el ÚLTIMO recurso
    antes de declarar brecha, no una alternativa al dato."""
    from shared.research import orchestrator

    evs = [Evidence(text="t", source="s", kind="registry", state=PROJECTED, score=1.0,
                    projection=_meta()),
           Evidence(text="u", source="s", kind="registry", state=REAL, score=1.0)]
    sq = SubQuestion(text="x")
    orchestrator._aplicar_evidencia_proyectada(sq, evs)
    assert sq.state != PROJECTED
