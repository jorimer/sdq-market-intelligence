"""El reenfoque narrativo del Informe de Contexto de Mercado.

Tres garantías que el rediseño introdujo y que no pueden regresar en silencio:

* El eje está REGISTRADO en el cerebro (doctrina + frame + thin templates) y la
  generación enruta por la ruta cerebro — la que corre el guard numérico. Una llamada
  que cae a la ruta legacy narra cifras sin gobernanza (lección 2026-06-23).
* El documento del cliente tiene la estructura nueva: sin el patrón mecánico
  «{proveedor} concluye / Lectura SDQ» repetido por conclusión, y sin secciones tituladas
  cuyo único contenido es "aún no hay X" — ese estado vive en Límites.
* Sin insumos (conclusiones no utilizables) el informe se genera igual, con su
  ``empty_reason``, y la capa IA se apaga sola en vez de romper el render.
"""
import asyncio
from typing import Any, Dict

import pytest

from modules.brand_intel import report as rpt
from modules.brand_intel import report_docs


# ── registro en el cerebro ────────────────────────────────────────────


def test_axis_is_registered_in_the_cerebro():
    from shared.narrative.cerebro import (
        AUDIENCE_FRAMES, AXIS_DOCTRINE, build_system, resolve_audience)

    assert "brand_intel" in AXIS_DOCTRINE
    assert "brand_intel" in AUDIENCE_FRAMES
    assert resolve_audience("brand_intel", None) == "cliente_marca"
    system = build_system("brand_intel", "cliente_marca", "detailed")
    # La doctrina refuerza las dos reglas del eje: no recalcular la causalidad del motor
    # determinista y no citar al proveedor conclusión por conclusión.
    assert "REGLA DURA DE CAUSALIDAD" in system
    assert "una por una" in system


def test_thin_templates_exist_for_the_three_sections():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    for template in rpt._CEREBRO_TEMPLATES.values():
        assert template in THIN_TEMPLATES, template
        # La regla dura de cifras es explícita en cada template del eje.
        assert "REGLA DURA DE CIFRAS" in THIN_TEMPLATES[template]


def test_generate_routes_through_the_cerebro_not_legacy(monkeypatch):
    """Regresión directa: con axis="brand_intel" y un template del eje, la generación
    debe entrar a la ruta cerebro (la del guard numérico), nunca caer a legacy."""
    from shared.narrative.claude_engine import NarrativeEngine, NarrativeResult

    engine = NarrativeEngine()
    calls = {}

    def _fake_guarded(client, system, user, max_tokens, context_str, cache_key,
                      template, context=None):
        calls["template"] = template
        calls["system"] = system
        return NarrativeResult(text="narrativa real", model_used="test")

    monkeypatch.setattr(engine, "_generate_guarded", _fake_guarded)
    monkeypatch.setattr(engine, "_get_client", lambda: object())
    monkeypatch.setattr("shared.narrative.claude_engine.budget_allows", lambda: True)

    res = asyncio.run(engine.generate(
        context={"marca": "Focal"}, template="brand_context_reading",
        mode="detailed", axis="brand_intel", audience="cliente_marca"))

    assert res.text == "narrativa real"
    assert calls["template"] == "brand_context_reading"
    assert "DOCTRINA DE CASA — Eje de inteligencia de marca" in calls["system"]


# ── estructura del documento ──────────────────────────────────────────


def test_sections_list_is_the_new_compact_one():
    keys = [k for k, _ in report_docs.SECTIONS]
    assert keys == ["executive", "explanations", "comparison", "sales", "priorities",
                    "plan", "proposals", "proposals_practice", "ticket",
                    "attribution", "methodology",
                    "sources", "limits"]
    # Las secciones que eran títulos con "aún no hay X" ya no existen como sección.
    for gone in ("forecast", "forecast_backtest", "forecast_track_record",
                 "scenarios", "signal_filter", "vigilance", "vigilance_agenda",
                 "decisions"):
        assert gone not in keys


