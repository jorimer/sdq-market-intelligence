"""Tests del orquestador v2: resolución, fusión de dato de motor, gate forward-looking."""
import pytest

import shared.research.decompose as decompose_mod
import shared.research.orchestrator as orch
from shared.registry.signals import GAP, REAL
from shared.research.data_pull import EnginePull
from shared.research.decompose import is_forward_looking
from shared.research.models import Evidence, SubQuestion
from shared.research.resolve import ResolvedEntity, detect_axes


# ─── resolución de eje ─────────────────────────────────────────────────
def test_detect_axes_banking_not_esg():
    # 'riesgo' NO debe activar esg (bug de substring 'esg' en 'riesgo').
    axes = detect_axes("perfil de riesgo de Banco Lafise y su liquidez")
    assert "banking" in axes
    assert "esg" not in axes


def test_is_forward_looking():
    assert is_forward_looking("qué tan expuesto está a un shock en los próximos 12 meses")
    assert is_forward_looking("proyección de la cartera a 2 años")
    assert not is_forward_looking("cuál es el rating actual del banco")


# ─── fusión de evidencia del motor ─────────────────────────────────────
def _pull(label="Banco Lafise", sk="banking"):
    return EnginePull(
        sector_key=sk, entity_label=label, period="2025-12", source="SIB · BCRD",
        payload={"scoring_result": {"overall_score": 78.0, "rating_tier": "A"}},
        evidence=[Evidence(text=f"{label}: rating A, score 78.0/100", source="SIB · BCRD",
                           kind="engine", state=REAL, score=100.0)],
        ok=True)


def test_merge_engine_evidence_makes_subquestion_real():
    sq = SubQuestion(text="perfil de riesgo de Banco Lafise", state=GAP, evidence=[])
    orch._merge_engine_evidence([sq], [_pull()])
    assert sq.state == REAL
    assert "banking" in sq.axes
    assert sq.evidence and sq.evidence[0].source == "SIB · BCRD"


def test_merge_single_subquestion_gets_all_live_pulls():
    # una sola sub-pregunta recibe el motor aunque no matchee por token.
    sq = SubQuestion(text="analiza esto", state=GAP, evidence=[])
    orch._merge_engine_evidence([sq], [_pull()])
    assert sq.state == REAL


def test_forward_gap_declared_when_future_and_engine_present():
    sq = SubQuestion(text="riesgo de Banco Lafise próximos 12 meses", state=REAL,
                     evidence=[_pull().evidence[0]])
    gaps = orch._forward_gaps("riesgo de Banco Lafise en los próximos 12 meses", [sq], [_pull()])
    assert len(gaps) == 1
    assert "prospectiva" in gaps[0].note.lower() or "futuro" in gaps[0].note.lower()


def test_no_forward_gap_when_no_engine_data():
    # sin dato de motor, la brecha la maneja el flujo de retrieval, no _forward_gaps.
    assert orch._forward_gaps("proyección a 12 meses", [], []) == []


# ─── narrativa: degrada a None sin motores ─────────────────────────────
@pytest.mark.asyncio
async def test_narrate_returns_none_without_pulls():
    from shared.research.narrate import narrate_answer
    assert await narrate_answer("una pregunta", []) is None


# ─── síntesis cross-dominio (tema-primero) ─────────────────────────────
def test_context_axes_banking_pulls_macro_monetary():
    from shared.research.resolve import context_axes
    ctx = context_axes("riesgo de liquidez del banco", ["banking"])
    assert "monetary_policy" in ctx and "macro" in ctx


def test_efficiency_chart_label_matches_section_title():
    """Regresión: el rótulo del gráfico para el sub-componente 'eficiencia' debe ser IDÉNTICO
    al encabezado de sección 'eficiencia_rentabilidad' del mismo archivo (una sola fuente,
    no una etiqueta truncada). Evita reincidir en el desalineamiento gráfico↔texto."""
    import shared.research.deep_report as dr
    payload = {"scoring_result": {"sub_components": {
        "solidez": 70.0, "calidad": 65.0, "eficiencia": 58.0,
        "liquidez": 80.0, "diversificacion": 60.0}}}
    charts = dr._charts_from_payload(payload)
    sub_chart = next(c for c in charts if "Sub-componentes" in c["title"])
    labels = [label for label, _ in sub_chart["items"]]
    assert dr.SECTION_TITLES["eficiencia_rentabilidad"] in labels
    assert "Eficiencia" not in labels  # ya no aparece la etiqueta truncada


