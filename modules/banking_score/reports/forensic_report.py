"""Renderizador del INFORME FORENSE branded (HTML, imprimible/descargable).

Toma el paquete forense (``historical_service.forensic_package``) + la prosa del cerebro y
produce un documento autocontenido con la marca SDQ·MIP: portada, resumen, gráficos SVG del
deterioro (computados del dato real), la lectura forense y metodología/fuentes. Es la versión
"informe" (documento) de la vista analítica — la que el dueño pidió como el mockup.

Sin dependencias externas (SVG inline, CSS inline) para que sirva como un solo archivo.
"""
from __future__ import annotations

import html as _html
import re
from typing import Dict, List, Optional


def _fnum(x: Optional[float], d: int = 1) -> str:
    return "—" if x is None else f"{x:,.{d}f}"


# ── Gráficos SVG (computados del dato real) ─────────────────────────

def _line_chart(series: List[Dict], keys: List[Dict], *, ymax: float, ymin: float = 0.0,
                W: int = 720, H: int = 240) -> str:
    pl, pb, pt, pr = 44, 28, 14, 12
    pts = [p for p in series if any(p.get(k["field"]) is not None for k in keys)]
    n = len(pts)
    if n < 2:
        return ""
    iw, ih = W - pl - pr, H - pt - pb

    def X(i: int) -> float:
        return pl + iw * i / (n - 1)

    def Y(v: float) -> float:
        return pt + ih * (1 - (min(v, ymax) - ymin) / (ymax - ymin))

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img">']
    for t in range(5):
        v = ymin + (ymax - ymin) * t / 4
        y = Y(v)
        out.append(f'<line x1="{pl}" y1="{y:.1f}" x2="{W-pr}" y2="{y:.1f}" stroke="#EAEFF6"/>')
        out.append(f'<text x="{pl-6}" y="{y+3:.1f}" text-anchor="end" font-size="10" '
                   f'fill="#76829C" font-family="monospace">{v:.0f}</text>')
    for i in range(0, n, max(1, n // 8)):
        out.append(f'<text x="{X(i):.1f}" y="{H-8}" text-anchor="middle" font-size="9" '
                   f'fill="#76829C" font-family="monospace">{pts[i]["fecha"][:7]}</text>')
    for k in keys:
        coords = [f'{X(i):.1f},{Y(float(p[k["field"]])):.1f}'
                  for i, p in enumerate(pts) if p.get(k["field"]) is not None]
        if coords:
            out.append(f'<polyline points="{" ".join(coords)}" fill="none" '
                       f'stroke="{k["color"]}" stroke-width="2.2"/>')
    out.append('</svg>')
    return "".join(out)


def _bar_chart(series: List[Dict], field: str, *, W: int = 720, H: int = 170) -> str:
    pl, pb, pt, pr = 44, 26, 12, 12
    vals = [(p["fecha"], p.get(field)) for p in series if p.get(field) is not None]
    n = len(vals)
    if n < 2:
        return ""
    iw, ih = W - pl - pr, H - pt - pb
    vmax = max(max(abs(v) for _, v in vals), 5.0)

    def X(i: int) -> float:
        return pl + iw * i / n

    def Y(v: float) -> float:
        return pt + ih * (1 - (v + vmax) / (2 * vmax))

    zero, bw = Y(0), iw / n * 0.66
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img">',
           f'<line x1="{pl}" y1="{zero:.1f}" x2="{W-pr}" y2="{zero:.1f}" stroke="#D6DEEC"/>']
    for i, (_, v) in enumerate(vals):
        x = X(i)
        y = Y(max(v, 0)) if v >= 0 else zero
        h = abs(Y(v) - zero)
        color = "#C8392E" if v < 0 else "#15875A"
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{color}"/>')
    for i in range(0, n, max(1, n // 8)):
        out.append(f'<text x="{X(i)+bw/2:.1f}" y="{H-8}" text-anchor="middle" font-size="9" '
                   f'fill="#76829C" font-family="monospace">{vals[i][0][:7]}</text>')
    out.append('</svg>')
    return "".join(out)


# ── Markdown mínimo → HTML (solo lo que emite la narrativa) ──────────

def _md_to_html(md: str) -> str:
    lines = (md or "").splitlines()
    html_parts, para = [], []

    def flush():
        if para:
            txt = " ".join(para).strip()
            if txt:
                html_parts.append(f"<p>{_inline(txt)}</p>")
            para.clear()

    for ln in lines:
        s = ln.strip()
        if s.startswith("## "):
            flush()
            html_parts.append(f"<h2>{_inline(s[3:].strip())}</h2>")
        elif s.startswith("# "):
            flush()
            html_parts.append(f"<h2>{_inline(s[2:].strip())}</h2>")
        elif not s or s == "---":
            flush()  # línea vacía o separador markdown → cierra el párrafo, no se renderiza
        else:
            para.append(s)
    flush()
    return "\n".join(html_parts)


def _inline(text: str) -> str:
    esc = _html.escape(text, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)


# ── Documento ───────────────────────────────────────────────────────

def render_forensic_html(pkg: Dict, narrative_md: str, *, degraded: bool = False) -> str:
    meta, bt, series = pkg["meta"], pkg["backtest"], pkg["series"]
    from modules.banking_score.historical_service import forensic_narrative_context
    ctx = forensic_narrative_context(pkg)

    chart_credito = _line_chart(
        series, [{"field": "morosidad_pct", "color": "#C8392E"},
                 {"field": "cobertura_pct", "color": "#0F7E7E"}], ymax=160)
    chart_dep = _bar_chart(series, "dep_mom_pct")
    narr_html = _md_to_html(narrative_md) if narrative_md else (
        '<p class="muted">La lectura narrativa no está disponible en este momento '
        '(motor IA sin presupuesto). Los datos y el backtest de arriba son completos.</p>'
        if degraded else "")

    lead = bt.get("lead_months")
    verdict = (f"Deterioro detectable desde {bt.get('onset_cluster')} — {lead} meses antes del "
               f"colapso." if bt.get("onset_cluster") and lead is not None
               else "Los ratios reportados nunca formaron un cluster de alerta antes de la salida.")

    nombre = _html.escape(meta["nombre"])
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SDQ·MIP — Informe Forense · {nombre}</title>
<style>
 :root{{--ink:#0A1A3A;--body:#43506B;--muted:#76829C;--accent:#1E6FFF;--alert:#C8392E;
   --teal:#0F7E7E;--border:#E7ECF3;--surface:#fff;--canvas:#F5F8FC}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--canvas);color:var(--ink);
   font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.55}}
 .wrap{{max-width:860px;margin:0 auto;padding:0 22px 70px}}
 h1,h2{{font-family:"Plus Jakarta Sans",Inter,sans-serif;letter-spacing:-.02em}}
 .cover{{background:linear-gradient(180deg,#0A1A3A,#0d2350);color:#EAF0FB;border-radius:16px;
   padding:30px 32px;margin:26px 0 18px;position:relative;overflow:hidden}}
 .cover .brand{{display:flex;align-items:center;gap:9px;font-weight:800;font-size:15px}}
 .cover .dot{{width:9px;height:9px;border-radius:50%;background:var(--alert)}}
 .cover .kick{{color:#9db4e8;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
   font-size:11px;margin-top:16px}}
 .cover h1{{color:#fff;font-size:30px;margin:6px 0 4px}}
 .cover .sub{{color:#b9c7e6;font-size:14px}}
 .cover .meta{{display:flex;flex-wrap:wrap;gap:16px;margin-top:16px;font-size:12.5px;color:#c7d4ee}}
 .cover .meta b{{color:#fff;font-weight:600}}
 .stamp{{position:absolute;top:18px;right:-34px;transform:rotate(38deg);background:var(--alert);
   color:#fff;font-weight:800;letter-spacing:.16em;font-size:11px;padding:5px 44px}}
 .verdict{{display:inline-block;margin-top:16px;background:rgba(200,57,46,.16);
   border:1px solid rgba(242,100,90,.5);color:#ffd9d4;padding:7px 13px;border-radius:9px;
   font-size:13px;font-weight:600}}
 section{{background:var(--surface);border:1px solid var(--border);border-radius:14px;
   padding:22px 24px;margin:14px 0}}
 .eyebrow{{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#1551C0}}
 section h2{{font-size:19px;margin:.3em 0 .5em}} p{{color:var(--body);font-size:14.5px}}
 .stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:4px 0}}
 .stat{{background:var(--canvas);border:1px solid var(--border);border-radius:11px;padding:12px 13px}}
 .stat .n{{font-family:"Plus Jakarta Sans";font-size:23px;font-weight:800;
   font-variant-numeric:tabular-nums}} .stat .n.alert{{color:var(--alert)}} .stat .n.warn{{color:#B7791F}}
 .stat .l{{font-size:11px;color:var(--muted);margin-top:2px}}
 .legend{{display:flex;gap:16px;font-size:12px;color:var(--muted);margin:6px 0}}
 .legend i{{display:inline-block;width:15px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}}
 .cap{{font-size:12px;color:var(--muted);margin-top:6px}} .muted{{color:var(--muted)}}
 table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}}
 th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--border);color:var(--body)}}
 th{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
 .foot{{color:#9AA6BF;font-size:11.5px;text-align:center;margin-top:20px;line-height:1.6}}
 @media print{{body{{background:#fff}} section,.cover{{break-inside:avoid}}}}
</style></head><body><div class="wrap">
 <div class="cover">
  <div class="stamp">FORENSE</div>
  <div class="brand"><span class="dot"></span>SDQ·MIP <span style="opacity:.5;font-weight:500">Market Intelligence</span></div>
  <div class="kick">Informe Forense · Retrospectivo</div>
  <h1>{nombre}</h1>
  <div class="sub">Anatomía de una quiebra · reconstrucción del deterioro sobre dato mensual real</div>
  <div class="meta"><span>Período&nbsp; <b>{ctx['periodo_dato']}</b></span>
   <span>Tipo&nbsp; <b>{_html.escape(meta['tipo_entidad'] or '—')}</b></span>
   <span>Colapso&nbsp; <b>{bt.get('exit_date') or '—'}</b></span></div>
  <div class="verdict">⚠ {verdict}</div>
 </div>

 <section>
  <span class="eyebrow">Resumen forense</span>
  <div class="stats">
   <div class="stat"><div class="n warn">{bt.get('onset_cluster') or '—'}</div><div class="l">Inicio del deterioro</div></div>
   <div class="stat"><div class="n alert">{lead if lead is not None else '—'}</div><div class="l">Meses de anticipación</div></div>
   <div class="stat"><div class="n">{_fnum(ctx['morosidad_maxima_pct'])}%</div><div class="l">Morosidad máxima</div></div>
   <div class="stat"><div class="n">{bt.get('n_high_months', 0)}</div><div class="l">de {meta['n_periodos']} meses en alerta</div></div>
  </div>
 </section>

 <section>
  <span class="eyebrow">Riesgo de crédito y colchón de provisiones</span>
  <h2>El deterioro que cuentan los ratios</h2>
  <div class="legend"><span><i style="background:var(--alert)"></i>Morosidad %</span>
   <span><i style="background:var(--teal)"></i>Cobertura %</span></div>
  {chart_credito}
  <div class="cap">Morosidad (+90d) y cobertura de provisiones, mensual. Fuente: estado de situación, SB.</div>
 </section>

 <section>
  <span class="eyebrow">Fondeo</span>
  <h2>Fuga de depósitos</h2>
  {chart_dep}
  <div class="cap">Variación intermensual de depósitos del público. Fuente: estado de situación, SB.</div>
 </section>

 <section>
  <span class="eyebrow">Lectura forense</span>
  {narr_html}
 </section>

 <section>
  <span class="eyebrow">Metodología · Fuentes</span>
  <h2>Procedencia y límites</h2>
  <p>Todas las cifras salen del <b>estado de situación y de resultados mensual por entidad</b>
   publicado por la Superintendencia de Bancos (microportal <i>Cronología SB</i>). El motor de
   Alerta Temprana aplica sus reglas puras sobre esa serie; el inicio del deterioro es el primer
   mes con un cluster de ≥2 alertas altas simultáneas.</p>
  <p class="muted">Límite declarado: el capital regulatorio Basilea no existe en el balance
   contable pre-2004 — el apalancamiento patrimonio/activos es un proxy etiquetado. Informe
   retrospectivo/forense: reconstruye lo observable entonces; no es una calificación emitida en
   su momento.</p>
  <table><tr><th>Fuente</th><th>Serie</th><th>Licencia</th></tr>
   <tr><td>Superintendencia de Bancos RD — Cronología SB</td><td>Estados financieros mensuales por entidad</td><td>Pública</td></tr></table>
 </section>

 <div class="foot">SDQ·MIP — Market Intelligence Report · Informe Forense Retrospectivo<br>
  Dato real de fuente pública. No constituye asesoría de inversión.</div>
</div></body></html>"""
