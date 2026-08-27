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
        # La FRASE en que el modelo usó cada cifra. Es lo que distingue una invención de una
        # cifra real dicha en otra forma —los dos casos opuestos que el guard confunde— y sin
        # ella la única manera de saberlo era regenerar el informe y perderlo otra vez.
        frases = {str(f.get("cifra", ""))[:40]: str(f.get("frase") or "")
                  for f in (det.get("guard_fragmentos") or []) if isinstance(f, dict)}
        # QUÉ CAPA marcó cada cifra. Es lo que decide la calibración: hoy el detector
        # MECÁNICO solo alcanza para matar un informe, y es la capa que produjo las cinco
        # familias de falso positivo. Las marcas anteriores a este registro no la traen y
        # quedan como "(sin registrar)" — no se les supone "det", que sería inventar el dato
        # que se está midiendo.
        capas = {str(f.get("cifra", ""))[:40]: str(f.get("capa") or "(sin registrar)")
                 for f in (det.get("guard_fragmentos") or []) if isinstance(f, dict)}
        for m in marcas:
            clave = _cifra_de(str(m))
            e = por_cifra.setdefault(clave, {
                "cifra": clave, "veces": 0, "modulos": set(), "plantillas": set(),
                "ejemplo": str(m)[:180], "frases": [], "ultima_vez": None,
                "por_capa": {},
            })
            capa = capas.get(str(m)[:40], "(sin registrar)")
            e["por_capa"][capa] = e["por_capa"].get(capa, 0) + 1
            frase = frases.get(str(m)[:40])
            if frase and frase not in e["frases"]:
                # Se guardan VARIAS: la misma cifra usada en dos frases distintas dice algo
                # que una sola no dice — si el modelo la repite en el mismo sentido, es una
                # derivación que le falta al contexto; si la usa para cosas distintas, es
                # relleno.
                e["frases"].append(frase[:220])
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

    # LA REGLA DE DOS CAPAS, EN SOMBRA. Se mide sin cambiar ninguna política: cuántas marcas
    # las puso el detector mecánico SOLO —y por tanto NO habrían bloqueado si exigiéramos que
    # el juez semántico coincida— contra cuántas las confirman las dos.
    #
    # Va acá y no en una opinión mía porque la pregunta del dueño fue exactamente ésa, y el
    # registro no la podía contestar: el lazo fusiona `det + llm` para repararlos juntos y el
    # origen se perdía. Las marcas anteriores a esta medición se cuentan aparte y NO se
    # reparten: suponerles una capa sería fabricar el dato que se está midiendo.
    por_capa: Dict[str, int] = {}
    for e in orden:
        for capa, n in (e.get("por_capa") or {}).items():
            por_capa[capa] = por_capa.get(capa, 0) + int(n)
    medidas = sum(n for c, n in por_capa.items() if c != "(sin registrar)")

    return {
        "desde": ini.date().isoformat(), "hasta": fin.date().isoformat(),
        "modulo": modulo,
        "narrativas_generadas": narrativas,
        "narrativas_con_marca": con_marca,
        "regla_de_dos_capas": {
            "por_capa": por_capa,
            "marcas_con_capa_registrada": medidas,
            "publicadas_pese_a_la_marca": por_capa.get("det", 0),
            "bloquearon_la_entrega": por_capa.get("ambos", 0) + por_capa.get("juez", 0),
            "como_leerlo": (
                "«det» = solo el detector mecánico; «juez» = solo el semántico; «ambos» = "
                "los dos. La regla VIGENTE bloquea solo lo que el juez confirma, así que "
                "«publicadas_pese_a_la_marca» son informes que SÍ se entregaron y que "
                "señalan un hueco de contexto por cerrar — ésta es la lista de trabajo, no "
                "una alarma. «(sin registrar)» son marcas anteriores al registro de capas: "
                "NO se reparten, porque suponerles un origen sería inventar el dato que "
                "decide."),
        },
        "cifras": orden,
        "truncado": len(filas) >= MAX_FILAS,
        "como_leerlo": (
            "Una cifra que se REPITE entre ejes, plantillas o períodos es la firma de un "
            "falso positivo: un número real que el contexto no sirve en la forma en que el "
            "modelo lo escribe (pasó con «69 %» por redondeo y con «132 %», que era la razón "
            "1,32 servida). Una cifra que aparece una sola vez es lo que el guard vino a "
            "atrapar. Ante una marca, la primera pregunta es si esa cifra es una FORMA de "
            "algo que sí servimos — y para contestarla está `frases`, que muestra CÓMO la "
            "usó el modelo sin tener que regenerar el informe."),
    }
