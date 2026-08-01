"""La ingesta de planes del cliente y la sección «El plan bajo el instrumento».

Lo que estos tests protegen: (a) el RECIBO — una meta sin texto literal no se guarda, y
releer un documento jamás toca lo que un humano ya adoptó o descartó; (b) el PORTÓN —
el lector propone y solo la adopción crea decisiones, por el mismo camino y con la misma
aritmética de factibilidad que el alta manual; (c) la MEDIDA EXTERNA — registrable con
su fuente, nunca dentro de la aritmética muestral; (d) la SECCIÓN — sus categorías de
brecha son mecánicas y desaparece del documento cuando no hay plan que narrar.
"""
import json
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.testclient import TestClient

import asyncio

from modules.brand_intel import report as rpt
from modules.brand_intel import report_docs
from modules.brand_intel import service as svc
from modules.brand_intel.tests.test_report_narrative import _payload
from modules.brand_intel.api.router import router
from modules.brand_intel.ingest import plans as pl
from modules.brand_intel.models.models import (
    BrandDecision,
    BrandPlanDocument,
    BrandPlanGoal,
)
from shared.auth.dependencies import get_current_user, get_db
from shared.auth.models import UserRole


class _Block:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, payload: Any, stop_reason: str = "end_turn"):
        self.stop_reason = stop_reason
        body = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = [_Block(body)]


class _FakeClient:
    def __init__(self, *responses: _Response):
        self._queued = list(responses)
        self.prompts: List[str] = []
        self.messages = self

    def create(self, **kwargs: Any) -> _Response:
        self.prompts.append(kwargs["messages"][0]["content"][0]["text"])
        return self._queued.pop(0)


def _goal_row(**over: Any) -> Dict[str, Any]:
    base = {
        "claim": "Recuperar la penetración de 4 semanas de 43% a 51%.",
        "page_number": 11, "kind": "meta", "metric_code": "reach_1m",
        "segment": "total", "target_from": 43.0, "target_to": 51.0,
        "expected_move": None, "owner_declared": "Agencia",
        "measure_source": "tracker", "confident": True,
    }
    base.update(over)
    return base


def _reading_payload(goals: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"title": "Plan Conecta", "source_org": "Agencia Demo", "goals": goals}


def _client(db, role=UserRole.admin, org=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/brand-intel")

    class _U:
        def __init__(self, r, o):
            self.role = r
            self.organization_id = o
            self.email = "analista@sdq.test"

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role, org)
    return TestClient(app)


# ─────────────────────────── lector ───────────────────────────


def test_reads_goals_with_their_receipt():
    fake = _FakeClient(_Response(_reading_payload([_goal_row()])))
    reading = pl.read_plan(["Página con texto."], client=fake)
    assert reading.title == "Plan Conecta"
    assert len(reading.goals) == 1
    g = reading.goals[0]
    assert g.claim.startswith("Recuperar la penetración")
    assert g.page_number == 11
    assert g.metric_code == "reach_1m"


def test_document_without_text_layer_yields_empty_reading_not_error():
    reading = pl.read_plan(["", "   "], client=_FakeClient())
    assert reading.goals == []


def test_short_claims_and_duplicates_are_dropped():
    fake = _FakeClient(_Response(_reading_payload([
        _goal_row(), _goal_row(),                 # duplicada
        _goal_row(claim="corta"),                 # sin recibo citable
    ])))
    reading = pl.read_plan(["Página."], client=fake)
    assert len(reading.goals) == 1


def test_numbers_are_kept_only_if_parseable():
    fake = _FakeClient(_Response(_reading_payload([
        _goal_row(target_from="no-numero", expected_move=None),
    ])))
    g = pl.read_plan(["Página."], client=fake).goals[0]
    assert g.target_from is None


def test_html_to_text_strips_scripts_and_tags():
    html = (b"<html><head><style>.x{}</style><script>alert(1)</script></head>"
            b"<body><h1>Meta: subir 8 pp</h1><p>Detalle</p></body></html>")
    text = pl.html_to_text(html)
    assert "Meta: subir 8 pp" in text
    assert "alert" not in text and "<h1>" not in text


