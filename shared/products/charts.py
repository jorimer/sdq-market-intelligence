"""Gráficos de marca para los reportes — PNG embebible en PDF y Word.

Una sola implementación (matplotlib, backend Agg) → PNG con la paleta SDQ·MIP, que tanto el
motor PDF (reportlab Image) como el Word (python-docx add_picture) embeben. Sin dependencias
nuevas (matplotlib ya está en requirements). Defensivo: ante cualquier fallo devuelve None y
el reporte se ensambla sin el gráfico (nunca rompe).
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

# Backend sin display (servidor headless) — debe fijarse antes de importar pyplot.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_NAVY = "#1A365D"
_BLUE = "#2B6CB0"
_SIGNAL = "#E11D48"
_GRID = "#E2E8F0"
_GRAY = "#718096"


def bar_chart_png(
    title: str,
    items: Sequence[Tuple[str, Optional[float]]],
    path: str,
    *,
    signed: bool = False,
    unit: str = "",
) -> Optional[str]:
    """Gráfico de barras horizontales de marca → PNG en *path*. Devuelve el path o None.

    *items* = ``[(label, value), …]`` en el orden a mostrar (se pinta de arriba a abajo).
    ``signed`` colorea positivos (navy) vs negativos (signal-red) — para contribuciones/
    crecimiento. ``unit`` se anexa a la etiqueta de valor. Valores None se omiten."""
    data = [(str(lbl), float(v)) for lbl, v in items if isinstance(v, (int, float))]
    if not data:
        return None
    try:
        labels = [d[0] for d in data]
        values = [d[1] for d in data]
        n = len(data)
        fig, ax = plt.subplots(figsize=(6.4, max(1.4, 0.42 * n + 0.6)), dpi=150)
        y = list(range(n))[::-1]  # primero arriba
        colors = [(_SIGNAL if (signed and v < 0) else _BLUE) for v in values]
        bars = ax.barh(y, values, color=colors, height=0.62, zorder=3)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9, color=_NAVY)
        ax.set_title(title, fontsize=11, color=_NAVY, fontweight="bold", loc="left", pad=10)
        ax.tick_params(length=0)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(_GRID)
        ax.xaxis.grid(True, color=_GRID, linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        if signed:
            ax.axvline(0, color=_GRAY, linewidth=0.8, zorder=2)
        vmax = max(abs(v) for v in values) or 1.0
        pad = vmax * 0.02
        for rect, v in zip(bars, values):
            ax.text(v + (pad if v >= 0 else -pad), rect.get_y() + rect.get_height() / 2,
                    f"{v:+.2f}{unit}" if signed else f"{v:.1f}{unit}",
                    va="center", ha="left" if v >= 0 else "right",
                    fontsize=8, color=_NAVY)
        ax.margins(x=0.18)
        fig.tight_layout(pad=0.6)
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path if os.path.exists(path) else None
    except Exception:  # noqa: BLE001 — un gráfico nunca debe romper el reporte
        try:
            plt.close("all")
        except Exception:  # noqa: BLE001
            pass
        return None


def render_charts(charts: Optional[List[dict]], out_dir: str, prefix: str) -> List[Tuple[str, str]]:
    """Genera los PNG de *charts* (``[{title, items, signed?, unit?}]``) en *out_dir*.

    Devuelve ``[(title, png_path)]`` solo de los que se generaron (defensivo)."""
    out: List[Tuple[str, str]] = []
    for i, ch in enumerate(charts or []):
        if not ch or not ch.get("items"):
            continue
        path = os.path.join(out_dir, f"{prefix}_chart{i}.png")
        png = bar_chart_png(ch.get("title", ""), ch["items"], path,
                            signed=bool(ch.get("signed")), unit=ch.get("unit", ""))
        if png:
            out.append((ch.get("title", ""), png))
    return out