def _payload(**overrides) -> Dict[str, Any]:
    """Un payload mínimo con la forma real de ``build_report``."""
    base: Dict[str, Any] = {
        "engagement": {"slug": "demo", "client": "Cliente", "focal_brand": "Focal",
                       "market": "RD", "category": "QSR", "provider": "Ipsos"},
        "waves": [{"code": "w1", "label": "Ola 1", "period": None, "base": 300}],
        "sections": {
            "explanations": {"available": False, "reason": "Sin conclusiones."},
            "category": {"available": False, "reason": "—"},
            "funnel": {"available": False},
            "ticket": {"available": False, "reason": "Sin serie de ticket."},
            "attribution": {"available": False, "reason": "Se requieren dos olas."},
            "forecast_backtest": {"available": False, "reason": "—"},
            "forecast_track_record": {"available": False, "reason": "Aún no hay "
                                      "pronósticos puntuados."},
            "signal_filter": {"available": False, "reason": "—"},
            "decisions": {"decisions": [], "summary": {}},
            "scenarios": {"available": False, "reason": "—"},
            "vigilance": {"available": False, "reason": "—"},
            "plan": {"available": False, "documents": [], "goals": [], "rows": [],
                     "note": "Aún no hay planes del cliente cargados ni decisiones "
                             "registradas para seguimiento."},
            "sales": {"available": False,
                      "reason": "No hay jornadas de venta cargadas para el encargo."},
            "comparison": {"available": False, "reason": "Sin indicadores núcleo."},
        },
        "executive": {"findings": [], "empty_reason": "Sin conclusiones del proveedor "
                      "utilizables ni insumos de entorno."},
        "methodology": [],
        "sources": [],
        "limits": ["Aún no hay pronósticos puntuados.",
                   "Aún no hay decisiones del cliente registradas para seguimiento."],
    }
    base.update(overrides)
    return base


def test_report_without_inputs_generates_with_empty_reasons():
    narratives, tables = report_docs.narratives_and_tables(_payload())
    assert "Sin conclusiones del proveedor" in narratives["executive"]
    assert "Sin conclusiones." in narratives["explanations"]
    # Las secciones sin insumo NO aparecen con título propio…
    assert "ticket" not in narratives
    assert "attribution" not in narratives
    # …y su estado vive en Límites, que siempre está.
    assert "limits" in narratives
    assert tables == []


def test_empty_states_live_in_limits_not_as_sections(db, engagement):
    """Con el fixture real (3 olas, sin decisiones): los límites declaran el pronóstico
    sin puntuar y el ledger vacío; el documento no imprime títulos para decirlos."""
    p = rpt.build_report(db, engagement)
    joined = " ".join(p["limits"])
    assert "decisiones del cliente registradas" in joined
    narratives, _tables = report_docs.narratives_and_tables(p)
    assert "decisions" not in narratives
    assert "forecast" not in narratives


def test_fallback_reading_does_not_repeat_the_quote_pattern():
    """La composición determinista tampoco vuelve al patrón «concluye/Lectura SDQ»:
    percepción va agrupada por dirección, no una línea por conclusión."""
    competitivas = [
        {"claim": f"La marca {i} retrocede en preferencia.", "direction": "baja",
         "reading": "El entorno del período fue favorable: este retroceso no se "
                    "explica por condiciones de mercado."}
        for i in range(10)
    ]
    xp = {"available": True, "entorno": {}, "explicadas": [],
          "competitivas": competitivas, "sin_capa": [], "note": "n."}
    p = _payload()
    p["sections"]["explanations"] = xp
    narratives, _ = report_docs.narratives_and_tables(p)
    texto = narratives["explanations"]
    assert "concluye:" not in texto
    # Diez conclusiones de la misma dirección son UN grupo con ejemplos, no diez líneas.
    assert "10 conclusión(es) de percepción" in texto
    assert texto.count("retrocede en preferencia") <= 2


def test_undeflated_ticket_prints_nominal_only_with_its_reason():
    """Con serie pero sin deflactor, la tabla no imprime una columna Real de n/d y la
    sección declara el motivo en vez de desaparecer en silencio."""
    p = _payload()
    p["sections"]["ticket"] = {
        "available": True, "deflated": False,
        "reason": "Sin serie de inflación cargada para el tramo.",
        "series": [{"label": "Ola 1", "nominal": 1100.0, "real": None}],
    }
    narratives, tables = report_docs.narratives_and_tables(p)
    assert "Sin serie de inflación" in narratives["ticket"]
    titulos = [t for t, _ in tables]
    assert "Ticket promedio por ola (nominal)" in titulos
    assert "Ticket nominal y en pesos constantes" not in titulos


