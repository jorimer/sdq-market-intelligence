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
from shared.validation.control_tamano import (VEREDICTO_CONTROL_NO_EVALUABLE,
                                              VEREDICTO_SCORE_SUPERA,
                                              veredicto_de_control)
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
    por_tamano = _parcial_por_tamano(by_year, clave)

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
        **por_tamano,
        "by_year": per_year,
        "quintile_spread": _quintile_spread_by_year(by_year, clave=clave),
        # Concluyente = el IC medio anual con su intervalo de Student-t no cruza cero.
        "conclusive": bool(ic and ic["ci_lo"] is not None and ic["ci_lo"] > 0),
        "invertido": bool(ic and ic["ci_hi"] is not None and ic["ci_hi"] < 0),
    }


#: Mínimo de sujetos por año para computar un parcial de primer orden que signifique algo.
#: Con menos, el parcial es aritmética sobre ruido.
_MIN_POR_ANO = 4

NOTA_PARCIAL_TAMANO = (
    "IC de rango PARCIAL: ordena el mismo desenlace con el IAI manteniendo CONSTANTE el "
    "tamaño del sector. Contesta en UN número la pregunta que el control por tamaño obliga a "
    "contestar comparando dos a ojo — «¿el índice aporta por encima del tamaño?»— y se "
    "construye igual que el titular: parcial por año y media con intervalo de Student-t sobre "
    "la serie anual, que es la inferencia que respeta el clustering por año. Ojo con lo que "
    "NO es: `sector_size` es una VARIABLE del propio IAI, así que mantenerlo constante mide "
    "el índice SIN su componente de tamaño, no un índice distinto. Un intervalo que no cruza "
    "cero por arriba es la única forma de sostener que aporta."
)


def _parcial_por_tamano(by_year: Dict[str, List[Dict]], clave: str) -> Dict:
    """El parcial controlando por TAMAÑO, por año y promediado con su intervalo.

    **Por qué existe.** El control por tamaño publica dos cifras —el IC del índice y el del
    tamaño solo— y deja la conclusión al lector. Eso funciona cuando alguien las mira; el
    2026-09-01 se citó el −0,274 sin el −0,323 de al lado y se reportó como «el índice ordena
    la inversión al revés» un resultado que la plataforma computaba como EMPATE. Dos cifras
    que hay que comparar a ojo son una conclusión sin computar, y en este repo las relaciones
    se computan.

    Se construye como el titular —parcial por año, media con t sobre la serie— y no como un
    parcial apilado: el bootstrap apilado remuestrea pares como si fueran independientes y
    sobrestima la precisión, que es justo lo que este módulo declara del ρ pooled.

    Un año sin tamaño en sus filas, o con menos de cuatro sujetos, no produce parcial y se
    cuenta: la cobertura viaja para que un parcial de 3 años no se lea como uno de 16.

    **UN AÑO SUELTO NO SIGNIFICA NADA, y eso se midió.** Con nueve sujetos y un índice que
    contiene al tamaño, el denominador del parcial de primer orden se acerca a cero y un solo
    intercambio de posiciones mueve el resultado casi de un extremo al otro: sobre una fixture
    de seis sujetos donde el parcial verdadero es ~0, un par de swaps daba −0,955. Por eso el
    titular es la MEDIA anual con su intervalo —el mismo estimador del IC de arriba— y por eso
    `by_year` no publica esta serie: invitaría a leer un año.

    Y la colinealidad perfecta —un año donde el IAI y el tamaño ordenan idéntico— no devuelve
    cero sino NADA: el parcial no existe ahí. Ese año se descarta y baja la cobertura.
    """
    anuales: List[float] = []
    for rows in by_year.values():
        con_tamano = [r for r in rows if r.get("sector_size") is not None]
        if len(con_tamano) < _MIN_POR_ANO:
            continue
        rr = _partial_spearman([r["iai_score"] for r in con_tamano],
                               [r[clave] for r in con_tamano],
                               [r["sector_size"] for r in con_tamano])
        if rr is not None:
            anuales.append(rr)
    if not anuales:
        return {"spearman_partial_size": None, "spearman_partial_size_ci": [None, None],
                "spearman_partial_size_n_years": 0,
                "aporta_sobre_el_tamano": False, "nota_partial_size": NOTA_PARCIAL_TAMANO}
    ic = mean_ic_with_t(anuales)
    lo = ic["ci_lo"] if ic else None
    return {
        "spearman_partial_size": ic["mean_ic"] if ic else None,
        "spearman_partial_size_ci": [lo, ic["ci_hi"] if ic else None],
        "spearman_partial_size_n_years": len(anuales),
        # La conclusión, COMPUTADA: solo un intervalo entero por encima de cero sostiene que
        # el índice aporta algo que el tamaño no explica.
        "aporta_sobre_el_tamano": bool(lo is not None and lo > 0),
        "nota_partial_size": NOTA_PARCIAL_TAMANO,
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
    "Validación DIRECCIONAL, no grado-Basilea. Mide si el IAI en T ordena el desenlace que "
    "encabeza este bloque, en T+1 (IC de rango de Spearman). TITULAR: el IC MEDIO de las "
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
    "El eje se valida contra DOS desenlaces y no contra uno: la INVERSIÓN realizada (IED del "
    "BCRD por actividad), que es la que el índice dice anticipar y la que encabeza este "
    "bloque, y el empleo formal, que está en `outcomes` y que el índice NO dice anticipar. "
    "`headline_outcome` nombra cuál de los dos sostiene una afirmación; si es `null`, ninguno "
    "la sostiene. Y toda cifra de este bloque viaja con `veredicto_contra_el_tamano`: sin él, "
    "«el índice ordena» y «el tamaño ordena y el índice lo copia» son indistinguibles"
)


