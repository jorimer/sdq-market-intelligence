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
        curva_calibracion=tuple(curva), ordena=ordena, nivel_confiable=nivel, motivo=motivo)


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