def test_fallback_priorities_keep_the_decisions_summary():
    """Con decisiones registradas y la IA degradada, el agregado no se pierde."""
    p = _payload()
    p["sections"]["decisions"] = {
        "decisions": [{"title": "Bajar precio combo", "label": "Ticket",
                       "status": "open", "observed_delta": None,
                       "detectable_threshold": 5.0}],
        "summary": {"total": 3, "closed": 1},
    }
    narratives, tables = report_docs.narratives_and_tables(p)
    assert "1 de 3" in narratives["priorities"]
    # El ledger ya no se imprime como tabla: el plan es del cliente (2026-08-01).
    assert not any(t == "Seguimiento de las decisiones del cliente" for t, _ in tables)


def test_ai_overlay_wins_over_the_deterministic_fallback():
    p = _payload()
    narratives, _ = report_docs.narratives_and_tables(
        p, ai={"executive": "Síntesis real del trimestre."})
    assert narratives["executive"] == "Síntesis real del trimestre."


# ── contexto para el cerebro ──────────────────────────────────────────


def test_cerebro_contexts_only_repackage_what_was_computed():
    xp = {
        "available": True,
        "entorno": {"inflacion": {"label": "Inflación", "value": 4.1, "unit": "%",
                                  "direction": "adverso", "doctrine": "d"}},
        "environment_stance": "exigente",
        "explicadas": [{"claim": "El consumo cae.", "subjects": ["Focal"],
                        "direction": "baja", "channel": "consumo",
                        "reading": "lectura del motor"}],
        "competitivas": [
            {"claim": "A cae.", "direction": "baja", "reading": "r1"},
            {"claim": "B cae.", "direction": "baja", "reading": "r1"},
            {"claim": "C sube.", "direction": "sube", "reading": "r2"},
        ],
        "sin_capa": [{"claim": "perfil"}],
        "note": "nota",
    }
    p = _payload()
    p["sections"]["explanations"] = xp
    ctxs = rpt.cerebro_contexts(p)

    lectura = ctxs["explanations"]
    assert lectura["explicadas"][0]["lectura"] == "lectura del motor"
    grupos = lectura["competitivas_por_direccion"]
    assert grupos["baja"]["n"] == 2 and grupos["sube"]["n"] == 1
    assert grupos["baja"]["lectura"] == "r1"
    assert lectura["sin_capa_n"] == 1
    assert set(ctxs) == {"executive", "explanations", "priorities", "plan",
                         "sales", "comparison", "proposals", "proposals_practice"}


def test_ai_narratives_skip_when_there_is_nothing_to_narrate():
    out = asyncio.run(rpt.ai_narratives(_payload()))
    assert out == {}


def test_ai_narratives_drop_static_fallback_sections(monkeypatch):
    """Una sección degradada a fallback estático NO llega al documento del cliente:
    se omite y el render cae a la composición determinista."""
    from shared.narrative.claude_engine import (
        STATIC_FALLBACK_GENERIC, STATIC_FALLBACK_MODEL, NarrativeResult)

    async def _fake_generate(context, template, mode, axis, audience):
        return NarrativeResult(text=STATIC_FALLBACK_GENERIC,
                               model_used=STATIC_FALLBACK_MODEL)

    import shared.narrative.claude_engine as ce
    monkeypatch.setattr(ce.narrative_engine, "generate", _fake_generate)

    p = _payload()
    p["sections"]["explanations"] = {"available": True, "entorno": {},
                                     "explicadas": [], "competitivas": [
                                         {"claim": "x", "direction": "baja",
                                          "reading": "r"}],
                                     "sin_capa": [], "note": "n"}
    out = asyncio.run(rpt.ai_narratives(p))
    assert out == {}


def test_render_pdf_works_end_to_end_without_ai(db, engagement, tmp_path):
    """El documento completo se escribe sin narrativa IA (fallback determinista)."""
    p = rpt.build_report(db, engagement)
    path = report_docs.render(p, fmt="pdf", output_dir=str(tmp_path))
    assert path.endswith(".pdf")
    import os
    assert os.path.getsize(path) > 0


# ── las dos secciones de propuestas ───────────────────────────────────


