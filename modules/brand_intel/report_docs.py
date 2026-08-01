"""El informe de contexto de marca en PDF y Word.

El módulo entregaba solo HTML imprimible, contra el propio estándar de la casa
(``docs/REPORT_STANDARD.md``: online · PDF · Word). Un cliente que paga un informe espera
un documento, no una pestaña del navegador.

**No se escribe un renderizador nuevo.** `shared.products.render_product_pdf` es el punto
de entrada único de la plataforma —portada de marca, encabezado corrido, numeración,
disclaimer— y con ``fmt="docx"`` produce el Word con la misma anatomía. Aquí solo se
traduce el informe a lo que ese renderizador espera: narrativas por sección y tablas.

**Registro Deep Dive, no plantilla.** Las tres secciones narrativas (resumen ejecutivo,
lectura del trimestre, qué mover y qué no) las redacta el cerebro compartido
(``shared/narrative/cerebro.py``, eje ``brand_intel``) sobre lo que los motores
deterministas YA calcularon — el LLM sintetiza, nunca decide causalidad ni cifras. Si la
narrativa IA degrada (sin API key, presupuesto), cada sección cae a su composición
determinista: cifras siempre correctas, prosa más mecánica, nunca relleno hueco.

Las secciones estructuralmente vacías (pronóstico puntuado, ledger de decisiones, ticket
sin serie) NO ocupan un título propio: su estado se declara en Límites. Un informe con
títulos seguidos de "aún no hay X" se lee incompleto, no honesto.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.brand_intel.report import _fmt, group_competitivas

#: Orden y título de cada sección del documento del cliente. Menos y más densas que la
#: vista HTML interna (que conserva el desglose por motor): el cliente lee una síntesis;
#: el detalle de trabajo vive en la vista interna y en la nota de mesa con el proveedor.
#: Fuera del documento: share, divergencia y embudo (re-análisis del dato del proveedor)
#: y las secciones aún vacías por pocas olas (pronóstico puntuado, ledger de decisiones),
#: cuyo estado se declara en Límites.
SECTIONS: List[Tuple[str, str]] = [
    ("executive", "Resumen ejecutivo"),
    ("explanations", "Lectura del trimestre"),
    ("priorities", "Qué mover y qué no"),
    ("plan", "El plan bajo el instrumento"),
    ("ticket", "El ticket en pesos constantes"),
    ("attribution", "¿La marca o el mercado?"),
    ("methodology", "Metodología"),
    ("sources", "Fuentes"),
    ("limits", "Límites declarados"),
]

#: Veredictos de atribución traducidos: el término interno (`solo_marca`) es vocabulario
#: de motor, no de lector. Un tecnicismo crudo en la tabla de un PDF de cliente es un bug.
_VERDICT_LABEL = {
    "marca": "Movimiento de la marca",
    "solo_marca": "Movimiento de la marca",
    "categoria": "Arrastre de la categoría",
    "mixto": "Mixto (categoría y marca)",
    "sin_movimiento": "Sin movimiento",
}

_STRENGTH_LABEL = {"confirmada": "Confirmada", "marginal": "En el filo",
                   "contextual": "Contexto"}

_SOURCE_LABEL = {"forecast": "Pronóstico", "tracker": "Tracker",
                 "decision": "Decisiones", "macro": "Entorno macro",
                 "category": "Categoría", "funnel": "Embudo"}

_PRIORITY_LABEL = {"alta": "Alta", "media": "Media", "baja": "Baja"}

#: Estados de medibilidad de un compromiso del plan (categorías mecánicas del ledger).
_GAP_LABEL = {
    "evaluable": "Evaluable hoy",
    "sub_detectable": "Meta menor al mínimo detectable",
    "sin_datos_del_corte": "Sin datos del corte en el libro",
    "sin_umbral": "Sin umbral de éxito declarado",
    "dato_externo": "Se mide con fuente externa",
}


def _md_list(items: Sequence[str]) -> str:
    return "\n".join(f"- {i}" for i in items if i)


def _fallback_executive(payload: Dict[str, Any]) -> str:
    """Resumen determinista: los findings calculados, o el motivo del vacío."""
    ejec = payload.get("executive") or {}
    findings = ejec.get("findings") or []
    if findings:
        return _md_list([f"**{f['figure']}** — {f['title']}. {f['detail']}"
                         for f in findings])
    return str(ejec.get("empty_reason")
               or "Ninguna sección reunió los insumos mínimos para un hallazgo.")


def _fallback_explanations(xp: Dict[str, Any], proveedor: str) -> str:
    """Lectura determinista, ya sin el patrón cita-por-cita.

    Las conclusiones de percepción se agrupan por dirección (la lectura del motor
    depende solo de dirección × postura del entorno): decenas de líneas casi idénticas
    se vuelven un grupo con su lectura y dos ejemplos. Las explicadas conservan su
    lectura propia — cada una es distinta de verdad.
    """
    if not xp.get("available"):
        return str(xp.get("reason") or "Sin conclusiones utilizables del proveedor.")
    partes: List[str] = []
    entorno = xp.get("entorno") or {}
    if entorno:
        partes.append("**El entorno del período:**\n" + _md_list([
            f"**{f.get('label')}: "
            f"{_fmt(f.get('value')) if f.get('unit') == '%' else str(f.get('value')) + str(f.get('unit') or '')}** "
            f"({f.get('direction')}) — {f.get('doctrine')}."
            for f in entorno.values()]))
    explicadas = xp.get("explicadas") or []
    if explicadas:
        partes.append(
            f"**Lo que el entorno ayuda a explicar** (conclusiones de {proveedor} sobre "
            "consumo y gasto):\n"
            + _md_list([f"«{e['claim']}» — {e.get('reading') or ''}"
                        for e in explicadas]))
    grupos = group_competitivas(xp)
    if grupos:
        lineas = []
        for g in grupos.values():
            ejemplos = "; ".join(f"«{c['claim']}»" for c in g["conclusiones"][:2])
            lineas.append(f"**{g['n']} conclusión(es) de percepción** — "
                          f"{g.get('lectura') or ''} Por ejemplo: {ejemplos}.")
        partes.append("**Lo que el entorno no explica** — indicadores de percepción; "
                      "su lectura es competitiva:\n" + _md_list(lineas))
    partes.append(str(xp.get("note") or ""))
    return "\n\n".join(x for x in partes if x)


def _fallback_priorities(s: Dict[str, Any]) -> str:
    """Prioridades deterministas: agenda + disciplina de umbral + riesgos declarados."""
    vig = s.get("vigilance") or {}
    ag = (vig.get("agenda") or {}) if vig.get("available") else {}
    items = ag.get("items") or []
    partes: List[str] = []
    if items:
        partes.append(_md_list([
            f"**{i['title']}** (prioridad {_PRIORITY_LABEL.get(i['priority'], i['priority']).lower()}). "
            f"{i['rationale']}" for i in items]))
    else:
        partes.append(str(ag.get("empty_reason") or ag.get("note") or vig.get("reason")
                          or "El trimestre no justifica una reunión de resultados."))
    sf = s.get("signal_filter") or {}
    if sf.get("available") and sf.get("note"):
        partes.append(str(sf["note"]))
    esc = s.get("scenarios") or {}
    riesgos = [f"**{r['risk']}.** {r['detail']}" for r in (esc.get("risks") or [])]
    if riesgos:
        partes.append("**Riesgos declarados:**\n" + _md_list(riesgos))
    dec = s.get("decisions") or {}
    if dec.get("decisions"):
        resumen = dec.get("summary") or {}
        partes.append(f"Decisiones del cliente en seguimiento: "
                      f"{resumen.get('closed', 0)} de {resumen.get('total', 0)} "
                      "cerradas (el detalle, en la tabla de seguimiento).")
    return "\n\n".join(p for p in partes if p)


def _is_measurable(r: Dict[str, Any]) -> bool:
    """Un compromiso con algo que medir: métrica del tracker o umbral declarado.

    El resto son compromisos operativos (acciones adoptadas del plan) — legítimos en el
    ledger, pero enumerarlos en el documento del cliente es devolverle su propio plan."""
    return bool(r.get("metric_code")) or r.get("success_threshold") is not None


def _fallback_plan(plan: Dict[str, Any]) -> str:
    """El plan bajo el instrumento, composición determinista y AGREGADA: los veredictos
    mecánicos de las metas medibles — nunca la lista completa de un plan de 100 puntos."""
    rows = plan.get("rows") or []
    medibles = [r for r in rows if _is_measurable(r)]
    operativos = len(rows) - len(medibles)
    partes: List[str] = [str(plan.get("note") or "")]
    if medibles:
        partes.append("**Metas con medida:**\n" + _md_list([
            f"**{r['title']}** — {_GAP_LABEL.get(r['gap'], r['gap'])}. {r['needs']}"
            for r in medibles]))
    if operativos:
        partes.append(f"Además, {operativos} compromiso(s) operativo(s) del plan "
                      "quedaron en seguimiento sin meta numérica propia; su detalle "
                      "vive en el registro de la plataforma.")
    docs = plan.get("documents") or []
    if docs:
        partes.append("Documentos del plan cargados: " + "; ".join(
            f"«{d.get('title') or d.get('filename')}»"
            + (f" ({d['source_org']})" if d.get("source_org") else "")
            for d in docs) + ".")
    return "\n\n".join(x for x in partes if x)


def narratives_and_tables(
    payload: Dict[str, Any],
    ai: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], List[Tuple[str, Sequence[Sequence[str]]]]]:
    """Traduce el informe al par (narrativas, tablas) que espera el renderizador.

    ``ai`` trae las secciones narradas por el cerebro (``report.ai_narratives``); las que
    falten caen a su composición determinista. Una sección cuyo insumo no existe (ticket
    sin serie, atribución sin dos olas) se omite del documento — su motivo ya está en
    Límites — en vez de imprimir un título con una frase de disculpa.
    """
    s = payload["sections"]
    ai = ai or {}
    n: Dict[str, str] = {}
    tables: List[Tuple[str, Sequence[Sequence[str]]]] = []
    proveedor = payload["engagement"].get("provider") or "el proveedor"

    # ── Resumen ejecutivo ──
    n["executive"] = ai.get("executive") or _fallback_executive(payload)

    # ── Lectura del trimestre ──
    xp = s.get("explanations") or {}
    n["explanations"] = ai.get("explanations") or _fallback_explanations(xp, proveedor)

    # ── Qué mover y qué no (agenda + filtro de señal + escenarios + decisiones) ──
    n["priorities"] = ai.get("priorities") or _fallback_priorities(s)
    sig = s.get("signal_filter") or {}
    if sig.get("available") and (sig.get("rows") or []):
        tables.append(("Movimiento mínimo detectable por indicador",
                       [["Indicador", "Corte", "Valor", "Base muestral",
                         "Mínimo detectable", "¿Sostiene una decisión?"]] +
                       [[r["label"], r["segment"], _fmt(r["value"]),
                         str(r["base_n"] or "—"), _fmt(r["threshold"], " pp"),
                         "Sí" if r["publishable"] else "No: base insuficiente"]
                        for r in sig["rows"]]))
    esc = s.get("scenarios") or {}
    if esc.get("available") and (esc.get("scenarios") or []):
        tables.append(("Escenarios y lectura de la banda",
                       [["Escenario", "Supuestos", "Lectura"]] +
                       [[r["label"], " ".join(r["assumptions"]),
                         {"sesgo_a_la_baja": "Sesgo a la baja",
                          "sesgo_al_alza": "Sesgo al alza",
                          "simetrica": "Simétrica"}.get(r["band_reading"],
                                                        r["band_reading"])]
                        for r in esc["scenarios"]]))
    vig = s.get("vigilance") or {}
    if vig.get("available"):
        señales = [x for grupo in (vig.get("signals") or {}).values() for x in grupo]
        if señales:
            tables.append(("Qué se movió desde la última entrega",
                           [["Fuente", "Señal", "Lectura", "Fuerza"]] +
                           [[_SOURCE_LABEL.get(x["source"], x["source"]), x["label"],
                             x["reading"],
                             _STRENGTH_LABEL.get(x["strength"], x["strength"])]
                            for x in señales]))
    # El ledger de decisiones NO se imprime como tabla en el documento del cliente:
    # fue el cliente quien envió su plan, y una tabla que se lo repite no es informe.
    # El seguimiento con veredictos vive en la vista interna; cuando una ola emita
    # veredictos, la narrativa de prioridades los lee desde el contexto.

    # ── El plan bajo el instrumento ── (solo con planes o decisiones; sin ellos, el
    # estado vive en Límites). PROSA SOLA, sin tabla: el plan es DEL CLIENTE — él ya lo
    # conoce, y devolvérselo fila por fila no aporta. Lo que SDQ agrega es la lectura
    # estratégica y qué puede certificarse; el detalle por meta vive en la vista
    # interna de la app, no en el documento (decisión del dueño, 2026-08-01).
    plan = s.get("plan") or {}
    if plan.get("available"):
        n["plan"] = ai.get("plan") or _fallback_plan(plan)

    # ── Ticket ── (solo con serie; sin serie, el motivo ya está en Límites)
    tic = s.get("ticket") or {}
    if tic.get("available"):
        serie_ticket = tic.get("series") or []
        if serie_ticket and tic.get("deflated"):
            tables.append(("Ticket nominal y en pesos constantes",
                           [["Ola", "Nominal", "Real"]] +
                           [[r["label"], _fmt(r["nominal"], ""), _fmt(r["real"], "")]
                            for r in serie_ticket]))
        elif serie_ticket:
            # Sin deflactor no hay columna "Real" que imprimir: una tabla titulada
            # "pesos constantes" llena de n/d confunde; la nominal sola es honesta.
            tables.append(("Ticket promedio por ola (nominal)",
                           [["Ola", "Nominal"]] +
                           [[r["label"], _fmt(r["nominal"], "")]
                            for r in serie_ticket]))
        n["ticket"] = str(tic.get("deflator_note") or tic.get("reason") or "")

    # ── Atribución ── (la tabla se queda: ya es legible)
    att = s.get("attribution") or {}
    if att.get("available"):
        filas_att = att.get("rows") or []
        if filas_att:
            tables.append(("Movimiento: cuánto es categoría y cuánto es marca",
                           [["Indicador", "Movimiento", "Efecto categoría",
                             "Efecto marca", "Origen del movimiento"]] +
                           [[r["label"], _fmt(r["delta"], " pp"),
                             _fmt(r["category_effect"], " pp"),
                             _fmt(r["brand_effect"], " pp"),
                             _VERDICT_LABEL.get(r["verdict"], r["verdict"])]
                            for r in filas_att]))
        n["attribution"] = str(att.get("note") or "")

    # ── Anexo ──
    n["methodology"] = _md_list(
        [f"**{m['title']}** {m.get('text', '')}" for m in payload.get("methodology") or []])
    n["sources"] = _md_list(
        [f"{f['name']}{' — ' + f['provider'] if f.get('provider') else ''}"
         for f in payload.get("sources") or []])
    n["limits"] = _md_list(payload.get("limits") or [])

    # El renderizador numera las secciones por orden de inserción; el orden se impone
    # aquí. Una sección sin insumo (ticket/atribución) simplemente no aparece.
    ordenadas = {k: n[k] for k, _ in SECTIONS if n.get(k)}
    return ordenadas, tables


def render(payload: Dict[str, Any], fmt: str = "pdf",
           output_dir: Optional[str] = None,
           ai: Optional[Dict[str, str]] = None) -> str:
    """Escribe el informe en PDF o Word con el chrome de marca de la casa.

    ``ai`` son las narrativas del cerebro (``report.ai_narratives_sync``); sin ellas el
    documento sale con la composición determinista — el llamador decide si paga la
    generación (el endpoint del cliente la paga; los tests no).
    """
    from shared.products.render import render_product_pdf

    eng = payload["engagement"]
    olas = ", ".join(w["label"] for w in payload.get("waves") or [])
    narratives, tables = narratives_and_tables(payload, ai=ai)

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
        # Las tablas van DESPUÉS del texto, como anexo: un informe que abre con
        # páginas de tablas se lee como un volcado de datos (pedido del dueño).
        tables_last=True,
    )
