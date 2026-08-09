"""Catálogo canónico de las 32 provincias de la República Dominicana.

Es la columna vertebral de la granularidad SUB-NACIONAL. Hasta ahora el eje social
resolvía todo contra las 10 *regiones de desarrollo* (``shared.data.one_client.REGIONS``);
varias fuentes reales —la planilla de cobertura educativa de la ONE, los tableros
provinciales del SIUBEN— publican por provincia, y ese detalle se descartaba en el
parser. Este módulo da los slugs estables para conservarlo.

Diseño:

* **Provincia → región de desarrollo** está declarado acá (Decreto 710-04). Sirve para
  agregar hacia arriba sin perder el detalle: una serie provincial siempre puede
  colapsarse a su región, nunca al revés.
* **El emparejamiento de etiquetas es tolerante pero nunca adivina.** Los proveedores
  escriben la misma provincia de varias formas ("San Jose De Ocoa" / "San José de Ocoa")
  y algunos archivos vienen con la codificación rota de origen (``Dajab?n``). El
  resolvedor prueba, en orden: exacto normalizado → alias declarado → prefijo común más
  largo ESTRICTAMENTE único. Si el prefijo no distingue a un único candidato, devuelve
  ``None`` y lo registra: preferimos una fila descartada y contada a una fila asignada a
  la provincia equivocada.

Los slugs son ASCII y no colisionan con los de las 10 regiones (que viven en
``one_client.REGIONS``), así que ambos niveles pueden convivir en la misma columna
``sd_indicators.entity_key``, distinguidos por ``disaggregation``.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sdq.reference.provinces")

# (slug, nombre display, región de desarrollo) — 31 provincias + el Distrito Nacional.
# La regionalización es la del Decreto 710-04 (las 10 regiones que usa la ONE).
PROVINCES: List[Tuple[str, str, str]] = [
    # Cibao Norte
    ("espaillat", "Espaillat", "cibao_norte"),
    ("puerto_plata", "Puerto Plata", "cibao_norte"),
    ("santiago", "Santiago", "cibao_norte"),
    # Cibao Sur
    ("la_vega", "La Vega", "cibao_sur"),
    ("monsenor_nouel", "Monseñor Nouel", "cibao_sur"),
    ("sanchez_ramirez", "Sánchez Ramírez", "cibao_sur"),
    # Cibao Nordeste
    ("duarte", "Duarte", "cibao_nordeste"),
    ("hermanas_mirabal", "Hermanas Mirabal", "cibao_nordeste"),
    ("maria_trinidad_sanchez", "María Trinidad Sánchez", "cibao_nordeste"),
    ("samana", "Samaná", "cibao_nordeste"),
    # Cibao Noroeste
    ("dajabon", "Dajabón", "cibao_noroeste"),
    ("monte_cristi", "Monte Cristi", "cibao_noroeste"),
    ("santiago_rodriguez", "Santiago Rodríguez", "cibao_noroeste"),
    ("valverde", "Valverde", "cibao_noroeste"),
    # Valdesia
    ("azua", "Azua", "valdesia"),
    ("peravia", "Peravia", "valdesia"),
    ("san_cristobal", "San Cristóbal", "valdesia"),
    ("san_jose_de_ocoa", "San José de Ocoa", "valdesia"),
    # Enriquillo
    ("bahoruco", "Bahoruco", "enriquillo"),
    ("barahona", "Barahona", "enriquillo"),
    ("independencia", "Independencia", "enriquillo"),
    ("pedernales", "Pedernales", "enriquillo"),
    # El Valle
    ("elias_pina", "Elías Piña", "el_valle"),
    ("san_juan", "San Juan", "el_valle"),
    # Higuamo
    ("hato_mayor", "Hato Mayor", "higuamo"),
    ("monte_plata", "Monte Plata", "higuamo"),
    ("san_pedro_de_macoris", "San Pedro de Macorís", "higuamo"),
    # Ozama o Metropolitana
    ("distrito_nacional", "Distrito Nacional", "ozama"),
    ("santo_domingo", "Santo Domingo", "ozama"),
    # Yuma
    ("el_seibo", "El Seibo", "yuma"),
    ("la_altagracia", "La Altagracia", "yuma"),
    ("la_romana", "La Romana", "yuma"),
]

# Variantes históricas / administrativas que los proveedores usan para la misma
# provincia. Se declaran acá para que el emparejamiento sea EXACTO y no dependa del
# recurso difuso: extender esta tabla es la forma correcta de absorber un cambio de
# etiqueta del emisor.
PROVINCE_ALIASES: Dict[str, str] = {
    "bahoruco": "bahoruco",
    "baoruco": "bahoruco",                       # grafía oficial alterna
    "salcedo": "hermanas_mirabal",               # nombre anterior (hasta 2007)
    "monte christi": "monte_cristi",
    "montecristi": "monte_cristi",
    "el seybo": "el_seibo",
    "seibo": "el_seibo",
    "el seibo": "el_seibo",
    "santo domingo de guzman": "distrito_nacional",
    "d n": "distrito_nacional",
    "san pedro macoris": "san_pedro_de_macoris",
    "san jose ocoa": "san_jose_de_ocoa",
    "espaillat": "espaillat",
    "peravia bani": "peravia",
}

# Longitud mínima de prefijo para el recurso difuso. Por debajo de esto un prefijo no
# distingue nada útil y preferimos no emparejar.
_MIN_PREFIX = 4


def _norm(s: object) -> str:
    """Clave insensible a acento/caso/espacios, y a la puntuación que agrega el emisor."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(c if (c.isalnum() or c.isspace()) else " " for c in t)
    return " ".join(t.casefold().split())