def test_reread_replaces_proposals_but_never_touches_adopted(db, engagement):
    plan = BrandPlanDocument(engagement_id=engagement.id, filename="plan.pdf")
    db.add(plan)
    db.flush()
    adopted = BrandPlanGoal(
        engagement_id=engagement.id, plan_document_id=plan.id,
        claim="Meta ya adoptada por el revisor.", status="adoptada",
        adopted_decision_id="dec-1")
    stale = BrandPlanGoal(
        engagement_id=engagement.id, plan_document_id=plan.id,
        claim="Propuesta vieja que la relectura reemplaza.", status="propuesta")
    db.add_all([adopted, stale])
    db.flush()

    reading = pl.PlanReading(title="", source_org="", goals=[
        pl.PlanGoal(claim="Propuesta nueva tras releer el documento.",
                    page_number=2, kind="meta", metric_code="reach_1m",
                    segment="total", target_from=None, target_to=None,
                    expected_move=8.0, owner_declared="", measure_source="tracker",
                    confident=True),
    ])
    summary = pl.store_plan_goals(db, engagement.id, plan.id, reading)
    db.flush()

    claims = {g.claim: g.status for g in db.query(BrandPlanGoal).all()}
    assert "Meta ya adoptada por el revisor." in claims          # intocable
    assert "Propuesta vieja que la relectura reemplaza." not in claims
    assert claims["Propuesta nueva tras releer el documento."] == "propuesta"
    assert summary["guardadas"] == 1
    assert summary["mapeadas_al_tracker"] == 1


# ─────────────────────── medida externa en el ledger ───────────────────────


def test_external_decision_is_recorded_outside_sampling_arithmetic(db, engagement):
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/decisions",
        json={"title": "Subir engagement digital de 56% a 75%",
              "external_measure": "analytics de plataformas sociales",
              "baseline_wave_code": "w3"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "unevaluable"
    assert "el tracker no la evalúa" in body["feasibility"]["reason"]

    out = svc.evaluate_decisions(db, engagement.id)
    row = out["decisions"][0]
    assert row["external_measure"] == "analytics de plataformas sociales"
    assert row["status"] == "unevaluable"
    assert row["detectable_threshold"] is None


def test_decision_requires_exactly_one_measure(db, engagement):
    c = _client(db)
    neither = c.post("/api/v1/brand-intel/engagements/demo/decisions",
                     json={"title": "Sin medida", "baseline_wave_code": "w3"})
    both = c.post("/api/v1/brand-intel/engagements/demo/decisions",
                  json={"title": "Con dos medidas", "metric_code": "reach_7d",
                        "external_measure": "analytics", "baseline_wave_code": "w3"})
    assert neither.status_code == 422
    assert both.status_code == 422


# ─────────────────────────── API de planes ───────────────────────────


def _upload(db, monkeypatch, goals: List[Dict[str, Any]]):
    """Sube un plan con el lector doblado — la API real, el LLM no."""
    reading = pl.PlanReading(
        title="Plan Conecta", source_org="Agencia Demo",
        goals=[g for g in (pl._parse(r) for r in goals) if g is not None])
    monkeypatch.setattr(pl, "read_plan", lambda *a, **k: reading)
    c = _client(db)
    r = c.post("/api/v1/brand-intel/engagements/demo/plans",
               files={"file": ("plan.html", b"<html><body>Plan</body></html>",
                               "text/html")})
    assert r.status_code == 201, r.text
    return c, r.json()


def test_upload_proposes_goals_without_touching_the_ledger(db, engagement, monkeypatch):
    c, body = _upload(db, monkeypatch, [_goal_row()])
    assert body["goals"]["propuestas"] == 1
    assert body["lectura"]["mapeadas_al_tracker"] == 1
    # El portón: nada llegó al ledger todavía.
    assert db.query(BrandDecision).count() == 0


def test_upload_rejects_unsupported_formats(db, engagement):
    r = _client(db).post(
        "/api/v1/brand-intel/engagements/demo/plans",
        files={"file": ("plan.docx", b"PK", "application/octet-stream")})
    assert r.status_code == 400


def test_adoption_creates_the_decision_through_the_same_gate(db, engagement, monkeypatch):
    c, body = _upload(db, monkeypatch, [_goal_row(expected_move=10.0)])
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]

    r = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
               f"/goals/{goal['id']}/adopt",
               json={"baseline_wave_code": "w2", "target_wave_code": "w3",
                     "brand_slug": "focal"})
    assert r.status_code == 201 or r.status_code == 200, r.text
    out = r.json()
    assert out["goal"]["status"] == "adoptada"
    dec = db.query(BrandDecision).one()
    assert dec.metric_code == "reach_1m"
    assert dec.success_threshold == 10.0            # default de la meta extraída
    assert "Adoptada del plan" in (dec.rationale or "")
    # Adoptar dos veces la misma meta es un conflicto, no un duplicado silencioso.
    r2 = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
                f"/goals/{goal['id']}/adopt", json={"baseline_wave_code": "w2"})
    assert r2.status_code == 409


