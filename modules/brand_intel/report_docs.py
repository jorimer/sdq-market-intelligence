"""El informe de contexto de marca en PDF y Word.

El módulo entregaba solo HTML imprimible, contra el propio estándar de la casa
(``docs/REPORT_STANDARD.md``: online · PDF · Word). Un cliente que paga un informe espera
un documento, no una pestaña del navegador.

**No se escribe un renderizador nuevo.** `shared.products.render_product_pdf` es el punto
de entrada único de la plataforma —portada de marca, encabezado corrido, numeración,
disclaimer— y con ``fmt="docx"`` produce el Word con la misma anatomía. Aquí solo se
traduce el informe a lo que ese renderizador espera: narrativas por sección y tablas. Así
este informe se ve como los demás y hereda cualquier mejora del chrome sin tocarlo.

Las secciones que no reúnen sus insumos **entran igual, con su motivo**. Un informe al que
le faltan capítulos sin decir por qué se lee como un informe incompleto; uno que declara
"esta ola no mide alcance en dos marcas" se lee como un informe honesto.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.brand_intel.report import _fmt

#: Orden y título de cada sección en el documento. Es el mismo del HTML: un cliente que
#: recibe los dos no debería tener que reconciliarlos.
SECTIONS: List[Tuple[str, str]] = [
    ("executive", "Las lecturas del trimestre"),
    ("vigilance_agenda", "Lo que el trimestre justifica discutir"),
    ("category", "Tamaño de la categoría y share"),
    ("divergence", "Preferencia declarada y tráfico efectivo"),
    ("funnel", "Conversión por escalón"),
    ("ticket", "El ticket en pesos constantes"),
    ("attribution", "¿La marca o el mercado?"),
    ("forecast", "Regla de pronóstico y track record"),
    ("scenarios", "Qué podría invalidar el pronóstico"),
    ("signal_filter", "Qué movimiento puede sostener una decisión"),
    ("vigilance", "Qué se movió desde la última entrega"),
    ("decisions", "Seguimiento de las decisiones del cliente"),
    ("methodology", "Metodología"),
    ("sources", "Fuentes"),
    ("limits", "Límites declarados"),
]


def _md_list(items: Sequence[str]) -> str:
    return "\n".join(f"- {i}" for i in items if i)


def _unavailable(section: Dict[str, Any]) -> Optional[str]:
    """El motivo por el que una sección no se puede calcular, si no se puede."""
    if section.get("available") is False:
        return str(section.get("reason") or "No hay insumos suficientes para esta sección.")
    return None


def narratives_and_tables(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, str], List[Tuple[str, Sequence[Sequence[str]]]]]:
    """Traduce el informe al par (narrativas, tablas) que espera el renderizador."""
    s = payload["sections"]
    n: Dict[str, str] = {}
    tables: List[Tuple[str, Sequence[Sequence[str]]]] = []

    # ── Resumen ejecutivo ──
    ejec = payload.get("executive") or {}
    findings = ejec.get("findings") or []
    n["executive"] = (
        _md_list([f"**{f['figure']}** — {f['title']}. {f['detail']}" for f in findings])
        if findings
        else str(ejec.get("empty_reason")
                 or "Ninguna sección reunió los insumos mínimos para un hallazgo.")
    )

    # ── Agenda ──
    ag = (s["vigilance"].get("agenda") or {}) if s["vigilance"].get("available") else {}
    items = ag.get("items") or []
    n["vigilance_agenda"] = (
        _md_list([f"**{i['title']}** ({i['priority']}). {i['rationale']}" for i in items])
        if items
        else str(ag.get("empty_reason") or ag.get("note")
                 or "El trimestre no justifica una reunión de resultados.")
    )

    # ── Categoría y share ──
    cat = s["category"]
    motivo = _unavailable(cat)
    if motivo:
        n["category"] = motivo
    else:
        olas = cat.get("waves") or []
        filas_share = [["Marca"] + [w["label"] for w in olas]]
        for row in cat.get("share") or []:
            por_ola = {p["wave"]: p["share"] for p in row["series"]}
            filas_share.append(
                [row["name"]] + [_fmt(por_ola.get(w["code"])) for w in olas])
        if len(filas_share) > 1:
            tables.append(("Share de la categoría, ola a ola", filas_share))
        partes = [str(cat.get("denominator_note") or "")]
        crec = cat.get("category_growth_pct")
        if crec is not None:
            partes.append(f"Tamaño de la categoría: **{_fmt(crec)}** entre la primera y la "
                          "última ola con denominador.")
        partes.append(str(cat.get("growth_basis") or ""))
        for w in cat.get("waves_without_denominator") or []:
            partes.append(f"{w['label']} no tiene share: no mide alcance en suficientes "
                          "marcas del set.")
        n["category"] = "\n\n".join(p for p in partes if p)

    # ── Actitud vs comportamiento ──
    div = cat.get("divergence") or []
    lectura = cat.get("divergence_reading")
    if div:
        tables.append(("Preferencia declarada contra tráfico efectivo",
                       [["Ola", "Preferencia declarada", "Share de tráfico"]] +
                       [[d["label"], _fmt(d["attitude"]), _fmt(d["behaviour"])] for d in div]))
    n["divergence"] = (
        (f"Entre {lectura['wave_from']} y {lectura['wave_to']} preferencia y tráfico se "
         f"movieron en direcciones opuestas: preferencia {_fmt(lectura['delta_attitude'], ' pp')}, "
         f"tráfico {_fmt(lectura['delta_behaviour'], ' pp')}.")
        if lectura and lectura.get("diverging") else
        ("Actitud y comportamiento se mueven en el mismo sentido: están alineados."
         if lectura else "Requiere preferencia declarada y alcance en las mismas olas.")
    )

    # ── Embudo ──
    fun = s["funnel"]
    motivo = _unavailable(fun)
    if motivo:
        n["funnel"] = motivo
    else:
        marcas = fun.get("funnels") or []
        if marcas:
            pasos = [st["label"] for st in marcas[0]["steps"]]
            tables.append((f"Conversión por escalón · ola {fun['wave']['label']}",
                           [["Marca"] + pasos + ["Total"]] +
                           [[m["name"]] + [_fmt(st["conversion"]) for st in m["steps"]]
                            + [_fmt(m["end_to_end"])] for m in marcas]))
        peor = fun.get("weakest_step")
        n["funnel"] = (
            f"Escalón de mayor rezago: **{peor['step_label']}**. La marca focal convierte "
            f"{_fmt(peor['focal_conversion'])} frente al {_fmt(peor['leader_conversion'])} de "
            f"{peor.get('leader_name') or peor['leader']} — una brecha de "
            f"{_fmt(peor['gap'], ' pp')}."
            if peor else "Sin escalón de rezago identificable."
        )

    # ── Ticket ──
    tic = s["ticket"]
    motivo = _unavailable(tic)
    if motivo:
        n["ticket"] = motivo
    else:
        serie_ticket = tic.get("series") or []
        if serie_ticket:
            tables.append(("Ticket nominal y en pesos constantes",
                           [["Ola", "Nominal", "Real"]] +
                           [[r["label"], _fmt(r["nominal"], ""), _fmt(r["real"], "")]
                            for r in serie_ticket]))
        n["ticket"] = str(tic.get("deflator_note") or "")

    # ── Atribución ──
    att = s["attribution"]
    motivo = _unavailable(att)
    if motivo:
        n["attribution"] = motivo
    else:
        filas_att = att.get("rows") or []
        if filas_att:
            tables.append(("Movimiento: cuánto es categoría y cuánto es marca",
                           [["Indicador", "Movimiento", "Categoría", "Marca", "Origen"]] +
                           [[r["label"], _fmt(r["delta"], " pp"),
                             _fmt(r["category_effect"], " pp"), _fmt(r["brand_effect"], " pp"),
                             r["verdict"]] for r in filas_att]))
        n["attribution"] = str(att.get("note") or "")

    # ── Pronóstico ──
    bt, tr = s["forecast_backtest"], s["forecast_track_record"]
    if bt.get("ranking"):
        tables.append(("Reglas de pronóstico por error de backtest",
                       [["Regla", "Error medio", "Series"]] +
                       [[r["rule"], _fmt(r["mae"], " pp"), str(r["n_series"])]
                        for r in bt["ranking"]]))
    n["forecast"] = " ".join(p for p in [str(bt.get("note") or ""),
                                         str(tr.get("reason") or "")] if p) or "—"

    # ── Escenarios ──
    esc = s["scenarios"]
    motivo = _unavailable(esc)
    if motivo:
        n["scenarios"] = motivo
    else:
        filas_esc = esc.get("scenarios") or []
        if filas_esc:
            tables.append(("Escenarios y lectura de la banda",
                           [["Escenario", "Supuestos", "Lectura"]] +
                           [[r["label"], " ".join(r["assumptions"]), r["band_reading"]]
                            for r in filas_esc]))
        riesgos = [f"**{r['risk']}** {r['detail']}" for r in (esc.get("risks") or [])]
        n["scenarios"] = "\n\n".join(
            p for p in [str(esc.get("note") or ""), _md_list(riesgos)] if p)

    # ── Filtro de señal ──
    sig = s["signal_filter"]
    motivo = _unavailable(sig)
    if motivo:
        n["signal_filter"] = motivo
    else:
        filas_sig = sig.get("rows") or []
        if filas_sig:
            tables.append(("Movimiento mínimo detectable por indicador",
                           [["Indicador", "Corte", "Valor", "Base", "Umbral", "Estado"]] +
                           [[r["label"], r["segment"], _fmt(r["value"]),
                             str(r["base_n"] or "—"), _fmt(r["threshold"], " pp"),
                             "Utilizable" if r["publishable"] else "No utilizable"]
                            for r in filas_sig]))
        n["signal_filter"] = str(sig.get("note") or "")

    # ── Vigilancia ──
    vig = s["vigilance"]
    motivo = _unavailable(vig)
    if motivo:
        n["vigilance"] = motivo
    else:
        señales = [x for grupo in (vig.get("signals") or {}).values() for x in grupo]
        if señales:
            tables.append(("Panel de vigilancia",
                           [["Fuente", "Señal", "Lectura", "Fuerza"]] +
                           [[x["source"], x["label"], x["reading"], x["strength"]]
                            for x in señales]))
        n["vigilance"] = str(vig.get("note") or "")

    # ── Decisiones ──
    dec = s["decisions"]
    filas_dec = dec.get("decisions") or []
    if filas_dec:
        tables.append(("Ledger de decisiones",
                       [["Decisión", "Indicador", "Estado", "Movimiento", "Umbral"]] +
                       [[r["title"], r["label"], r["status"],
                         _fmt(r["observed_delta"], " pp"),
                         _fmt(r["detectable_threshold"], " pp")] for r in filas_dec]))
        n["decisions"] = f"{dec['summary']['closed']} de {dec['summary']['total']} cerradas."
    else:
        n["decisions"] = ("Aún no hay decisiones registradas. Cada decisión requiere "
                          "métrica, línea base, ventana de evaluación, umbral de éxito y "
                          "responsable.")

    # ── Anexo ──
    n["methodology"] = _md_list(
        [f"**{m['title']}** {m.get('text', '')}" for m in payload.get("methodology") or []])
    n["sources"] = _md_list(
        [f"{f['name']}{' — ' + f['provider'] if f.get('provider') else ''}"
         for f in payload.get("sources") or []])
    n["limits"] = _md_list(payload.get("limits") or [])

    # El renderizador numera las secciones por orden de inserción, así que el orden se
    # impone aquí y es el mismo del HTML: quien reciba los dos no debería reconciliarlos.
    ordenadas = {k: (n.get(k) or "—") for k, _ in SECTIONS}
    return ordenadas, tables


def render(payload: Dict[str, Any], fmt: str = "pdf",
           output_dir: Optional[str] = None) -> str:
    """Escribe el informe en PDF o Word con el chrome de marca de la casa."""
    from shared.products.render import render_product_pdf

    eng = payload["engagement"]
    olas = ", ".join(w["label"] for w in payload.get("waves") or [])
    narratives, tables = narratives_and_tables(payload)

    return render_product_pdf(
        sector_key="brand_intel",
        display_name=eng["focal_brand"],
        title="Informe de Contexto de Mercado",
        period=olas or "—",
        narratives=narratives,
        section_titles=dict(SECTIONS),
        tables=tables,
        subtitle=" · ".join(x for x in [eng.get("client"), eng.get("category"),
                                        eng.get("market")] if x),
        watermark="Documento confidencial · uso interno del cliente",
        output_dir=output_dir,
        fmt=fmt,
    )