def _payload_con_evidencia() -> Dict[str, Any]:
    """Payload con venta disponible: el insumo mínimo que habilita proponer."""
    p = _payload()
    p["sections"]["sales"] = {
        "available": True, "growth_composition": {"sales_change_pct": 5.7},
        "real_check": None, "by_city": [], "by_channel": [],
        "contracting_cities": [],
    }
    p["sections"]["plan"] = {
        "available": True,
        "documents": [{"title": "Benchmark competitivo", "source_org": "Agencia",
                       "filename": "b.pdf", "id": "d1", "status": "leido"}],
        "goals": [{"claim": "El modelo a seguir es Taco Bell USA en redes.",
                   "page_number": 12, "measure_source": "externa", "kind": "meta",
                   "metric_code": None, "segment": "total", "target_from": None,
                   "target_to": None, "expected_move": None,
                   "owner_declared": None, "status": "propuesta"}],
        "rows": [], "note": "n",
    }
    return p


def test_practice_context_carries_the_expediente_and_awaits_the_first_section():
    """La práctica sectorial citable son las AFIRMACIONES DE LOS PROPIOS DOCUMENTOS del
    cliente, con su lámina: es lo que la separa de opinión de categoría."""
    ctxs = rpt.cerebro_contexts(_payload_con_evidencia())
    pr = ctxs["proposals_practice"]
    assert pr["practicas_en_el_expediente"][0]["afirmacion"].startswith("El modelo")
    assert pr["practicas_en_el_expediente"][0]["lamina"] == 12
    assert pr["documentos_del_expediente"][0]["titulo"] == "Benchmark competitivo"
    # Se rellena en la generación, no aquí: esta sección no puede saber sola qué dijo
    # la anterior.
    assert pr["propuestas_ya_formuladas"] is None
    # La evidencia es la MISMA de la sección anterior: cambia el permiso, no el dato.
    assert pr["evidencia_de_venta"] == ctxs["proposals"]["evidencia_de_venta"]


def test_practice_section_is_generated_after_and_receives_the_first(monkeypatch) -> None:
    from shared.narrative.claude_engine import NarrativeResult

    seen: Dict[str, Any] = {}

    async def _fake_generate(context, template, mode, axis, audience):
        if template == "brand_sdq_proposals_practice":
            seen["ya"] = context.get("propuestas_ya_formuladas")
        return NarrativeResult(text=f"texto de {template}", model_used="claude-x")

    import shared.narrative.claude_engine as ce
    monkeypatch.setattr(ce.narrative_engine, "generate", _fake_generate)

    out = asyncio.run(rpt.ai_narratives(_payload_con_evidencia()))
    assert out["proposals"] == "texto de brand_sdq_proposals"
    assert out["proposals_practice"] == "texto de brand_sdq_proposals_practice"
    # Recibió el texto de la sección de evidencia para COMPLEMENTARLA, no repetirla.
    assert seen["ya"] == "texto de brand_sdq_proposals"


def test_practice_section_never_appears_without_its_anchor(monkeypatch):
    """Si la sección de evidencia pura no salió, la de práctica sectorial tampoco:
    publicar criterio externo sin su contrapartida medida es lo que la separación evita."""
    from shared.narrative.claude_engine import NarrativeResult

    async def _fake_generate(context, template, mode, axis, audience):
        if template == "brand_sdq_proposals":
            return NarrativeResult(text="", model_used="claude-x")
        return NarrativeResult(text=f"texto de {template}", model_used="claude-x")

    import shared.narrative.claude_engine as ce
    monkeypatch.setattr(ce.narrative_engine, "generate", _fake_generate)

    out = asyncio.run(rpt.ai_narratives(_payload_con_evidencia()))
    assert "proposals" not in out
    assert "proposals_practice" not in out


def test_practice_template_bans_invented_impact_and_demands_declaring_the_external():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    t = THIN_TEMPLATES["brand_sdq_proposals_practice"]
    assert "REGLA DURA DE CIFRAS" in t
    assert "IMPACTO NUMÉRICO" in t
    assert "practicas_en_el_expediente" in t
    assert "propuestas_ya_formuladas" in t
    # La sección de evidencia pura conserva la prohibición completa.
    assert "buenas prácticas de marketing" in THIN_TEMPLATES["brand_sdq_proposals"]


def test_practice_section_renders_after_the_evidence_one():
    keys = [k for k, _ in report_docs.SECTIONS]
    assert keys.index("proposals_practice") == keys.index("proposals") + 1
    n, _ = report_docs.narratives_and_tables(
        _payload_con_evidencia(),
        ai={"proposals": "A", "proposals_practice": "B"})
    assert n["proposals"] == "A" and n["proposals_practice"] == "B"
    # Y sin narrativa no hay título vacío: no existe composición determinista.
    n2, _ = report_docs.narratives_and_tables(_payload_con_evidencia())
    assert "proposals" not in n2 and "proposals_practice" not in n2


