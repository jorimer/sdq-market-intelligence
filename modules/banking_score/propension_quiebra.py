"""Propensión a la quiebra — el modelo que evalúa a CUALQUIER banco vivo.

Qué es y en qué se diferencia de lo que ya había. `early_warning` cuenta umbrales cruzados y
los pondera: es un tablero de monitoreo derivado de la literatura de la crisis de 2003, y sus
indicadores se diseñaron para el rating, no para predecir. Cruzar un umbral tira toda la
información del valor —una morosidad de 5.1% y una de 40% cuentan igual—, y ponderar señales
por separado asume que cada una aporta de forma independiente.

Este módulo hace la pregunta directa: dado el estado de un banco HOY, ¿cuál es su propensión
a quebrar? Se entrena sobre la cohorte curada de `validation/terminaciones` —las quiebras
reales del sistema dominicano, con causa verificada fuera de los ratios— y aprende:

  • el valor CONTINUO de cada indicador, no si cruzó un umbral;
  • las INTERACCIONES entre ellos, que es donde vive el mecanismo real. Una morosidad alta con
    cobertura alta no es lo mismo que la misma morosidad sin provisiones; una fuga de
    depósitos en un banco capitalizado no es la misma que en uno apalancado. El riesgo no es
    la suma de las señales sueltas, y un modelo aditivo no puede verlo.

CALIBRACIÓN — la parte que un índice no puede dar. Para decir "propensión de X%" hace falta
que cuando el modelo diga X%, ocurra X% de las veces. Dos trampas concretas, medidas:

  • Entrenar con ``class_weight="balanced"`` ayuda a ORDENAR con eventos raros y DESTRUYE el
    nivel: sobre este panel emite una mediana de 36.5% cuando la tasa real es 1.82%, y su
    Brier queda 10× peor que un modelo que siempre diga la tasa base. Eso no son
    probabilidades, son puntajes.
  • Y el Brier solo engaña en la dirección contraria con eventos raros: una constante del
    1.82% lo gana fácil. Por eso se reporta junto a la curva de calibración por deciles.

Se entrena sin reequilibrar y se calibra aparte, y el resultado declara AMBAS cosas: cuánto
ordena (AUC con su intervalo) y cuánto acierta el nivel (Brier contra la constante, y la
curva). Si el nivel no se sostiene, el modelo se publica como ORDENAMIENTO y lo dice.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.banking_score.validation.hazard import (
    GRADUATION_AUC_FLOOR,
    MIN_ENTIDADES_CON_EVENTO,
    MIN_EVENTOS,
    construir_panel_riesgo,
)
from modules.banking_score.validation.ew_calibration import FEATURES

logger = logging.getLogger("sdq.banking.propension")

# Pares cuya INTERACCIÓN tiene un mecanismo detrás. No se cruzan todas contra todas: con 26
# eventos, quince interacciones sobreajustan garantizado. Cada par está acá porque hay una
# razón de negocio para esperar que el efecto de uno dependa del otro.
INTERACCIONES: Tuple[Tuple[str, str, str], ...] = (
    # Mora sin provisiones que la cubran: la pérdida va directo al capital.
    ("morosidad_nivel", "brecha_provisiones", "mora sin cobertura"),
    # Fuga de depósitos en un banco que además pierde capital: el clásico de 2003.
    ("estres_liquidez", "erosion_capital", "fuga con capital cediendo"),
    # Crecimiento acelerado con la mora ya subiendo: originación que se deteriora.
    ("crecimiento_anomalo", "salto_morosidad", "crecer prestando mal"),
)

# Criterio de NIVEL: el error relativo del decil de mayor riesgo. Se juzga ahí y no por el
# Brier global porque con una tasa base de 1.8% ganarle a la constante es casi imposible
# aunque el modelo sea bueno —el Brier premia predecir siempre la base—, y porque es el decil
# superior el que se usa para decidir. En el medio de la distribución, con ~2 eventos por
# decil, lo que se mide es ruido.
ERROR_DECIL_ACEPTABLE = 0.35   # |predicho − observado| / observado en el decil superior
# Y el decil superior tiene que separarse de verdad de la tasa base, o el "orden" no sirve.
SEPARACION_MINIMA = 2.0        # veces la tasa base


@dataclass(frozen=True)
class ModeloPropension:
    """Modelo entrenado + su veredicto sobre qué puede y qué no puede afirmar."""
    features: Tuple[str, ...]
    coef: Dict[str, float]
    intercepto: float
    media: Tuple[float, ...]
    escala: Tuple[float, ...]
    tasa_base: float
    n_periodos: int
    n_eventos: int
    n_entidades: int
    auc: Optional[float]
    auc_ic95: Optional[Tuple[float, float]]
    brier: Optional[float]
    brier_constante: Optional[float]
    curva_calibracion: Tuple[Tuple[float, float, int], ...] = field(default=())
    # Dirección EMPÍRICA por variable: (media en quiebras, media en el resto, AUC univariado).
    # Es lo que permite distinguir un IMPULSOR de un CONTROL estadístico — ver `_rol`.
    perfil_univariado: Dict[str, Tuple[float, float, float]] = field(default_factory=dict)
    ordena: bool = False
    nivel_confiable: bool = False
    motivo: Optional[str] = None

    @property
    def uso_admitido(self) -> str:
        """Qué se puede afirmar con este modelo. Es la salida que importa: publicar un
        porcentaje que el modelo no sostiene es exactamente lo que hay que impedir."""
        if not self.ordena:
            return "ninguno — el modelo no supera el criterio de graduación"
        if not self.nivel_confiable:
            return ("ORDENAMIENTO — 'este banco está más expuesto que aquel'. NO publicar la "
                    "cifra como probabilidad: el nivel no está calibrado")
        return ("PROPENSIÓN por BANDA — el decil de mayor riesgo reproduce su tasa observada. "
                "La cifra se publica como banda de riesgo, no como probabilidad puntual de "
                "una entidad: en el medio de la distribución el dato es ruido")


def _matriz(X: Sequence[Sequence[float]]) -> Tuple[List[List[float]], Tuple[str, ...]]:
    """Agrega las interacciones a la matriz base. Los nombres viajan con las columnas."""
    idx = {f: i for i, f in enumerate(FEATURES)}
    nombres = list(FEATURES) + [f"{a}×{b}" for a, b, _ in INTERACCIONES]
    out = []
    for fila in X:
        extra = [fila[idx[a]] * fila[idx[b]] for a, b, _ in INTERACCIONES]
        out.append(list(fila) + extra)
    return out, tuple(nombres)


def entrenar(panel: Dict[str, Dict[date, Dict]], terminaciones, panel_end: date,
             con_interacciones: bool = True) -> ModeloPropension:
    """Entrena sobre la cohorte CURADA y decide qué puede afirmar el resultado."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    Xb, y, g = construir_panel_riesgo(panel, terminaciones, panel_end, solo_curadas=True)
    X, nombres = (_matriz(Xb) if con_interacciones else (list(Xb), tuple(FEATURES)))
    Xa, ya, ga = np.asarray(X, float), np.asarray(y), np.asarray(g)
    n_ev = int(ya.sum()) if ya.size else 0
    ents = set(ga.tolist()) if ga.size else set()
    ents_ev = ({e for e, lab in zip(ga.tolist(), ya.tolist()) if lab == 1}
               if ga.size else set())
    tasa = float(ya.mean()) if ya.size else 0.0
    vacio: Dict[str, Any] = dict(
        features=nombres, coef={}, intercepto=0.0, media=(), escala=(), tasa_base=tasa,
        n_periodos=len(y), n_eventos=n_ev, n_entidades=len(ents), auc=None, auc_ic95=None,
        brier=None, brier_constante=None)
    if n_ev < MIN_EVENTOS or len(ents_ev) < MIN_ENTIDADES_CON_EVENTO:
        return ModeloPropension(**vacio, motivo=f"eventos insuficientes ({n_ev})")

    # Perfil univariado ANTES de ajustar: qué hace cada variable por su cuenta. Sin esto no
    # se puede saber si un coeficiente narra un mecanismo o solo controla varianza ajena.
    perfil: Dict[str, Tuple[float, float, float]] = {}
    for i, nom in enumerate(nombres):
        col = Xa[:, i]
        try:
            auc_u = float(roc_auc_score(ya, col))
        except ValueError:
            auc_u = 0.5
        perfil[nom] = (round(float(col[ya == 1].mean()), 4),
                       round(float(col[ya == 0].mean()), 4), round(auc_u, 3))

    sc = StandardScaler().fit(Xa)
    Xs = sc.transform(Xa)
    # SIN class_weight: reequilibrar ayuda a ordenar y destruye el nivel. Con eventos raros la
    # regularización L2 fuerte es lo que sostiene el ajuste — 26 eventos y nueve columnas.
    clf = LogisticRegression(max_iter=5000, C=0.3).fit(Xs, ya)

    preds = np.full(len(ya), tasa)
    for e in ents:
        tr, te = ga != e, ga == e
        if ya[tr].sum() < 3:
            continue
        preds[te] = LogisticRegression(max_iter=5000, C=0.3).fit(
            Xs[tr], ya[tr]).predict_proba(Xs[te])[:, 1]
    auc = float(roc_auc_score(ya, preds)) if len(set(ya.tolist())) > 1 else None
    brier = float(brier_score_loss(ya, preds))
    brier_cte = float(np.mean((tasa - ya) ** 2))

    rng = np.random.default_rng(0)
    ent_arr = np.array(sorted(ents))
    aucs: List[float] = []
    for _ in range(400):
        m = rng.choice(ent_arr, size=len(ent_arr), replace=True)
        idx = np.concatenate([np.where(ga == e)[0] for e in m])
        if len(set(ya[idx].tolist())) < 2:
            continue
        aucs.append(float(roc_auc_score(ya[idx], preds[idx])))
    ic = ((float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5)))
          if len(aucs) >= 100 else None)

    # Curva de calibración por deciles de riesgo predicho: (predicho, observado, n).
    orden = np.argsort(preds)
    curva: List[Tuple[float, float, int]] = []
    for trozo in np.array_split(orden, 10):
        if len(trozo):
            curva.append((round(float(preds[trozo].mean()), 5),
                          round(float(ya[trozo].mean()), 5), int(len(trozo))))

    ordena = bool(ic and ic[0] > GRADUATION_AUC_FLOOR)
    # El nivel se juzga en el decil superior: es el que se usa para decidir y el único con
    # suficientes eventos para medir algo.
    nivel = False
    err_decil = None
    if curva:
        pred_top, obs_top, _ = curva[-1]
        separa = obs_top / tasa if tasa else 0.0
        err_decil = abs(pred_top - obs_top) / obs_top if obs_top else None
        nivel = bool(err_decil is not None and err_decil <= ERROR_DECIL_ACEPTABLE
                     and separa >= SEPARACION_MINIMA)
    motivo = None
    if not ordena:
        motivo = (f"el IC inferior del AUC ({ic[0]:.3f}) no supera {GRADUATION_AUC_FLOOR}"
                  if ic else "no se pudo estimar el intervalo del AUC")
    elif not nivel:
        motivo = ("el decil de mayor riesgo no reproduce su propia tasa observada dentro de "
                  f"±{ERROR_DECIL_ACEPTABLE:.0%}" if err_decil is not None else
                  "no se pudo evaluar la calibración")
    return ModeloPropension(
        features=nombres,
        coef={n: round(float(c), 4) for n, c in zip(nombres, clf.coef_[0])},
        intercepto=round(float(clf.intercept_[0]), 4),
        media=tuple(round(float(v), 6) for v in sc.mean_),
        escala=tuple(round(float(v), 6) for v in sc.scale_),
        tasa_base=round(tasa, 5), n_periodos=len(y), n_eventos=n_ev, n_entidades=len(ents),
        auc=None if auc is None else round(auc, 4),
        auc_ic95=None if ic is None else (round(ic[0], 4), round(ic[1], 4)),
        brier=round(brier, 5), brier_constante=round(brier_cte, 5),
        curva_calibracion=tuple(curva), perfil_univariado=perfil,
        ordena=ordena, nivel_confiable=nivel, motivo=motivo)


