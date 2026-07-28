"""Lógica compartida del informe forense (PDF y Word): clasificación de la NATURALEZA de la
salida (quiebra vs otras causas), humanización de fechas, tarjetas de cifras, timeline de la
lectura del modelo y dictamen de legibilidad. Sin dependencias de render — transforma el
``pkg`` en estructuras que ambos renderizadores pintan igual, para que la FORMA no divergir.

Principio (decisión del dueño): NO todo el que sale del sistema quebró. El informe se genera
para toda entidad que salió —agrega valor— pero DEBE reflejar cuando la salida no fue quiebra
sino otras causas (fusión, absorción, cambio de nombre). El modelo ponderado lo decide leyendo
los ratios en la ventana de salida.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

ALERT_LABEL = {
    "salto_morosidad": "salto de morosidad",
    "morosidad_nivel": "morosidad sobre su tipo",
    "brecha_provisiones": "colapso de cobertura",
    "erosion_capital": "erosión de capital",
    "estres_liquidez": "fuga de depósitos",
    "crecimiento_anomalo": "expansión anómala",
    "solvencia_piso": "solvencia al piso",
    "concentracion": "concentración",
    "fondeo_caro": "fondeo caro",
}

# Umbral de morosidad "sana" por tipo de entidad (histórico → string). Espeja
# early_warning.MOROSIDAD_FLOOR_BY_TYPE pero mapeado desde el ``tipo_entidad`` del histórico.
_TIPO_FLOOR = {
    "bancos multiples": 5.0,
    "asociaciones de ahorros y prestamos": 7.0,
    "bancos de ahorro y credito": 9.0,
    "corporaciones de credito": 15.0,
}
_DEFAULT_FLOOR = 7.0

# Naturalezas de la salida.
QUIEBRA = "quiebra"
NO_QUIEBRA = "no_quiebra"
INDETERMINADA = "indeterminada"


def humanize_month(iso: Optional[str]) -> str:
    """'2002-07-01' | '2002-07' → 'jul 2002'. '2002' → '2002'. None → '—'."""
    if not iso:
        return "—"
    parts = str(iso).split("-")
    year = parts[0]
    if len(parts) >= 2:
        try:
            return f"{_MESES[int(parts[1]) - 1]} {year}"
        except (ValueError, IndexError):
            return year
    return year


def _norm_tipo(tipo: Optional[str]) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", (tipo or "").lower()).encode("ascii", "ignore").decode().strip()


def _floor(tipo: Optional[str]) -> float:
    return _TIPO_FLOOR.get(_norm_tipo(tipo), _DEFAULT_FLOOR)


def _exit_ratios(series: List[Dict], n: int = 6) -> Tuple[Optional[float], Optional[float]]:
    """Morosidad y cobertura promedio en los últimos *n* meses de dato (la ventana de salida)."""
    tail = series[-n:]
    moras = [p["morosidad_pct"] for p in tail if p.get("morosidad_pct") is not None]
    cobs = [p["cobertura_pct"] for p in tail if p.get("cobertura_pct") is not None]
    mora = sum(moras) / len(moras) if moras else None
    cob = sum(cobs) / len(cobs) if cobs else None
    return mora, cob


def _idx_of(series: List[Dict], iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    key = str(iso)[:7]
    for i, p in enumerate(series):
        if str(p["fecha"])[:7] == key:
            return i
    return None


def marker_indices(pkg: Dict) -> Dict[str, Optional[int]]:
    """Índices del onset y de la salida. Si la salida OFICIAL cae más allá del último dato,
    ancla la marca al último mes reportado (la salida visible en el dato)."""
    series, bt = pkg["series"], pkg["backtest"]
    onset = _idx_of(series, bt.get("onset_cluster"))
    exit_i = _idx_of(series, bt.get("exit_date"))
    if exit_i is None and series and bt.get("exit_date"):
        # salida oficial fuera del rango del dato → usar el último mes reportado
        if str(bt["exit_date"])[:7] >= str(series[-1]["fecha"])[:7]:
            exit_i = len(series) - 1
    return {"onset": onset, "exit": exit_i}


def classify_exit(pkg: Dict, ctx: Dict) -> str:
    """Naturaleza de la salida, decidida por el modelo sobre la ventana final:
      • QUIEBRA      — en el roster curado, o hubo cluster de deterioro (onset), o salió
                       enferma (morosidad sobre su tipo / cobertura colapsada).
      • NO_QUIEBRA   — salió SANA (mora baja, cobertura sólida): fusión/absorción/renombre.
      • INDETERMINADA— desapareció sin señal clara / poco dato: posible quiebra sin confirmar.
    """
    from modules.banking_score.sib_historical_backtest import FAILED_COHORT
    meta, series, bt = pkg["meta"], pkg["series"], pkg["backtest"]
    if any(c["nombre"] == meta.get("nombre") for c in FAILED_COHORT):
        return QUIEBRA
    floor = _floor(meta.get("tipo_entidad"))
    mora_exit, cob_exit = _exit_ratios(series)
    distress = (bool(bt.get("onset_cluster"))
                or (mora_exit is not None and mora_exit >= floor)
                or (cob_exit is not None and cob_exit < 60))
    if distress:
        return QUIEBRA
    healthy = (mora_exit is not None and mora_exit < floor
               and (cob_exit is None or cob_exit >= 100))
    n_mora = sum(1 for p in series[-6:] if p.get("morosidad_pct") is not None)
    if healthy and n_mora >= 3:
        return NO_QUIEBRA
    return INDETERMINADA


def exit_label(kind: str) -> str:
    """Etiqueta de la marca vertical de salida en los gráficos."""
    return "colapso" if kind == QUIEBRA else "salida"


def headings(pkg: Dict, ctx: Dict, kind: str) -> Dict[str, str]:
    """Subtítulo de portada y veredicto (headline), adaptados a la naturaleza de la salida."""
    meta, bt = pkg["meta"], pkg["backtest"]
    nombre = meta.get("nombre", "La entidad")
    exit_h = humanize_month(bt.get("exit_date"))
    mora_exit, cob_exit = _exit_ratios(pkg["series"])
    if kind == QUIEBRA:
        onset, lead = bt.get("onset_cluster"), bt.get("lead_months")
        if onset and lead is not None and lead >= 1:
            verdict = (f"Deterioro detectable desde {humanize_month(onset)} — {lead} meses antes "
                       "del colapso.")
        elif onset and lead is not None:
            verdict = (f"El deterioro de crédito se hizo visible recién en {humanize_month(onset)}, "
                       "el mes del colapso — señal tardía, sin ventaja de anticipación.")
        else:
            verdict = ("Quiebra sin cluster de deterioro de crédito previo en el dato contable — "
                       "punto ciego típico del fraude ocultado.")
        return {"subtitle": "Anatomía de una quiebra · reconstrucción del deterioro sobre dato "
                            "mensual real", "verdict": verdict, "section": "Anatomía de la quiebra"}
    if kind == NO_QUIEBRA:
        detalle = []
        if mora_exit is not None:
            detalle.append(f"morosidad {mora_exit:.1f}%")
        if cob_exit is not None:
            detalle.append(f"cobertura {cob_exit:.0f}%")
        ratios = f" ({', '.join(detalle)})" if detalle else ""
        verdict = (f"{nombre} no quebró: al salir del sistema en {exit_h} sus ratios eran sanos"
                   f"{ratios}. La salida respondió a otras causas —fusión, absorción o cambio de "
                   "nombre—, no a insolvencia.")
        return {"subtitle": "Salida del sistema — no fue quiebra · análisis sobre dato mensual real",
                "verdict": verdict, "section": "Por qué NO fue una quiebra"}
    verdict = (f"{nombre} salió del sistema en {exit_h}. Los ratios disponibles no muestran un "
               "cluster de deterioro que confirme una quiebra; la salida pudo deberse a otras "
               "causas (fusión, absorción, renombre) o a un colapso no legible en el dato.")
    return {"subtitle": "Salida del sistema — causas no concluyentes · análisis sobre dato mensual "
                        "real", "verdict": verdict, "section": "Naturaleza de la salida"}


def stat_cards(pkg: Dict, ctx: Dict, kind: str = QUIEBRA) -> List[Dict]:
    """Las 4 cifras clave, adaptadas a la naturaleza de la salida."""
    bt = pkg["backtest"]
    exit_h = humanize_month(bt.get("exit_date"))
    mora_exit, cob_exit = _exit_ratios(pkg["series"])
    if kind == QUIEBRA:
        lead = bt.get("lead_months")
        onset = bt.get("onset_cluster")
        mora_max = ctx.get("morosidad_maxima_pct")
        peor_fuga = ctx.get("peor_fuga_depositos_pct")
        antic = (f"{lead} meses" if (lead is not None and lead >= 1)
                 else "sin anticipación" if lead is not None else "—")
        return [
            {"value": humanize_month(onset) if onset else "sin cluster",
             "label": "Inicio del deterioro detectable", "tone": "warn"},
            {"value": antic,
             "label": f"Anticipación al colapso ({exit_h})", "tone": "alert"},
            {"value": f"{mora_max:.0f}%" if mora_max is not None else "—",
             "label": "Morosidad máxima", "tone": "alert"},
            {"value": f"{peor_fuga:.0f}%" if peor_fuga is not None else "—",
             "label": f"Peor fuga de depósitos ({humanize_month(ctx.get('peor_fuga_fecha'))})",
             "tone": "alert"},
        ]
    tone = "ok" if kind == NO_QUIEBRA else "warn"
    diag = "No fue quiebra" if kind == NO_QUIEBRA else "Sin confirmar"
    return [
        {"value": exit_h, "label": "Salida del sistema", "tone": "ink"},
        {"value": f"{mora_exit:.1f}%" if mora_exit is not None else "—",
         "label": "Morosidad al salir", "tone": tone},
        {"value": f"{cob_exit:.0f}%" if cob_exit is not None else "—",
         "label": "Cobertura al salir", "tone": tone},
        {"value": diag, "label": "Diagnóstico", "tone": tone},
    ]


def model_timeline(pkg: Dict, ctx: Dict, kind: str = QUIEBRA) -> List[Dict]:
    """La lectura del modelo como secuencia. En una salida NO-quiebra, dice que el motor no
    activó ningún cluster (consistente con una salida por otras causas)."""
    bt = pkg["backtest"]
    exit_iso = bt.get("exit_date")
    if kind != QUIEBRA:
        sana = [{"fecha": "toda la serie", "flag": "SIN ALERTA", "tone": "ok",
                 "text": ("El motor de Alerta Temprana no activó ningún cluster de deterioro en "
                          "toda la serie: los ratios de crédito y liquidez se mantuvieron sanos.")}]
        sana.append({"fecha": humanize_month(exit_iso), "flag": "SALIDA", "tone": "warn",
                     "text": ("Salida del sistema no atribuible a insolvencia — patrón de fusión, "
                              "absorción o cambio de nombre." if kind == NO_QUIEBRA else
                              "Salida del sistema sin señal contable de quiebra; causa no "
                              "concluyente desde el dato.")})
        return sana

    onset = bt.get("onset_cluster")
    lead = bt.get("lead_months")
    n_high = bt.get("n_high_months") or 0
    mora_max = ctx.get("morosidad_maxima_pct")
    rows: List[Dict] = []
    if onset:
        cluster = [ALERT_LABEL.get(c, c) for c in (ctx.get("cluster_en_onset") or [])]
        conv = ", ".join(cluster) if cluster else "varias señales altas"
        rows.append({
            "fecha": humanize_month(onset), "flag": "GATILLO", "tone": "alert",
            "text": (f"Convergencia de señales ({conv}) en un solo corte → alerta roja."
                     + (f" {lead} meses de ventaja sobre el colapso." if lead is not None else ""))})
        if n_high > 1:
            rows.append({
                "fecha": f"{humanize_month(onset)} → {humanize_month(exit_iso)}",
                "flag": "SOSTENIDO", "tone": "warn",
                "text": (f"La alerta no se revierte: {n_high} meses en alerta entre el onset y el "
                         "cierre del período. El deterioro es proceso, no evento puntual.")})
    else:
        rows.append({
            "fecha": humanize_month(bt.get("first_high_raw")), "flag": "PUNTO CIEGO", "tone": "warn",
            "text": ("Los ratios reportados nunca formaron un cluster de deterioro de CRÉDITO "
                     "anticipado: el colapso no fue legible en el dato contable (firma típica del "
                     "fraude ocultado).")})
    if exit_iso:
        rows.append({
            "fecha": humanize_month(exit_iso), "flag": "COLAPSO", "tone": "alert",
            "text": ("Salida del sistema."
                     + (f" Morosidad máxima {mora_max:.0f}%: cartera prácticamente liquidada como "
                        "activo generador de valor." if mora_max is not None else ""))})
    return rows


def legibility(pkg: Dict, ctx: Dict, kind: str = QUIEBRA) -> Dict:
    """Dictamen. En una salida NO-quiebra, explica que la salida tuvo OTRAS causas (el punto
    que el dueño exige que el informe refleje)."""
    bt = pkg["backtest"]
    mora_exit, cob_exit = _exit_ratios(pkg["series"])
    if kind == NO_QUIEBRA:
        return {
            "legible": True,
            "title": "Diagnóstico: no fue una quiebra",
            "text": ("Al momento de salir del sistema la entidad presentaba ratios sanos "
                     f"(morosidad {mora_exit:.1f}%{f', cobertura {cob_exit:.0f}%' if cob_exit is not None else ''}) "
                     "y sin cluster de alerta. Ese perfil es incompatible con una insolvencia: la "
                     "salida respondió a OTRAS causas —típicamente fusión, absorción o cambio de "
                     "nombre—. El análisis se incluye por completitud del universo histórico, no "
                     "como caso de quiebra."),
        }
    if kind == INDETERMINADA:
        return {
            "legible": False,
            "title": "Diagnóstico: naturaleza de la salida no concluyente",
            "text": ("El dato disponible no permite afirmar quiebra ni descartarla: no se formó un "
                     "cluster de deterioro, pero la información es insuficiente para confirmar una "
                     "salida sana. Pudo ser fusión/renombre o un colapso no reflejado en los ratios "
                     "contables (p. ej. fraude ocultado). Se reporta como no concluyente."),
        }
    onset = bt.get("onset_cluster")
    lead = bt.get("lead_months")
    cluster = ctx.get("cluster_en_onset") or []
    tuvo_corrida = "estres_liquidez" in cluster
    if onset and lead is not None and lead >= 3:
        conf = (" La fuga de depósitos confirmó la señal de crédito en el mismo corte."
                if tuvo_corrida else "")
        return {
            "legible": True,
            "title": "Los ratios vieron venir esta quiebra",
            "text": (f"El deterioro fue legible en el dato público: el cluster de señales de crédito "
                     f"se formó {lead} meses antes del colapso.{conf} Es el caso que el análisis "
                     "cuantitativo de estados financieros sí captura — la credencial dura frente a "
                     "una calificadora que solo mira el rating emitido."),
        }
    return {
        "legible": False,
        "title": "Punto ciego: los ratios no vieron esta quiebra a tiempo",
        "text": ("Los estados financieros públicos no formaron una alerta de crédito anticipada — "
                 "la firma típica del fraude ocultado (como Baninter, con contabilidad paralela). "
                 "Es la limitación DECLARADA del método: detecta insolvencia económica, no "
                 "contabilidad fraudulenta. Contra ese flanco hacen falta señales de anomalía "
                 "—crecimiento atípico, concentración, dependencia interbancaria— complementarias."),
    }