# ── la portada declara el corte y sus bases ───────────────────────────


def test_cover_period_says_what_is_measured_and_against_what():
    """La portada no lista las trece olas: dice cuál se mide y contra cuáles compara."""
    p = _payload()
    p["frame"] = {
        "available": True,
        "target": {"code": "2026-06", "label": "2026-06", "period": "2026-06-01"},
        "previous": {"code": "2026-03", "label": "Mar '26", "period": "2026-02-08"},
        "previous_gap_months": 4,
        "year_ago": {"code": "2025-05", "label": "May '25", "period": "2025-05-07"},
        "year_ago_gap_months": 13, "year_ago_reason": None,
    }
    p["waves"] = [{"code": "2018-09", "label": "2018-09", "period": "2018-09-01",
                   "base": 300},
                  {"code": "2026-06", "label": "2026-06", "period": "2026-06-01",
                   "base": 300}]
    txt = rpt.cover_period(p)
    # La etiqueta que era el propio código se homogeneiza a la forma corta.
    assert txt.startswith("Jun '26 — ola medida")
    assert "compara contra Mar '26 (ola anterior, 4 meses)" in txt
    assert "May '25 (interanual, 13 meses)" in txt
    assert "serie disponible: 2 olas desde Sep '18" in txt
    # Y NO es el volcado de la serie.
    assert txt.count("·") == 2


def test_cover_period_declares_a_missing_year_ago_base():
    p = _payload()
    p["frame"] = {
        "available": True,
        "target": {"code": "2025-08", "label": "Ago '25", "period": "2025-08-01"},
        "previous": {"code": "2025-05", "label": "May '25", "period": "2025-05-07"},
        "previous_gap_months": 3,
        "year_ago": None, "year_ago_gap_months": None,
        "year_ago_reason": "La ola más próxima a doce meses atrás queda fuera de "
                           "tolerancia.",
    }
    txt = rpt.cover_period(p)
    assert "sin base interanual (La ola más próxima" in txt
    assert "interanual, " not in txt


def test_cover_period_falls_back_to_the_series_without_a_frame():
    p = _payload()
    assert rpt.cover_period(p) == "Ola 1"
    p["frame"] = {"available": False, "reason": "x"}
    assert rpt.cover_period(p) == "Ola 1"


# ── el veredicto de significancia se COMPUTA ──────────────────────────


def _comparison(rows):
    return {"available": True, "rows": rows, "frame": {}, "note": "n"}


def test_movement_verdicts_partitions_and_writes_the_reading():
    """Regresión del defecto de producción (2026-08-12): con la satisfacción moviéndose
    7 pp contra un umbral de 8,2 el informe publicó «la única métrica que la muestra puede
    distinguir del azar es la satisfacción» y montó un plan encima, contradiciendo a la
    sección de comparación del MISMO documento. Las cifras eran correctas; falló la
    relación. Por eso la relación se computa acá y el modelo la copia."""
    v = rpt.movement_verdicts(_comparison([
        {"metric_code": "satisfaction_t2b", "label": "Satisfacción", "value": 94.0,
         "previous": {"delta": 7.0, "threshold": 8.2, "verdict": "not_detectable"}},
        {"metric_code": "brand_opinion_t2b", "label": "Opinión", "value": 65.0,
         "previous": {"delta": -6.0, "threshold": 8.0, "verdict": "not_detectable"}},
    ]))
    assert v["n_detectables"] == 0 and v["n_total"] == 2
    assert v["detectables"] == []
    assert "NINGUNO" in v["lectura"]
    # La consecuencia va DECLARADA en el contexto, no confiada al criterio del modelo.
    assert "NO puede ser la premisa de un plan" in v["lectura"]
    assert {m["metric_code"] for m in v["no_detectables"]} == {
        "satisfaction_t2b", "brand_opinion_t2b"}


def test_movement_verdicts_counts_the_detectable_ones():
    v = rpt.movement_verdicts(_comparison([
        {"metric_code": "a", "label": "A", "value": 30.0,
         "previous": {"delta": 12.0, "threshold": 7.0, "verdict": "improved"}},
        {"metric_code": "b", "label": "B", "value": 10.0,
         "previous": {"delta": 1.0, "threshold": 6.0, "verdict": "not_detectable"}},
    ]))
    assert v["n_detectables"] == 1 and v["n_total"] == 2
    assert v["detectables"][0]["metric_code"] == "a"
    assert "1 de 2" in v["lectura"]