def evaluar(modelo: ModeloPropension, indicadores: Dict[str, float]) -> Dict[str, Any]:
    """La propensión de UN banco a partir de sus indicadores actuales.

    Devuelve la cifra SIEMPRE acompañada de qué se puede afirmar con ella. Un consumidor no
    debería poder tomar el número sin el uso admitido — es la misma disciplina que el error
    que viaja con la solvencia reconstruida.
    """
    import math

    if not modelo.coef:
        return {"propension": None, "uso_admitido": modelo.uso_admitido,
                "motivo": modelo.motivo}
    idx = {f: i for i, f in enumerate(FEATURES)}
    base = [float(indicadores.get(f, 0.0)) for f in FEATURES]
    fila = base + [base[idx[a]] * base[idx[b]] for a, b, _ in INTERACCIONES]
    z = modelo.intercepto
    for v, media, escala, nombre in zip(fila, modelo.media, modelo.escala, modelo.features):
        z += modelo.coef[nombre] * ((v - media) / (escala or 1.0))
    p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
    return {
        "propension": round(p, 5),
        "veces_la_base": round(p / modelo.tasa_base, 2) if modelo.tasa_base else None,
        "uso_admitido": modelo.uso_admitido,
        "publicable_como_probabilidad": modelo.nivel_confiable,
    }


