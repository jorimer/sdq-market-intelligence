"""IDM convergent-validity report: does the IDM rank the 10 development regions
like the PNUD regional HDI (IDHr)? Spearman + bootstrap CI + the side-by-side
ranking, with the largest divergence surfaced honestly.
"""
from typing import Dict, List, Optional, Tuple

from modules.social_dev.validation.idhr import IDHR, SOURCE
from shared.validation.control_tamano import NOTA_CONTROL, veredicto_de_control
from shared.validation.metrics import spearman_bootstrap_ci


def _latest_idm_scores(db) -> Dict[str, float]:
    """{region_slug: development_score} for the latest persisted period."""
    return _latest_idm_scores_con_periodo(db)[1]


def _latest_idm_scores_con_periodo(db) -> Tuple[Optional[str], Dict[str, float]]:
    """``(período, {region: score})``. El PERÍODO viaja porque el control por tamaño tiene
    que leer la población de ESE año, no de hoy: comparar un score de 2024 contra la
    población de 2025 sería medir dos momentos distintos."""
    from modules.social_dev.models.models import DevelopmentScore
    from modules.social_dev.service import _period_key

    rows = db.query(DevelopmentScore).all()
    if not rows:
        return None, {}
    latest = max((r.period for r in rows), key=_period_key)
    return latest, {r.entity_key: r.development_score for r in rows
                    if r.period == latest and r.development_score is not None}


def _desc_ranks(scores: Dict[str, float]) -> Dict[str, int]:
    """Rank 1 = highest score."""
    order = sorted(scores, key=lambda k: -scores[k])
    return {k: i + 1 for i, k in enumerate(order)}


# La prosa vive en constantes y el N se computa: escrito a mano decía «las mismas 10
# regiones» y «N=10», que hoy es cierto y deja de serlo en cuanto una región se quede sin
# score — el disclaimer seguiría afirmando 10 mientras la tabla muestra nueve.
_CONVERGENTE_QUE_ES = (
    "Validez CONVERGENTE (no backtest): un Gate E temporal no aplica al IDM —índice "
    "relativo cross-región cuyas variables nacionales normalizan plano—, así que se valida "
    "contra una medida INDEPENDIENTE de desarrollo: el IDH regional (IDHr) del PNUD"
)
_CONVERGENTE_LECTURA = (
    "ρ de Spearman alto = el IDM ordena el desarrollo regional como el índice oficial"
)
_CONVERGENTE_LIMITE = (
    "El IDHr es ~2010 (último regional oficial citable); los rankings regionales son "
    "estructuralmente estables, por eso la correlación de rango es válida."
)


def _disclaimer(n: int, divergencia: str) -> str:
    """Arma el disclaimer con el N real del cruce y la región que más se aparta."""
    return (
        f"{_CONVERGENTE_QUE_ES} para las mismas {n} regiones. {_CONVERGENTE_LECTURA}. "
        f"N={n} (IC ancho, honesto). La divergencia mayor es {divergencia}: el IDHr suele "
        f"encumbrar a Ozama por la dimensión de ingreso (área metropolitana), que el IDM no "
        f"captura por región. {_CONVERGENTE_LIMITE}"
    )



# ── El CONTROL POR TAMAÑO ──────────────────────────────────────────────────────
#
# `social_dev` era el ÚNICO motor del catálogo sin control por tamaño, y el motivo declarado
# era de DATO —la población por región no estaba conectada— y no de diseño. Ya lo está
# (`shared.data.sisdom_poblacion`), así que el control corresponde y se computa.
#
# Qué contesta: un ρ alto contra el IDHr NO distingue «el IDM mide desarrollo» de «las
# regiones grandes puntúan alto en las dos cosas». Son lecturas opuestas y llevan a arreglos
# incompatibles — es el mismo hallazgo que en el IAI resultó ser el deflactor y en banca que
# el activo total ordena mejor que el score entero.

#: De dónde sale el tamaño. La prosa vive en constantes: incrustada en un dict se parte por
#: ancho de línea y la frase deja de existir en el fuente aunque el valor sea correcto.
VARIABLE_DE_TAMANO = "poblacion_de_la_region"
NOTA_TAMANO = (
    "población de la región (SISDOM, cuadro 02 3 009b, proyecciones de la ONE). Son "
    "proyecciones basadas en el censo de 2010 y no en el Censo 2022: para ORDENAR regiones "
    "por tamaño —que es todo lo que hace el control— el orden es estable"
)
SIN_POBLACION = (
    "no evaluable: la población por región no está en la base para este período, así que no "
    "hay con qué ordenar por tamaño. No es «el control salió bien»"
)