def _disclaimer(n_ramas: int, n_years: int) -> str:
    """Arma el disclaimer con el tamaño REAL del panel, no con el que tenía al escribirse."""
    return (
        f"{_METODO_TITULAR} Resolución: {n_ramas} ramas, NO 17 — {_METODO_RESOLUCION}. "
        f"Panel chico ({n_ramas} ramas × {n_years} años); con n por año ≈{n_ramas} el IC "
        f"mínimo detectable es alto. {_METODO_POTENCIA} {_METODO_DOS_DESENLACES}."
    )


#: Claves que el encabezado republica bajo OTRO nombre o con otra forma, en vez de copiarlas
#: tal cual: `que_mide`/`resolucion` salen como `outcome`/`resolution` —los nombres que los
#: consumidores ya leen— y `control_solo_tamano` sube aplanado al del desenlace primario, con
#: su veredicto al lado. El resto se copia verbatim, y hay un test que lo exige: copiar a mano
#: un subconjunto es cómo el encabezado se desincroniza del primario sin que nada falle.
_NO_SE_COPIAN_TAL_CUAL = ("que_mide", "resolucion", "contraste_nivel", "nota_contraste",
                          "fuente", "control_solo_tamano")


def _bloque_plano(primario: Dict) -> Dict:
    """El encabezado plano del reporte, DERIVADO del desenlace primario.

    **Por qué existe.** Estas claves —`outcome`, `mean_yearly_ic`, `ic_ci`, `n_observations`—
    son las que lee cualquier consumidor que no baje a `outcomes`, y hasta el 2026-09-01
    llevaban el desenlace de EMPLEO «por continuidad con lo ya publicado», mientras
    `outcome_primario` decía `inversion` y este mismo reporte declaraba que el empleo «NO es
    lo que el IAI dice anticipar». El comentario que estaba acá ya anticipaba el fallo —«le
    pasó a la tabla comercial»— y volvió a pasar: se leyó el IC de inversión sin su control y
    se reportó como «significativamente negativa» un resultado que la plataforma computa como
    EMPATE con el tamaño. Un campo que hay que saber no leer es una trampa, no un contrato.

    **Se DERIVA y no se escribe.** Copiar las claves a mano es cómo el encabezado se
    desincroniza de `outcomes[outcome_primario]` sin que nada falle; hay un test que compara
    las dos puntas.

    **Y el veredicto contra el tamaño viaja ACÁ**, no dos niveles más abajo. Es la misma regla
    que el sujeto con el número: una cifra cuyo calificador vive en otra rama del payload se
    publica sin el calificador.
    """
    control = ((primario.get("control_solo_tamano") or {}).get("intensidad")
               if primario.get("control_solo_tamano") else None)
    plano = {k: v for k, v in primario.items() if k not in _NO_SE_COPIAN_TAL_CUAL}
    plano["outcome"] = primario.get("que_mide")
    plano["resolution"] = primario.get("resolucion")
    plano["control_solo_tamano"] = control
    # Sin control el veredicto NO es «bien»: es «no lo sé», y se dice. Un `None` mudo acá se
    # leería como que la cifra no necesita calificador, que es el defecto del `stale=null`.
    plano["veredicto_contra_el_tamano"] = (
        control.get("veredicto") if control else VEREDICTO_CONTROL_NO_EVALUABLE)
    # Y los BOOLEANOS al lado de la prosa. La UI tiene que decidir si pinta «Significativo» y
    # no puede hacerlo buscando la palabra «empate» dentro de un texto: esa prosa se traduce,
    # se reescribe y no es un contrato. Se conservan los mismos nombres que dentro del
    # control — es el mismo hecho, y dos vocabularios para el mismo hecho es cómo dos
    # superficies del documento terminan diciendo cosas distintas.
    plano["el_tamano_alcanza_al_score"] = bool(control and control.get(
        "el_tamano_alcanza_al_score"))
    plano["empata_con_el_score"] = bool(control and control.get("empata_con_el_score"))
    return plano


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


