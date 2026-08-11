"""Índice de Solidez de Aseguradora (ISF) — insurer solidity index.

Mirrors the pension ISA: a 0-100 band index over REAL public SIS data (audited
statements por cía), NOT a credit rating. Five dimensions (weights sum to 1.0),
each scored 0-100 by a HYBRID of an absolute band (0.5) + peer min-max (0.5) so the
score is both anchored and discriminating; the overall is the weighted mean over the
PRESENT dimensions, with ``coverage`` = share of the declared methodology backed by
real data.

    solvencia         0.35  patrimonio / activos                 higher=better
    siniestralidad    0.20  siniestros / primas (loss ratio)     lower ratio=better
    liquidez          0.15  activos líquidos / reservas técnicas  higher=better
    escala            0.15  activos totales (log)                 higher=better
    resultado_tecnico 0.15  1 − combined ratio (margen técnico)   higher=better

With audited statements ingested, coverage ≈ 1.0 → the ISF emits an ABSOLUTE band
(Sólida/Adecuada/En vigilancia/Frágil) besides ranking. Missing inputs → the
dimension is a declared gap (present=False), never fabricated.
"""
import math
from statistics import pstdev  # noqa: F401  (reserved for future dispersion use)
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# Dimension spec: weight, direction, and absolute anchors (worst→0, best→100).
# Solvencia y liquidez usan los ÍNDICES REGULATORIOS oficiales que publica la SIS
# (Ley 146-02, Art. 164): índice = recurso disponible / mínimo requerido, ≥1 = cumple.
# Los anclajes reflejan el umbral regulatorio 1.0 (cumplimiento) como piso de referencia.
# ``wabs`` = peso de la banda ABSOLUTA vs. min-max entre pares. Solvencia y liquidez son
# ÍNDICES regulatorios (valor absoluto significativo: 1.0 = cumple sin colchón), así que
# pesan más hacia lo absoluto que las dimensiones puramente relativas.
DIMENSIONS = [
    {"key": "solvencia", "label": "Solvencia regulatoria (PTA/margen requerido, Ley 146-02)",
     "weight": 0.35, "direction": "higher", "lo": 0.60, "ref": 1.00, "hi": 4.00,
     "log": False, "wabs": 0.75},
    {"key": "siniestralidad", "label": "Siniestralidad (loss ratio)", "weight": 0.20,
     "direction": "lower", "lo": 0.80, "ref": 0.45, "hi": 0.20, "log": False},
    {"key": "liquidez", "label": "Liquidez regulatoria (disponible/mínimo, Ley 146-02)",
     "weight": 0.15, "direction": "higher", "lo": 0.60, "ref": 1.00, "hi": 4.00,
     "log": False, "wabs": 0.65},
    {"key": "escala", "label": "Escala (activos totales)", "weight": 0.15,
     "direction": "higher", "lo": 1.5e8, "ref": 1.0e9, "hi": 1.8e10, "log": True},
    # Margen técnico = 1 − combined ratio; ``ref`` = 0.00 es el breakeven técnico
    # (combined ratio 100%), el único de los tres cortes con ancla económica real.
    {"key": "resultado_tecnico", "label": "Margen técnico (1 − combined ratio)", "weight": 0.15,
     "direction": "higher", "lo": -0.15, "ref": 0.00, "hi": 0.25, "log": False},
]
_WABS = 0.5  # hybrid weight of the absolute band vs. peer min-max
_MIN_COVERAGE = 0.50
_BANDS = [(75, "Sólida"), (60, "Adecuada"), (45, "En vigilancia"), (0, "Frágil")]

# Techo de banda para quien incumple el margen de SOLVENCIA regulatorio (Ley 146-02, índice
# < 1.0). Decisión de producto del dueño, 2026-08-07: el capital regulatorio es la condición
# que define si la entidad puede seguir operando, así que ninguna entidad por debajo del
# mínimo puede mostrar una banda que un lector interpreta como "está bien".
#
# El tope aplica SOLO a solvencia, no a liquidez: el capital es estructural y la liquidez
# fluctúa —Aseguradora Agropecuaria, agrícola, incumple liquidez por estacionalidad de
# siniestros teniendo solvencia 3.22—. Y aplica sin graduar por materialidad: un umbral del
# tipo "solo si está 10% corto" agrega un parámetro arbitrario que habría que defender ante
# un cliente, mientras que "cumple o no cumple" es la propia definición legal.
BAND_CAP_INCUMPLIMIENTO = "En vigilancia"
_BAND_ORDER = [name for _t, name in _BANDS]  # mejor → peor