def _poblacion_por_region(db, periodo: Optional[str]) -> Dict[str, float]:
    """``{region: habitantes}`` al *periodo*, o la última observación ANTERIOR.

    Nunca hacia adelante y nunca un promedio: el tamaño de una región es una magnitud que se
    arrastra, y rellenar con lo que vino después mete en el control información que en ese
    período no existía.
    """
    from modules.social_dev.models.models import SocialIndicator
    from shared.data.sisdom_poblacion import THEME

    q = db.query(SocialIndicator).filter(SocialIndicator.theme == THEME)
    if periodo:
        q = q.filter(SocialIndicator.period <= str(periodo))
    ultima: Dict[str, tuple] = {}
    for f in q.all():
        if f.value is None:
            continue
        previo = ultima.get(f.entity_key)
        if previo is None or f.period > previo[0]:
            ultima[f.entity_key] = (f.period, float(f.value))
    return {k: v for k, (_p, v) in ultima.items()}


def control_solo_tamano(db, common: List[str], rho: Optional[float],
                        ic: Optional[List], periodo: Optional[str]) -> Dict:
    """El MISMO desenlace —el IDHr— ordenado SOLO por el tamaño de la región.

    La clave se devuelve SIEMPRE, incluso sin población: un control que desaparece cuando le
    falta el insumo deja publicada la cifra del score sin la vara que la acota, y ese
    silencio se lee como que el control se hizo.

    Se compara sobre las MISMAS regiones que el score (``common``) y se exige la cobertura
    completa: un control computado sobre otro universo no acota nada. Con N=10 no hay margen
    para perder observaciones y seguir hablando del mismo panel.
    """
    base: Dict = {"variable": VARIABLE_DE_TAMANO, "metrica": "Spearman",
                  "nota": f"{NOTA_CONTROL} — {NOTA_TAMANO}",
                  "n_del_score": len(common), "periodo_de_la_poblacion": periodo}
    poblacion = _poblacion_por_region(db, periodo)
    pares = [(poblacion[k], IDHR[k]) for k in common if k in poblacion]
    if len(pares) < len(common) or len(pares) < 3:
        return {**base, "spearman": None, "spearman_ci": None, "n": len(pares),
                "comparable": False, "control_medido": False,
                "el_tamano_alcanza_al_score": False, "empata_con_el_score": False,
                "veredicto": SIN_POBLACION}
    r, lo, hi = spearman_bootstrap_ci([p for p, _y in pares], [y for _p, y in pares])
    # La regla del empate vive en UN solo lugar (`shared.validation.control_tamano`): si se
    # repitiera acá, dos motores podrían llamar «empate» a cosas distintas en el mismo
    # documento. Compara MAGNITUDES, no signos, que es lo correcto para un control.
    juicio = veredicto_de_control(rho, ic, None if r is None else round(r, 3))
    return {
        **base,
        "spearman": None if r is None else round(r, 3),
        "spearman_ci": [None if lo is None else round(lo, 2),
                        None if hi is None else round(hi, 2)],
        "n": len(pares), "comparable": True, "control_medido": r is not None,
        "spearman_del_score": rho,
        **juicio,
    }


def build_convergent_validity(db) -> Dict:
    """IDM regional ranking vs PNUD IDHr — Spearman ρ + bootstrap CI + pairs."""
    periodo, idm = _latest_idm_scores_con_periodo(db)
    common = sorted(set(idm) & set(IDHR))
    if len(common) < 3:
        return {"has_data": False, "n_regions": len(common)}

    xs = [idm[k] for k in common]
    ys = [IDHR[k] for k in common]
    rho, lo, hi = spearman_bootstrap_ci(xs, ys)

    idm_rank = _desc_ranks({k: idm[k] for k in common})
    idhr_rank = _desc_ranks({k: IDHR[k] for k in common})
    pairs = [{
        "region": k,
        "idm_score": round(idm[k], 2),
        "idm_rank": idm_rank[k],
        "idhr": IDHR[k],
        "idhr_rank": idhr_rank[k],
        "rank_diff": idm_rank[k] - idhr_rank[k],
    } for k in common]
    pairs.sort(key=lambda p: p["idhr_rank"])

    top = max(pairs, key=lambda p: abs(p["rank_diff"]))
    spearman = None if rho is None else round(rho, 3)
    ic = [None if lo is None else round(lo, 2), None if hi is None else round(hi, 2)]
    return {
        "has_data": True,
        "n_regions": len(common),
        # El control viaja PEGADO a la cifra que acota. Un número que hay que ir a buscar a
        # otro documento no se lee junto al que corrige, y entonces no corrige nada.
        "control_solo_tamano": control_solo_tamano(db, common, spearman, ic, periodo),
        "spearman": spearman,
        "spearman_ci": ic,
        "pairs": pairs,
        "source": SOURCE,
        "top_divergence": {"region": top["region"], "rank_diff": top["rank_diff"]},
        "disclaimer": _disclaimer(len(common), str(top["region"])),
    }