# Cómo se NOMBRA cada variable cuando se explica a un comité. Los `code` internos
# —"brecha_provisiones", "estres_liquidez"— son etiquetas de motor, no conceptos de riesgo.
# Cómo se EXPRESA el valor de cada variable. Las features vienen transformadas —
# `morosidad_nivel` es "mora menos el piso de su tipo", así que un banco sano da −4.0— y
# publicar el número transformado no dice nada. Es el mismo defecto que ya apareció en la
# §Alerta Temprana: la cifra sale con su unidad o no sale.
#   (formato, sufijo, factor)  ·  el valor se multiplica por `factor` antes de formatear
EXPRESION: Dict[str, Tuple[str, str, float]] = {
    "morosidad_nivel": ("{:+.2f}", " puntos respecto del piso de su tipo", 1.0),
    "salto_morosidad": ("{:+.2f}", " puntos de mora en doce meses", 1.0),
    "brecha_provisiones": ("{:.1f}", " puntos de cobertura faltante", 1.0),
    "erosion_capital": ("{:+.2f}", " puntos de capital sobre activos en doce meses", 1.0),
    "crecimiento_anomalo": ("{:+.1f}", "% de variación interanual de activos", 100.0),
    "estres_liquidez": ("{:+.1f}", "% de variación trimestral de depósitos (signo invertido)",
                        100.0),
}


