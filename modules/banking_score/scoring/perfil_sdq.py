"""Perfil SDQ — dos ejes independientes en vez de una notación de calificadora.

Reemplaza la lectura de ``SDQ-AAA … SDQ-D`` por **Ejecución** (qué tan bien le va) y
**Resiliencia** (qué tan expuesta está), cada uno 0-100 con su propia banda. Ver
``docs/SPEC_PERFIL_SDQ_TAXONOMIA.md``.

No se recalibra nada. Los cinco sub-componentes ya ponderados se reagrupan en dos familias
y el peso se renormaliza dentro de cada una — reusando ``calculate_deterministic_score``,
que ya renormaliza sobre los pesos que recibe y ya excluye los sub-componentes N/D. Es una
capa de agregación distinta sobre trabajo validado, no un motor nuevo.

**Los dos ejes NO son simétricos, y es deliberado:**

* **Resiliencia es ABSOLUTA.** Hereda las bandas del ISF/ISA (75/60/45), que están ancladas
  en umbrales con significado propio. Un 62 de Resiliencia significa lo mismo este trimestre
  que el próximo.
* **Ejecución es RELATIVA al panel.** Sus cortes salen de los percentiles del universo
  comparable, porque no existe un "breakeven de eficiencia bancaria" análogo al índice
  regulatorio o al combined ratio 100%. Inventarle un corte fijo sería el error que ya se
  cometió con los anclajes del ISF: fijar un rango teórico y descubrir después que el mercado
  entero cae de un lado. Cada respuesta expone los cortes usados para que sean auditables.
"""
from typing import Any, Dict, List, Optional, Sequence

from modules.banking_score.scoring.engine import calculate_deterministic_score
from modules.banking_score.scoring.weights import get_sub_component_weights

# Reagrupación de los 5 sub-componentes (spec §3.1 banca, §7.3 fiduciarias). Es genérica:
# vale para los 6 perfiles de `WEIGHT_PROFILES`, no solo para los dos que trata el spec.
COMPONENTES_RESILIENCIA = ("solidez", "calidad", "liquidez", "diversificacion")
COMPONENTES_EJECUCION = ("eficiencia",)

# Resiliencia hereda las bandas ya vigentes en ISF/ISA/ISARS: un vocabulario por eje en los
# cuatro sectores, que es el objetivo del spec.
BANDAS_RESILIENCIA = [(75.0, "Sólida"), (60.0, "Adecuada"), (45.0, "En vigilancia"),
                      (0.0, "Frágil")]
# Nombres cerrados en §4.1 — elegidos para no colisionar con ninguna de las tres familias de
# banda ya en producción ni con el literal "Datos insuficientes".
BANDAS_EJECUCION = ("Sobresaliente", "Competitiva", "Rezagada", "Deficiente")

# Panel mínimo para calcular cortes propios. Mismo criterio que
# ``shared.indices.normalization._MIN_N``: con menos datos los cuartiles no significan nada.
# Debajo del umbral se usan los cortes del universo completo — declarado en la respuesta,
# nunca en silencio.
MIN_PANEL_PROPIO = 12
# Debajo de este universo, la banda sola engaña: el reporte debe mostrar la posición
# relativa junto a ella (regla de N chico, §4.2).
MIN_UNIVERSO_SIN_POSICION = 15


def _percentil(ordenados: Sequence[float], q: float) -> float:
    if len(ordenados) == 1:
        return ordenados[0]
    pos = q * (len(ordenados) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordenados) - 1)
    return ordenados[lo] + (pos - lo) * (ordenados[hi] - ordenados[lo])


def calcular_ejes(sub_scores: Dict[str, Optional[float]],
                  entity_type: Optional[str] = None) -> Dict[str, float]:
    """Los dos ejes de una entidad, por reagregación de sus sub-componentes."""
    w = get_sub_component_weights(entity_type)
    return {
        "resiliencia": calculate_deterministic_score(
            sub_scores, {k: w[k] for k in COMPONENTES_RESILIENCIA if k in w}),
        "ejecucion": calculate_deterministic_score(
            sub_scores, {k: w[k] for k in COMPONENTES_EJECUCION if k in w}),
    }