def test_movement_verdicts_absent_without_comparison():
    assert rpt.movement_verdicts({}) is None
    assert rpt.movement_verdicts({"available": False, "rows": []}) is None
    # Un indicador sin ola previa no es un movimiento: no entra al conteo.
    v = rpt.movement_verdicts(_comparison([
        {"metric_code": "a", "label": "A", "value": 1.0, "previous": None},
        {"metric_code": "b", "label": "B", "value": 2.0,
         "previous": {"delta": 9.0, "threshold": 5.0, "verdict": "improved"}},
    ]))
    assert v["n_total"] == 1


def test_the_three_sections_that_can_confuse_level_with_movement_get_the_verdict():
    """Las tres secciones que reciben el filtro de señal o la comparación llevan el
    veredicto computado Y la aclaración de qué significa «publishable». Servir el filtro
    solo fue lo que produjo «todas las métricas superan su umbral mínimo detectable»."""
    p = _payload()
    p["sections"]["comparison"] = _comparison([
        {"metric_code": "a", "label": "A", "value": 1.0,
         "previous": {"delta": 1.0, "threshold": 9.0, "verdict": "not_detectable"}}])
    p["sections"]["signal_filter"] = {
        "available": True, "rows": [{"metric_code": "a", "threshold": 9.0,
                                     "publishable": True}], "note": "nota"}
    p["sections"]["explanations"] = {"available": True, "entorno": {}, "explicadas": [],
                                     "competitivas": [], "sin_capa": [], "note": "n"}
    ctxs = rpt.cerebro_contexts(p)
    for key, bloque in (("priorities", "filtro_senal"),
                        ("proposals", "umbrales_de_decision"),
                        ("proposals_practice", "umbrales_de_decision")):
        v = ctxs[key]["veredictos_de_movimiento"]
        assert v is not None and v["n_detectables"] == 0, key
        assert "publicar el NIVEL" in ctxs[key][bloque]["que_significa_publishable"], key


def test_templates_ban_calling_a_metric_significant():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    for t in ("brand_sdq_proposals", "brand_sdq_proposals_practice",
              "brand_context_priorities"):
        body = THIN_TEMPLATES[t]
        assert "REGLA DURA DE SIGNIFICANCIA" in body, t
        assert "veredictos_de_movimiento" in body, t
        assert "publicar el NIVEL" in body or "publicar el nivel" in body, t


def test_no_context_serves_a_threshold_block_without_its_verdict():
    """La regla, no la lista: CUALQUIER contexto que sirva umbrales —hoy o el que se agregue
    mañana— debe servir también el veredicto computado de los movimientos. Un umbral sin su
    veredicto al lado es exactamente el insumo que produjo el defecto: el modelo tiene que
    inferir la significancia y la infiere mal."""
    p = _payload()
    p["sections"]["comparison"] = _comparison([
        {"metric_code": "a", "label": "A", "value": 1.0,
         "previous": {"delta": 1.0, "threshold": 9.0, "verdict": "not_detectable"}}])
    p["sections"]["signal_filter"] = {
        "available": True, "rows": [{"metric_code": "a", "threshold": 9.0,
                                     "publishable": True}], "note": "nota"}
    p["sections"]["explanations"] = {"available": True, "entorno": {}, "explicadas": [],
                                     "competitivas": [], "sin_capa": [], "note": "n"}
    p["sections"]["sales"] = {"available": True, "growth_composition": {},
                              "real_check": None, "by_city": [], "by_channel": [],
                              "contracting_cities": []}

    huerfanos = [
        key for key, ctx in rpt.cerebro_contexts(p).items()
        if any(ctx.get(b) for b in ("filtro_senal", "umbrales_de_decision"))
        and not ctx.get("veredictos_de_movimiento")
    ]
    assert huerfanos == [], (
        f"contextos con umbrales y sin veredicto de movimiento: {huerfanos}")


# ── la brecha ENTRE indicadores ───────────────────────────────────────