@pytest.mark.asyncio
async def test_synthesis_integrates_multiple_engines(monkeypatch):
    import shared.research.deep_report as dr

    class T:
        entities = [ResolvedEntity("banking", "id1", "Banco Lafise")]
        axes: list = []
        context = ["monetary_policy", "macro"]

    def fake_pull_entity(db, e):
        return _pull("Banco Lafise", "banking")

    def fake_pull_axis(db, sk):
        return EnginePull(sector_key=sk, entity_label=f"Sistema {sk}", period="2026-03",
                          source=f"BCRD·{sk}", payload={"index": {"score": 55.0}},
                          evidence=[Evidence(text=f"{sk} sistema: score 55.0", source=f"BCRD·{sk}",
                                             kind="engine", state=REAL, score=90.0)], ok=True)

    import shared.research.data_pull as dp
    import shared.research.narrate as nar
    monkeypatch.setattr(dp, "pull_entity", fake_pull_entity)
    monkeypatch.setattr(dp, "pull_axis", fake_pull_axis)

    async def fake_synth(question, live, *, forward_gaps=None, reasons=None, lang="es"):
        # recibe los 3 motores (entidad + 2 de contexto) → integra
        assert len(live) == 3
        return "## Tesis\nLafise es vulnerable al fondeo.\n## Mecanismos de transmisión\n..."

    monkeypatch.setattr(nar, "narrate_synthesis", fake_synth)

    report = await dr.build_synthesis_report("riesgo de liquidez de Banco Lafise próximos 12 meses",
                                             db=object(), targets=T(), forward_gaps=[])
    assert report is not None
    assert report.ordered_keys[0] == "dictamen"
    assert "evidencia" in report.ordered_keys
    # las fuentes de los 3 motores aparecen (síntesis multi-dominio).
    assert any("monetary_policy" in s or "BCRD" in s for s in report.sources)


# ─── end-to-end (sin DB, sin Cerebro): pull inyectado vía monkeypatch ──
@pytest.mark.asyncio
async def test_answer_uses_engine_evidence_and_declares_forward_gap(monkeypatch):
    # Resolver → una entidad bancaria; pull → dato real; retrieval → vacío.
    monkeypatch.setattr(orch, "resolve_targets",
                        lambda q, db: type("T", (), {"entities": [
                            ResolvedEntity("banking", "id1", "Banco Lafise")], "axes": []})())
    monkeypatch.setattr(orch, "pull_entity", lambda db, e: _pull())
    monkeypatch.setattr(decompose_mod, "retrieve",
                        lambda *a, **k: [])  # sin metodología
    ans = await orch.answer_question(
        "¿Cuál es el perfil de riesgo de Banco Lafise y su exposición a un shock de "
        "liquidez en los próximos 12 meses?", db=None, narrate=False)
    # La sub-pregunta se ancló al dato REAL del motor.
    assert any(sq.state == REAL for sq in ans.sub_questions)
    assert ans.coverage_real > 0
    # La parte prospectiva se declaró como brecha, no se rellenó.
    assert any("prospectiva" in g.note.lower() for g in ans.gaps)
    # La fuente del motor aparece.
    assert "SIB · BCRD" in ans.sources


# ─── latencia (roadmap #4): cosecha única + router acotado ─────────────
@pytest.mark.asyncio
async def test_synthesis_uses_preharvested_pulls_without_repulling(monkeypatch):
    """Si el orquestador ya cosechó, build_synthesis_report NO re-cosecha (el doble
    pull_entity era el desperdicio: cada snapshot son varios queries)."""
    import shared.research.data_pull as dp
    import shared.research.deep_report as dr
    import shared.research.narrate as nar

    def _boom(*a, **k):
        raise AssertionError("no debe re-cosechar si recibe pulls")
    monkeypatch.setattr(dp, "pull_entity", _boom)
    monkeypatch.setattr(dp, "pull_axis", _boom)

    async def fake_synth(question, live, *, forward_gaps=None, reasons=None, lang="es"):
        assert len(live) == 1
        return "## Tesis\nok"
    monkeypatch.setattr(nar, "narrate_synthesis", fake_synth)

    class T:
        entities = [ResolvedEntity("banking", "id1", "Banco Lafise")]
        axes: list = []
        context: list = []

    report = await dr.build_synthesis_report("pregunta", db=object(), targets=T(),
                                             forward_gaps=[], pulls=[_pull()])
    assert report is not None and report.ordered_keys[0] == "dictamen"


@pytest.mark.asyncio
async def test_route_bounded_times_out_to_curated(monkeypatch):
    """Un router colgado no cuelga el research: al vencer el techo, lista vacía
    (el contexto curado ya sembrado por resolve queda como piso)."""
    import asyncio

    async def hang(question, db):
        await asyncio.sleep(60)
    monkeypatch.setattr(orch, "route_domains", hang)
    monkeypatch.setattr(orch, "_ROUTE_TIMEOUT_S", 0.05)
    assert await orch._route_bounded("q", None) == []