def _expresar(nombre: str, valor: float, con_unidad: bool = True) -> str:
    """La cifra con su unidad. `con_unidad=False` para las referencias que van después de la
    primera mención: repetir "puntos respecto del piso de su tipo" tres veces en una frase la
    vuelve ilegible — el mismo problema que ya apareció en la §Alerta Temprana."""
    fmt, sufijo, factor = EXPRESION.get(nombre, ("{:.2f}", "", 1.0))
    return fmt.format(valor * factor) + (sufijo if con_unidad else "")


CONCEPTOS: Dict[str, str] = {
    "morosidad_nivel": "el nivel de morosidad",
    "salto_morosidad": "el salto reciente de la morosidad",
    "brecha_provisiones": "la cobertura de provisiones",
    "erosion_capital": "la erosión del capital",
    "crecimiento_anomalo": "el ritmo de expansión del balance",
    "estres_liquidez": "la salida de depósitos",
}
# Y las interacciones se nombran por su MECANISMO, no por el producto de dos variables:
# "morosidad_nivel×brecha_provisiones" no le dice nada a nadie.
CONCEPTOS_INTERACCION: Dict[str, str] = {
    f"{a}×{b}": razon for a, b, razon in INTERACCIONES
}
# QUÉ SIGNIFICA estar del lado riesgoso de cada variable. La descomposición da el valor, el
# contraste con la cohorte y el factor —todo verificable— pero no el SENTIDO: por qué ese
# patrón mata a un banco. Eso es conocimiento de dominio y se declara acá, una vez, en vez de
# dejar que cada informe lo improvise (o que el modelo narrativo lo invente).
#
# Cada lectura se escribió mirando lo que la cohorte MUESTRA, no lo que el manual dice. Donde
# las dos difieren, se nombra la diferencia: esconderla dejaría al informe contradiciendo a la
# literatura sin avisar, que es peor que contradecirla explícitamente.
LECTURA_DE_NEGOCIO: Dict[str, str] = {
    "crecimiento_anomalo": (
        "un balance que se achica es la señal, no el que crece: los depósitos se van, la "
        "cartera se liquida y la entidad se encoge mientras muere. Conviene decirlo porque "
        "es lo contrario de lo que postula la literatura de la crisis de 2003 —la burbuja de "
        "crédito que precede al estallido—; en la cohorte dominicana ese patrón no aparece"),
    "morosidad_nivel": (
        "la mora por encima de lo habitual para su tipo de entidad es deterioro ya ocurrido y "
        "ya reconocido en el balance: no anticipa nada, confirma"),
    "salto_morosidad": (
        "lo que anticipa no es el nivel sino la velocidad: una cartera que se deteriora rápido "
        "avisa antes que una que está mal hace años"),
    "erosion_capital": (
        "el colchón que absorbe las pérdidas se está consumiendo, y a diferencia del nivel de "
        "capital —que un banco grande puede tener estructuralmente bajo y estable— la caída "
        "sostenida sí precede a la salida"),
    "estres_liquidez": (
        "la salida de depósitos es el mecanismo por el que un problema de solvencia se vuelve "
        "un problema de caja, y es lo que fuerza la intervención antes de que los ratios "
        "terminen de reflejar el daño"),
}

