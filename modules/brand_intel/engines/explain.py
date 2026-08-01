"""Explicar las conclusiones del proveedor con los datos de SDQ.

Éste es el motor del giro de producto. El informe anterior describía el mercado — que es
exactamente lo que el proveedor ya entregó, con más autoridad — y por eso no se podía
cobrar. Lo que SDQ puede aportar y nadie más en la alianza tiene es el **porqué
económico**: el proveedor mide que la incidencia de consumo cae; SDQ tiene la inflación,
la tasa de política, la actividad económica y el tipo de cambio para decir qué parte de
eso es el entorno apretando y qué parte es la marca.

**Determinista a propósito.** Cada explicación es (a) la conclusión literal del proveedor,
(b) los factores macro pertinentes CON SUS VALORES del contrato compartido, y (c) una
frase de canal escrita aquí como doctrina — por qué ese factor toca esa métrica. Nada se
genera: un modelo redactando causalidad libre es la manera más rápida de imprimir una
explicación falsa con tono seguro. La doctrina de canales es revisable en este archivo,
igual que ``macro_sector.yaml`` lo es para los sectores.

La honestidad del motor está en negarse: una conclusión sobre percepción de marca
(favorito, opinión, fidelidad) NO se explica con macro — decir «tu caída de imagen es la
inflación» sería inventar. Esas van al otro lado del informe: si el entorno del período
fue favorable y la marca cayó, el entorno no lo explica, y ESO es el hallazgo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: Familias de métrica → canal económico. La pertenencia decide QUÉ factores del
#: contrato macro son pertinentes para explicar un movimiento de esa métrica.
#: Percepción no aparece: el entorno no explica imagen, y fingirlo sería inventar.
CONSUMO = {"reach_7d", "reach_1m", "reach_3m", "ever_tried", "last_visit_share"}
GASTO = {"ticket_avg"}
PERCEPCION = {"favourite_place", "awareness_total", "awareness_spontaneous",
              "awareness_tom", "brand_opinion_t2b", "loyalty_t2b",
              "satisfaction_t2b", "delivery_t2b", "attribute_index"}

#: Sinónimos de búsqueda: el contrato rotula sus factores con `key` y `label` propios;
#: esto los encuentra sin acoplarse a la ortografía exacta del productor.
_FACTOR_MATCH: Dict[str, List[str]] = {
    "inflacion": ["inflacion", "inflación"],
    "tpm": ["politica monetaria", "política monetaria", "tpm"],
    "imae": ["imae", "actividad economica", "actividad económica"],
    "remesas": ["remesas"],
    "tipo_cambio": ["cambiaria", "tipo de cambio", "depreciacion", "depreciación"],
}


def _find_factor(factors: Sequence[Dict[str, Any]], factor_key: str,
                 ) -> Optional[Dict[str, Any]]:
    """El factor del contrato que corresponde a un canal, si está y trae valor."""
    needles = _FACTOR_MATCH.get(factor_key, [factor_key])
    for f in factors:
        haystack = f"{f.get('key', '')} {f.get('label', '')}".lower()
        if any(n in haystack for n in needles):
            return f if f.get("value") is not None else None
    return None


def _channel_for(metric_code: Optional[str]) -> Optional[str]:
    if metric_code in CONSUMO:
        return "consumo"
    if metric_code in GASTO:
        return "gasto"
    return None


def explain_conclusions(
    conclusions: Sequence[Any],
    macro_factors: Sequence[Dict[str, Any]],
    environment_stance: Optional[str] = None,
) -> Dict[str, Any]:
    """Reparte las conclusiones utilizables entre lo que el entorno explica y lo que no.

    El entorno se declara UNA vez, con sus valores (``entorno``). Cada conclusión
    explicada recibe una lectura PROPIA que cruza su dirección con los factores de su
    canal — no una lista genérica de factores repetida bajo cada frase, que fue la
    primera versión y se leía mecánica y rellena. El insight vive en el cruce: caer con
    el bolsillo apretado es consistente; caer con el entorno a favor no tiene excusa.

    Tres salidas, y las tres son producto:

    * ``explicadas`` — conclusiones de consumo/gasto CON dirección, cada una con su
      lectura de entorno. Una conclusión sin dirección (un perfil por edades, un corte
      por NSE) no recibe capa: el entorno no dice nada sobre ella y fingirlo es relleno.
    * ``competitivas`` — conclusiones de percepción, donde el motor SE NIEGA a invocar
      macro. Si el entorno del período fue favorable y una marca cae, esa negativa es la
      lectura: no lo explica el entorno, es dinámica competitiva.
    * ``sin_capa`` — sin métrica resuelta o sin dirección: citables, no explicables.
    """
    entorno = _environment_block(macro_factors)
    explicadas: List[Dict[str, Any]] = []
    competitivas: List[Dict[str, Any]] = []
    sin_capa: List[Dict[str, Any]] = []

    for c in conclusions:
        if getattr(c, "kind", "hallazgo") != "hallazgo":
            continue                     # recomendaciones y contexto no se explican
        base: Dict[str, Any] = {
            "claim": str(c.claim),
            "subjects": list(getattr(c, "subjects", None) or []),
            "metric_code": getattr(c, "metric_code", None),
            "direction": getattr(c, "direction", None),
            "wave_label": getattr(c, "wave_label", None),
        }
        channel = _channel_for(base["metric_code"])
        if channel is None or not base["direction"]:
            if base["metric_code"] in PERCEPCION:
                competitivas.append({
                    **base,
                    "reading": _competitive_reading(base, environment_stance),
                })
            else:
                sin_capa.append(base)
            continue

        reading = _environment_reading(base, channel, entorno)
        if reading:
            explicadas.append({**base, "channel": channel, "reading": reading})
        else:
            sin_capa.append({**base, "reason": "El contrato macro no trae los factores "
                                               "de este canal en el período."})

    return {
        "available": bool(explicadas or competitivas),
        "entorno": entorno,
        "explicadas": explicadas,
        "competitivas": competitivas,
        "sin_capa": sin_capa,
        "environment_stance": environment_stance,
        "note": _note(explicadas, competitivas, sin_capa),
    }


def _environment_block(factors: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """El entorno del período, declarado una vez con sus valores y su doctrina."""
    out: Dict[str, Any] = {}
    for key, doctrine in (
        ("inflacion", "comprime el gasto discrecional del hogar; comer fuera es de lo "
                      "primero que se recorta o se espacia"),
        ("tpm", "encarece el crédito de consumo y las tarjetas que financian parte del "
                "gasto en restaurantes"),
        ("imae", "marca el pulso del ingreso disponible: una economía que crece "
                 "sostiene visitas"),
        ("tipo_cambio", "los insumos importados (proteína, lácteos, trigo, empaques) se "
                        "pagan en dólares: empuja el costo del plato"),
        ("remesas", "sostienen el consumo de los hogares receptores"),
    ):
        f = _find_factor(factors, key)
        if f is not None:
            out[key] = {"label": f.get("label"), "value": f.get("value"),
                        "unit": f.get("unit"), "direction": f.get("direction"),
                        "reading": f.get("reading"), "doctrine": doctrine}
    return out


def _fmt_factor(f: Dict[str, Any]) -> str:
    v = f.get("value")
    unit = f.get("unit") or ""
    txt = f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    return f"{f.get('label')} en {txt}{unit}"


def _environment_reading(base: Dict[str, Any], channel: str,
                         entorno: Dict[str, Any]) -> Optional[str]:
    """La lectura de UNA conclusión: su dirección cruzada con su canal.

    Las frases están escritas aquí como doctrina, con los valores del período
    incrustados. El cruce (dirección × postura del factor) es lo que evita el relleno:
    la misma inflación acompaña una caída, agrava el mérito de un avance y dignifica
    una estabilidad — tres lecturas distintas del mismo dato.
    """
    d = base["direction"]
    quien = ", ".join(base.get("subjects") or []) or "La marca"
    if channel == "gasto":
        inf_g: Optional[Dict[str, Any]] = entorno.get("inflacion")
        fx: Optional[Dict[str, Any]] = entorno.get("tipo_cambio")
        if inf_g is None and fx is None:
            return None
        partes = []
        if inf_g is not None:
            partes.append(f"con {_fmt_factor(inf_g)}, parte del movimiento nominal es "
                          "traslado de precios, no consumo real")
        if fx is not None:
            adverso = fx.get("direction") == "adverso"
            partes.append(
                f"{_fmt_factor(fx)} {'encarece' if adverso else 'alivia'} el costo "
                "en dólares de los insumos importados del plato")
        return "; ".join(partes).capitalize() + "."

    inf: Optional[Dict[str, Any]] = entorno.get("inflacion")
    imae: Optional[Dict[str, Any]] = entorno.get("imae")
    if inf is None and imae is None:
        return None
    bolsillo_apretado = inf is not None and inf.get("direction") == "adverso"
    ciclo_favorable = imae is not None and imae.get("direction") == "favorable"

    if d == "baja":
        if inf is not None and bolsillo_apretado:
            return (f"El retroceso de {quien} es consistente con el bolsillo del "
                    f"período: {_fmt_factor(inf)} ({inf.get('direction')}) recorta el "
                    "gasto discrecional, y comer fuera es de lo primero que se espacia."
                    + (f" El ciclo general no lo explica ({_fmt_factor(imae)}): el "
                       "apretón es de precios, no de actividad."
                       if imae is not None and ciclo_favorable else ""))
        if imae is not None:
            return (f"El ciclo acompaña la lectura: {_fmt_factor(imae)} "
                    f"({imae.get('direction')}); un enfriamiento de actividad espacia "
                    "las visitas antes que cualquier otra partida del hogar.")
    if d == "sube":
        partes = []
        if inf is not None and bolsillo_apretado:
            partes.append(f"{quien} avanza contra el viento del bolsillo — {_fmt_factor(inf)} "
                          "(adverso) — lo que hace el movimiento más meritorio de lo "
                          "que la cifra sola sugiere")
        if imae is not None and ciclo_favorable:
            partes.append(f"el ciclo acompaña ({_fmt_factor(imae)}): parte del avance "
                          "es marea del mercado, y separarlo de la gestión propia es "
                          "exactamente lo que la atribución de este informe hace")
        if partes:
            return (partes[0][0].upper() + partes[0][1:] +
                    ("; " + partes[1] if len(partes) > 1 else "") + ".")
    if d == "estable":
        if inf is not None and bolsillo_apretado:
            return (f"Que {quien} sostenga el nivel con {_fmt_factor(inf)} (adverso) "
                    "es defensa de posición: el gasto discrecional del hogar está bajo "
                    "presión y la frecuencia no cedió.")
        if imae is not None:
            return (f"Estabilidad en línea con el entorno: {_fmt_factor(imae)} "
                    f"({imae.get('direction')}) no empuja ni frena la categoría en el "
                    "período.")
    return None


def _competitive_reading(base: Dict[str, Any], stance: Optional[str]) -> str:
    """La lectura de una conclusión de percepción: el entorno NO la explica.

    La frase cambia con la postura del entorno porque el contraste es el insight:
    una caída de preferencia en un entorno favorable no tiene excusa macro.
    """
    d = base.get("direction")
    if stance == "favorable" and d == "baja":
        return ("El entorno del período fue favorable: este retroceso no se explica por "
                "condiciones de mercado, sino por dinámica competitiva — es accionable "
                "por la marca.")
    if stance == "adverso" and d == "sube":
        return ("Avanzar con el entorno en contra es doblemente meritorio: el movimiento "
                "es de la marca, no de la marea.")
    if d == "estable":
        return ("Indicador de percepción: se mueve por experiencia y comunicación, no "
                "por el ciclo económico. Su estabilidad es atribuible a la marca.")
    return ("Indicador de percepción: el entorno económico no lo explica; el movimiento "
            "es dinámica competitiva entre marcas.")


def _note(explicadas: List[Any], competitivas: List[Any], sin_capa: List[Any]) -> str:
    parts = [f"{len(explicadas)} conclusión(es) del proveedor con capa explicativa "
             f"del entorno; {len(competitivas)} de percepción, donde el entorno no "
             "explica y la lectura es competitiva."]
    if sin_capa:
        parts.append(f"{len(sin_capa)} quedaron sin capa (sin métrica resuelta o sin "
                     "factores del período).")
    return " ".join(parts)