def _cap(band: str, cap: str) -> str:
    """La peor entre *band* y *cap*, en el orden de ``_BANDS``."""
    return band if _BAND_ORDER.index(band) >= _BAND_ORDER.index(cap) else cap


def band_for(score: Optional[float], solvencia_incumplida: bool = False) -> Optional[str]:
    """Banda del score, topeada si la entidad incumple el margen de solvencia.

    El tope NO cambia el ``overall_score`` — el índice sigue siendo el índice y su número se
    puede auditar contra las dimensiones. Solo acota la etiqueta cualitativa, que es la que
    un lector lee como afirmación.
    """
    if score is None:
        return None
    band = next((name for threshold, name in _BANDS if score >= threshold), "Frágil")
    return _cap(band, BAND_CAP_INCUMPLIMIENTO) if solvencia_incumplida else band


def _absolute(raw: float, spec: Dict) -> float:
    """Banda absoluta en dos tramos: ``lo``→0, **``ref``→50**, ``hi``→100.

    ``ref`` es el hecho económico de la dimensión — el umbral regulatorio de la Ley 146-02
    (índice 1.0 = cumple) o el breakeven técnico (combined ratio 100%). Anclarlo en 50 es lo
    que hace que el número signifique algo por sí solo: cumplir la ley es "adecuado", no un
    punto arbitrario de una recta.

    La versión anterior era una sola recta ``lo``→``hi`` con extremos fijados por rangos
    teóricos, no observados, y el resultado era un índice que no podía dar bien: la liquidez
    entregaba mediana 28/100 **con el mercado entero cumpliendo el mínimo legal**, porque el
    techo estaba en 5.0 y nadie llega. Ver ``docs/PROPUESTA_ANCLAJES_ISF.md``.

    Sin ``ref`` declarada se mantiene la recta simple, así que la función sigue sirviendo a
    dimensiones que no tienen un punto de referencia económico.
    """
    lo, hi, ref = spec["lo"], spec["hi"], spec.get("ref")
    if spec.get("log"):
        raw = math.log10(max(raw, 1.0))
        lo, hi = math.log10(lo), math.log10(hi)
        ref = math.log10(ref) if ref is not None else None
    if ref is None:
        frac = (raw - lo) / (hi - lo) if hi != lo else 0.5
        return max(0.0, min(1.0, frac)) * 100
    # Dos tramos. Funciona igual con dimensiones invertidas (hi < lo < ref), donde "mejor"
    # es un valor más bajo: la comparación con ref se hace en el sentido de la escala.
    bajo_ref = raw <= ref if hi > lo else raw >= ref
    if bajo_ref:
        frac = (raw - lo) / (ref - lo) if ref != lo else 1.0
        return max(0.0, min(1.0, frac)) * 50
    frac = (raw - ref) / (hi - ref) if hi != ref else 1.0
    return 50 + max(0.0, min(1.0, frac)) * 50


def _minmax(raw: float, peers: List[float], spec: Dict) -> Optional[float]:
    """Peer min-max en el MISMO espacio que la banda absoluta, con límites robustos.

    Dos correcciones sobre la versión anterior:

    * **Respeta el flag ``log`` de la dimensión.** ``escala`` se declara logarítmica y la
      banda absoluta lo aplicaba, pero el min-max corría en escala lineal: contra un máximo
      de RD$33.000 millones, una aseguradora en la mediana (RD$983 millones) sacaba ~3
      puntos. Media dimensión medía en una escala y la otra media en otra.
    * **Acota con la valla de Tukey** (``robust_bounds``) para que un outlier no comprima al
      resto. Sobre una distribución sesgada como los activos, la valla hay que calcularla en
      el espacio log o recorta la cola alta legítima como si fuera anomalía.
    """
    from shared.indices.normalization import robust_bounds

    if len(peers) < 2:
        return None
    v, vals = raw, peers
    if spec.get("log"):
        v = math.log10(max(raw, 1.0))
        vals = [math.log10(max(p, 1.0)) for p in peers]
    lo, hi = robust_bounds(vals)
    if hi == lo:
        return 50.0
    frac = (v - lo) / (hi - lo)
    if spec["direction"] == "lower":
        frac = 1 - frac
    return max(0.0, min(1.0, frac)) * 100