# Debajo de este factor multiplicativo, la contribución no cambia la conclusión y solo
# alarga el texto. Se acumula en "el resto" en vez de enumerarse.
FACTOR_MATERIAL = 1.10


# Una variable cuyo AUC univariado no se aparta de 0.5 no separa por su cuenta.
AUC_UNIVARIADO_MINIMO = 0.03      # |AUC − 0.5|

# El MECANISMO esperado de cada variable, declarado. `build_features` deja las seis en
# convención "positivo = peor", así que el mecanismo dice +1 en todas… salvo donde la
# evidencia de ESTE sistema lo contradice y hay una razón para creerle al dato.
MECANISMO_ESPERADO: Dict[str, int] = {
    "morosidad_nivel": +1,
    "salto_morosidad": +1,
    "erosion_capital": +1,
    "estres_liquidez": +1,
    # La cobertura reportada NO se comporta como protección en esta cohorte: las entidades que
    # salieron promediaban MENOS brecha (mejor cobertura) que las que sobrevivieron. La lectura
    # plausible es que mide honestidad de provisionamiento y no resguardo —un banco que difiere
    # el reconocimiento de pérdidas exhibe cobertura sana hasta el final, que es el patrón
    # Baninter—. Como no se puede sostener esa causa desde este dato, la variable se queda en
    # el modelo (quitarla baja el AUC de 0.750 a 0.713) pero NO se narra: 0 = sin mecanismo.
    "brecha_provisiones": 0,
    # El crecimiento sí tiene mecanismo, y es el CONTRARIO al de la literatura de 2003: los
    # bancos dominicanos que quebraron se contraían (−6.5% interanual promedio contra +18.5%).
    # Un balance que se achica es la señal. El dato es consistente y el mecanismo es claro.
    "crecimiento_anomalo": -1,
}


def _rol(modelo: ModeloPropension, nombre: str) -> str:
    """¿Este término narra un MECANISMO o solo controla varianza?

    Un IMPULSOR separa por su cuenta y su coeficiente apunta en la misma dirección que esa
    separación: se puede contar como causa.

    Un CONTROL no separa solo, o su coeficiente contradice lo que hace solo. Es un supresor
    —absorbe varianza que confunde a otro predictor— y su coeficiente NO es interpretable.
    Pasó de verdad con la cobertura de provisiones: AUC univariado 0.497, o sea nada, pero
    quitarla baja el modelo de 0.750 a 0.713 y lo saca de graduación. Es útil y no explica.
    Narrarla como causa producía la frase indefendible "tener las provisiones completas eleva
    la propensión a quebrar".
    """
    perfil = modelo.perfil_univariado.get(nombre)
    if not perfil:
        return "control"
    _, _, auc_u = perfil
    if abs(auc_u - 0.5) < AUC_UNIVARIADO_MINIMO:
        return "control"          # no separa por su cuenta
    esperado = MECANISMO_ESPERADO.get(nombre)
    if not esperado:
        return "control"          # sin mecanismo declarado (o declarado como no narrable)
    coef = modelo.coef.get(nombre, 0.0)
    # El coeficiente tiene que apuntar donde el mecanismo dice. Si no, el término está
    # absorbiendo varianza ajena y contarlo como causa inventa la historia que no tiene.
    return "impulsor" if (coef > 0) == (esperado > 0) else "control"