_BY_NORM: Dict[str, str] = {_norm(name): slug for slug, name, _r in PROVINCES}
_BY_NORM.update({_norm(slug.replace("_", " ")): slug for slug, _n, _r in PROVINCES})
_BY_NORM.update({_norm(k): v for k, v in PROVINCE_ALIASES.items()})

REGION_OF: Dict[str, str] = {slug: region for slug, _n, region in PROVINCES}
NAME_OF: Dict[str, str] = {slug: name for slug, name, _r in PROVINCES}


def province_catalog() -> List[Tuple[str, str, str]]:
    """``[(slug, nombre, region_slug)]`` — el catálogo completo, para sembrar pares."""
    return list(PROVINCES)


def region_of(province_slug: str) -> Optional[str]:
    """Región de desarrollo a la que pertenece la provincia (para agregar hacia arriba)."""
    return REGION_OF.get(province_slug)


def _ascii_key(label: str) -> str:
    """Esqueleto ASCII de la etiqueta: lo que sobrevive a una codificación rota.

    Un archivo exportado con la página de códigos equivocada convierte ``ó`` en un byte
    que ninguna decodificación recupera. Quitar lo no-ASCII deja ``dajabn`` — suficiente
    para el prefijo común, insuficiente para el match exacto. Por eso alimenta SOLO al
    recurso difuso."""
    return "".join(c for c in _norm(label) if c.isascii())


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _best_effort_match(label: str) -> Optional[str]:
    """Provincia más plausible para una etiqueta que no calzó exacto — o ``None``.

    El puntaje pesa TRES cosas a la vez, y las tres hacen falta::

        3·prefijo_común − largo_del_nombre − largo_de_la_etiqueta

    * el prefijo común premia el parecido;
    * restar el largo del nombre castiga al candidato que la etiqueta deja a medias;
    * restar el largo de la etiqueta castiga al candidato que ignora la cola.

    Sin el segundo término, ``"Santiago, Dominican Republic"`` cae en *Santiago
    Rodríguez* (comparte 9 caracteres contra los 8 de *Santiago*). Sin el tercero,
    ``"Santiago Rodr?guez"`` —con el acento roto por la codificación— cae en *Santiago*.
    Los dos casos son reales: el primero viene de GDELT, el segundo de los CSV del
    SIUBEN.

    Dos rechazos explícitos, porque el default es no emparejar:

    * una etiqueta que es prefijo ESTRICTO de dos o más provincias sin completar
      ninguna (``"Santi"``, ``"La"``) no distingue nada;
    * un empate en el puntaje tampoco. Nunca se desempata por orden alfabético: eso
      sería adivinar con cara de regla.
    """
    key = _ascii_key(label)
    if len(key) < _MIN_PREFIX:
        return None
    names = [(slug, _ascii_key(name)) for slug, name, _r in PROVINCES]
    # Abreviatura ambigua: prefijo de varias, completa ninguna.
    if sum(1 for _s, cand in names if cand.startswith(key)) > 1 and \
            not any(cand == key for _s, cand in names):
        return None
    scored = sorted(
        ((3 * _common_prefix(key, cand) - len(cand) - len(key), _common_prefix(key, cand), slug)
         for slug, cand in names),
        reverse=True,
    )
    best = scored[0]
    runner = scored[1] if len(scored) > 1 else (float("-inf"), 0, "")
    if best[1] < _MIN_PREFIX or best[0] <= runner[0]:
        return None
    return best[2]


def province_slug(label: object) -> Optional[str]:
    """Slug de la provincia para una etiqueta del proveedor; ``None`` si no se reconoce.

    Orden: exacto normalizado → alias declarado → mejor esfuerzo puntuado. Devolver
    ``None`` es un resultado legítimo y se registra — una fila sin provincia reconocida
    se cuenta como descartada, jamás se reparte a la provincia más parecida."""
    text = str(label or "").strip()
    if not text:
        return None
    hit = _BY_NORM.get(_norm(text))
    if hit:
        return hit
    fuzzy = _best_effort_match(text)
    if fuzzy:
        logger.info("[provincias] etiqueta %r resuelta por mejor esfuerzo → %s", text, fuzzy)
        return fuzzy
    return None