def test_ladder_gap_is_a_subpopulation_with_its_own_margin():
    """El hueco entre dos peldaños ANIDADOS es una proporción de la misma muestra: lleva
    margen de error propio. Reproduce las cifras reales del corte Mar '26."""
    from modules.brand_intel.engines.funnel import ladder_gaps

    rungs = {"awareness_total": 87.0, "ever_tried": 82.0, "reach_3m": 60.0,
             "reach_1m": 43.0, "reach_7d": 27.0}
    bases = dict.fromkeys(rungs, 300)
    rows = {(r["de"], r["a"]): r for r in ladder_gaps(rungs, bases)}

    g = rows[("reach_1m", "reach_7d")]
    assert g["brecha"] == 16.0
    assert g["margen_de_error"] == pytest.approx(4.15, abs=0.02)
    assert g["verdicto"] == "distinguible_de_cero"
    # El sujeto viaja con el número, y lo escribe el motor.
    assert g["sujeto_de_la_brecha"] == (
        "personas que consumieron en el último mes pero no en los últimos 7 días")
    assert all(r["verdicto"] == "distinguible_de_cero" for r in rows.values())


def test_ladder_gap_declares_instead_of_interpreting():
    """Las tres formas en que la brecha NO se publica: sin dato, sin base común y con el
    anidamiento roto. Ninguna se rellena y ninguna se calla."""
    from modules.brand_intel.engines.funnel import ladder_gaps

    base = {"awareness_total": 87.0, "ever_tried": 82.0, "reach_3m": 60.0,
            "reach_1m": 43.0, "reach_7d": 27.0}
    bases = dict.fromkeys(base, 300)

    sin_dato = ladder_gaps({**base, "reach_7d": None}, bases)
    assert sin_dato[-1]["verdicto"] == "sin_dato" and sin_dato[-1]["brecha"] is None

    otra_base = ladder_gaps(base, {**bases, "reach_7d": 82})
    assert otra_base[-1]["verdicto"] == "no_computable"
    assert "no comparten base" in otra_base[-1]["nota"]

    # Anidamiento roto: el peldaño posterior supera al anterior.
    roto = ladder_gaps({**base, "reach_7d": 55.0}, bases)
    assert roto[-1]["verdicto"] == "inconsistente"
    assert roto[-1]["sujeto_de_la_brecha"] is not None   # el sujeto existe…
    assert "no describe ninguna población" in roto[-1]["nota"]   # …pero no se le aplica


def test_a_tiny_gap_is_not_distinguishable_from_zero():
    from modules.brand_intel.engines.funnel import ladder_gaps

    rows = ladder_gaps({"reach_1m": 43.0, "reach_7d": 42.7}, {"reach_1m": 300,
                                                              "reach_7d": 300})
    g = [r for r in rows if r["de"] == "reach_1m"][0]
    assert g["brecha"] == pytest.approx(0.3)
    assert g["verdicto"] == "no_distinguible_de_cero"


def test_the_authorised_gaps_reach_every_prescribing_context():
    p = _payload()
    p["sections"]["funnel"] = {
        "available": True,
        "ladder_gaps": [{"de": "reach_1m", "a": "reach_7d", "brecha": 16.0,
                         "margen_de_error": 4.15, "verdicto": "distinguible_de_cero",
                         "sujeto_de_la_brecha": "personas que…"}],
    }
    p["sections"]["explanations"] = {"available": True, "entorno": {}, "explicadas": [],
                                     "competitivas": [], "sin_capa": [], "note": "n"}
    p["sections"]["comparison"] = _comparison([
        {"metric_code": "a", "label": "A", "value": 1.0,
         "previous": {"delta": 1.0, "threshold": 9.0, "verdict": "not_detectable"}}])
    ctxs = rpt.cerebro_contexts(p)
    for key in ("priorities", "proposals", "proposals_practice"):
        b = ctxs[key]["brechas_entre_indicadores"]
        assert b and b["brechas"][0]["brecha"] == 16.0, key
        # La regla viaja con el dato: el modelo no tiene que recordar el porqué.
        assert "no se compara" in b["regla"], key


def test_templates_forbid_comparing_unrelated_levels():
    from shared.narrative.claude_engine import THIN_TEMPLATES

    for t in ("brand_sdq_proposals", "brand_sdq_proposals_practice",
              "brand_context_priorities"):
        body = THIN_TEMPLATES[t]
        assert "REGLA DURA DE COMPARABILIDAD" in body, t
        assert "brechas_entre_indicadores" in body, t
        assert "sujeto_de_la_brecha" in body, t
