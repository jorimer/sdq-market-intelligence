"""Gate-E sectorial report — does IAI_T rank next-year employment growth?

Spearman rank IC (with a bootstrap CI) between the branch IAI in T and Δemployment
in T+1, plus the rank IC per year and the growth spread between the top and bottom
IAI quintiles. Because the IAI contains ``sector_growth_T`` (and a level proxy of
employment), the report also gives the PARTIAL rank IC controlling for
``sector_growth_T`` — if the signal survives, it isn't merely serial inertia.

Honest by construction: the panel is small (~10 branches × ~6 year-pairs), so this
is a DIRECTIONAL validation reported with its n and CI, never grade-Basel. A weak
or null IC is a valid result and is shown as-is, not massaged.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.validation.historical import build_iai_panel, build_iai_panel_ied
from modules.sector_intel.validation.outcomes import (
    employment_by_branch, ied_by_activity, label_panel, label_panel_ied,
)
from shared.validation.control_tamano import veredicto_de_control
from shared.validation.metrics import mean_ic_with_t, spearman, spearman_bootstrap_ci


def _metricas_gate_e(labeled: List[Dict], clave: str) -> Dict:
    """El bloque de métricas del Gate E contra CUALQUIER desenlace.

    Existe porque el eje pasó a tener dos: el empleo (contra el que el IAI da nulo) y la
    inversión realizada (la que el índice sí dice anticipar). Escribir el segundo copiando
    el primero habría dejado dos cálculos que se desincronizan — la forma exacta del defecto
    «un guard existe en un motor y falta en el otro» que este repo ya acumuló siete veces.
    """
    xs = [r["iai_score"] for r in labeled]
    ys = [r[clave] for r in labeled]
    pooled_rho, pooled_lo, pooled_hi = spearman_bootstrap_ci(xs, ys)

    by_year: Dict[str, List[Dict]] = {}
    for r in labeled:
        by_year.setdefault(r["period"], []).append(r)
    per_year: List[Dict] = []
    yearly: List[float] = []
    for yr in sorted(by_year):
        rows = by_year[yr]
        rr = spearman([x["iai_score"] for x in rows], [x[clave] for x in rows])
        per_year.append({"year": yr, "n": len(rows),
                         "spearman": None if rr is None else round(rr, 3)})
        if rr is not None:
            yearly.append(round(rr, 3))
    ic = mean_ic_with_t(yearly)

    g_rows = [r for r in labeled if r.get("sector_growth") is not None]
    partial = partial_n = None
    if len(g_rows) >= 4:
        partial = _partial_spearman([r["iai_score"] for r in g_rows],
                                    [r[clave] for r in g_rows],
                                    [r["sector_growth"] for r in g_rows])
        partial_n = len(g_rows)

    return {
        "n_observations": len(labeled),
        "n_branches": len({r["branch"] for r in labeled}),
        "years": [min(by_year), max(by_year)],
        "mean_yearly_ic": ic["mean_ic"] if ic else None,
        "n_years": ic["n_years"] if ic else len(yearly),
        "ic_t_stat": ic["t_stat"] if ic else None,
        "ic_ci": [ic["ci_lo"], ic["ci_hi"]] if ic else [None, None],
        "spearman_pooled": None if pooled_rho is None else round(pooled_rho, 3),
        "spearman_pooled_ci": [None if pooled_lo is None else round(pooled_lo, 3),
                               None if pooled_hi is None else round(pooled_hi, 3)],
        "spearman_partial_growth": partial,
        "spearman_partial_n": partial_n,
        "by_year": per_year,
        "quintile_spread": _quintile_spread_by_year(by_year, clave=clave),
        # Concluyente = el IC medio anual con su intervalo de Student-t no cruza cero.
        "conclusive": bool(ic and ic["ci_lo"] is not None and ic["ci_lo"] > 0),
        "invertido": bool(ic and ic["ci_hi"] is not None and ic["ci_hi"] < 0),
    }


def _partial_spearman(x: List[float], y: List[float], z: List[float]) -> Optional[float]:
    """First-order partial rank correlation of x,y controlling for z."""
    rxy, rxz, ryz = spearman(x, y), spearman(x, z), spearman(y, z)
    if None in (rxy, rxz, ryz):
        return None
    denom = ((1 - rxz ** 2) * (1 - ryz ** 2)) ** 0.5
    return round((rxy - rxz * ryz) / denom, 3) if denom > 0 else None


def _quintile_spread_by_year(by_year: Dict[str, List[Dict]], k: int = 5,
                             clave: str = "emp_growth_next") -> Optional[Dict]:
    """Top-vs-bottom IAI k-tile outcome spread computed WITHIN each year, then averaged.

    Ranking the branches among themselves each year avoids the cross-year mixing of
    stacking all rows together (the same year-clustering bias as the pooled IC, in
    smaller magnitude). Years with fewer than ``k`` branches are skipped.
    """
    tops: List[float] = []
    bottoms: List[float] = []
    spreads: List[float] = []
    for rows in by_year.values():
        if len(rows) < k:
            continue
        pairs = sorted((r["iai_score"], r[clave]) for r in rows)
        size = len(pairs) // k
        bottom = [o for _i, o in pairs[:size]]
        top = [o for _i, o in pairs[-size:]]
        tops.append(sum(top) / len(top))
        bottoms.append(sum(bottom) / len(bottom))
        spreads.append(tops[-1] - bottoms[-1])
    if not spreads:
        return None
    return {"top_iai_mean_growth": round(sum(tops) / len(tops), 2),
            "bottom_iai_mean_growth": round(sum(bottoms) / len(bottoms), 2),
            "spread": round(sum(spreads) / len(spreads), 2),
            "n_years": len(spreads)}


# La prosa vive en constantes; las CUENTAS del panel se computan. Escrito a mano decía
# «10 ramas» en dos lugares: cierto hoy, y falso el día que el ENCFT publique una rama más o
# que una se quede sin empleo comparable. Es la misma forma del defecto que el IRMP publicó
# («5 países» contra un panel de 24) y que el eje social tenía latente.
_METODO_TITULAR = (
    "Validación DIRECCIONAL, no grado-Basilea. Mide si el IAI en T ordena el crecimiento del "
    "empleo formal por rama en T+1 (IC de rango de Spearman). TITULAR: el IC MEDIO de las "
    "cross-sections anuales, con CI de Student-t sobre la serie de IC por año (la inferencia "
    "correcta para un panel sector-año, que respeta el clustering por año). El IC apilado "
    "(pooled) se reporta como SECUNDARIO: su bootstrap remuestrea pares como si fueran "
    "independientes y sobrestima la precisión. El outcome es un CAMBIO (Δ% empleo), no un "
    "nivel; aun así se reporta el IC PARCIAL controlando por el crecimiento del sector en T "
    "(sector_growth_T) para acotar la inercia serial."
)
_METODO_RESOLUCION = (
    "manufactura local, zonas francas y minería colapsan en «Industrias» del lado del empleo"
)
_METODO_POTENCIA = (
    "Un IC inconcluso por potencia es un resultado válido y se muestra tal cual."
)


def _resolucion(n_ramas: int) -> str:
    return (f"{n_ramas} ramas de actividad (ENCFT); IAI agregado por tamaño del sector")


_METODO_DOS_DESENLACES = (
    "El eje se valida contra DOS desenlaces y no contra uno: el empleo formal (el que este "
    "bloque encabeza, por continuidad con lo ya publicado) y la INVERSIÓN realizada (IED del "
    "BCRD por actividad), que es la que el índice dice anticipar. `headline_outcome` nombra "
    "cuál de los dos sostiene una afirmación; si es `null`, ninguno la sostiene"
)


def _disclaimer(n_ramas: int, n_years: int) -> str:
    """Arma el disclaimer con el tamaño REAL del panel, no con el que tenía al escribirse."""
    return (
        f"{_METODO_TITULAR} Resolución: {n_ramas} ramas, NO 17 — {_METODO_RESOLUCION}. "
        f"Panel chico ({n_ramas} ramas × {n_years} años); con n por año ≈{n_ramas} el IC "
        f"mínimo detectable es alto. {_METODO_POTENCIA} {_METODO_DOS_DESENLACES}."
    )


def _titular(empleo: Dict, inversion: Optional[Dict]) -> Optional[str]:
    """Qué desenlace sostiene una afirmación: el concluyente; si ninguno, ninguno.

    No se elige el «mejor»: se elige el que tiene el intervalo del lado correcto de cero.
    Un titular por mayor magnitud convertiría un resultado no concluyente en una credencial.
    """
    if inversion and inversion.get("conclusive"):
        return "inversion"
    if empleo.get("conclusive"):
        return "empleo"
    return None


def _gate_e_inversion(db: Session) -> Optional[Dict]:
    """Gate E contra la IED realizada — el desenlace que el IAI sí pretende anticipar.

    Primario: la INTENSIDAD (IED_{T+1} por unidad de tamaño del sector). El nivel en
    millones lo domina cuán grande es la actividad, así que ordenar por nivel mediría
    tamaño y no atractivo; se reporta igual, como contraste declarado.

    Devuelve ``None`` —no un cero, no un bloque vacío— cuando todavía no hay panel: la
    ausencia del dato es una brecha declarada, no un resultado nulo.
    """
    panel = build_iai_panel_ied(db)
    etiquetado = label_panel_ied(panel, ied_by_activity(db))
    con_intensidad = [r for r in etiquetado if r.get("ied_intensity_next") is not None]
    if len(con_intensidad) < 3:
        return None
    primario = _metricas_gate_e(con_intensidad, "ied_intensity_next")
    contraste = _metricas_gate_e(etiquetado, "ied_next") if len(etiquetado) >= 3 else None
    # CONTROL OBLIGATORIO, no un extra. La intensidad se computa dividiendo por el tamaño, y
    # el tamaño es una VARIABLE del propio IAI: un índice que premia a los sectores grandes
    # queda mecánicamente anti-correlacionado con cualquier cosa dividida por tamaño. Sin
    # medir qué hace el tamaño SOLO contra el mismo desenlace, «el IAI ordena al revés la
    # inversión» y «el deflactor produce el signo» son indistinguibles — y son conclusiones
    # opuestas. Se computa reemplazando el score por el tamaño sobre el MISMO panel.
    solo_tamano = [{**r, "iai_score": r["sector_size"]} for r in con_intensidad]
    control = _metricas_gate_e(solo_tamano, "ied_intensity_next")
    solo_tamano_nivel = [{**r, "iai_score": r["sector_size"]}
                         for r in etiquetado if r.get("sector_size") is not None]
    control_nivel = (_metricas_gate_e(solo_tamano_nivel, "ied_next")
                     if len(solo_tamano_nivel) >= 3 else None)
    return {
        **primario,
        "que_mide": ("intensidad de inversión extranjera directa realizada en T+1 (IED por "
                     "unidad de tamaño del sector) — el desenlace que el IAI targetea"),
        "fuente": "BCRD · Flujos de IED por actividad económica (anual)",
        "resolucion": "9 actividades de IED del BCRD (cobertura parcial de los 17 sectores)",
        "contraste_nivel": contraste,
        "nota_contraste": ("el nivel de IED en millones lo domina el tamaño de la actividad; "
                           "se muestra para acotar, no como titular"),
        # El mismo desenlace, ordenado SOLO por tamaño. Es la vara contra la que se lee el
        # primario: si el tamaño solo produce el mismo signo y magnitud, el resultado es del
        # deflactor y no del índice.
        # El veredicto se COMPUTA acá y no lo infiere el lector. Este control existe desde la
        # Fase 3 y traía las dos cifras sueltas: −0,321 del índice contra −0,323 del tamaño
        # solo. Un cliente que lee el catálogo no tiene por qué deducir de esos dos números
        # que el índice no agrega nada — esa frase es la conclusión, y las conclusiones se
        # computan. Misma regla del empate que los otros siete motores, importada.
        "control_solo_tamano": {
            "intensidad": {**control,
                           **veredicto_de_control(primario.get("mean_yearly_ic"),
                                                  primario.get("ic_ci"),
                                                  (control or {}).get("mean_yearly_ic"))},
            "nivel": ({**control_nivel,
                       **veredicto_de_control((contraste or {}).get("mean_yearly_ic"),
                                              (contraste or {}).get("ic_ci"),
                                              (control_nivel or {}).get("mean_yearly_ic"))}
                      if control_nivel else None),
        },
        "nota_control": ("`sector_size` es a la vez el deflactor de la intensidad y una "
                         "variable del IAI. El control ordena el mismo desenlace usando solo "
                         "el tamaño: compará su IC con el del índice antes de atribuirle el "
                         "signo al índice."),
    }


def gate_e_report(db: Session) -> Dict:
    """Run the Gate-E backtest from the persisted IAI + ENCFT employment."""
    panel = build_iai_panel(db)
    labeled = label_panel(panel, employment_by_branch(db))
    if len(labeled) < 3:
        return {"has_data": False,
                "reason": "panel insuficiente con lookahead — corre sector-snapshot "
                          "y encft-empleo-sync antes del Gate E"}

    iai = [r["iai_score"] for r in labeled]
    out = [r["emp_growth_next"] for r in labeled]
    # SECONDARY (kept for transparency): the pooled Spearman over the ~60 stacked
    # sector-year pairs. Its bootstrap resamples pairs as if independent — they are
    # clustered by year (common macro shock) and sector — so it understates the CI.
    pooled_rho, pooled_lo, pooled_hi = spearman_bootstrap_ci(iai, out)

    by_year: Dict[str, List[Dict]] = {}
    for r in labeled:
        by_year.setdefault(r["period"], []).append(r)
    per_year = []
    for yr in sorted(by_year):
        rows = by_year[yr]
        rr = spearman([x["iai_score"] for x in rows], [x["emp_growth_next"] for x in rows])
        per_year.append({"year": yr, "n": len(rows),
                         "spearman": None if rr is None else round(rr, 3)})

    # HEADLINE: the classical panel IC — mean of the per-year cross-sectional rank ICs
    # with a Student-t CI over the series of yearly ICs (correct clustering by year).
    yearly = [p["spearman"] for p in per_year if p["spearman"] is not None]
    ic = mean_ic_with_t(yearly)

    # partial control on the rows where sector_growth_T exists (the first panel year
    # has no prior year → no growth); reported with its own n.
    g_rows = [r for r in labeled if r.get("sector_growth") is not None]
    partial = partial_n = None
    if len(g_rows) >= 4:
        partial = _partial_spearman([r["iai_score"] for r in g_rows],
                                    [r["emp_growth_next"] for r in g_rows],
                                    [r["sector_growth"] for r in g_rows])
        partial_n = len(g_rows)

    n_ramas = len({r["branch"] for r in labeled})
    empleo = _metricas_gate_e(labeled, "emp_growth_next")
    inversion = _gate_e_inversion(db)

    return {
        "has_data": True,
        # El desenlace de EMPLEO se conserva arriba —es el que ya está publicado y citado—
        # pero deja de ser el único: `outcomes` trae los dos y `headline_outcome` dice cuál
        # sostiene una afirmación. Ver la nota del disclaimer.
        "outcome": "crecimiento del empleo formal (Δ% T+1, ENCFT)",
        "resolution": _resolucion(n_ramas),
        **{k: v for k, v in empleo.items() if k not in ("conclusive", "invertido")},
        "spearman_pooled_note": ("pooled sobre los pares sector-año apilados (sin "
                                 "clustering año/sector) — sobrestima la precisión; "
                                 "el titular es el IC medio anual con t"),
        "outcomes": {"empleo": {**empleo,
                                "que_mide": "crecimiento del empleo formal por rama (Δ% T+1, "
                                            "ENCFT) — NO es lo que el IAI dice anticipar"},
                     **({"inversion": inversion} if inversion else {})},
        "headline_outcome": _titular(empleo, inversion),
        # QUÉ desenlace targetea el índice. Es un hecho de DISEÑO y no el veredicto de la
        # última corrida: `headline_outcome` dice cuál sostiene una afirmación —y puede ser
        # None— mientras que éste dice cuál hay que MIRAR aunque no concluya. Sin la
        # distinción, un consumidor que no encuentra titular cae al primer bloque que haya,
        # y acá el primero es el de empleo: el que este mismo reporte declara que «NO es lo
        # que el IAI dice anticipar». Le pasó a la tabla comercial.
        "outcome_primario": "inversion" if inversion else "empleo",
        "disclaimer": _disclaimer(n_ramas, empleo["n_years"] or 0),
    }
