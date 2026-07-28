"""Lógica compartida del informe forense (PDF y Word): humanización de fechas, tarjetas de
cifras clave, timeline de la lectura del modelo y el dictamen de legibilidad (ratios vs
fraude). Sin dependencias de render — solo transforma el ``pkg`` en estructuras que ambos
renderizadores pintan igual, para que la FORMA no divergir entre formatos."""
from __future__ import annotations

from typing import Dict, List, Optional

_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Etiquetas legibles de los códigos de alerta (para la timeline).
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


def _idx_of(series: List[Dict], iso: Optional[str]) -> Optional[int]:
    """Índice en la serie cuyo mes coincide con *iso* (compara prefijo YYYY-MM)."""
    if not iso:
        return None
    key = str(iso)[:7]
    for i, p in enumerate(series):
        if str(p["fecha"])[:7] == key:
            return i
    return None


def marker_indices(pkg: Dict) -> Dict[str, Optional[int]]:
    """Índices (en la serie) del onset del cluster y del colapso — para las marcas verticales."""
    series, bt = pkg["series"], pkg["backtest"]
    return {"onset": _idx_of(series, bt.get("onset_cluster")),
            "exit": _idx_of(series, bt.get("exit_date"))}


def stat_cards(pkg: Dict, ctx: Dict) -> List[Dict]:
    """Las 4 cifras clave del resumen ejecutivo (valor · etiqueta · tono)."""
    bt = pkg["backtest"]
    lead = bt.get("lead_months")
    onset = bt.get("onset_cluster")
    mora_max = ctx.get("morosidad_maxima_pct")
    peor_fuga = ctx.get("peor_fuga_depositos_pct")
    return [
        {"value": humanize_month(onset) if onset else "sin cluster",
         "label": "Inicio del deterioro detectable", "tone": "warn"},
        {"value": f"{lead} meses" if lead is not None else "—",
         "label": f"Anticipación al colapso ({humanize_month(bt.get('exit_date'))})", "tone": "alert"},
        {"value": f"{mora_max:.0f}%" if mora_max is not None else "—",
         "label": "Morosidad máxima", "tone": "alert"},
        {"value": f"{peor_fuga:.0f}%" if peor_fuga is not None else "—",
         "label": f"Peor fuga de depósitos ({humanize_month(ctx.get('peor_fuga_fecha'))})",
         "tone": "alert"},
    ]


def model_timeline(pkg: Dict, ctx: Dict) -> List[Dict]:
    """La lectura del backtest como secuencia temporal: gatillo · sostenido · colapso.

    Cada fila: ``{fecha, flag, tone, text}``. Generaliza a cualquier entidad — si no hubo
    cluster, la fila de gatillo lo dice (punto ciego)."""
    bt = pkg["backtest"]
    onset = bt.get("onset_cluster")
    lead = bt.get("lead_months")
    n_high = bt.get("n_high_months") or 0
    exit_iso = bt.get("exit_date")
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
            "text": ("Los ratios reportados nunca formaron un cluster de ≥2 alertas altas "
                     "simultáneas: el deterioro no fue legible en el dato contable con anticipación "
                     "(firma típica del fraude ocultado).")})

    if exit_iso:
        rows.append({
            "fecha": humanize_month(exit_iso), "flag": "COLAPSO", "tone": "alert",
            "text": ("Salida del sistema."
                     + (f" Morosidad máxima {mora_max:.0f}%: cartera prácticamente liquidada como "
                        "activo generador de valor." if mora_max is not None else ""))})
    return rows


def legibility(pkg: Dict, ctx: Dict) -> Dict:
    """Dictamen de legibilidad — el diferenciador vs Fitch: ¿los ratios vieron venir esta
    quiebra, o fue un punto ciego (fraude/contabilidad paralela)? Generaliza por entidad."""
    bt = pkg["backtest"]
    onset = bt.get("onset_cluster")
    lead = bt.get("lead_months")
    cluster = ctx.get("cluster_en_onset") or []
    tuvo_corrida = "estres_liquidez" in cluster
    legible = bool(onset and lead is not None and lead >= 3)
    if legible:
        conf = (" La fuga de depósitos confirmó la señal de crédito en el mismo corte."
                if tuvo_corrida else "")
        return {
            "legible": True,
            "title": "Los ratios vieron venir esta quiebra",
            "text": (f"El deterioro fue legible en el dato público: el cluster de señales se formó "
                     f"{lead} meses antes del colapso.{conf} Es el caso que el análisis cuantitativo "
                     "de estados financieros sí captura — la credencial dura frente a una "
                     "calificadora que solo mira el rating emitido."),
        }
    return {
        "legible": False,
        "title": "Punto ciego: los ratios no vieron esta quiebra a tiempo",
        "text": ("Los estados financieros públicos no formaron una alerta anticipada — la firma "
                 "típica del fraude ocultado (como Baninter, con contabilidad paralela) o de un "
                 "deterioro que no pasó por los ratios contables. Es la limitación DECLARADA del "
                 "método: detecta insolvencia económica, no contabilidad fraudulenta. Contra ese "
                 "flanco hacen falta señales de anomalía —crecimiento atípico, concentración, "
                 "dependencia interbancaria— como capa complementaria."),
    }