def test_adopting_an_external_goal_records_its_source(db, engagement, monkeypatch):
    c, body = _upload(db, monkeypatch, [_goal_row(
        claim="Pasar de 44% a 30% de no-seguidores en redes en 6 meses.",
        metric_code="", measure_source="analytics de plataformas sociales")])
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]
    r = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
               f"/goals/{goal['id']}/adopt", json={"baseline_wave_code": "w2"})
    assert r.status_code in (200, 201), r.text
    dec = db.query(BrandDecision).one()
    assert dec.metric_code is None
    assert dec.external_measure == "analytics de plataformas sociales"


def test_adopting_a_mapped_goal_as_external_wins_over_the_inherited_metric(
        db, engagement, monkeypatch):
    """El payload exacto del drawer en modo «Fuente externa» (metric_code null +
    external_measure) sobre una meta que el lector SÍ mapeó al tracker: la fuente
    externa manda y la métrica heredada no puede reventar el XOR (regresión)."""
    c, body = _upload(db, monkeypatch, [_goal_row()])          # mapeada a reach_1m
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]
    r = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
               f"/goals/{goal['id']}/adopt",
               json={"metric_code": None,
                     "external_measure": "dato transaccional del operador",
                     "segment": "total", "brand_slug": None,
                     "baseline_wave_code": "w2"})
    assert r.status_code in (200, 201), r.text
    dec = db.query(BrandDecision).one()
    assert dec.metric_code is None
    assert dec.external_measure == "dato transaccional del operador"


def test_the_reader_marker_tracker_never_becomes_an_external_source(
        db, engagement, monkeypatch):
    """Meta con measure_source='tracker' pero métrica fuera del diccionario (anulada al
    guardar): adoptarla sin medida explícita debe fallar el XOR con 422, no crear una
    decisión cuya fuente externa es literalmente 'tracker'."""
    c, body = _upload(db, monkeypatch, [_goal_row(metric_code="metrica_inexistente",
                                                  measure_source="tracker")])
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]
    assert goal["metric_code"] is None                        # anulada por el store
    r = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
               f"/goals/{goal['id']}/adopt", json={"baseline_wave_code": "w2"})
    assert r.status_code == 422
    # El 422 no consumió la meta: sigue propuesta y adoptable con medida explícita.
    goal2 = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]
    assert goal2["status"] == "propuesta"


def test_reuploading_the_same_file_reconciles_instead_of_duplicating(
        db, engagement, monkeypatch):
    """Subir dos veces el mismo archivo relee sobre el MISMO plan: las propuestas se
    reemplazan, lo adoptado sobrevive, y no aparecen documentos duplicados."""
    c, body = _upload(db, monkeypatch, [_goal_row()])
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]
    c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
           f"/goals/{goal['id']}/adopt", json={"baseline_wave_code": "w2"})

    _c2, body2 = _upload(db, monkeypatch, [_goal_row(), _goal_row(
        claim="Meta nueva que apareció en la versión corregida del plan.")])
    assert body2["id"] == plan_id                             # mismo documento
    plans = c.get("/api/v1/brand-intel/engagements/demo/plans").json()
    assert len(plans) == 1
    metas = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"]
    estados = sorted(m["status"] for m in metas)
    # La adoptada sobrevive; la relectura solo repone propuestas.
    assert estados.count("adoptada") == 1
    assert db.query(BrandDecision).count() == 1


def test_ai_narratives_narrate_the_plan_alone_without_explanations(monkeypatch):
    """Sin conclusiones del proveedor pero con plan: la sección del plan narra sola."""
    import shared.narrative.claude_engine as ce
    from shared.narrative.claude_engine import NarrativeResult

    calls = []

    async def _fake_generate(context, template, mode, axis, audience):
        calls.append(template)
        return NarrativeResult(text="narrativa del plan", model_used="test")

    monkeypatch.setattr(ce.narrative_engine, "generate", _fake_generate)
    p = _payload()
    p["sections"]["plan"] = {
        "available": True, "documents": [], "goals": [],
        "rows": [{"decision_id": "d1", "title": "Meta", "metric_code": "reach_1m",
                  "medida": "Consumo último mes", "segment": "total", "owner": None,
                  "success_threshold": 8.0, "baseline_value": 43.0,
                  "detectable_threshold": 7.9, "feasible": True,
                  "gap": "evaluable", "needs": "Nada: la próxima ola la evalúa.",
                  "reason": "Evaluable.", "external_measure": None,
                  "rationale": None}],
        "note": "1 de 1.",
    }
    out = asyncio.run(rpt.ai_narratives(p))
    assert out == {"plan": "narrativa del plan"}
    assert calls == ["brand_plan_readiness"]