def _acuerdo_entre_instrumentos(primario: Dict, control: Dict) -> Dict:
    """¿El parcial por tamaño y el control por tamaño dicen lo MISMO?

    Son dos instrumentos para la misma pregunta —«¿el índice aporta por encima del tamaño?»—
    y podrían discrepar. Publicarlos uno al lado del otro sin decirlo deja al lector armando
    la conclusión, que es exactamente el modo de falla que motivó el parcial. Si discrepan, lo
    dice acá; y **discrepar no es un error**: el control compara MAGNITUDES de dos órdenes
    separados y el parcial mantiene el tamaño constante dentro de cada año, así que sobre un
    panel chico pueden separarse. Lo que no puede pasar es que el documento no lo mencione.
    """
    parcial_aporta = bool(primario.get("aporta_sobre_el_tamano"))
    control_aporta = (control or {}).get("veredicto") == VEREDICTO_SCORE_SUPERA
    coinciden = parcial_aporta == control_aporta
    return {
        "el_parcial_dice_que_aporta": parcial_aporta,
        "el_control_dice_que_aporta": control_aporta,
        "coinciden": coinciden,
        "nota": ("los dos instrumentos coinciden" if coinciden else
                 "los DOS instrumentos NO coinciden: el parcial por tamaño dice que el índice "
                 f"{'sí' if parcial_aporta else 'no'} aporta y el control por tamaño dice que "
                 f"{'sí' if control_aporta else 'no'}. Con un panel de este tamaño la "
                 "discrepancia es esperable —el control compara magnitudes de dos órdenes "
                 "separados y el parcial mantiene el tamaño constante dentro de cada año—, "
                 "así que NO se puede sostener la afirmación de ventaja apoyándose en uno "
                 "solo de los dos"),
    }


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
        # ¿Los dos instrumentos dicen lo mismo? Computado, no dejado al lector.
        "acuerdo_entre_los_dos_instrumentos": _acuerdo_entre_instrumentos(primario, control),
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
    empleo = {**_metricas_gate_e(labeled, "emp_growth_next"),
              "que_mide": ("crecimiento del empleo formal por rama (Δ% T+1, ENCFT) — NO es lo "
                           "que el IAI dice anticipar"),
              "resolucion": _resolucion(n_ramas)}
    inversion = _gate_e_inversion(db)

    # QUÉ desenlace targetea el índice. Es un hecho de DISEÑO y no el veredicto de la última
    # corrida: `headline_outcome` dice cuál SOSTIENE una afirmación —y puede ser None—
    # mientras que éste dice cuál hay que MIRAR aunque no concluya.
    outcomes = {"empleo": empleo, **({"inversion": inversion} if inversion else {})}
    primario_clave = "inversion" if inversion else "empleo"

    return {
        "has_data": True,
        # EL ENCABEZADO LLEVA EL PRIMARIO, derivado. Hasta el 2026-09-01 llevaba el de empleo
        # «por continuidad con lo ya publicado», y el consumidor que no bajaba a `outcomes`
        # leía el desenlace que este mismo reporte declara que el índice NO dice anticipar.
        **_bloque_plano(outcomes[primario_clave]),
        "spearman_pooled_note": ("pooled sobre los pares sector-año apilados (sin "
                                 "clustering año/sector) — sobrestima la precisión; "
                                 "el titular es el IC medio anual con t"),
        "outcomes": outcomes,
        "headline_outcome": _titular(empleo, inversion),
        "outcome_primario": primario_clave,
        "disclaimer": _disclaimer(n_ramas, empleo["n_years"] or 0),
    }