def _combined_no_interpretable(fin: Dict[str, Any]) -> Optional[str]:
    """Razón por la que el combined ratio de ESTA aseguradora no mide desempeño, o None.

    Delega en ``perfil_sdq.motivo_combined_no_interpretable``: una sola definición para los
    dos motores. Acá se evalúa sobre el ÚLTIMO ejercicio porque es la base del ISF, mientras
    que Perfil SDQ la evalúa sobre el ciclo — cambia el insumo, no la regla.
    """
    from modules.insurance_intel.scoring.perfil_sdq import motivo_combined_no_interpretable

    dev = fin.get("primas_devengadas")
    if not dev:
        return None
    def _frac(k: str) -> Optional[float]:
        v = fin.get(k)
        return (v / dev) if v is not None else None
    return motivo_combined_no_interpretable(_frac("primas_cedidas"),
                                            _frac("productos_inversion"))


def _raw_metric(fin: Dict[str, Any], key: str) -> Optional[float]:
    """Derive a dimension's raw ratio from an insurer's financials dict."""
    g = fin.get
    # Las dos dimensiones que salen del combined ratio (35% del índice) se DECLARAN ausentes
    # cuando el ratio no describe a esta compañía: la fronting cuyo riesgo está reasegurado y
    # la de anualidades cuyo siniestro lo paga el rendimiento.
    #
    # CONSECUENCIA, medida y no supuesta: conservan ``overall_score`` —la cobertura cae a 0.65,
    # por encima de ``_MIN_COVERAGE``— pero PIERDEN la banda, porque banda exige cobertura
    # ≥0.99. Es la regla que ya regía para el dato ausente, aplicada al dato presente que no
    # mide lo que la dimensión afirma medir; afecta a 4 de 34 aseguradoras en el ejercicio 2024.
    if key in ("siniestralidad", "resultado_tecnico") and _combined_no_interpretable(fin):
        return None
    if key == "solvencia":
        return g("indice_solvencia")  # oficial (PTA/MSMR), Ley 146-02 Art. 160-161
    if key == "siniestralidad":
        # Base INCURRIDA sobre DEVENGADA (revisión actuarial 2026-08). Antes era pagado
        # sobre suscrito: numerador y denominador en distinta base. Sin la base nueva se
        # declara la brecha — no se cae al cálculo viejo, porque mezclar bases entre
        # compañías produce un ranking que no ordena lo que dice ordenar.
        inc, dev = g("siniestros_incurridos"), g("primas_devengadas")
        return (inc / dev) if inc is not None and dev else None
    if key == "liquidez":
        return g("indice_liquidez")  # oficial (DLGFL/LMR), Ley 146-02 Art. 162
    if key == "escala":
        return g("activos_totales")
    if key == "resultado_tecnico":
        # Margen técnico = 1 − combined ratio (loss ratio + expense ratio).
        #
        # La definición anterior era ``(ingresos_totales − gastos_totales) / primas`` y
        # CONTABA LOS SINIESTROS DOS VECES: la sección 5 del catálogo SIS (Ley 146-02) no
        # es "gastos" en sentido económico — es el lado deudor bruto e incluye las
        # reclamaciones pagadas (5101/5301), que ya pesan en ``siniestralidad``, además de
        # la prima cedida al reasegurador y los movimientos de reservas. Restarle solo los
        # siniestros tampoco alcanzaba: dejaba cesión y reservas dentro del expense ratio.
        #
        # ``gastos_operativos`` se arma por selección explícita de cuentas (comisiones +
        # G&A + otros gastos de operación del seguro directo), así que loss y expense son
        # mutuamente excluyentes por construcción. Ancla económica: margen 0 = combined
        # ratio 100% = breakeven técnico.
        # Base INCURRIDA/DEVENGADA (revisión actuarial 2026-08): el catálogo constituye la
        # reserva en la sección 5 y la libera en la 4, así que ambas magnitudes siempre
        # fueron computables. Con la base corregida el breakeven vuelve a significar lo que
        # dice: la mediana del panel pasa de un margen de +12.2% —implausible— a +4.2%.
        sin, gop, pri = (g("siniestros_incurridos"), g("gastos_operativos"),
                         g("primas_devengadas"))
        if sin is None or gop is None or not pri:
            return None  # brecha declarada — nunca se reconstruye con la fórmula vieja
        return 1.0 - (sin + gop) / pri
    return None


