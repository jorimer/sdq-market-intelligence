"""Assemble the rating backtest report (metrics + honesty caveats).

Deterministic and cheap (in-memory over the rating history), so it can be
recomputed on demand or on a schedule from the Operation Console.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, BankingData
from modules.banking_score.scoring.perfil_sdq import BANDAS_RESILIENCIA
from modules.banking_score.validation.metrics import (
    deterioration_rate_by_tier, gini_bootstrap_ci,
)
from modules.banking_score.validation.outcomes_derivation import (
    HORIZON_Q, derive_observations,
)
from shared.validation.metrics import monotonicity_violations

# Below this many deterioration events the Gini is too thin to lean on.
_THIN_EVENTS = 30

# La prosa vive en constantes; la BANDA y su N se computan del propio resultado. El caveat
# anterior era una frase fija —«ruido muestral en tiers intermedios»— y describía mal el
# defecto: la anomalía está en la banda SUPERIOR y con el N más grande del panel. Es la
# doctrina de que las relaciones se computan y el texto las copia, no al revés.
_CAVEAT_NO_ORDENA = (
    "La curva de deterioro por banda NO ordena el riesgo, así que la tabla por banda no se "
    "publica como ordenamiento"
)
_CAVEAT_NO_ES_RUIDO = (
    "no es ruido de un tier intermedio ni de una muestra chica: es una inversión con N "
    "grande. El score continuo sí discrimina débilmente (ver Gini y su IC); la clasificación "
    "en bandas, no"
)


# El CONTROL POR TAMAÑO. Un score que ordena entidades de tamaños muy distintos queda
# mecánicamente correlacionado con el tamaño, y el Gini no distingue «el score ordena» de «el
# tamaño ordena y el score lo copia». Medido en producción (2026-08-19): el activo total SOLO
# ordena el desenlace con +0,413, mejor que el score entero. Sin esta cifra al lado, la del
# score afirma más de lo que muestra. Mismo control que `sector_intel` publica como
# `control_solo_tamano` desde la Fase 3.
NOTA_CONTROL_TAMANO = (
    "el mismo desenlace ordenado SOLO por el activo total de la entidad, sobre el mismo "
    "panel. Es la vara contra la que se lee el Gini del score: si el tamaño solo alcanza el "
    "mismo poder, el score no está agregando nada por encima de cuán grande es la entidad"
)


#: Qué se le dice al lector del control de UNA familia. Va aparte de `NOTA_CONTROL_TAMANO`
#: porque esa habla del agregado: acá el desenlace es el de la familia, no la unión.
NOTA_EXTRA_TAMANO = (
    "activo total de la entidad al corte, contra el desenlace de ESTA familia (no contra "
    "el agregado de las tres)"
)


# Las FAMILIAS del desenlace. La unión de las tres se publicaba como un solo «distress
# financiero» y medido en producción resultó 83 % pérdidas, 22 % crédito y 0 % solvencia: una
# cifra que el lector atribuye al fenómeno que tiene en la cabeza, que no es el que domina.
# Separarlas da señales que se pueden defender de a una, con su propio N y su propio IC.
FAMILIAS_DESENLACE = (
    ("resultados", ("roa_negativo_sostenido",),
     "pérdidas sostenidas — ROA negativo en ≥2 trimestres del horizonte"),
    ("credito", ("morosidad_x2",),
     "deterioro de crédito — la morosidad al menos se duplica"),
    ("capital", ("solvencia_breach",),
     "solvencia por debajo del mínimo regulatorio de 10 %"),
)


def _senal(obs, reglas, tier_order, n_boot: int) -> Dict:
    """Discriminación del score contra UNA familia de desenlace.

    Tres estados que no son lo mismo y el reporte los distingue: **concluyente** (IC
    enteramente positivo), **invertida** (IC enteramente negativo — el score ordena al revés,
    que es un hallazgo, no una ausencia) y **no concluyente** (el IC cruza cero). Una familia
    cuya regla no disparó nunca no es ninguna de las tres: es NO EVALUABLE, y decirlo es
    distinto de decir que no discrimina.
    """
    y = [1 if set(o.triggers or ()) & set(reglas) else 0 for o in obs]
    n_ev = sum(y)
    if n_ev == 0:
        return {"n_observations": len(obs), "n_events": 0, "evaluable": False,
                "gini": None, "gini_ci": None, "conclusive": False, "invertida": False,
                "nota": "la regla no disparó en toda la ventana: no hay evidencia, ni a "
                        "favor ni en contra"}
    g, lo, hi = gini_bootstrap_ci([o.score for o in obs], y, n_boot=n_boot)
    by_tier, monotonic = deterioration_rate_by_tier([o.tier for o in obs], y, tier_order)
    return {
        "n_observations": len(obs), "n_events": n_ev, "evaluable": True,
        "event_rate": n_ev / len(obs),
        "gini": g, "gini_ci": [lo, hi] if g is not None else None,
        "conclusive": bool(g is not None and lo is not None and lo > 0),
        "invertida": bool(g is not None and hi is not None and hi < 0),
        "by_tier": by_tier, "monotonic": monotonic,
        "by_tier_ordena_riesgo": monotonic,
        "monotonic_violations": monotonicity_violations(by_tier),
    }


def senales_por_familia(obs, tier_order, n_boot: int,
                        db: Optional[Session] = None) -> Dict:
    """Una señal por familia + cuál es la titular (la concluyente con más eventos).

    Mismo contrato que seguros y pensiones (`signals` + `headline_signal`), a propósito: dos
    ejes que se leen igual se comparan sin traducir.
    """
    señales = {clave: {**_senal(obs, reglas, tier_order, n_boot), "que_mide": glosa}
               for clave, reglas, glosa in FAMILIAS_DESENLACE}
    # EL CONTROL VIAJA DENTRO DE CADA SEÑAL, pegado al Gini que acota. Estaba solo en la
    # raíz del reporte —acotando el agregado— y la credencial comercial, que publica la
    # señal TITULAR, salía sin control: `control_medido: false` en producción, en el eje
    # insignia. Mismo lugar que en seguros, pensiones, comercio e IRMP.
    if db is not None:
        for clave, reglas, _glosa in FAMILIAS_DESENLACE:
            señales[clave]["control_solo_tamano"] = control_por_familia(
                db, obs, señales[clave], reglas)
    concluyentes = [(v["n_events"], k) for k, v in señales.items() if v.get("conclusive")]
    titular = max(concluyentes)[1] if concluyentes else None
    return {"signals": señales, "headline_signal": titular}


def _activos_por_observacion(db: Session, obs) -> List[Optional[float]]:
    """El activo total de cada observación, en el MISMO orden que *obs*.

    Se extrae aparte porque ahora el control se computa una vez por FAMILIA de desenlace y
    no solo sobre el agregado: leer la base una vez por familia sería el mismo trabajo
    cuatro veces.
    """
    activos = {(str(d.bank_id), d.period_end): d.activos_totales
               for d in db.query(BankingData).all()}
    return [None if (a := activos.get((str(o.bank_id), o.period_end))) is None else float(a)
            for o in obs]


def control_por_familia(db: Session, obs, señal: Dict, reglas) -> Dict:
    """El control de UNA familia: el MISMO desenlace de esa familia, ordenado solo por activo.

    **Por qué por familia y no uno solo para todo.** El control del agregado acota la cifra
    del agregado, y la credencial comercial publica la de la señal TITULAR —que es otra—.
    Emparejar la cifra de un desenlace con el control de otro sería peor que no traer
    control: diría que se comparó cuando no. Es la misma forma que ya usan seguros,
    pensiones, comercio e IRMP: el control viaja DENTRO de su señal.

    Usa `shared.validation.control_tamano.medir_control_de_tamano` en vez de la cuenta
    propia que había acá: así trae el veredicto, la cobertura del panel y la negativa a
    comparar universos distintos, que la versión local no computaba.
    """
    from shared.validation.control_tamano import medir_control_de_tamano

    y = [1 if set(o.triggers or ()) & set(reglas) else 0 for o in obs]
    return medir_control_de_tamano(
        _activos_por_observacion(db, obs), y, señal.get("gini"),
        variable="activos_totales", nota_extra=NOTA_EXTRA_TAMANO,
        ic_del_score=señal.get("gini_ci"))


def control_solo_tamano(db: Session, obs, n_boot: int,
                        gini_del_score: Optional[float] = None,
                        ic_del_score: Optional[List] = None) -> Dict:
    """El MISMO desenlace, ordenado solo por el activo total. Con su N y su motivo si falta.

    El tamaño entra con la misma convención que el score —más activo = menos riesgo— así que
    su Gini se lee en la misma escala y se compara de frente. Las observaciones sin activo
    quedan fuera y se declaran: un control computado sobre otro universo no acota nada.
    """
    # La clave se devuelve SIEMPRE, incluso sin base: un control que desaparece cuando falta
    # su insumo deja publicada la cifra del score sin la vara que la acota, y ese silencio se
    # lee como que el control se hizo. Lo vigila `test_control_de_tamano`.
    if db is None:
        return {"gini": None, "gini_ci": None, "n": 0,
                "motivo": "sin sesión de base: el control no se pudo computar en esta corrida",
                "nota": NOTA_CONTROL_TAMANO}
    pares = [(float(a), 1 if o.deteriorated else 0)
             for o, a in zip(obs, _activos_por_observacion(db, obs)) if a]
    if not pares:
        return {"gini": None, "gini_ci": None, "n": 0,
                "motivo": "ninguna observación del panel trae activo total: el control no se "
                          "puede computar con lo que hay",
                "nota": NOTA_CONTROL_TAMANO}
    g, lo, hi = gini_bootstrap_ci([v for v, _e in pares], [e for _v, e in pares],
                                  n_boot=n_boot)
    # EL VEREDICTO, que faltaba. Sin él, el control publicaba dos Ginis y dejaba la
    # comparación a cargo del lector — y la tabla comercial, que no puede leer, lo tomaba
    # como «no evaluable». La regla vive en `shared.validation.control_tamano`: acá se
    # llama, no se reimplementa.
    from shared.validation.control_tamano import veredicto_de_control

    redondeado = None if g is None else round(g, 4)
    return {
        "gini": redondeado,
        "gini_ci": None if g is None or lo is None or hi is None else [round(lo, 4),
                                                                      round(hi, 4)],
        "n": len(pares),
        "n_sin_activo": len(obs) - len(pares),
        "variable": "activos_totales",
        "nota": NOTA_CONTROL_TAMANO,
        "gini_del_score": gini_del_score,
        **veredicto_de_control(gini_del_score, ic_del_score, redondeado),
    }


# La POBLACIÓN sobre la que se midió, que hasta ahora no viajaba con la cifra. Medido el
# 2026-08-19: 794 de las 1.693 observaciones (47 %) son entidades de intermediación cambiaria
# —que no otorgan crédito— y aportan el 63 % de los eventos. No están por descuido: el producto
# es un *Financial Entity Score* sobre todo el universo supervisado por la SIB
# (`banking_score/SPEC.md` §1). Pero un Gini citado sin decir sobre quién se midió se lee como
# discriminación entre bancos, y no es eso.
NOTA_POBLACION = (
    "el Gini se midió sobre TODO el universo supervisado por la SIB, no solo sobre bancos: el "
    "panel incluye entidades de intermediación cambiaria y fiduciarias, que no otorgan crédito "
    "y son órdenes de magnitud más chicas. Citar la cifra sin nombrar su población la hace leer "
    "como discriminación entre bancos"
)

#: Tipos de entidad SIN libro de crédito. Se nombran para poder decir qué parte del panel son,
#: no para excluirlos: están en el universo por diseño del producto.
SIN_LIBRO_DE_CREDITO = ("cambiaria", "fiduciaria")


def poblacion_del_panel(db: Session, obs) -> Dict:
    """Quién está en el panel, con su N y sus eventos. El sujeto viaja con el número.

    Se computa del propio panel —nunca se transcribe— porque la composición cambia con cada
    trimestre ingerido y una cuota escrita a mano se desincroniza en la primera corrida.
    """
    if db is None:
        return {"nota": NOTA_POBLACION,
                "motivo": "sin sesión de base: la composición no se pudo computar"}
    tipos = {str(b.id): (b.bank_type.value if hasattr(b.bank_type, "value") else str(b.bank_type))
             for b in db.query(Bank).all()}
    por_tipo: Dict[str, Dict[str, int]] = {}
    for o in obs:
        clave = tipos.get(str(o.bank_id)) or "desconocido"
        fila = por_tipo.setdefault(clave, {"n": 0, "eventos": 0})
        fila["n"] += 1
        fila["eventos"] += 1 if o.deteriorated else 0
    total = len(obs) or 1
    eventos = sum(f["eventos"] for f in por_tipo.values()) or 1
    orden = sorted(por_tipo.items(), key=lambda kv: -kv[1]["n"])
    # Los conteos se agregan sobre `por_tipo` —que es Dict[str, int]— y no sobre las filas de
    # salida, que mezclan el nombre del tipo con sus cifras. Sumar sobre un dict heterogéneo
    # es cómo un error de suma se esconde detrás de un tipo `object`.
    sin_credito_tipos = [t for t, _v in orden if t in SIN_LIBRO_DE_CREDITO]
    n_sin_credito = sum(por_tipo[t]["n"] for t in sin_credito_tipos)
    ev_sin_credito = sum(por_tipo[t]["eventos"] for t in sin_credito_tipos)
    filas = [{"tipo_de_entidad": t, **v,
              "cuota_de_observaciones": round(v["n"] / total, 4),
              "cuota_de_eventos": round(v["eventos"] / eventos, 4),
              "otorga_credito": t not in SIN_LIBRO_DE_CREDITO}
             for t, v in orden]
    return {
        "n_observaciones": len(obs),
        "por_tipo_de_entidad": filas,
        "sin_libro_de_credito": {
            "tipos": sin_credito_tipos,
            "n": n_sin_credito,
            "cuota_de_observaciones": round(n_sin_credito / total, 4),
            "cuota_de_eventos": round(ev_sin_credito / eventos, 4),
        },
        "nota": NOTA_POBLACION,
    }


def composicion_del_desenlace(obs) -> Dict:
    """Cuántos eventos aporta CADA regla del desenlace, y cuántos son exclusivos de ella.

    El desenlace «distress» es la UNIÓN de tres reglas, y el reporte las nombraba a las tres
    como si pesaran parecido. Medido en el panel de producción: la de ganancias (ROA<0
    sostenido) aporta 250 de los 301 eventos, la de crédito 66, y la de SOLVENCIA **cero** —
    nunca disparó en toda la ventana. Sin esta composición, «el score discrimina distress
    financiero» se lee como si midiera deterioro de crédito o de capital, y mide sobre todo
    persistencia de resultados.

    Una regla que no dispara no es un criterio estricto: es un criterio que no está midiendo,
    y hay que declararlo en vez de seguir listándolo.
    """
    reglas = ("morosidad_x2", "solvencia_breach", "roa_negativo_sostenido")
    total = sum(1 for o in obs if o.deteriorated)
    fuego = {r: 0 for r in reglas}
    exclusivos = {r: 0 for r in reglas}
    for o in obs:
        disparadas = tuple(o.triggers or ())
        for r in disparadas:
            if r in fuego:
                fuego[r] += 1
        if len(disparadas) == 1 and disparadas[0] in exclusivos:
            exclusivos[disparadas[0]] += 1
    return {
        "n_eventos": total,
        "por_regla": [
            {"regla": r, "eventos": fuego[r], "exclusivos": exclusivos[r],
             "cuota": round(fuego[r] / total, 4) if total else None}
            for r in reglas
        ],
        "reglas_sin_disparar": [r for r in reglas if fuego[r] == 0],
    }


def _pct(v: float) -> str:
    """Porcentaje con coma decimal: el reporte se lee en español y viaja a un PDF."""
    return f"{v * 100:.1f}".replace(".", ",") + " %"


def _caveat_de_monotonia(violaciones) -> str:
    """Nombra la inversión concreta —qué bandas, con qué tasas y qué N— o describe el hueco."""
    if not violaciones:
        return f"{_CAVEAT_NO_ORDENA}."
    v = violaciones[0]
    return (
        f"{_CAVEAT_NO_ORDENA}: «{v['mejor']}» (n={v['mejor_n']}) registra "
        f"{_pct(v['mejor_rate'])} de deterioro, por encima de «{v['peor']}» "
        f"(n={v['peor_n']}, {_pct(v['peor_rate'])}) — {_CAVEAT_NO_ES_RUIDO}."
    )


def build_backtest_report(db: Session, horizon_q: int = HORIZON_Q,
                          n_boot: int = 1000) -> Dict:
    obs = derive_observations(db, horizon_q=horizon_q)
    # Orden de mejor a peor. `BANDAS_RESILIENCIA` YA cierra con el corte 0.0 → "Frágil";
    # agregarlo otra vez duplicaba la fila de Frágil en `by_tier` (fila repetida en el
    # informe de validación publicado, y una comparación tautológica rate<=rate en la
    # monotonía). Mismo off-by-one que sacaba la fila "Frágil | 0 – 0" en Criterios §4.
    tier_order = [n for _c, n in BANDAS_RESILIENCIA]

    if not obs:
        return {
            "ok": False,
            "horizon_quarters": horizon_q,
            "n_observations": 0,
            "n_events": 0,
            "message": "No hay suficiente histórico para backtestear (faltan períodos con horizonte).",
        }

    scores = [o.score for o in obs]
    labels = [1 if o.deteriorated else 0 for o in obs]
    tiers = [o.tier for o in obs]
    n_events = sum(labels)

    g, g_lo, g_hi = gini_bootstrap_ci(scores, labels, n_boot=n_boot)
    by_tier, monotonic = deterioration_rate_by_tier(tiers, labels, tier_order)

    caveats = [
        "Validación preliminar — NO es un rating grado-Basilea ni una PD calibrada.",
        "Desenlace = distress financiero (mora que se duplica / solvencia <10% / ROA<0 "
        "sostenido), NO quiebras: el sistema bancario dominicano no registra defaults en "
        "la ventana, así que la discriminación es direccional.",
        "Se excluye a propósito el 'downgrade ≥2 bandas' como desenlace: está sesgado por "
        "el piso/techo de la escala (una entidad ya en la banda más baja no puede caer dos "
        "bandas) y produce un Gini negativo artificial; no mide deterioro real.",
        "Sin vintages de datos: la línea de tiempo usa period_end (fin de trimestre), "
        "no la fecha de publicación original. Se asume el rezago de publicación del SIB.",
    ]
    if n_events < _THIN_EVENTS:
        caveats.insert(0, f"Pocos eventos ({n_events}): el Gini es indicativo, no concluyente.")
    composicion = composicion_del_desenlace(obs)
    # Una regla declarada que aporta CERO eventos no es un criterio estricto: es un criterio
    # que no mide, y listarla como si midiera infla lo que el desenlace abarca.
    if composicion["reglas_sin_disparar"]:
        caveats.insert(0, "Reglas del desenlace que NUNCA dispararon en la ventana y por lo "
                          "tanto no aportan evidencia: "
                          + ", ".join(composicion["reglas_sin_disparar"]) + ".")
    dominante = max(composicion["por_regla"], key=lambda r: r["eventos"])
    if dominante["cuota"] and dominante["cuota"] >= 0.66:
        caveats.insert(0, f"El desenlace lo domina UNA regla: «{dominante['regla']}» aporta "
                          f"{dominante['eventos']} de los {composicion['n_eventos']} eventos "
                          f"({_pct(dominante['cuota'])}). La discriminación medida es sobre "
                          f"todo contra ese fenómeno, no contra los tres por igual.")
    familias = senales_por_familia(obs, tier_order, n_boot, db=db)
    invertidas = [k for k, v in familias["signals"].items() if v.get("invertida")]
    if invertidas:
        caveats.insert(0, "El score ordena AL REVÉS contra "
                          + ", ".join(f"«{k}»" for k in invertidas)
                          + " (IC del Gini enteramente negativo). Es un hallazgo, no una "
                            "ausencia de señal, y no debe leerse como discriminación débil.")
    poblacion = poblacion_del_panel(db, obs)
    # Si buena parte del panel no otorga crédito, decirlo es parte de la cifra. Callarlo deja
    # publicada una discriminación que el lector atribuye a bancos.
    sin_credito = (poblacion.get("sin_libro_de_credito") or {})
    if sin_credito.get("cuota_de_observaciones", 0) >= 0.10:
        caveats.insert(0, (
            f"El {_pct(sin_credito['cuota_de_observaciones'])} del panel son entidades que NO "
            f"otorgan crédito ({', '.join(sin_credito['tipos'])}), y aportan el "
            f"{_pct(sin_credito['cuota_de_eventos'])} de los eventos. Están en el universo por "
            "diseño del producto, pero la cifra no se puede leer como discriminación entre "
            "bancos."))
    control = control_solo_tamano(db, obs, n_boot, gini_del_score=g,
                                  ic_del_score=[g_lo, g_hi] if g is not None else None)
    # Si el tamaño SOLO ordena igual o mejor que el score, decirlo es el hallazgo. Callarlo
    # deja publicada una cifra que el lector atribuye al score.
    if control.get("gini") is not None and g is not None and control["gini"] >= g:
        caveats.insert(0, "El activo total SOLO ordena este desenlace con Gini "
                          f"{control['gini']}, contra {round(g, 4)} del score: sobre este "
                          "panel el score no agrega poder discriminante por encima del "
                          "tamaño de la entidad.")
    violaciones = monotonicity_violations(by_tier)
    if not monotonic:
        caveats.insert(0, _caveat_de_monotonia(violaciones))

    return {
        "ok": True,
        "horizon_quarters": horizon_q,
        "n_observations": len(obs),
        "n_events": n_events,
        "event_rate": n_events / len(obs),
        "gini": g,
        "gini_ci": [g_lo, g_hi] if g is not None else None,
        "by_tier": by_tier,
        "monotonic": monotonic,
        # Que la curva ORDENE el riesgo es una afirmación aparte de que exista: sin esto, la
        # superficie que la dibuja tiene que deducirlo, y la deducción se pierde en el camino
        # a un PDF o a una lámina.
        "by_tier_ordena_riesgo": monotonic,
        "composicion_del_desenlace": composicion,
        # La población viaja con la cifra, no en un documento aparte: un lector que ve el Gini
        # tiene que ver ahí mismo sobre quién se midió.
        "poblacion_del_panel": poblacion,
        # El control NO es un extra: viaja pegado a la cifra que acota, porque un número que
        # hay que ir a buscar a otro documento no acota nada.
        "control_solo_tamano": control,
        # El agregado se conserva porque es la cifra que ya está publicada y citada, pero
        # marcado por lo que es: la unión de tres fenómenos en proporciones muy desiguales.
        "desenlace_agregado": True,
        **familias,
        "monotonic_violations": violaciones,
        "caveats": caveats,
    }
