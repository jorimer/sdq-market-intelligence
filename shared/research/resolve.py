"""Resolución de eje + entidad de una pregunta libre (orquestador v2).

El salto de calidad del motor: en vez de solo hacer match léxico contra docs, detecta
QUÉ eje(s) del catálogo toca la pregunta y si nombra una ENTIDAD (un banco, una AFP, una
aseguradora…), para luego traer su dato REAL vía ``snapshot`` (ver ``data_pull``). Sin
esto, una pregunta sobre "Banco Lafise" recuperaba metodología genérica; con esto, ancla
al rating/score/liquidez reales de Lafise.

Determinista y sin importar módulos: las entidades salen del ``scope_options()`` que cada
producto ya expone al catálogo (mismo patrón que el selector del front)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented

# Léxico curado por eje (español-neutro, sin acentos). Una pregunta que contenga
# cualquiera de estos términos apunta a ese eje. Curado > inferido: es la señal de
# ruteo, tiene que ser precisa. Ampliable sin tocar lógica.
AXIS_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "banking": ("banco", "banca", "bancari", "rating", "calificacion", "solidez",
                "liquidez", "mora", "cartera", "solvencia", "eficiencia", "deposito",
                "aeh", "asociacion de ahorro", "ahorro", "prestamo"),
    "macro": ("macro", "inflacion", "pib", "crecimiento", "riesgo pais", "fiscal",
              "deficit", "reservas", "tipo de cambio", "soberano"),
    "monetary_policy": ("politica monetaria", "tpm", "tasa de politica", "tasa de interes",
                        "bcrd tasa", "postura monetaria"),
    "trade": ("comercio exterior", "exportacion", "importacion", "balanza", "arancel",
              "aduana", "socio comercial"),
    "tourism": ("turismo", "turistico", "hotel", "ocupacion", "llegada de turistas"),
    "free_zones": ("zona franca", "zonas francas", "manufactura", "cnzfe", "izf"),
    "energy": ("energia", "energetic", "electric", "generacion", "renovable", "sie", "apagon"),
    "telecom": ("telecom", "telefonia", "internet", "banda ancha", "movil", "penetracion"),
    "construction": ("construccion", "cemento", "permisos de construccion", "vivienda", "obra"),
    # agribusiness tenía CatalogEntry + summarizer pero NUNCA keywords → una pregunta de sector
    # agro caía a scoping con cobertura 0 aunque el eje IAI existía (mismo modo de falla que
    # 'insurance' arriba). El stem "agro" en frontera de palabra cubre agropecuario/agroindustria/
    # agrícola/agroindustrial; "iai" activa por el índice. Verificado con detect_axes en el test.
    "agribusiness": ("agro", "agropecuari", "agroindustri", "agricol", "iai"),
    "esg": ("esg", "clima", "climatic", "ambiental", "carbono", "resiliencia climatica",
            "adaptacion", "sostenibilidad"),
    "pension": ("pension", "afp", "sipen", "fondo de pension", "cotizante", "rentabilidad afp"),
    # "asegurador" (stem) cubre asegurador/aseguradora/aseguradoras — hallazgo del piloto:
    # "mercado asegurador" no matcheaba ("aseguradora" es más largo y "seguro" no es
    # substring de "asegurador") → el eje primario no se detectaba y el gate caía a scoping.
    "insurance": ("seguro", "asegurador", "isf", "primas", "siniestralidad"),
    # Además de las frases técnicas, lenguaje natural de comprador (hallazgo del piloto P4-P6:
    # con las frases técnicas SÍ ruteaba, pero preguntas normales de "motores del crecimiento"
    # nunca lo activaban → la tabla de 17 sectores no salía).
    "economic_structure": ("estructura de la economia", "estructura economica",
                           "sectores de origen", "valor agregado por sector",
                           "motor del crecimiento", "motores del crecimiento",
                           "motores sectoriales", "motor sectorial",
                           "que sectores impulsan", "que mueve la economia",
                           "aporte de cada sector", "aporte sectorial",
                           "contribucion sectorial", "contribucion de cada sector",
                           "sectores que mas crecen", "que sector crece mas"),
    # Eje SUB-NACIONAL: el único cuyo sujeto es la demarcación. Además del vocabulario
    # temático (pobreza, desarrollo social, IDM), lleva los términos GEOGRÁFICOS —
    # provincia, región, territorial— porque la pregunta típica no nombra el índice sino
    # el corte: "¿cómo varía X por provincia?". Sin ellos, la única fuente con dato
    # dentro del país no se activaba nunca.
    "social_dev": ("desarrollo social", "idm", "pobreza", "pobreza extrema",
                   "desigualdad", "alfabetizacion", "analfabetismo", "escolaridad",
                   "informalidad", "inclusion financiera", "hacinamiento",
                   "por provincia", "provincial", "provincias", "por region",
                   "regiones de desarrollo", "territorial", "demarcacion",
                   "siuben", "brecha territorial", "indice de desarrollo"),
    # El sujeto de este eje es un INSTRUMENTO NORMATIVO. Las palabras evitan a propósito los
    # términos genéricos de política pública ("meta", "indicador", "cumplimiento") que
    # activarían el eje ante cualquier pregunta sectorial: acá se enruta cuando la pregunta
    # es POR LA NORMA, no por el tema que la norma regula.
    "law": ("ley", "leyes", "decreto", "articulado", "articulo", "norma", "normativa",
            "estrategia nacional de desarrollo", "end 2030", "ley 1-12",
            "meta rd 2036", "cumplimiento de la ley", "metas de la ley",
            "evaluacion de la ley", "obligacion legal", "pacto electrico",
            "pacto fiscal", "pacto educativo", "instrumento normativo"),
}

# Términos genéricos que NO distinguen una entidad (evitan matches espurios al resolver
# nombres del roster: "banco", "multiple" aparecen en casi todos los labels bancarios).
# Los gentilicios/país tampoco distinguen (hallazgo del piloto Fase 2: "mercado asegurador
# dominicano" resolvía "Banco Popular DOMINICANO" y "Qik ... DOMINICANO" — ruido).
# "sucursal"/"ahorros"/"prestamos" son forma legal, no identidad: "Citibank N.A. SUCURSAL
# República Dominicana" colgaba de la palabra "sucursal" y una pregunta sobre abrir una
# sucursal de comida rápida resolvía Citibank y anclaba TODO el informe a su rating.
_ENTITY_STOPWORDS = frozenset(
    "banco banca multiple ahorro ahorros credito creditos prestamo prestamos servicios "
    "sa srl de del la el los las asociacion sucursal sucursales bank "
    "aseguradora seguros compania cia fondo afp administradora s a "
    "dominicano dominicana dominicanos dominicanas republica".split())

# Tokens AMBIGUOS: sí distinguen una entidad dentro del roster, pero son palabras comunes
# del español (o topónimos) que aparecen en preguntas que NO tratan de esa entidad:
# "reservas" (Banreservas / reservas internacionales), "popular" (Banco Popular / "la marca
# más popular"), "motor" (Motor Crédito / "el motor de la economía"), "caribe" (Banco Caribe /
# la región), "crecer"/"siembra" (AFP / el verbo y la agricultura), "colonial" (aseguradora /
# la zona colonial)… Curado desde la auditoría del roster real (banca 35 + AFP + países).
# Un match colgado SOLO de un token ambiguo exige corroboración: que la pregunta también
# active el eje de esa entidad (p.ej. "banco"/"rating"). Sin eje, se descarta — el caso
# Citibank←"sucursal" del informe McDonald's. La segunda capa (``entity_check``) deja que
# el Cerebro vete lo que la corroboración léxica no alcanza a distinguir.
_AMBIGUOUS_TOKENS = frozenset(
    "nacional popular real romana caribe internacional reservas motor digital union "
    "santa cruz costa cibao duarte vega crecer siembra atlantico atlantica "
    "colonial universal general monumental humano futuro confianza progreso".split())


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def _kw_hit(kw: str, q: str) -> bool:
    """¿El keyword (stem) aparece en *q* en frontera de palabra? Evita falsos positivos
    de substring (p.ej. 'esg' dentro de 'riesgo'). Permite sufijo ('bancari' → bancario)."""
    return re.search(r"\b" + re.escape(kw), q) is not None


def _tokens(s: str) -> List[str]:
    """Tokens alfanuméricos normalizados (sin puntuación)."""
    return re.findall(r"[a-z0-9]+", _norm(s))


@dataclass
class ResolvedEntity:
    sector_key: str
    scope_value: str      # lo que snapshot(scope=…) resuelve (id o nombre)
    label: str            # nombre visible de la entidad
    matched_on: str = ""  # token distintivo que disparó el match
    # Match DÉBIL: colgado de un token ambiguo, o sin que la pregunta active el eje de la
    # entidad. Es la señal para que ``entity_check`` (Cerebro) verifique la pertinencia
    # antes de anclar el informe a esta entidad. Un match fuerte+eje no se re-verifica.
    weak: bool = False


@dataclass
class Targets:
    axes: List[str] = field(default_factory=list)          # ejes primarios sin entidad
    entities: List[ResolvedEntity] = field(default_factory=list)
    context: List[str] = field(default_factory=list)       # dominios de contexto (sistema)
    reasons: Dict[str, str] = field(default_factory=dict)  # eje → por qué la pregunta lo convoca

    @property
    def is_empty(self) -> bool:
        return not self.axes and not self.entities


def detect_axes(question: str) -> List[str]:
    """Ejes cuyo léxico aparece en la pregunta: primero los productizados (catálogo), luego los
    ejes BASE de sector (hojas del VAB sin producto dedicado, SPEC-4). Un slug base solo se agrega
    si ningún eje productizado ya lo cubre."""
    q = _norm(question)
    hits: List[str] = []
    for entry in PRODUCT_CATALOG:
        kws = AXIS_KEYWORDS.get(entry.sector_key, ())
        if any(_kw_hit(kw, q) for kw in kws) and entry.sector_key not in hits:
            hits.append(entry.sector_key)
    from shared.research.sector_base import base_sector_keywords
    for slug, kws in base_sector_keywords().items():
        if slug not in hits and any(_kw_hit(kw, q) for kw in kws):
            hits.append(slug)
    # SPEC-6: intención de comparación regional (Centroamérica y el Caribe) → eje regional.
    from shared.research.regional_benchmark import REGIONAL_KEYWORDS
    if any(_kw_hit(kw, q) for kw in REGIONAL_KEYWORDS):
        hits.append("regional_benchmark")
    return hits


def _distinctive_tokens(label: str) -> List[str]:
    """Tokens que identifican una entidad (≥4 chars, no genéricos): 'lafise', 'popular'…"""
    return [t for t in _tokens(label) if len(t) >= 4 and t not in _ENTITY_STOPWORDS]


def resolve_entities(question: str, db: Optional[Session],
                     axes: Optional[List[str]] = None) -> List[ResolvedEntity]:
    """Resuelve entidades nombradas en la pregunta contra el roster ``scope_options()`` de
    los productos (los de *axes* si se da, si no todos los implementados). Match por token
    distintivo (evita colgar de 'banco'/'seguros'). Un token AMBIGUO (palabra común que
    además nombra una entidad: 'reservas', 'popular', 'motor'…) solo ancla si la pregunta
    también activa el eje de esa entidad — sin esa corroboración, se descarta (el informe
    McDonald's se ancló a Citibank por la palabra 'sucursal'). Resiliente por producto."""
    if db is None:
        return []
    q = _norm(question)
    detected = frozenset(axes or ())
    candidates = axes if axes else [e.sector_key for e in PRODUCT_CATALOG]
    out: List[ResolvedEntity] = []
    seen: set = set()
    for sk in candidates:
        if not is_implemented(sk):
            continue
        axis_detected = sk in detected
        try:
            product = get_product(sk, db)
            fn = getattr(product, "scope_options", None)
            if not callable(fn):
                continue
            for opt in fn():
                label = str(opt.get("label", ""))
                hits = [tok for tok in _distinctive_tokens(label)
                        if re.search(rf"\b{re.escape(tok)}\b", q)]
                if not hits:
                    continue
                strong = [tok for tok in hits if tok not in _AMBIGUOUS_TOKENS]
                if not strong and not axis_detected:
                    continue  # solo tokens ambiguos y sin eje corroborante → espurio
                key = (sk, str(opt.get("value")))
                if key not in seen:
                    seen.add(key)
                    out.append(ResolvedEntity(
                        sector_key=sk, scope_value=str(opt.get("value")), label=label,
                        matched_on=(strong or hits)[0],
                        # fuerte+eje = confianza plena; lo demás lo re-verifica el Cerebro.
                        weak=not (strong and axis_detected)))
        except Exception:  # noqa: BLE001 — un roster que falla no rompe la resolución
            if db is not None:
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
    return out


# Dominios de CONTEXTO que una pregunta convoca además del primario — el corazón del
# research tema-primero: una pregunta de una entidad/sector casi nunca se contesta con un
# solo motor. Un riesgo de liquidez bancaria se transmite por el canal monetario y macro;
# un sector se lee contra el ciclo. Curado por dominio primario + intención de la pregunta.
_CONTEXT_FOR: Dict[str, Tuple[str, ...]] = {
    "banking": ("monetary_policy", "macro"),      # fondeo/condiciones sistémicas
    "insurance": ("macro",),
    "pension": ("macro",),
    "tourism": ("macro",), "free_zones": ("macro", "trade"), "energy": ("macro",),
    "telecom": ("macro",), "construction": ("macro",), "trade": ("macro",),
    "esg": ("macro",), "agribusiness": ("macro", "trade"),
}
# Términos que suman el dominio regulatorio/político como contexto.
_REGULATORY_TERMS = ("regulator", "politic", "gobernanz", "riesgo pais", "soberano",
                     "confianza", "electoral")

# Señal de intención SECTORIAL en una pregunta macro/crecimiento: si el primario es 'macro' y
# la pregunta toca la composición por sector, se suma economic_structure como CONTEXTO (la
# tabla de aporte por sector). Se condiciona a estos términos —en vez de sumarlo a CADA macro—
# para no inflar el contexto de una pregunta macro genérica (ver `_MAX_DOMAINS` en
# domain_router.py: un dictamen de 3-4 motores es síntesis, uno de 8 es ruido). Los términos son
# genéricos ('sector'/'sectorial'/'rama de actividad') a propósito: los específicos de motores
# sectoriales ya elevan economic_structure a PRIMARIO vía AXIS_KEYWORDS, y este bloque salta lo
# que ya es primario.
_SECTORAL_INTENT_TERMS = ("sector", "sectorial", "rama de actividad", "ramas de actividad",
                          "actividad economica", "por industria", "composicion de la economia")


def context_axes(question: str, primary: List[str]) -> List[str]:
    """Dominios de contexto (a-nivel-sistema) que la pregunta convoca, además de los
    primarios. Es lo que convierte el research en síntesis cross-dominio, no en una ficha."""
    q = _norm(question)
    out: List[str] = []
    for ax in primary:
        for ctx in _CONTEXT_FOR.get(ax, ("macro",)):
            if ctx not in out and ctx not in primary:
                out.append(ctx)
    # Contexto regulatorio/político si la pregunta lo toca (el producto 'macro' lo cubre).
    if any(_kw_hit(t, q) for t in _REGULATORY_TERMS) and "macro" not in out and "macro" not in primary:
        out.append("macro")
    # Composición sectorial como contexto de una pregunta macro/crecimiento SOLO si la pregunta
    # toca la intención sectorial — no se infla el contexto de cada macro genérica.
    if ("macro" in primary and "economic_structure" not in primary
            and "economic_structure" not in out
            and any(_kw_hit(t, q) for t in _SECTORAL_INTENT_TERMS)):
        out.append("economic_structure")
    return out


def finalize_targets(question: str, axes: List[str],
                     entities: List[ResolvedEntity]) -> Targets:
    """Arma el ``Targets`` final desde ejes detectados + entidades. Reutilizable: cuando
    ``entity_check`` descarta una entidad espuria, el contexto se recomputa desde acá (si
    no, el contexto sembrado por la entidad falsa —monetario/macro de un banco que no
    venía al caso— sobreviviría al descarte)."""
    # Un eje con entidad resuelta ya se cubre por la entidad; deja en `axes` solo los
    # ejes SIN entidad (para pull a-nivel-sistema).
    axes_with_entity = {e.sector_key for e in entities}
    axes_only = [a for a in axes if a not in axes_with_entity]
    primary = list(axes) + [e.sector_key for e in entities]
    return Targets(axes=axes_only, entities=entities,
                   context=context_axes(question, primary))


def resolve_targets(question: str, db: Optional[Session]) -> Targets:
    """Ejes detectados + entidades resueltas. Las entidades se buscan primero en los ejes
    detectados; si no hay eje detectado pero sí una entidad, su eje entra igual."""
    axes = detect_axes(question)
    entities = resolve_entities(question, db, axes or None)
    return finalize_targets(question, axes, entities)