def test_document_text_is_clipped_to_column_sizes_at_the_write_boundary(
        db, engagement, monkeypatch):
    """El caso real que tumbó la primera adopción en prod: un 'responsable' de 122
    caracteres contra owner VARCHAR(120). SQLite no valida largos y Postgres sí — el
    recorte vive en la frontera de escritura, así que se prueba sobre lo GUARDADO."""
    owner_122 = ("Todos · Recomendación especial para: KFC RD (ya tiene cultura "
                 "multi-plataforma) o Little Caesars (ya tiene el brand voice)")
    assert len(owner_122) > 120
    c, body = _upload(db, monkeypatch, [_goal_row(
        metric_code="", measure_source="analytics de plataformas sociales",
        owner_declared=owner_122, segment="S" * 80)])
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]
    assert len(goal["segment"]) <= 60                         # recortado al guardar

    r = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
               f"/goals/{goal['id']}/adopt", json={"baseline_wave_code": "w2"})
    assert r.status_code in (200, 201), r.text
    dec = db.query(BrandDecision).one()
    assert dec.owner is not None and len(dec.owner) <= 120
    assert len(dec.segment) <= 60


def test_dismiss_requires_a_note_and_marks_the_plan_reviewed(db, engagement, monkeypatch):
    c, body = _upload(db, monkeypatch, [_goal_row()])
    plan_id = body["id"]
    goal = c.get(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}").json()["metas"][0]

    sin_nota = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
                      f"/goals/{goal['id']}/dismiss", json={"note": ""})
    assert sin_nota.status_code == 422

    r = c.post(f"/api/v1/brand-intel/engagements/demo/plans/{plan_id}"
               f"/goals/{goal['id']}/dismiss",
               json={"note": "Meta de inversión, no de mercado."})
    assert r.status_code == 200
    plans = c.get("/api/v1/brand-intel/engagements/demo/plans").json()
    assert plans[0]["status"] == "revisado"


def test_client_document_never_replays_the_plan_as_tables(db, engagement):
    """El plan es DEL CLIENTE: el documento no se lo devuelve fila por fila. Ni la
    tabla de medibilidad ni el ledger de decisiones se imprimen; la sección es prosa
    y las tablas restantes van al FINAL del documento (tables_last)."""
    c = _client(db)
    c.post("/api/v1/brand-intel/engagements/demo/decisions",
           json={"title": "Subir alcance 10 puntos", "metric_code": "reach_7d",
                 "baseline_wave_code": "w2", "brand_slug": "focal",
                 "success_threshold": 10.0})
    p = rpt.build_report(db, engagement)
    narratives, tables = report_docs.narratives_and_tables(p)
    titles = [t for t, _ in tables]
    assert "Metas del plan y su medibilidad" not in titles
    assert "Seguimiento de las decisiones del cliente" not in titles
    assert "plan" in narratives                      # la sección existe, en prosa

    captured = {}

    def _fake_render(**kwargs):
        captured.update(kwargs)
        return "/tmp/x.pdf"

    import shared.products.render as spr
    orig = spr.render_product_pdf
    spr.render_product_pdf = _fake_render
    try:
        report_docs.render(p, fmt="pdf")
    finally:
        spr.render_product_pdf = orig
    assert captured["tables_last"] is True


def test_fallback_plan_aggregates_operational_commitments():
    """Un cliente que adopta el plan entero (100+ compromisos) no recibe un inventario:
    lo operativo se agrega a un conteo y solo lo medible se detalla."""
    rows = ([{"title": f"Acción operativa {i}", "metric_code": None,
              "success_threshold": None, "gap": "dato_externo",
              "needs": "Dato externo.", "medida": "x", "segment": "total",
              "detectable_threshold": None}
             for i in range(40)] +
            [{"title": "Meta medible", "metric_code": "reach_1m",
              "success_threshold": 8.0, "gap": "evaluable",
              "needs": "Nada: la próxima ola la evalúa.", "medida": "Consumo último mes",
              "segment": "total", "detectable_threshold": 7.9}])
    texto = report_docs._fallback_plan({"rows": rows, "note": "1 de 41.",
                                        "documents": []})
    assert "Meta medible" in texto
    assert "40 compromiso(s) operativo(s)" in texto
    assert "Acción operativa 7" not in texto