def explicar(modelo: ModeloPropension, indicadores: Dict[str, float]) -> Dict[str, Any]:
    """POR QUÉ este banco tiene esta propensión — descomposición EXACTA, no una heurística.

    En una regresión logística la contribución de cada término al log-odds es
    ``coeficiente × valor estandarizado``, y la suma más el intercepto reconstruye la
    propensión sin residuo. Eso permite atribuir el resultado con precisión en vez de
    razonar sobre los coeficientes en abstracto.

    Se expresa como FACTOR multiplicativo (``exp`` de la contribución), que es lo que un
    comité entiende: "la cobertura divide su propensión a la mitad" dice algo; "aporta −0.69
    al log-odds" no.

    Las relaciones —qué empuja hacia arriba, qué hacia abajo, cuál pesa más— se computan acá
    y el modelo narrativo las COPIA. Es la misma doctrina de siempre: el modelo acierta las
    cifras y falla las relaciones.
    """
    import math

    if not modelo.coef:
        return {"disponible": False, "motivo": modelo.motivo}
    idx = {f: i for i, f in enumerate(FEATURES)}
    base = [float(indicadores.get(f, 0.0)) for f in FEATURES]
    fila = base + [base[idx[a]] * base[idx[b]] for a, b, _ in INTERACCIONES]

    terminos: List[Dict[str, Any]] = []
    z_total = modelo.intercepto
    for v, media, escala, nombre in zip(fila, modelo.media, modelo.escala, modelo.features):
        z = (v - media) / (escala or 1.0)
        aporte = modelo.coef[nombre] * z
        z_total += aporte
        es_inter = "×" in nombre
        terminos.append({
            "nombre": nombre,
            "concepto": (CONCEPTOS_INTERACCION.get(nombre) if es_inter
                         else CONCEPTOS.get(nombre, nombre)),
            "es_interaccion": es_inter,
            "valor": round(v, 4),
            "desvios_del_promedio": round(z, 2),
            "aporte_logodds": round(aporte, 4),
            "factor": round(math.exp(aporte), 3),
        })
    p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z_total))))

    for t in terminos:
        t["rol"] = _rol(modelo, t["nombre"])
        perfil = modelo.perfil_univariado.get(t["nombre"])
        if perfil:
            t["media_en_quiebras"], t["media_en_el_resto"], t["auc_univariado"] = perfil
    # Solo los IMPULSORES se narran. Un control mejora el ajuste y no cuenta una historia:
    # atribuirle una causa es inventar el mecanismo que justamente no tiene.
    impulsores = [t for t in terminos if t["rol"] == "impulsor"]
    suben = sorted([t for t in impulsores if t["factor"] >= FACTOR_MATERIAL],
                   key=lambda t: -t["factor"])
    bajan = sorted([t for t in impulsores if t["factor"] <= 1 / FACTOR_MATERIAL],
                   key=lambda t: t["factor"])
    inters = [t for t in terminos if t["es_interaccion"]
              and abs(math.log(t["factor"] or 1)) > 0.02]
    return {
        "disponible": True,
        "propension": round(p, 5),
        "veces_la_base": round(p / modelo.tasa_base, 2) if modelo.tasa_base else None,
        "tasa_base": modelo.tasa_base,
        # sujeto-ok: cada término nombra su indicador en `concepto`; no es una cuota sobre
        # una población, es el aporte de una variable a la propensión de ESTA entidad.
        "empujan_al_alza": suben,
        "empujan_a_la_baja": bajan,
        "interacciones_activas": [t for t in inters if t.get("rol") == "impulsor"],
        "controles_no_narrables": [t["concepto"] for t in terminos if t["rol"] == "control"],
        "factor_dominante": (max(terminos, key=lambda t: abs(math.log(t["factor"] or 1)))
                             if terminos else None),
        "uso_admitido": modelo.uso_admitido,
    }


