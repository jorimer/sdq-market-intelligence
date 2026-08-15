"""Propensión a quebrar — modelo de riesgo en tiempo discreto.

Qué cambia respecto de `ew_calibration`. Ese módulo entrena un CLASIFICADOR DE HORIZONTE
FIJO: toma una observación por entidad, H meses antes de su salida, y pregunta "¿sale en H
meses?". Eso tiene cuatro problemas para lo que el producto necesita:

  • Desperdicia el panel. Para calibrar a 24 meses usa UNA fila por entidad y descarta los
    otros doscientos meses de su historia: de 36.996 entidad-mes, la matriz usaba 1.325.
  • Trata a las entidades vivas como "no quebró", cuando son CENSURADAS: no quebraron
    todavía, que no es lo mismo.
  • Mete en la misma dicotomía a las que salieron por fusión o cambio de nombre. Contarlas
    como supervivientes sesga hacia un lado; como quiebras, hacia el otro.
  • Devuelve un índice ponderado, no una probabilidad. "Este banco tiene esta propensión a
    quebrar" es una afirmación que un índice normalizado no puede sostener.

El modelo de riesgo en tiempo discreto resuelve las cuatro. Pregunta, trimestre a trimestre:
*dado que la institución llegó viva hasta acá, ¿cuál es la probabilidad de que quiebre en el
próximo período?* Usa TODAS las entidad-período, maneja la censura, admite covariables que
cambian en el tiempo —ahí entra la trayectoria— y emite una probabilidad por período.

RIESGOS EN COMPETENCIA. Salir por quiebra y salir por fusión son desenlaces distintos. Acá
una fusión, una salida voluntaria o un renombre CENSURAN a la institución en esa fecha: deja
de estar en riesgo, y no se la cuenta ni como quiebra ni como superviviente eterna. El
renombre además no es una salida real —la institución sigue bajo otro nombre— pero se censura
igual, porque el panel la sigue con otra clave y unirlas exigiría un mapa de linaje completo.
Censurar es la opción conservadora: no inventa un evento ni una supervivencia.

DE DÓNDE SALE LA ETIQUETA. De `terminaciones`, y con la curaduría aplicada. Se reporta por
separado el ajuste sobre etiquetas CURADAS —limpio, la etiqueta viene de afuera de los
ratios— y sobre INFERIDAS —contaminado, porque la etiqueta se construye con las mismas
variables que después predicen—. Mismo estándar con que `deal_scoring` separa sus labels
ex-ante de los retrospectivos. El contaminado sirve para desarrollar; no para graduar.

GRADUACIÓN. El modelo no se comunica como predictivo hasta que su validación lo gane: el
límite inferior del IC del AUC debe superar `GRADUATION_AUC_FLOOR`, el mismo criterio y el
mismo umbral que usa `deal_scoring.validation.learning_curve`. No se gradúa por N.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.banking_score.validation.ew_calibration import (
    FEATURES,
    build_features,
    morosidad_floor,
)

logger = logging.getLogger("sdq.banking.hazard")

# Mismo umbral que la curva de aprendizaje de deal_scoring: el IC-INFERIOR del AUC debe
# superarlo. Graduar por N sería fabricación: un modelo no se comunica como predictivo hasta
# que su validación lo gane.
GRADUATION_AUC_FLOOR = 0.65
# Mínimos para una validación honesta. Debajo de esto no se reporta AUC — sería ruido.
MIN_EVENTOS = 10
MIN_ENTIDADES_CON_EVENTO = 5
# Cadencia del panel de riesgo. Trimestral: es la del dato moderno y la de la decisión.
MES_TRIMESTRAL = (3, 6, 9, 12)


@dataclass(frozen=True)
class HazardResult:
    etiqueta: str                  # "curada" | "inferida"
    n_periodos: int                # filas entidad-período en riesgo
    n_eventos: int
    n_entidades: int
    n_entidades_con_evento: int
    auc: Optional[float]
    auc_ic95: Optional[Tuple[float, float]]
    brier: Optional[float]         # calibración: no basta con ordenar bien
    coef: Dict[str, float]
    gradua: bool
    motivo: Optional[str]

    def resumen(self) -> str:
        if not self.gradua or self.auc is None or self.auc_ic95 is None:
            return f"NO gradúa — {self.motivo}"
        return (f"gradúa (AUC {self.auc:.3f}, IC inferior "
                f"{self.auc_ic95[0]:.3f} > {GRADUATION_AUC_FLOOR})")


def construir_panel_riesgo(panel: Dict[str, Dict[date, Dict]], terminaciones,
                           panel_end: date, solo_curadas: bool = False
                           ) -> Tuple[List[List[float]], List[int], List[str]]:
    """Dataset entidad-período: una fila por trimestre en que la institución estuvo en riesgo.

    El evento es la quiebra en ese período. Fusión, salida voluntaria, renombre y fin del
    panel CENSURAN: la institución sale del conjunto en riesgo sin aportar un evento.
    """
    por_nombre = {t.entidad_nombre: t for t in terminaciones}
    X: List[List[float]] = []
    y: List[int] = []
    groups: List[str] = []
    for code, series in panel.items():
        fechas = sorted(series)
        if not fechas:
            continue
        # Runs por nombre — la institución, no el slot (ver `terminaciones.detectar`).
        runs: List[Tuple[str, List[date]]] = []
        for d in fechas:
            nom = str(series[d].get("entidad_nombre") or "")
            if runs and runs[-1][0] == nom:
                runs[-1][1].append(d)
            else:
                runs.append((nom, [d]))
        for nombre, ds in runs:
            t = por_nombre.get(nombre)
            if solo_curadas and (t is None or t.origen_etiqueta != "curada"):
                # Sin etiqueta curada la institución no entra: ni como riesgo ni como evento.
                # Es lo que hace que el ajuste "curado" sea limpio, aunque chico.
                continue
            if t is not None and t.naturaleza == "no_evaluable" and not t.causa_curada:
                continue      # no se sabe qué fue; no aporta ni evento ni supervivencia
            es_quiebra = bool(t and t.es_quiebra)
            floor = morosidad_floor(series[ds[-1]].get("tipo_entidad"))
            trimestrales = [d for d in ds if d.month in MES_TRIMESTRAL]
            if not trimestrales:
                continue
            # El evento va en el último período TRIMESTRAL observado, no en el mes exacto de
            # la salida: Baninter sale en mayo y Bancrédito en diciembre, y exigir que el mes
            # de salida cayera en trimestre borraba silenciosamente cuatro de las siete
            # quiebras curadas. La fecha de salida rara vez respeta la cadencia del panel.
            ultimo = trimestrales[-1]
            for d in trimestrales:
                fx = build_features(series, d, floor)
                if not fx:
                    continue
                # El resto de sus períodos son "estuvo en riesgo y no quebró todavía" — que
                # es exactamente la información que el clasificador de horizonte fijo tiraba.
                evento = 1 if (es_quiebra and d == ultimo) else 0
                X.append([fx[k] for k in FEATURES])
                y.append(evento)
                groups.append(nombre)
    return X, y, groups


def ajustar(panel: Dict[str, Dict[date, Dict]], terminaciones, panel_end: date,
            solo_curadas: bool = False) -> HazardResult:
    """Ajusta el hazard y decide si GRADÚA.

    Devuelve `gradua=False` con su motivo cuando el dato no sostiene la afirmación. Ese es el
    resultado esperado hoy —siete quiebras curadas no gradúan nada— y reportarlo bien vale
    más que un coeficiente con decimales.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    etiqueta = "curada" if solo_curadas else "inferida"
    X, y, g = construir_panel_riesgo(panel, terminaciones, panel_end, solo_curadas)
    Xa, ya, ga = np.asarray(X, float), np.asarray(y), np.asarray(g)
    n_ev = int(ya.sum()) if ya.size else 0
    ents = set(ga.tolist()) if ga.size else set()
    ents_ev = {e for e, lab in zip(ga.tolist(), ya.tolist()) if lab == 1} if ga.size else set()
    base: Dict[str, Any] = dict(
        etiqueta=etiqueta, n_periodos=len(y), n_eventos=n_ev, n_entidades=len(ents),
        n_entidades_con_evento=len(ents_ev), auc=None, auc_ic95=None, brier=None,
        coef={}, gradua=False, motivo=None)
    if n_ev < MIN_EVENTOS:
        return HazardResult(**{**base, "motivo": f"solo {n_ev} eventos (mínimo {MIN_EVENTOS})"})
    if len(ents_ev) < MIN_ENTIDADES_CON_EVENTO:
        return HazardResult(**{**base,
                               "motivo": f"los eventos vienen de {len(ents_ev)} entidades "
                                         f"(mínimo {MIN_ENTIDADES_CON_EVENTO})"})

    Xs = StandardScaler().fit_transform(Xa)
    clf = LogisticRegression(max_iter=3000, class_weight="balanced").fit(Xs, ya)
    coef = {k: round(float(c), 4) for k, c in zip(FEATURES, clf.coef_[0])}

    # Validación leave-one-ENTITY-out: dos trimestres del mismo banco no son independientes.
    preds = np.zeros(len(ya))
    for e in ents:
        tr, te = ga != e, ga == e
        if ya[tr].sum() < 3:
            continue
        preds[te] = (LogisticRegression(max_iter=3000, class_weight="balanced")
                     .fit(Xs[tr], ya[tr]).predict_proba(Xs[te])[:, 1])
    auc = float(roc_auc_score(ya, preds)) if len(set(ya.tolist())) > 1 else None
    brier = float(brier_score_loss(ya, preds))

    # IC del AUC por bootstrap DE ENTIDADES, no de períodos.
    rng = np.random.default_rng(0)
    ent_arr = np.array(sorted(ents))
    aucs: List[float] = []
    for _ in range(400):
        muestra = rng.choice(ent_arr, size=len(ent_arr), replace=True)
        idx = np.concatenate([np.where(ga == e)[0] for e in muestra])
        if len(set(ya[idx].tolist())) < 2:
            continue
        aucs.append(float(roc_auc_score(ya[idx], preds[idx])))
    ic = ((float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5)))
          if len(aucs) >= 100 else None)

    gradua = bool(ic and ic[0] > GRADUATION_AUC_FLOOR)
    motivo = None
    if not gradua:
        motivo = (f"el IC inferior del AUC ({ic[0]:.3f}) no supera {GRADUATION_AUC_FLOOR}"
                  if ic else "no se pudo estimar el intervalo del AUC")
    # La contaminación se declara SIEMPRE, gradúe o no: sobre etiquetas inferidas el AUC está
    # inflado porque la etiqueta se construyó con las mismas variables que predicen.
    if not solo_curadas:
        motivo = ((motivo + "; ") if motivo else "") + (
            "además la etiqueta es INFERIDA de los ratios: diagnóstico contaminado, no "
            "validación")
        gradua = False
    return HazardResult(**{**base, "auc": None if auc is None else round(auc, 4),
                           "auc_ic95": None if ic is None else (round(ic[0], 4), round(ic[1], 4)),
                           "brier": round(brier, 5), "coef": coef,
                           "gradua": gradua, "motivo": motivo})


def formato(rs: Sequence[HazardResult]) -> str:
    lineas = [f"{'etiqueta':10} {'períodos':>9} {'eventos':>8} {'entidades':>10} "
              f"{'AUC':>7} {'IC95':>16} {'Brier':>8}  veredicto"]
    lineas.append("-" * len(lineas[0]))
    for r in rs:
        ic = f"[{r.auc_ic95[0]:.3f},{r.auc_ic95[1]:.3f}]" if r.auc_ic95 else "—"
        auc = f"{r.auc:.3f}" if r.auc is not None else "—"
        br = f"{r.brier:.4f}" if r.brier is not None else "—"
        lineas.append(f"{r.etiqueta:10} {r.n_periodos:9} {r.n_eventos:8} "
                      f"{r.n_entidades:10} {auc:>7} {ic:>16} {br:>8}  {r.resumen()}")
    return "\n".join(lineas)