def test_plans_are_isolated_per_engagement(db, engagement, monkeypatch):
    engagement.organization_id = "org-1"
    db.commit()
    _c, body = _upload(db, monkeypatch, [_goal_row()])
    stranger = _client(db, role=UserRole.viewer, org="org-2")
    assert stranger.get(
        f"/api/v1/brand-intel/engagements/demo/plans/{body['id']}").status_code == 404


# ──────────────── plan_readiness y la sección del informe ────────────────


def test_plan_readiness_categories_are_mechanical(db, engagement):
    c = _client(db)
    # Evaluable: movimiento grande sobre métrica con base.
    c.post("/api/v1/brand-intel/engagements/demo/decisions",
           json={"title": "Subir alcance 10 puntos", "metric_code": "reach_7d",
                 "baseline_wave_code": "w2", "brand_slug": "focal",
                 "success_threshold": 10.0})
    # Sub-detectable.
    c.post("/api/v1/brand-intel/engagements/demo/decisions",
           json={"title": "Movimiento minúsculo", "metric_code": "reach_7d",
                 "baseline_wave_code": "w2", "brand_slug": "focal",
                 "success_threshold": 0.5})
    # Corte sin datos en el libro.
    c.post("/api/v1/brand-intel/engagements/demo/decisions",
           json={"title": "Preferencia en Santo Domingo", "metric_code": "favourite_place",
                 "baseline_wave_code": "w2", "brand_slug": "focal",
                 "segment": "Santo Domingo", "success_threshold": 6.0})
    # Fuente externa.
    c.post("/api/v1/brand-intel/engagements/demo/decisions",
           json={"title": "Engagement en redes",
                 "external_measure": "analytics de plataformas",
                 "baseline_wave_code": "w2"})

    out = svc.plan_readiness(db, str(engagement.id))
    gaps = {r["title"]: r["gap"] for r in out["rows"]}
    assert gaps["Subir alcance 10 puntos"] == svc.GAP_EVALUABLE
    assert gaps["Movimiento minúsculo"] == svc.GAP_SUB_DETECTABLE
    assert gaps["Preferencia en Santo Domingo"] == svc.GAP_SIN_DATOS
    assert gaps["Engagement en redes"] == svc.GAP_EXTERNA
    assert "1 de 4" in out["note"]

    # Y el corte faltante llega a Límites, atribuido a la carga, no al proveedor.
    p = rpt.build_report(db, engagement)
    joined = " ".join(p["limits"])
    assert "Santo Domingo" in joined and "cargada por SDQ" in joined


def test_section_absent_without_plan_and_present_with_it(db, engagement):
    p = rpt.build_report(db, engagement)
    narratives, tables = report_docs.narratives_and_tables(p)
    assert "plan" not in narratives

    _client(db).post("/api/v1/brand-intel/engagements/demo/decisions",
                     json={"title": "Subir alcance 10 puntos",
                           "metric_code": "reach_7d", "baseline_wave_code": "w2",
                           "brand_slug": "focal", "success_threshold": 10.0})
    p2 = rpt.build_report(db, engagement)
    narratives2, _tables2 = report_docs.narratives_and_tables(p2)
    assert "plan" in narratives2


def test_plan_context_serves_mechanical_verdicts_verbatim(db, engagement):
    """El LLM narra sobre veredictos servidos: el contexto lleva feasible/gap/umbral
    tal como los computó el ledger — si esto se rompe, el modelo queda decidiendo."""
    _client(db).post("/api/v1/brand-intel/engagements/demo/decisions",
                     json={"title": "Movimiento minúsculo", "metric_code": "reach_7d",
                           "baseline_wave_code": "w2", "brand_slug": "focal",
                           "success_threshold": 0.5})
    p = rpt.build_report(db, engagement)
    ctx = rpt.cerebro_contexts(p)["plan"]
    row = ctx["compromisos_medibles"][0]
    assert row["feasible"] is False
    assert row["gap"] == svc.GAP_SUB_DETECTABLE
    assert row["detectable_threshold"] is not None
    assert ctx["instrumento"]["olas_con_dato"]


def test_plan_thin_template_is_registered_in_the_cerebro():
    from shared.narrative.claude_engine import THIN_TEMPLATES
    tpl = THIN_TEMPLATES["brand_plan_readiness"]
    assert "REGLA DURA DE VEREDICTOS" in tpl
    assert "REGLA DURA DE CIFRAS" in tpl
    assert rpt._CEREBRO_TEMPLATES["plan"] == "brand_plan_readiness"
