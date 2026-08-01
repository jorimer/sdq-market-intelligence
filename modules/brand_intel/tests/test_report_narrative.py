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
    assert keys == ["executive", "explanations", "priorities", "ticket",
                    "attribution", "methodology", "sources", "limits"]
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
    assert any(t == "Seguimiento de las decisiones del cliente" for t, _ in tables)


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
    assert set(ctxs) == {"executive", "explanations", "priorities"}


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
