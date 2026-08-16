"""¿La concentración top-10 anticipa el deterioro de cartera? — la calibración que falta.

Por qué contra OTRA etiqueta. Los siete pesos de ``early_warning.ALERT_WEIGHTS`` se calibran
contra entidades que SALIERON del sistema, y esa cohorte vive en el ledger contable histórico,
donde la concentración en los diez mayores deudores no existe: es una divulgación de
supervisión, no una línea del balance (ver ``sib_basel_reconstruction`` para el caso análogo
de Basilea, que SÍ se pudo reconstruir porque es una transformación de cantidades del balance
— la concentración no lo es: ninguna operación sobre agregados devuelve la cola de una
distribución entre deudores).

La ventana donde el top-10 SÍ existe (2021→) no tiene quiebras contra las cuales medirlo. Pero
sí tiene deterioro de cartera observable, que es el desenlace que la concentración debería
anticipar según su propio mecanismo: si la exposición descansa en pocas contrapartes, el
incumplimiento de una se transmite a la mora del conjunto de forma no lineal.

Así que la pregunta se reformula, y el cambio de etiqueta se DECLARA: no "¿predice la
quiebra?" sino "¿anticipa el deterioro de la cartera en los próximos cuatro trimestres?".

El desenlace NO se inventa acá: se reusa ``validation.outcomes_derivation``, la definición de
distress financiero ya validada en el repo (morosidad que se duplica, solvencia bajo el piso
regulatorio, ROA negativo en dos trimestres consecutivos). Se agrega una variante ESTRICTAMENTE
crediticia —solo el salto de morosidad y los castigos— porque el mecanismo de la concentración
es de crédito: si anticipa el distress amplio pero no el crediticio, la asociación probablemente
corre por otro canal y decirlo importa más que reportar un peso.

Un peso ajustado acá NO es intercambiable con los otros siete: está medido contra otro
desenlace y sobre otra ventana. Mezclarlos en un mismo índice sin declararlo sería fabricar
coherencia. Por eso este módulo devuelve la evidencia, no un número para pegar en
``ALERT_WEIGHTS``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.banking.concentracion_calibration")

HORIZONTE_Q = 4          # trimestres hacia adelante en que se observa el desenlace
MOROSIDAD_SALTO = 1.5    # la mora crece 50% o más → deterioro crediticio
CASTIGOS_SALTO_PP = 0.5  # …o los castigos suben medio punto de la cartera
SOLVENCIA_PISO = 10.0    # mismo piso regulatorio que usa outcomes_derivation


@dataclass(frozen=True)
class Evidencia:
    """Resultado de UNA especificación. Nunca un peso suelto: el peso sin su n, su AUC y su
    intervalo es exactamente la clase de cifra que este trabajo vino a dejar de producir."""
    etiqueta: str            # qué desenlace se midió
    n_obs: int
    n_eventos: int
    n_entidades: int
    coef_estandarizado: Optional[float]
    odds_ratio: Optional[float]
    auc_loeo: Optional[float]
    ic95: Optional[Tuple[float, float]]
    identificable: bool
    motivo: Optional[str]    # por qué NO es identificable, cuando no lo es


def _serie(entidad: Dict, clave: str) -> Dict[date, float]:
    out: Dict[date, float] = {}
    for k, v in (entidad.get(clave) or {}).items():
        if v is None:
            continue
        try:
            y, m, d = str(k).split("-")
            out[date(int(y), int(m), int(d))] = float(v)
        except (ValueError, TypeError):
            continue
    return out


def deterioro_crediticio(mora: Dict[date, float], castigos: Dict[date, float],
                         base: date, horizonte: Sequence[date]) -> bool:
    """Deterioro ESTRICTAMENTE de crédito: el canal por el que la concentración debería
    operar. Distinto del distress amplio de ``outcomes_derivation``, que incluye solvencia y
    rentabilidad — si la señal aparece allá y no acá, el canal es otro."""
    m0 = mora.get(base)
    if m0 is not None and m0 > 0:
        if any(mora.get(p, 0.0) >= MOROSIDAD_SALTO * m0 for p in horizonte):
            return True
    c0 = castigos.get(base)
    if c0 is not None:
        if any(castigos.get(p, c0) - c0 >= CASTIGOS_SALTO_PP for p in horizonte):
            return True
    return False


def deterioro_amplio(mora: Dict[date, float], solv: Dict[date, float],
                     roa: Dict[date, float], base: date,
                     horizonte: Sequence[date]) -> bool:
    """Distress financiero — la definición YA VALIDADA en `validation.outcomes_derivation`,
    replicada acá sobre series (no sobre filas de DB) para poder correr contra el panel del
    API. Las reglas son las mismas: mora ×2, solvencia bajo el piso, ROA<0 en 2T seguidos."""
    m0 = mora.get(base)
    if m0 is not None and m0 > 0 and any(mora.get(p, 0.0) >= 2.0 * m0 for p in horizonte):
        return True
    if any(solv[p] < SOLVENCIA_PISO for p in horizonte if p in solv):
        return True
    neg = [p for p in horizonte if p in roa and roa[p] < 0]
    return len(neg) >= 2


def construir_matriz(panel: Dict[str, Dict], etiqueta: str = "credito"
                     ) -> Tuple[List[List[float]], List[int], List[str]]:
    """``(X, y, groups)`` con la concentración en *t* y el desenlace en *t+1..t+HORIZONTE_Q*.

    Se exige que la observación base y TODO su horizonte existan: sin el horizonte completo no
    se sabe si el desenlace no ocurrió o si no se pudo observar, y contarlo como "no ocurrió"
    sesga la tasa de eventos a la baja.
    """
    X: List[List[float]] = []
    y: List[int] = []
    groups: List[str] = []
    for nombre, ent in panel.items():
        conc = _serie(ent, "concentracion_top10")
        mora = _serie(ent, "morosidad")
        cast = _serie(ent, "castigos_pct")
        solv = _serie(ent, "solvencia")
        roa = _serie(ent, "roa")
        periodos = sorted(set(conc) & set(mora))
        todos = sorted(set(conc) | set(mora) | set(solv) | set(roa))
        for base in periodos:
            i = todos.index(base)
            horizonte = todos[i + 1: i + 1 + HORIZONTE_Q]
            if len(horizonte) < HORIZONTE_Q:
                continue
            evento = (deterioro_crediticio(mora, cast, base, horizonte)
                      if etiqueta == "credito"
                      else deterioro_amplio(mora, solv, roa, base, horizonte))
            X.append([conc[base], mora[base]])
            y.append(1 if evento else 0)
            groups.append(nombre)
    return X, y, groups


def calibrar(panel: Dict[str, Dict], etiqueta: str = "credito") -> Evidencia:
    """Regresión logística de deterioro sobre concentración, CONTROLANDO por la morosidad de
    partida — sin ese control, una asociación positiva podría ser solo que las entidades ya
    deterioradas están más concentradas, que es la dirección contraria de la causalidad que
    se quiere medir.

    Devuelve ``identificable=False`` con su motivo cuando el panel no sostiene una conclusión.
    Es el resultado más probable y el más importante de reportar bien: un peso ajustado sobre
    cinco eventos no es un peso, es ruido con decimales.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    X, y, g = construir_matriz(panel, etiqueta)
    Xa, ya, ga = np.asarray(X, float), np.asarray(y), np.asarray(g)
    n_ev = int(ya.sum()) if ya.size else 0
    n_ent = len(set(ga.tolist())) if ga.size else 0
    base = Evidencia(etiqueta=etiqueta, n_obs=len(y), n_eventos=n_ev, n_entidades=n_ent,
                     coef_estandarizado=None, odds_ratio=None, auc_loeo=None, ic95=None,
                     identificable=False, motivo=None)
    if n_ev < 10 or (len(y) - n_ev) < 10:
        return Evidencia(**{**base.__dict__,
                            "motivo": f"eventos insuficientes ({n_ev} de {len(y)} obs)"})
    if len({e for e, lab in zip(ga.tolist(), ya.tolist()) if lab == 1}) < 5:
        return Evidencia(**{**base.__dict__,
                            "motivo": "los eventos se concentran en menos de 5 entidades"})

    Xs = StandardScaler().fit_transform(Xa)
    clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(Xs, ya)
    coef = float(clf.coef_[0][0])          # el de la concentración

    # IC bootstrap por ENTIDAD: remuestrear observaciones trataría 20 trimestres del mismo
    # banco como 20 datos independientes y estrecharía el intervalo de forma falsa.
    rng = np.random.default_rng(0)
    entidades = np.array(sorted(set(ga.tolist())))
    coefs: List[float] = []
    for _ in range(400):
        muestra = rng.choice(entidades, size=len(entidades), replace=True)
        idx = np.concatenate([np.where(ga == e)[0] for e in muestra])
        yb = ya[idx]
        if yb.sum() < 5 or (len(yb) - yb.sum()) < 5:
            continue
        try:
            coefs.append(float(LogisticRegression(max_iter=1000, class_weight="balanced")
                               .fit(Xs[idx], yb).coef_[0][0]))
        except Exception:  # noqa: BLE001 — una remuestra degenerada no invalida el bootstrap
            continue
    ic = ((float(np.percentile(coefs, 2.5)), float(np.percentile(coefs, 97.5)))
          if len(coefs) >= 100 else None)

    preds = np.zeros(len(ya))
    for e in set(ga.tolist()):
        tr, te = ga != e, ga == e
        if ya[tr].sum() < 5:
            continue
        preds[te] = (LogisticRegression(max_iter=2000, class_weight="balanced")
                     .fit(Xs[tr], ya[tr]).predict_proba(Xs[te])[:, 1])
    auc = float(roc_auc_score(ya, preds)) if len(set(ya.tolist())) > 1 else None

    # Identificable = el intervalo no cruza cero. Si lo cruza, el dato no distingue la
    # asociación del azar y NO hay peso que publicar, por más que el punto sea positivo.
    identificable = bool(ic and (ic[0] > 0 or ic[1] < 0))
    return Evidencia(
        etiqueta=etiqueta, n_obs=len(y), n_eventos=n_ev, n_entidades=n_ent,
        coef_estandarizado=round(coef, 4), odds_ratio=round(float(np.exp(coef)), 3),
        auc_loeo=None if auc is None else round(auc, 3),
        ic95=None if ic is None else (round(ic[0], 4), round(ic[1], 4)),
        identificable=identificable,
        motivo=None if identificable else "el IC95 del coeficiente cruza cero",
    )


def formato(evs: Sequence[Evidencia]) -> str:
    filas = [f"{'desenlace':22} {'obs':>5} {'eventos':>8} {'entid':>6} {'coef':>8} "
             f"{'OR':>7} {'AUC':>6}  IC95            veredicto"]
    filas.append("-" * len(filas[0]))
    for e in evs:
        ic = f"[{e.ic95[0]:+.2f},{e.ic95[1]:+.2f}]" if e.ic95 else "—"
        ver = "identificable" if e.identificable else f"NO: {e.motivo}"
        filas.append(f"{e.etiqueta:22} {e.n_obs:5} {e.n_eventos:8} {e.n_entidades:6} "
                     f"{(e.coef_estandarizado if e.coef_estandarizado is not None else 0):8.3f} "
                     f"{(e.odds_ratio or 0):7.2f} {(e.auc_loeo or 0):6.3f}  {ic:15} {ver}")
    return "\n".join(filas)