def score_insurers(financials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure ISF scorer over a list of insurer financials dicts (testable, no DB).

    Each dict has ``slug``, ``name``, ``period`` + the raw figures (patrimonio,
    activos_totales, primas_suscritas, siniestros_pagados, reservas_tecnicas,
    activos_liquidos, ingresos_totales, gastos_totales)."""
    # Peer pools per dimension (for min-max), over insurers where the raw exists.
    raws: Dict[str, Dict[str, Optional[float]]] = {}
    for fin in financials:
        raws[fin["slug"]] = {d["key"]: _raw_metric(fin, d["key"]) for d in DIMENSIONS}
    pools = {d["key"]: [raws[s][d["key"]] for s in raws if raws[s][d["key"]] is not None]
             for d in DIMENSIONS}

    total_weight = sum(d["weight"] for d in DIMENSIONS)
    out: List[Dict[str, Any]] = []
    for fin in financials:
        slug = fin["slug"]
        dims: List[Dict[str, Any]] = []
        num = wsum = 0.0
        for d in DIMENSIONS:
            raw = raws[slug][d["key"]]
            present = raw is not None
            score = None
            if present:
                a = _absolute(raw, d)
                mm = _minmax(raw, pools[d["key"]], d)
                wabs = d.get("wabs", _WABS)
                score = round(wabs * a + (1 - wabs) * mm, 1) if mm is not None else round(a, 1)
                num += score * d["weight"]
                wsum += d["weight"]
            dims.append({"key": d["key"], "label": d["label"], "weight": d["weight"],
                         "raw": None if raw is None else round(raw, 4),
                         "score": score, "provenance": "real", "present": present})
        coverage = round(wsum / total_weight, 4) if total_weight else 0.0
        overall = round(num / wsum, 1) if wsum and coverage >= _MIN_COVERAGE else None
        # Incumplir el margen de solvencia (Ley 146-02, índice < 1.0) topea la banda.
        solv = raws[slug].get("solvencia")
        incumple = solv is not None and solv < 1.0
        band = band_for(overall, incumple) if coverage >= 0.99 else None
        out.append({
            "slug": slug, "name": fin.get("name", slug), "period": fin.get("period"),
            "overall_score": overall, "band": band,
            # ``band_capped`` distingue "En vigilancia por su score" de "En vigilancia porque
            # incumple": sin esta marca, la etiqueta sola no dice cuál de las dos cosas pasó.
            "band_capped": bool(band and incumple and band != band_for(overall)),
            "incumple_solvencia": None if solv is None else incumple,
            "coverage": coverage, "dimensions": dims,
            "score_kind": "absolute" if coverage >= 0.99 else "relative",
        })
    out.sort(key=lambda r: (r["overall_score"] is not None, r["overall_score"] or 0), reverse=True)
    return out


def _fallback_key(name: str) -> str:
    """Heuristic canonical key (used only if the official roster is unavailable): first two
    brand tokens (stable head vs. the truncated tail), with a lighter-slug fallback."""
    from shared.data.sis_solvency_client import brand_key
    from modules.insurance_intel.external.audited_excel_extractor import slugify_insurer
    bk = brand_key(name)
    return "_".join(bk.split("_")[:2]) if bk else (slugify_insurer(name) or "sin_nombre")


def _official_index() -> Dict[Any, Any]:
    """``{brand_key: (official_name, official_slug)}`` for the authorized-insurer roster.

    Trae además el índice COMPACTO bajo la clave especial ``("__compacto__",)``: resuelve los
    nombres donde el rubro es parte de la marca y ``brand_key`` los parte (Auto Seguro vs
    Autoseguro). Va dentro del mismo dict para no cambiar la firma de todo lo que lo consume.
    """
    from shared.data.sis_roster_client import official_insurers
    from shared.data.sis_solvency_client import brand_key, brand_key_compacta
    from modules.insurance_intel.external.audited_excel_extractor import slugify_insurer
    idx: Dict[Any, Any] = {}
    compacto: Dict[str, Any] = {}
    for name in official_insurers():
        v = (name, slugify_insurer(name))
        idx[brand_key(name)] = v
        compacto[brand_key_compacta(name)] = v
    if compacto:
        idx[("__compacto__",)] = compacto
    return idx


def _match_official(key: str, official: dict, nombre: Optional[str] = None):
    """Match an entity's brand key to an official company. exact → prefix (≥5) → unique
    first-token → clave compacta EXACTA. Returns ``(official_name, official_slug)`` or None.

    El último paso solo corre con *nombre* y solo por igualdad exacta: recupera los casos
    donde el rubro es parte de la marca, sin poder inventar parentescos.
    """
    compacto = official.get(("__compacto__",)) or {}
    reales = {k: v for k, v in official.items() if isinstance(k, str)}
    if key in reales:
        return reales[key]
    for ok, v in reales.items():
        short, long = sorted((key, ok), key=len)
        if len(short) >= 5 and long.startswith(short):
            return v
    first = key.split("_")[0]
    if len(first) >= 5:
        hits = [v for ok, v in reales.items() if ok.split("_")[0] == first]
        if len(hits) == 1:
            return hits[0]
    if nombre and compacto:
        from shared.data.sis_solvency_client import brand_key_compacta
        return compacto.get(brand_key_compacta(nombre))
    return None


def _canon_map(ents, official) -> tuple:
    """``{slug del año → (clave, nombre oficial, slug oficial)}`` + si es el camino heurístico.

    El nombre de hoja del Excel auditado se TRUNCA a 31 caracteres, así que el slug derivado
    deriva entre años y entre fuentes: hay hasta cuatro variantes de la misma compañía
    (``cuna``, ``cuna_mutual``, ``cuna_mutual_insurance_society_d``,
    ``cuna_mutual_insurance_trustage``). Este mapa las colapsa contra el roster oficial.

    Vive acá y se exporta porque **cualquier motor que consulte ``insurance_series`` por
    ``entity_slug`` lo necesita**: consultar por el slug canónico directamente no encuentra
    las series, que están guardadas bajo el slug derivado. Ese fue el defecto que dejó a
    siete aseguradoras sin Ejecución teniendo primas de cientos de millones.
    """
    from shared.data.sis_solvency_client import brand_key

    canon: Dict[str, tuple] = {}
    heuristic = not official
    for e in ents:
        if official:
            m = _match_official(brand_key(e.name), official, e.name)
            if m:
                canon[e.slug] = (m[1], m[0], m[1])  # key=slug, official name, official slug
        else:
            k = _fallback_key(e.name)
            canon[e.slug] = (k, e.name, e.slug)
    if heuristic and canon:
        # Sin roster, el nombre más largo es el de presentación por clave.
        best: Dict[str, tuple] = {}
        for e in ents:
            if e.slug not in canon:
                continue
            k = canon[e.slug][0]
            if k not in best or len(e.name or "") > len(best[k][1]):
                best[k] = (k, e.name, e.slug)
        canon = {s: best[c[0]] for s, c in canon.items()}
    return canon, heuristic


def _load_financials(db: Session) -> List[Dict[str, Any]]:
    """Assemble each insurer's latest figures from ``insurance_series``, grouped under the
    OFFICIAL roster identity (``companias-aseguradoras-y-reaseguradoras``): fragmented
    entities (audited sheet-name truncation drifts the slug across years) collapse into the
    authorized company they match, using its official name/slug. Entities that match no
    authorized company (defunct) drop out. Falls back to a heuristic key + latest-year filter
    if the roster is unavailable. Only ``entity_type='aseguradora'``."""
    from shared.data.sis_solvency_client import brand_key
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

    ents = (db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "aseguradora").all())
    if not ents:
        return []
    official = _official_index()

    canon, heuristic = _canon_map(ents, official)
    if not canon:
        return []

    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(canon)),
                    InsuranceSeries.value.isnot(None)).all())
    agg: Dict[str, Dict[str, Any]] = {}
    seen: Dict[tuple, str] = {}
    for r in rows:
        c = canon.get(r.entity_slug)
        if c is None:
            continue
        key, name, slug = c
        d = agg.setdefault(key, {"slug": slug, "name": name})
        sk = (key, r.series_code)
        if sk not in seen or r.period > seen[sk]:
            seen[sk] = r.period
            d[r.series_code] = r.value
            d["period"] = max(d.get("period", ""), r.period)
    if not agg:
        return []
    if heuristic:  # no roster → drop defunct via latest-year filter
        latest = max((str(d.get("period", ""))[:4] for d in agg.values()), default="")
        return [d for d in agg.values() if str(d.get("period", ""))[:4] == latest]
    return list(agg.values())


def compute_isf(db: Session) -> List[Dict[str, Any]]:
    """Compute the ISF per insurer from ingested audited-statement series. Empty until
    the financials sync populates ``insurance_series`` per entity — never fabricated."""
    financials = _load_financials(db)
    return score_insurers(financials) if financials else []