@pytest.mark.asyncio
async def test_answer_parallel_flow_end_to_end(monkeypatch):
    """Flujo con narrate+db: router y cosecha en paralelo, merge del router, y la síntesis
    recibe la cosecha (entidad + eje curado + eje agregado por el router) sin re-cosechar."""
    from shared.research.domain_router import RoutedDomain

    class T:
        entities = [ResolvedEntity("banking", "id1", "Banco Lafise")]
        axes: list = []
        context = ["macro"]          # curado
        reasons: dict = {}
    monkeypatch.setattr(orch, "resolve_targets", lambda q, db: T())

    async def fake_route(question, db):
        return [RoutedDomain("monetary_policy", "context", "canal de fondeo")]
    monkeypatch.setattr(orch, "route_domains", fake_route)

    pulled_axes: list = []
    monkeypatch.setattr(orch, "pull_entity", lambda db, e: _pull())
    monkeypatch.setattr(orch, "pull_axis",
                        lambda db, ax: (pulled_axes.append(ax) or _pull(f"Sistema {ax}", ax)))
    monkeypatch.setattr(decompose_mod, "retrieve", lambda *a, **k: [])

    seen = {}

    async def fake_build(question, db, targets, forward, pulls=None):
        seen["pulls"] = pulls
        return None  # → ensamblado liviano (no interesa la narrativa aquí)
    monkeypatch.setattr(orch, "build_synthesis_report", fake_build)
    monkeypatch.setattr(orch, "narrate_answer",
                        lambda *a, **k: _none_coro())

    ans = await orch.answer_question("riesgo de Banco Lafise", db=object(), narrate=True)
    assert ans is not None
    # cosechó el eje curado Y el que agregó el router — una sola vez cada uno
    assert pulled_axes == ["macro", "monetary_policy"]
    # la síntesis recibió la cosecha completa (1 entidad + 2 ejes)
    assert seen["pulls"] is not None and len(seen["pulls"]) == 3


async def _none_coro(*a, **k):
    return None


# ─── hallazgos del piloto Fase 2 (2026-07-12) ─────────────────────────
def test_gentilicio_is_not_a_distinctive_entity_token():
    """'dominicano/a' no distingue una entidad: "mercado asegurador dominicano" resolvía
    'Banco Popular DOMINICANO' y 'Qik ... DOMINICANO' (ruido del piloto). El gentilicio va
    a stopwords; los nombres reales siguen distinguiéndose por sus otros tokens."""
    from shared.research.resolve import _distinctive_tokens
    assert "dominicano" not in _distinctive_tokens("Banco Popular Dominicano")
    assert "popular" in _distinctive_tokens("Banco Popular Dominicano")
    assert "dominicano" not in _distinctive_tokens("Qik Banco Digital Dominicano")
    assert "digital" in _distinctive_tokens("Qik Banco Digital Dominicano")
    # 'nacional' NO va a stopwords: es el nombre distintivo de la Asociación La Nacional.
    assert "nacional" in _distinctive_tokens("Asociación La Nacional de Ahorros y Préstamos")


@pytest.mark.asyncio
async def test_axis_pulls_feed_honesty_ledger_and_forward_gap(monkeypatch):
    """Pregunta de SISTEMA (sin entidad) con cosecha de eje viva: el ledger debe acreditar
    la evidencia (cobertura real > 0, no '0%' con el dictamen lleno de dato) y la brecha
    prospectiva DEBE declararse — hallazgo del piloto: 'próximos 2-3 años' no se declaraba
    porque _forward_gaps solo veía pulls de entidad."""
    class T:
        entities: list = []
        axes = ["tourism"]
        context: list = []
        reasons: dict = {}
    monkeypatch.setattr(orch, "resolve_targets", lambda q, db: T())

    async def no_route(question, db):
        return []
    monkeypatch.setattr(orch, "route_domains", no_route)
    monkeypatch.setattr(orch, "pull_axis",
                        lambda db, ax: _pull(f"SDQ Tourism ({ax})", ax))
    monkeypatch.setattr(decompose_mod, "retrieve", lambda *a, **k: [])

    async def no_deep(question, db, targets, forward, pulls=None):
        return None
    monkeypatch.setattr(orch, "build_synthesis_report", no_deep)

    async def no_narr(*a, **k):
        return None
    monkeypatch.setattr(orch, "narrate_answer", no_narr)

    ans = await orch.answer_question(
        "¿Atractivo de un proyecto hotelero en los próximos 2-3 años?",
        db=object(), narrate=True)
    assert ans.coverage_real > 0, "la cosecha de eje viva debe acreditar el ledger"
    assert any("prospectiva" in g.note.lower() for g in ans.gaps), \
        "la brecha prospectiva debe declararse también en preguntas de sistema"


def test_detect_axes_mercado_asegurador():
    """Hallazgo del piloto: "mercado asegurador" no detectaba insurance ("aseguradora" es
    más largo que el texto y "seguro" no es substring de "asegurador") → el eje primario
    faltaba, el ledger quedaba en brecha y el gate caía a scoping para una pregunta
    respondible. El stem 'asegurador' cubre asegurador/aseguradora/aseguradoras."""
    axes = detect_axes("¿Conviene entrar al mercado asegurador dominicano?")
    assert "insurance" in axes
    # la forma femenina/plural sigue detectando
    assert "insurance" in detect_axes("solvencia de las aseguradoras dominicanas")
    assert "insurance" in detect_axes("primas de seguros en el mercado local")