def prosa(modelo: ModeloPropension, nombre_entidad: str,
          indicadores: Dict[str, float]) -> str:
    """La explicación en prosa de negocio, anclada al MECANISMO y no al signo del coeficiente.

    La versión anterior narraba el coeficiente y decía cosas como "lo que más la eleva es la
    cobertura de provisiones" —que, leído por un analista, significa que tener provisiones
    completas te acerca a la quiebra—. Dos reglas lo evitan:

      • Solo se narran los IMPULSORES. Los controles estadísticos se nombran como tales.
      • Cada factor se explica contra lo que HICIERON las entidades que salieron del sistema,
        no contra el signo del ajuste. Así el crecimiento se cuenta bien: los bancos
        dominicanos que quebraron se estaban CONTRAYENDO (−6.5% interanual promedio, contra
        +18.5% de los que sobrevivieron), y un balance que se achica es la señal, no el que
        crece. La literatura de 2003 dice lo contrario y el dato manda.
    """
    e = explicar(modelo, indicadores)
    if not e.get("disponible"):
        return f"No hay modelo de propensión disponible: {e.get('motivo')}."
    veces = e["veces_la_base"]
    comp = ("por encima de" if veces > 1.15 else
            "por debajo de" if veces < 0.85 else "en línea con")
    partes = [
        f"{nombre_entidad} presenta una propensión estimada de {e['propension']*100:.2f}% por "
        f"trimestre, {comp} la tasa base del sistema ({e['tasa_base']*100:.2f}%)."
    ]

    def _frase(t: Dict[str, Any], sube: bool) -> str:
        mq, mr = t.get("media_en_quiebras"), t.get("media_en_el_resto")
        ref = ""
        if mq is not None and mr is not None and not t["es_interaccion"]:
            ref = (f" —las que salieron del sistema promediaban "
                   f"{_expresar(t['nombre'], mq, False)} y las que sobrevivieron "
                   f"{_expresar(t['nombre'], mr, False)}—")
        verbo = "eleva" if sube else "reduce"
        valor = (_expresar(t["nombre"], t["valor"]) if not t["es_interaccion"]
                 else f"{t['valor']:.2f}")
        return (f"{t['concepto']} en {valor}{ref}, que {verbo} la propensión por un factor "
                f"de {t['factor']:.2f}")

    def _sentido(t: Dict[str, Any]) -> str:
        lect = LECTURA_DE_NEGOCIO.get(t["nombre"])
        return f" Lo que hay detrás: {lect}." if lect else ""

    if e["empujan_al_alza"]:
        partes.append("Lo que la empuja al alza: "
                      + "; ".join(_frase(t, True) for t in e["empujan_al_alza"][:2]) + ".")
        # El sentido se da del factor DOMINANTE, no de todos: repetir la lectura de negocio
        # por cada variable convierte el párrafo en un glosario.
        partes.append(_sentido(e["empujan_al_alza"][0]).strip())
    if e["empujan_a_la_baja"]:
        partes.append("En sentido contrario: "
                      + "; ".join(_frase(t, False) for t in e["empujan_a_la_baja"][:2]) + ".")
        if not e["empujan_al_alza"]:
            partes.append(_sentido(e["empujan_a_la_baja"][0]).strip())
    if not e["empujan_al_alza"] and not e["empujan_a_la_baja"]:
        partes.append("Ningún factor se aparta materialmente del promedio del sistema: el "
                      "resultado refleja un perfil sin rasgos distintivos en ninguna dirección.")
    if e["interacciones_activas"]:
        i = max(e["interacciones_activas"], key=lambda x: abs(x["factor"] - 1))
        signo = "agrava" if i["factor"] > 1 else "atenúa"
        partes.append(f"La combinación pesa aparte de las señales sueltas: {i['concepto']} "
                      f"{signo} el cuadro por un factor de {i['factor']:.2f}.")
    if e["controles_no_narrables"]:
        partes.append(
            f"El modelo incorpora además {len(e['controles_no_narrables'])} variables como "
            "control estadístico; mejoran el ajuste pero su coeficiente no describe un "
            "mecanismo y no se interpretan como causa.")
    partes.append(f"Uso admitido: {e['uso_admitido'].split('—')[0].strip()}.")
    return " ".join(partes)


def formato(m: ModeloPropension) -> str:
    lineas = [
        f"Cohorte: {m.n_periodos} entidad-trimestre · {m.n_eventos} quiebras · "
        f"{m.n_entidades} entidades · tasa base {m.tasa_base*100:.2f}% por trimestre",
    ]
    if m.auc is not None:
        ic = f"[{m.auc_ic95[0]:.3f}, {m.auc_ic95[1]:.3f}]" if m.auc_ic95 else "—"
        lineas.append(f"Ordena: AUC {m.auc:.3f} {ic}")
        lineas.append(f"Nivel:  Brier {m.brier:.4f} vs constante {m.brier_constante:.4f}")
    lineas.append(f"USO ADMITIDO: {m.uso_admitido}")
    if m.coef:
        lineas += ["", "Coeficientes (estandarizados):"]
        for n, c in sorted(m.coef.items(), key=lambda x: -abs(x[1])):
            marca = "  ← interacción" if "×" in n else ""
            lineas.append(f"   {n:44} {c:+.3f}{marca}")
    return "\n".join(lineas)
