"""Qué cifras marcó el guard numérico, consultable en vez de encontrable por casualidad.

**El problema que resuelve.** Cuando el guard determinista marca una cifra, el motor reintenta
y —si la marca sobrevive— la narrativa queda con `guard_unsupported`. Hasta acá eso viajaba a
dos lados: un `logger.warning` (que NO es evento de Sentry, así que no lo mira nadie) y un
contador `guard_flags` en el registro de gasto, que dice cuántas fueron pero no cuáles.

Con el contador solo se sabe que el guard actuó. Con el texto se sabe QUÉ marcó, y esa es toda
la diferencia entre los dos casos que existen:

- una cifra **inventada**, que es la razón de ser del guard y del veto;
- una cifra **real dicha en otra forma** —el «69 %» redondeado, el «132 %» que era la razón
  1,32 servida—, que es un FALSO veto y además, en su variante silenciosa, borra del informe
  una observación verdadera sin que aparezca error alguno.

Los dos falsos vetos de la semana del 2026-08-24 se descubrieron porque el dueño los vio en
pantalla. Uno por informe roto es un precio caro por un dato que ya estaba en la base.

**Por qué no hay tabla nueva.** `llm_calls` ya tiene una fila por llamada al modelo, con eje,
plantilla y fecha, y una columna `detail` de JSON libre. Las marcas viven ahí. Una tabla propia
habría pedido migración y un segundo lugar donde mirar; la regla del repo es buscar si otro
módulo ya lo resolvió antes de escribir el guard número dos.

**Lo que esto NO es.** No es una medida de calidad de la narrativa: una marca que el reintento
corrigió no deja rastro acá, porque la fila registra el estado FINAL. Cuenta lo que sobrevivió,
que es exactamente lo que llega a la decisión de vetar.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.observability.models import LLMCall

#: Rango por defecto: los últimos treinta días, igual que el de gasto.
DEFAULT_DAYS = 30

#: Tope de filas leídas. Es una consulta de consola, no un export.
MAX_FILAS = 2000

#: La cifra citada, al inicio de la marca: «132%: no coincide con…» → «132%».
_CIFRA = re.compile(r"^\s*([\d.,]+\s*(?:%|pp|puntos)?)\s*:", re.I)


def _rango(desde: Optional[date], hasta: Optional[date]) -> Tuple[datetime, datetime]:
    """Rango de fechas → intervalo de instantes, con ``hasta`` inclusivo del día completo.

    Mismo criterio que ``shared/observability/spend``: tomar la fecha tal cual dejaría fuera
    el último día, que es el que más se mira, y el error sería invisible porque el total
    seguiría siendo un número plausible.
    """
    fin_dia = hasta or datetime.now(timezone.utc).date()
    ini_dia = desde or (fin_dia - timedelta(days=DEFAULT_DAYS))
    return (datetime.combine(ini_dia, time.min),
            datetime.combine(fin_dia, time.max))


def _cifra_de(marca: str) -> str:
    """La cifra citada, que es por lo que se agrupa. Sin ella, la marca entera."""
    m = _CIFRA.match(marca or "")
    return (m.group(1).strip() if m else (marca or "").strip())[:40]


def marcas_del_guard(db: Session, desde: Optional[date] = None,
                     hasta: Optional[date] = None,
                     modulo: Optional[str] = None) -> Dict[str, Any]:
    """Las cifras que el guard marcó y que sobrevivieron al reintento, agrupadas.

    Se agrupa por CIFRA y no por plantilla porque la pregunta que responde es «¿esto que
    marcamos es siempre la misma forma de decir un número?». Una cifra que se repite entre
    ejes y períodos es la firma de un falso positivo estructural: un número real que el
    contexto no sirve en la forma en que el modelo lo escribe. Una cifra que aparece una
    vez, en una sección, es lo que el guard vino a atrapar.
    """
    ini, fin = _rango(desde, hasta)
    q = (db.query(LLMCall)
         .filter(LLMCall.created_at >= ini, LLMCall.created_at <= fin,
                 LLMCall.cache_hit.is_(False)))
    if modulo:
        q = q.filter(LLMCall.module == modulo)
    filas = q.order_by(LLMCall.created_at.desc()).limit(MAX_FILAS).all()

    por_cifra: Dict[str, Dict[str, Any]] = {}
    narrativas = 0
    con_marca = 0
    for f in filas:
        det: Dict[str, Any] = f.detail if isinstance(f.detail, dict) else {}
        narrativas += 1
        marcas = det.get("guard_marcas") or []
        # `guard_flags` existe desde antes que `guard_marcas`: una fila vieja tiene el
        # contador y ninguna marca. Se cuenta igual, y se DECLARA, para que un total bajo no
        # se lea como «no pasó nada» cuando en realidad es «no lo estábamos guardando».
        if not marcas and not det.get("guard_flags"):
            continue
        con_marca += 1
        if not marcas:
            marcas = [f"(sin detalle: {det.get('guard_flags')} marca(s) previas al registro)"]
        for m in marcas:
            clave = _cifra_de(str(m))
            e = por_cifra.setdefault(clave, {
                "cifra": clave, "veces": 0, "modulos": set(), "plantillas": set(),
                "ejemplo": str(m)[:180], "ultima_vez": None,
            })
            e["veces"] += 1
            if f.module:
                e["modulos"].add(f.module)
            if f.template:
                e["plantillas"].add(f.template)
            visto = f.created_at.isoformat() if f.created_at else None
            if visto and (e["ultima_vez"] is None or visto > e["ultima_vez"]):
                e["ultima_vez"] = visto

    orden: List[Dict[str, Any]] = sorted(
        ({**e, "modulos": sorted(e["modulos"]), "plantillas": sorted(e["plantillas"])}
         for e in por_cifra.values()),
        key=lambda e: (-int(e["veces"]), str(e["cifra"])))

    return {
        "desde": ini.date().isoformat(), "hasta": fin.date().isoformat(),
        "modulo": modulo,
        "narrativas_generadas": narrativas,
        "narrativas_con_marca": con_marca,
        "cifras": orden,
        "truncado": len(filas) >= MAX_FILAS,
        "como_leerlo": (
            "Una cifra que se REPITE entre ejes, plantillas o períodos es la firma de un "
            "falso positivo: un número real que el contexto no sirve en la forma en que el "
            "modelo lo escribe (pasó con «69 %» por redondeo y con «132 %», que era la razón "
            "1,32 servida). Una cifra que aparece una sola vez es lo que el guard vino a "
            "atrapar. Ante una marca, la primera pregunta es si esa cifra es una FORMA de "
            "algo que sí servimos."),
    }
