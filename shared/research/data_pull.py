"""Pull del resultado real de los motores para una entidad/eje resuelto (orquestador v2).

Le pide a cada motor su resultado YA computado vía ``snapshot`` (Deep Dive → el nivel más
rico; degrada a Insight si hace falta) y lo devuelve como: (a) el ``payload`` crudo —lo que
alimenta al Cerebro como 'datos' para que redacte circunscrito a lo recibido— y (b) unas
líneas de evidencia REAL legibles (cifras clave) para el ancla y el fallback determinista.

Anti-Frankenstein: usa el contrato ``SectorProduct`` del registro; no importa módulos.
Resiliente: una entidad sin dato/ nivel no disponible degrada a brecha, no rompe.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

from sqlalchemy.orm import Session

from shared.products.registry import CATALOG_BY_KEY, get_product
from shared.products.tiers import ProductTier
from shared.registry.signals import REAL
from shared.research.models import Evidence
from shared.research.resolve import ResolvedEntity

logger = logging.getLogger("sdq.research.data_pull")

# Clave canónica de la TPM (tasa de política monetaria) — la MISMA variable la citan dos
# motores: monetary_policy (log de decisiones del BCRD, fechado por reunión) y macro (la TPM
# como factor del IRMP, con su propia cadencia y lectura cualitativa). Se etiqueta en la
# evidencia de ambos con esta clave para que la síntesis las reconcilie en una sola línea sin
# parsear texto. Coincide con `key: policy_rate` en shared/doctrine/macro_sector.yaml.
TPM_VARIABLE = "policy_rate"


@dataclass
class EnginePull:
    """El resultado de un motor para una entidad: payload crudo + evidencia real."""

    sector_key: str
    entity_label: str
    period: Optional[str]
    source: str                       # fuente autoritativa del eje (catálogo)
    payload: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)
    ok: bool = False
    note: str = ""


def _fmt(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{v:.1f}" if isinstance(v, float) else str(v)
    return str(v)


def _banking_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                     source: str) -> List[Evidence]:
    """Evidencia REAL legible desde el payload de banca (rating + sub-componentes + pares)."""
    sr = (payload or {}).get("scoring_result") or {}
    if not sr:
        return []
    out: List[Evidence] = []
    tier = sr.get("banda_resiliencia")
    score = sr.get("overall_score")
    head = f"{label}: rating {tier}" if tier else f"{label}"
    if isinstance(score, (int, float)):
        head += f", score global {score:.1f}/100"
    pct = ((sr.get("percentiles") or {}).get("overall"))
    if isinstance(pct, (int, float)):
        head += f" (percentil {pct:.0f} vs el sistema)"
    out.append(Evidence(text=head + f" · período {period or 's/f'}.", source=source,
                        kind="engine", state=REAL, score=100.0))
    sub = sr.get("sub_components") or {}
    if sub:
        parts = ", ".join(f"{k} {_fmt(v)}" for k, v in sub.items())
        out.append(Evidence(text=f"Sub-componentes del rating: {parts}.",
                            source=source, kind="engine", state=REAL, score=99.0))
    peer = payload.get("peer_block") or {}
    if peer.get("cr5") is not None:
        out.append(Evidence(
            text=(f"Concentración del sistema ({peer.get('metric_label','activos')}): "
                  f"CR5 {_fmt(peer.get('cr5'))}, CR10 {_fmt(peer.get('cr10'))}, "
                  f"HHI {_fmt(peer.get('hhi'))}."),
            source=source, kind="engine", state=REAL, score=98.0))
    # Pares NOMBRADOS (si el motor los sirve): posición concreta + competidores con su dato.
    np_meta = peer.get("named_peers") or {}
    np_rows = np_meta.get("rows") or []
    subject = next((r for r in np_rows if r.get("is_subject")), None)
    if subject:
        pos = f"Posición nombrada: {subject.get('rank')} de {np_meta.get('n_system')} en el sistema"
        if subject.get("rank_in_type") and np_meta.get("n_type"):
            pos += (f"; {subject['rank_in_type']} de {np_meta['n_type']} "
                    f"entre {np_meta.get('entity_type') or 'su tipo'}")
        out.append(Evidence(text=pos + ".", source=source, kind="engine", state=REAL, score=97.5))
    peers_named = [r for r in np_rows if not r.get("is_subject")][:4]
    if peers_named:
        listed = ", ".join(f"{r.get('name')} ({_fmt(r.get('score'))}, {r.get('tier')})"
                           for r in peers_named)
        group = np_meta.get("entity_type") or "sistema"
        out.append(Evidence(text=f"Pares ({group}): {listed}.",
                            source=source, kind="engine", state=REAL, score=96.5))
    ew = sr.get("early_warning") or {}
    flags = ew.get("flags") if isinstance(ew, dict) else None
    if flags:
        out.append(Evidence(
            text=f"Alerta temprana: {len(flags)} bandera(s) de monitoreo activa(s) para la entidad.",
            source=source, kind="engine", state=REAL, score=97.0))
    return out


def _monetary_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                      source: str) -> List[Evidence]:
    """Evidencia REAL del motor de política monetaria (TPM + sesgo + pronóstico)."""
    out: List[Evidence] = []
    latest = (payload or {}).get("latest") or {}
    tpm = latest.get("tpm")
    if tpm is not None:
        out.append(Evidence(
            text=(f"Política monetaria (BCRD): TPM en {_fmt(tpm)}% "
                  f"({latest.get('sentido') or 'sin cambio'}) al {latest.get('fecha') or period}."),
            source=source, kind="engine", state=REAL, score=95.0, variable=TPM_VARIABLE))
    fc = (payload or {}).get("forecast") or {}
    prob = fc.get("prob_hold") or fc.get("probabilidad_hold") or fc.get("hold_prob")
    taylor = fc.get("taylor") or fc.get("tasa_taylor") or fc.get("implied_taylor")
    if prob is not None or taylor is not None:
        bits = []
        if prob is not None:
            bits.append(f"prob. de mantener {_fmt(prob if prob > 1 else prob * 100)}%")
        if taylor is not None:
            bits.append(f"Taylor implícita {_fmt(taylor)}%")
        out.append(Evidence(text="Sesgo prospectivo del modelo: " + ", ".join(bits) + ".",
                            source=source, kind="engine", state=REAL, score=93.0))
    return out or _generic_summary(label, payload, period, source)


def _macro_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                   source: str) -> List[Evidence]:
    """Evidencia REAL del motor macro/riesgo-país (banda IRMP + factores)."""
    out: List[Evidence] = []
    band = (payload or {}).get("irmp_band")
    score = (payload or {}).get("irmp_score")
    if band or score is not None:
        s = f" (IRMP {_fmt(score)})" if isinstance(score, (int, float)) else ""
        out.append(Evidence(text=f"Riesgo-país / macro: banda {band or '—'}{s} al {period}.",
                            source=source, kind="engine", state=REAL, score=94.0))
    for f in ((payload or {}).get("factors") or [])[:4]:
        if not isinstance(f, dict):
            continue
        name = f.get("name") or f.get("nombre") or f.get("label") or f.get("factor")
        val = next((f[k] for k in ("value", "valor", "score", "level")
                    if isinstance(f.get(k), (int, float))), None)
        if name and val is not None:
            dirn = f.get("direction") or f.get("direccion") or ""
            # `key` = clave estable del factor (policy_rate = TPM); etiqueta la variable para
            # que la síntesis reconcilie la TPM con la que cita monetary_policy.
            out.append(Evidence(text=f"{name}: {_fmt(val)}{(' · ' + str(dirn)) if dirn else ''}.",
                                source=source, kind="engine", state=REAL, score=88.0,
                                variable=str(f.get("key") or "")))
    return out or _generic_summary(label, payload, period, source)


def _generic_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                     source: str) -> List[Evidence]:
    """Evidencia REAL desde cualquier payload: extrae escalares del primer dict con 'score'
    o del nivel superior. Fallback para ejes sin summarizer dedicado (pensiones/seguros/esg)."""
    root = payload or {}
    # Busca un sub-dict de scoring (índice) o usa el top-level.
    cand = None
    for key in ("index", "scoring_result", "score"):
        v = root.get(key)
        if isinstance(v, dict):
            cand = v
            break
    cand = cand or root
    # Ignora claves de CONTEO/estructura (no son la señal): 'n_factors', 'n_scored'…
    # y los booleanos ('has_data' es int para isinstance — no es una cifra).
    scalars = {k: v for k, v in cand.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)
               and not k.lower().startswith(("n_", "num_", "count"))}
    if not scalars:
        return [Evidence(text=f"{label}: el motor devolvió resultado para el período {period or 's/f'}.",
                        source=source, kind="engine", state=REAL, score=90.0)]
    parts = ", ".join(f"{k} {_fmt(v)}" for k, v in list(scalars.items())[:6])
    return [Evidence(text=f"{label}: {parts} · período {period or 's/f'}.",
                    source=source, kind="engine", state=REAL, score=95.0)]


# ── Summarizers por-eje para los sectores restantes ─────────────────────────────
# Cada motor arma su ``payload`` con una forma distinta (6 familias); estos extractores
# sacan 2-4 cifras legibles de cada una para la sección "Evidencia por motor". Sin summarizer
# dedicado un sector caía a ``_generic_summary`` → "el motor devolvió resultado" (ruido).

def _humanize(slug: Any) -> str:
    return str(slug).replace("_", " ").strip().capitalize()


def _dim_scores(dims: Any) -> List[tuple]:
    """[(etiqueta, score)] de un bloque de dimensiones, sea dict {clave:{score,label?}} o
    lista [{key/label, score}]. Omite dimensiones sin score numérico (p.ej. brecha)."""
    out: List[tuple] = []
    if isinstance(dims, dict):
        for k, v in dims.items():
            if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                out.append((v.get("label") or _humanize(k), float(v["score"])))
    elif isinstance(dims, list):
        for v in dims:
            if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                out.append((v.get("label") or _humanize(v.get("key", "")), float(v["score"])))
    return out


def _dims_line(dims: Any) -> Optional[str]:
    """Línea 'impulsa X / lastra Y' con la dimensión más fuerte y la más débil."""
    items = _dim_scores(dims)
    if not items:
        return None
    items.sort(key=lambda x: x[1])
    if len(items) == 1:
        return f"Dimensión: {items[0][0]} ({_fmt(items[0][1])})."
    worst, best = items[0], items[-1]
    return f"Dimensiones: impulsa {best[0]} ({_fmt(best[1])}); lastra {worst[0]} ({_fmt(worst[1])})."


def _ev(text: str, source: str, score: float) -> Evidence:
    return Evidence(text=text, source=source, kind="engine", state=REAL, score=score)


def _make_index_summary(index_name: str):
    """Familia 'index' (tourism/free_zones/energy/telecom/construction): ``payload['index']``
    con ``<x>_score`` + banda + ``dimensions`` (dict) + niveles absolutos."""
    def _summary(label: str, payload: Dict[str, Any], period: Optional[str],
                 source: str) -> List[Evidence]:
        idx = (payload or {}).get("index") or {}
        out: List[Evidence] = []
        score = next((idx[k] for k in idx
                      if k.endswith("_score") and isinstance(idx[k], (int, float))), None)
        band = idx.get("band")
        if score is not None or band:
            s = f" {_fmt(score)}/100" if isinstance(score, (int, float)) else ""
            b = f" (banda {band})" if band else ""
            out.append(_ev(f"{label}: {index_name}{s}{b} · período {period or 's/f'}.", source, 94.0))
        line = _dims_line(idx.get("dimensions"))
        if line:
            out.append(_ev(line, source, 90.0))
        levels = idx.get("levels") or idx.get("metrics") or {}
        scal = [(k, v) for k, v in levels.items() if isinstance(v, (int, float))][:3]
        if scal:
            out.append(_ev("Niveles: " + ", ".join(f"{_humanize(k)} {_fmt(v)}" for k, v in scal) + ".",
                           source, 86.0))
        return out or _generic_summary(label, payload, period, source)
    return _summary


def _trade_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                   source: str) -> List[Evidence]:
    """Comercio: ``score.*`` (resiliencia + estructura exportadora + flujos)."""
    sc = (payload or {}).get("score") or {}
    out: List[Evidence] = []
    res = sc.get("resilience_score")
    if isinstance(res, (int, float)):
        out.append(_ev(f"{label}: resiliencia comercial {_fmt(res)}/100 · corte {period or 's/f'} "
                       f"(DGA, trimestral).", source, 94.0))
    bits = []
    for key, lbl in (("export_diversification", "diversificación export."),
                     ("import_dependency", "dependencia importadora"),
                     ("hhi_exports", "HHI export.")):
        v = sc.get(key)
        if isinstance(v, (int, float)):
            bits.append(f"{lbl} {_fmt(v)}")
    if bits:
        out.append(_ev(f"Estructura · corte {period or 's/f'} (DGA, trimestral): "
                       + ", ".join(bits) + ".", source, 90.0))
    flows = []
    for key, lbl in (("total_exports", "exportaciones"), ("total_imports", "importaciones")):
        v = sc.get(key)
        if isinstance(v, (int, float)):
            flows.append(f"{lbl} {_fmt(v)}")
    if flows:
        # ⚠️ Estos flujos son del TRIMESTRE de la DGA; el desglose por socio es ANUAL de
        # Comtrade. Sin la etiqueta el informe los sumaba como si fueran comparables.
        out.append(_ev(f"Flujos del corte {period or 's/f'} (US$MM, DGA trimestral — no "
                       f"comparables con los anuales de Comtrade): " + ", ".join(flows) + ".",
                       source, 86.0))
    # Socio × capítulo: QUÉ bienes vienen de cada socio. Es la única evidencia que responde
    # "¿qué le importamos a X, desglosado?" — sin ella el motor sólo tiene el agregado del
    # país y la cuota del socio, y con eso llegó a INFERIR la composición y presentarla como
    # "categorías plausibles". El sujeto viaja con el número: se nombra el socio en cada
    # línea, no se deja al modelo atribuirlo.
    _spc = dict((payload or {}).get("socios_por_capitulo") or {})
    _cob = _spc.pop("_cobertura", {}) or {}
    _spc.pop("_omitidos", None)          # forma anterior: se ignora si sobrevive en caché
    _om = max(0, (_cob.get("socios_con_desglose_computado") or 0) - len(_spc))
    for socio, d in _spc.items():
        caps = d.get("capitulos_top") or []
        if not caps:
            continue
        detalle = ", ".join(
            f"cap. {c['capitulo']} {_fmt(c['usd_mm'])} MM ({_fmt(c['pct'])}%)" for c in caps[:8])
        extra = f" — {d['truncado']} capítulos más no listados" if d.get("truncado") else ""
        out.append(_ev(
            f"Importaciones desde {socio} · año {d.get('period') or 's/f'} (UN Comtrade, anual; "
            f"NO es el corte trimestral de la DGA): "
            f"US${_fmt(d.get('total_usd_mm'))} MM en {d.get('n_capitulos')} capítulos HS. "
            # 96: por ENCIMA de resiliencia/estructura/flujos. Es la evidencia más específica
            # que tiene el eje —responde "qué se importa de quién"— y con el corte de 3 líneas
            # en pantalla las genéricas la desplazaban: el informe citaba "resiliencia 67.0"
            # mientras el cuerpo analizaba el desglose por socio y capítulo.
            f"Mayores: {detalle}.{extra}", source, 96.0))
    if _spc and _cob:
        # EN POSITIVO y con los números dados. La versión anterior decía "N orígenes más están
        # ingeridos pero no se listan acá" y el modelo lo publicó como "el sistema no computa
        # el desglose para 181 orígenes" — declaró faltante lo que sí existe, el defecto
        # simétrico de inferir lo que falta. Y además contó mal ("12 orígenes" con 11 nombres),
        # así que los conteos van servidos, no derivados.
        _n = _cob.get("socios_con_desglose_computado")
        # Score 97: por ENCIMA del desglose por socio. Si el lector se queda con una sola
        # línea, tiene que ser la que impide restar dos conteos y publicar una brecha falsa.
        out.append(_ev(
            f"Cobertura del desglose por origen: {_n} socios con desglose por capítulo "
            f"computado, 100% del valor importado. Este bloque lista los {len(_spc)} de mayor "
            f"valor; el resto está en el sistema y se consulta por socio. NO restes este "
            f"conteo del panel de socios (`n_partners`): la diferencia no es una brecha de "
            f"dato y no debe narrarse como tal.", source, 97.0))
    return out or _generic_summary(label, payload, period, source)


def _esg_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                 source: str) -> List[Evidence]:
    """ESG/clima (IRC): ``score.esg_score/band`` + breakdown + posición en el panel Caribe."""
    p = payload or {}
    sc = p.get("score") or {}
    out: List[Evidence] = []
    score, band = sc.get("esg_score"), sc.get("band")
    if isinstance(score, (int, float)) or band:
        s = f" {_fmt(score)}/100" if isinstance(score, (int, float)) else ""
        b = f" (banda {band})" if band else ""
        out.append(_ev(f"{label}: IRC{s}{b} · período {sc.get('period') or period or 's/f'}.",
                       source, 94.0))
    line = _dims_line((sc.get("breakdown") or {}).get("dimensions"))
    if line:
        out.append(_ev(line, source, 90.0))
    rank, n = p.get("rank"), p.get("n_countries")
    if isinstance(rank, (int, float)) and isinstance(n, (int, float)):
        out.append(_ev(f"Posición en el panel Caribe: {int(rank)} de {int(n)}.", source, 88.0))
    return out or _generic_summary(label, payload, period, source)


def _agribusiness_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                          source: str) -> List[Evidence]:
    """Agroindustria (sector_intel): ``latest.iai_score/iai_band`` + SGPS + ejes del IAI."""
    lt = (payload or {}).get("latest") or {}
    out: List[Evidence] = []
    score, band = lt.get("iai_score"), lt.get("iai_band")
    if isinstance(score, (int, float)) or band:
        s = f" {_fmt(score)}/100" if isinstance(score, (int, float)) else ""
        b = f" (banda {band})" if band else ""
        out.append(_ev(f"{label}: IAI{s}{b} · período {period or 's/f'}.", source, 94.0))
    sgps = lt.get("sgps_score")
    if isinstance(sgps, (int, float)):
        out.append(_ev(f"Momentum del sector (SGPS): {_fmt(sgps)}.", source, 90.0))
    line = _dims_line(lt.get("iai_breakdown"))
    if line:
        out.append(_ev(line.replace("Dimensiones", "Ejes del IAI"), source, 87.0))
    return out or _generic_summary(label, payload, period, source)


def _structure_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                       source: str) -> List[Evidence]:
    """Estructura de la economía: crecimiento del VA + principal motor/lastre + concentración."""
    st = (payload or {}).get("structure") or {}
    out: List[Evidence] = []
    g = st.get("total_va_growth")
    if isinstance(g, (int, float)):
        out.append(_ev(f"{label}: crecimiento del Valor Agregado {_fmt(g)}% · período {period or 's/f'}.",
                       source, 94.0))

    def _sector_bit(d: Any, tag: str) -> Optional[str]:
        if isinstance(d, dict) and d.get("sector"):
            extra = []
            if isinstance(d.get("weight"), (int, float)):
                extra.append(f"peso {_fmt(d['weight'])}%")
            if isinstance(d.get("growth"), (int, float)):
                extra.append(f"crece {_fmt(d['growth'])}%")
            return f"{tag} {d['sector']}" + (f" ({', '.join(extra)})" if extra else "")
        return None
    parts = [b for b in (_sector_bit(st.get("top_driver"), "principal motor"),
                         _sector_bit(st.get("top_drag"), "principal lastre")) if b]
    if parts:
        out.append(_ev("Composición — " + "; ".join(parts) + ".", source, 89.0))
    hhi = st.get("concentration_hhi")
    if isinstance(hhi, (int, float)):
        out.append(_ev(f"Concentración sectorial (HHI): {_fmt(hhi)}.", source, 85.0))
    return out or _generic_summary(label, payload, period, source)


def _named_rating_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                          source: str, *, index_name: str) -> List[Evidence]:
    """Forma NOMBRADA de pension/insurance: ``rating.overall_score/band`` + dimensiones (lista)
    + pares NOMBRADOS del sistema (``payload['peers']`` ya trae el roster completo con score)."""
    rating = payload.get("rating") or {}
    out: List[Evidence] = []
    score, band = rating.get("overall_score"), rating.get("band")
    if isinstance(score, (int, float)) or band:
        s = f" {_fmt(score)}/100" if isinstance(score, (int, float)) else ""
        b = f" (banda {band})" if band else ""
        out.append(_ev(f"{label}: {index_name}{s}{b} · período {period or 's/f'}.", source, 94.0))
    line = _dims_line(rating.get("dimensions"))
    if line:
        out.append(_ev(line, source, 90.0))
    ranked = [p for p in (payload.get("peers") or [])
              if isinstance(p, dict) and isinstance(p.get("overall_score"), (int, float))]
    if ranked:
        ranked.sort(key=lambda p: p["overall_score"], reverse=True)
        subj = rating.get("slug") or rating.get("name")
        rank = next((i for i, p in enumerate(ranked, start=1)
                     if subj and subj in (p.get("slug"), p.get("name"))), None)
        if rank:
            out.append(_ev(f"Posición nombrada: {rank} de {len(ranked)} en el sistema.",
                           source, 89.5))
        listed = ", ".join(f"{p.get('name') or p.get('slug')} ({_fmt(p['overall_score'])})"
                           for p in ranked
                           if not (subj and subj in (p.get("slug"), p.get("name"))))
        if listed:
            out.append(_ev(f"Pares del sistema ({index_name}): {listed}.", source, 88.5))
    return out


def _pension_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                     source: str) -> List[Evidence]:
    """Pensiones (SIPEN): nombrado (``rating.*`` = ISA) o pulse de sistema (``dispersion.*``)."""
    p = payload or {}
    if p.get("rating"):
        return _named_rating_summary(label, p, period, source, index_name="ISA") \
            or _generic_summary(label, payload, period, source)
    out: List[Evidence] = []
    disp = p.get("dispersion") or {}
    avg = disp.get("average")
    if isinstance(avg, (int, float)):
        out.append(_ev(f"{label}: rentabilidad promedio del sistema {_fmt(avg)}% · período {period or 's/f'}.",
                       source, 93.0))
    bits = []
    if isinstance(disp.get("spread_pp"), (int, float)):
        bits.append(f"dispersión entre AFP {_fmt(disp['spread_pp'])} pp")
    n = disp.get("n_afp") or disp.get("n_scoreable")
    if isinstance(n, (int, float)):
        bits.append(f"{int(n)} AFP")
    if bits:
        out.append(_ev("Sistema: " + ", ".join(bits) + ".", source, 89.0))
    return out or _generic_summary(label, payload, period, source)


def _insurance_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                       source: str) -> List[Evidence]:
    """Seguros (SIS): nombrado (``rating.*`` = ISF) o pulse de mercado (``pulse.*``)."""
    p = payload or {}
    if p.get("rating"):
        return _named_rating_summary(label, p, period, source, index_name="ISF") \
            or _generic_summary(label, payload, period, source)
    out: List[Evidence] = []
    pu = p.get("pulse") or {}
    prem = pu.get("total_premiums_rd")
    if isinstance(prem, (int, float)):
        out.append(_ev(f"{label}: primas del mercado RD$ {prem:,.0f} · período {period or 's/f'}.",
                       source, 93.0))
    bits = []
    if isinstance(pu.get("growth_pct"), (int, float)):
        bits.append(f"crecimiento {_fmt(pu['growth_pct'])}%")
    if isinstance(pu.get("top4_concentration_pct"), (int, float)):
        bits.append(f"concentración top-4 {_fmt(pu['top4_concentration_pct'])}%")
    if isinstance(pu.get("active_insurers"), (int, float)):
        bits.append(f"{int(pu['active_insurers'])} aseguradoras")
    if bits:
        out.append(_ev("Mercado: " + ", ".join(bits) + ".", source, 89.0))
    return out or _generic_summary(label, payload, period, source)


# Summarizer de evidencia por eje (real, no genérico). Usado por pull_axis (contexto de
# sistema) Y pull_entity (entidad resuelta); cada uno tolera la forma pulse y la nombrada.
def _social_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                    source: str) -> List[Evidence]:
    """Desarrollo social (IDM): score + banda + desglose + posición en el panel.

    Este eje es SUB-NACIONAL: sus sujetos son demarcaciones, no países ni firmas. Por
    eso la evidencia de distribución pesa tanto como el nivel — en un panel con 40
    puntos de amplitud, el promedio dice poco y la dispersión lo dice casi todo."""
    p = payload or {}
    sc = p.get("score") or {}
    out: List[Evidence] = []
    score, band = sc.get("development_score"), sc.get("band")
    if isinstance(score, (int, float)) or band:
        s = f" {_fmt(score)}/100" if isinstance(score, (int, float)) else ""
        b = f" (banda {band})" if band else ""
        out.append(_ev(f"{label}: IDM{s}{b} · período {sc.get('period') or period or 's/f'}.",
                       source, 94.0))
    line = _dims_line(sc.get("breakdown"))
    if line:
        out.append(_ev(line, source, 90.0))
    rank, n = p.get("rank"), p.get("n_entities")
    if isinstance(rank, (int, float)) and isinstance(n, (int, float)):
        out.append(_ev(f"Posición en el panel de demarcaciones: {int(rank)} de {int(n)}.",
                       source, 88.0))
    dist = p.get("distribution") or {}
    if isinstance(dist.get("mean"), (int, float)) and isinstance(dist.get("spread"), (int, float)):
        out.append(_ev(
            f"Distribución del panel ({int(dist.get('n') or 0)} demarcaciones): media "
            f"{_fmt(dist['mean'])}, amplitud {_fmt(dist['spread'])} puntos entre la mayor y "
            "la menor.", source, 86.0))
    return out or _generic_summary(label, payload, period, source)


_AXIS_SUMMARY = {
    "banking": _banking_summary,
    "monetary_policy": _monetary_summary,
    "macro": _macro_summary,
    "trade": _trade_summary,
    "tourism": _make_index_summary("ITT"),
    "free_zones": _make_index_summary("IZF"),
    "energy": _make_index_summary("índice de energía"),
    "telecom": _make_index_summary("índice de telecom"),
    "construction": _make_index_summary("ICC"),
    "agribusiness": _agribusiness_summary,
    "esg": _esg_summary,
    "pension": _pension_summary,
    "insurance": _insurance_summary,
    "economic_structure": _structure_summary,
    "social_dev": _social_summary,
}


def _declares_no_data(payload: Dict[str, Any]) -> bool:
    """¿El payload DECLARA que no hay dato? (``has_data``/``has_score`` en False). Un motor
    honesto sin dato no es cosecha viva: contarlo inflaba el ledger de cobertura y mostraba
    "has_data False" como evidencia (hallazgo del piloto: seguros sin dato de pulse en prod)."""
    return payload.get("has_data") is False or payload.get("has_score") is False


def pull_sector_base(sector_key: str) -> Optional[EnginePull]:
    """SPEC-4 — pull BASE de una hoja del PIB-por-origen del BCRD (sin producto dedicado).

    Piso de inteligencia sourced al BCRD: aporte al Valor Agregado (share nominal), crecimiento real
    interanual y ranking entre sectores, del último año disponible. Evita que un sector con dato del
    BCRD caiga a scoping con cobertura 0. Devuelve ``None`` si el slug no es hoja base o no hay dato
    (para que el llamador degrade con honestidad, no fabrique)."""
    from shared.research.sector_base import BASE_SECTORS, SECTOR_BASE_SOURCE

    meta = BASE_SECTORS.get(sector_key)
    if meta is None:
        return None
    label = meta[0]
    from shared.data.bcrd_sectors import VAR_GROWTH, VAR_SIZE, bcrd_sectors_client

    try:
        size = [r for r in bcrd_sectors_client.fetch(series=VAR_SIZE) if r.value is not None]
        growth = [r for r in bcrd_sectors_client.fetch(series=VAR_GROWTH) if r.value is not None]
    except Exception:  # noqa: BLE001 — sin dato del BCRD el sector simplemente no rinde base
        return None

    mine = [r for r in size if r.dimension == sector_key]
    if not mine:
        return None
    latest = max(r.period for r in mine)
    my_size = next((r.value for r in mine if r.period == latest), None)
    # ``size`` ya está filtrado a value-no-None; ``or 0.0`` solo estrecha el tipo para mypy.
    peers = sorted(((r.dimension, r.value or 0.0) for r in size if r.period == latest),
                   key=lambda t: t[1], reverse=True)
    rank = next((i + 1 for i, (d, _v) in enumerate(peers) if d == sector_key), None)
    my_growth = next((r.value for r in growth
                      if r.dimension == sector_key and r.period == latest), None)

    ev: List[Evidence] = []
    if my_size is not None:
        head = f"{label}: aporta {_fmt(my_size)}% del Valor Agregado"
        if rank and peers:
            head += f" (puesto {rank} de {len(peers)} sectores)"
        ev.append(_ev(head + f" · {latest} (cuentas nacionales BCRD).", SECTOR_BASE_SOURCE, 92.0))
    if my_growth is not None:
        ev.append(_ev(f"{label}: creció {_fmt(my_growth)}% real interanual en {latest} (BCRD).",
                      SECTOR_BASE_SOURCE, 90.0))
    if sector_key == "financiero":  # SPEC-2: puente al detalle por entidad
        ev.append(_ev("Para el detalle por entidad (rating, solvencia, mora, eficiencia), ver el "
                      "eje de banca (SIB).", SECTOR_BASE_SOURCE, 70.0))
    if not ev:
        return None
    return EnginePull(
        sector_key=sector_key, entity_label=label, period=latest, source=SECTOR_BASE_SOURCE,
        payload={"has_data": True, "sector_size": my_size, "sector_growth": my_growth,
                 "rank": rank, "base_sector": True},
        evidence=ev, ok=True,
    )


REGIONAL_AXIS = "regional_benchmark"


def pull_regional_benchmark() -> Optional[EnginePull]:
    """SPEC-6 — RD vs promedio Centroamérica+Caribe (WDI): gran-composición + crecimiento, con el
    límite honesto declarado. ``None`` si el WDI no responde (→ brecha declarada, no fabricación)."""
    from shared.research.regional_benchmark import REGIONAL_SOURCE, build_regional_comparison

    data = build_regional_comparison()
    if data is None:
        return None
    ev: List[Evidence] = []
    comp = cast(List[Dict[str, Any]], data.get("composition") or [])
    if comp:
        bits = "; ".join(
            f"{c['sector']} RD {_fmt(c['dom'])}% vs {_fmt(c['region_avg'])}% regional"
            for c in comp)
        yr = data.get("year")
        ev.append(_ev(f"Composición del valor agregado — {bits} · {yr} (WDI, promedio de "
                      f"{comp[0]['n_peers']} pares de Centroamérica y el Caribe).",
                      REGIONAL_SOURCE, 88.0))
    growth = data.get("growth")
    if isinstance(growth, dict):
        ev.append(_ev(f"Crecimiento del PIB real: RD {_fmt(growth['dom'])}% vs {_fmt(growth['region_avg'])}% "
                      f"promedio regional · {growth['year']} (WDI).", REGIONAL_SOURCE, 88.0))
    if not ev:
        return None
    # Límite de honestidad: el WDI no desagrega minería/turismo/construcción cross-country.
    ev.append(_ev("Alcance de la comparación regional: el WDI solo desagrega agricultura, industria y "
                  "servicios entre países — no permite comparar minería, turismo ni construcción por "
                  "separado contra la región.", REGIONAL_SOURCE, 60.0))
    return EnginePull(sector_key=REGIONAL_AXIS, entity_label="Comparación regional (CA y Caribe)",
                      period=str(data.get("year") or ""), source=REGIONAL_SOURCE,
                      payload={"has_data": True, "regional": True}, evidence=ev, ok=True)


def pull_axis(db: Optional[Session], sector_key: str) -> EnginePull:
    """Cosecha a-nivel-SISTEMA de un motor de contexto (sin entidad): macro, monetario, etc.
    Es lo que trae el telón cross-dominio para la síntesis (condiciones sistémicas). Prueba
    niveles (deep_dive→insight→pulse) con ``scope=None``; el primero con dato gana."""
    from shared.research.sector_base import is_base_sector

    entry = CATALOG_BY_KEY.get(sector_key)
    source = entry.source if entry else sector_key
    label = entry.display_name if entry else sector_key
    base = EnginePull(sector_key=sector_key, entity_label=label, period=None, source=source)
    # SPEC-6: comparación regional (WDI) — independiente de la sesión; degrada a vacío si WDI no responde.
    if sector_key == REGIONAL_AXIS:
        rb = pull_regional_benchmark()
        return rb if rb is not None else base
    # SPEC-4: una hoja del VAB sin producto dedicado rinde su piso del BCRD (share + crecimiento +
    # ranking). Es independiente de la sesión (dato del cliente bcrd_sectors) → antes del guard de db.
    if is_base_sector(sector_key):
        base_pull = pull_sector_base(sector_key)
        return base_pull if base_pull is not None else base
    if db is None:
        return base
    product = get_product(sector_key, db)
    if product is None:
        return base
    for tier in (ProductTier.deep_dive, ProductTier.insight, ProductTier.pulse):
        try:
            snap = product.snapshot(tier, "", scope=None)
        except Exception:  # noqa: BLE001 — nivel no disponible sin entidad
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            continue
        payload = snap.payload or {}
        if not payload or _declares_no_data(payload):
            continue  # sin dato en este nivel → probar el siguiente
        ev = _AXIS_SUMMARY.get(sector_key, _generic_summary)(label, payload, snap.period, source)
        return EnginePull(sector_key=sector_key, entity_label=label, period=snap.period,
                          source=source, payload=payload, evidence=ev, ok=bool(ev))
    base.note = f"Sin dato de sistema para '{label}'."
    return base


def pull_entity(db: Optional[Session], resolved: ResolvedEntity) -> EnginePull:
    """Trae el resultado del motor para *resolved* (Deep Dive → Insight → brecha)."""
    entry = CATALOG_BY_KEY.get(resolved.sector_key)
    source = entry.source if entry else resolved.sector_key
    base = EnginePull(sector_key=resolved.sector_key, entity_label=resolved.label,
                      period=None, source=source)
    if db is None:
        base.note = "Sin sesión de datos."
        return base
    product = get_product(resolved.sector_key, db)
    if product is None:
        base.note = "Motor no implementado."
        return base

    for tier in (ProductTier.deep_dive, ProductTier.insight):
        try:
            snap = product.snapshot(tier, "", scope=resolved.scope_value)
        except Exception as e:  # noqa: BLE001 — sin dato para la entidad en ese nivel
            logger.info("snapshot %s/%s (%s) no disponible: %s",
                        resolved.sector_key, tier.value, resolved.label, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            continue
        payload = snap.payload or {}
        if not payload or _declares_no_data(payload):
            continue  # el motor declara "sin dato" → probar el siguiente nivel / brecha
        summarizer = _AXIS_SUMMARY.get(resolved.sector_key, _generic_summary)
        ev = summarizer(resolved.label, payload, snap.period, source)
        return EnginePull(sector_key=resolved.sector_key, entity_label=resolved.label,
                          period=snap.period, source=source, payload=payload,
                          evidence=ev, ok=bool(ev), note="")

    base.note = f"Sin dato del motor para '{resolved.label}' en este período."
    return base