def banda_resiliencia(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    return next((n for t, n in BANDAS_RESILIENCIA if score >= t), "Frágil")


def cortes_ejecucion(valores: Sequence[float]) -> Optional[Dict[str, float]]:
    """Cortes por cuartil del panel: p75 → Sobresaliente, p50 → Competitiva, p25 → Rezagada."""
    vals = sorted(v for v in valores if v is not None)
    if len(vals) < 4:
        return None
    return {"p25": _percentil(vals, 0.25), "p50": _percentil(vals, 0.50),
            "p75": _percentil(vals, 0.75)}


def banda_ejecucion(score: Optional[float], cortes: Optional[Dict[str, float]]) -> Optional[str]:
    """Banda de Ejecución contra los cortes del panel. Sin cortes no se inventa banda."""
    if score is None or not cortes:
        return None
    if score >= cortes["p75"]:
        return BANDAS_EJECUCION[0]
    if score >= cortes["p50"]:
        return BANDAS_EJECUCION[1]
    if score >= cortes["p25"]:
        return BANDAS_EJECUCION[2]
    return BANDAS_EJECUCION[3]


def perfil_panel(entidades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perfil SDQ de un panel completo, agrupando por ``entity_type``.

    Cada entidad de *entidades* necesita ``sub_scores`` y ``entity_type``; el resto de las
    claves se conserva. Devuelve ``{"entidades": [...], "cortes_por_tipo": {...}}``.

    Los cortes de Ejecución se calculan **por tipo de entidad**, no sobre el universo entero:
    la distribución difiere demasiado entre familias para compartir cortes. Medido en
    producción (2026-08-07): la mediana de Ejecución es **37.8 en cambiarias** y **73.5 en
    banca múltiple**. Con cortes únicos, casi toda la intermediación cambiaria caería en
    "Deficiente" y casi toda la banca múltiple en "Sobresaliente" — describiendo la diferencia
    entre dos modelos de negocio como si fuera diferencia de desempeño.

    Un tipo con menos de ``MIN_PANEL_PROPIO`` entidades usa los cortes del universo completo,
    y su fila lo declara en ``cortes_origen``.
    """
    for e in entidades:
        e.update(calcular_ejes(e.get("sub_scores") or {}, e.get("entity_type")))

    universo = cortes_ejecucion([e["ejecucion"] for e in entidades])
    por_tipo: Dict[str, List[Dict[str, Any]]] = {}
    for e in entidades:
        por_tipo.setdefault(e.get("entity_type") or "—", []).append(e)

    cortes_por_tipo: Dict[str, Any] = {}
    for tipo, filas in por_tipo.items():
        propios = cortes_ejecucion([f["ejecucion"] for f in filas]) if len(filas) >= MIN_PANEL_PROPIO else None
        cortes = propios or universo
        origen = "propios" if propios else ("universo" if universo else None)
        cortes_por_tipo[tipo] = {"cortes": cortes, "origen": origen, "n": len(filas)}

        ordenadas = sorted(filas, key=lambda f: f["ejecucion"], reverse=True)
        posicion = {id(f): i + 1 for i, f in enumerate(ordenadas)}
        for f in filas:
            f["banda_resiliencia"] = banda_resiliencia(f["resiliencia"])
            f["banda_ejecucion"] = banda_ejecucion(f["ejecucion"], cortes)
            f["cortes_origen"] = origen
            # Regla de N chico (§4.2): con un universo chico la banda sola engaña —
            # "Sobresaliente" entre 4 dice bastante menos que "Sobresaliente" entre 42.
            f["universo"] = len(filas)
            f["posicion_ejecucion"] = posicion[id(f)]
            f["requiere_posicion_visible"] = len(filas) < MIN_UNIVERSO_SIN_POSICION

    return {"entidades": entidades, "cortes_por_tipo": cortes_por_tipo}


def correlacion(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson entre los dos ejes — el gate del §8.

    Si supera 0.7-0.8, los ejes son la misma información con dos etiquetas y el argumento de
    "separar desempeño de exposición" no se sostiene frente a un cliente técnico que pida ver
    los números. Medido en producción sobre las 92 entidades: **0.002 global**, máximo 0.617
    (corporaciones de crédito, N=4). El split discrimina.
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)
