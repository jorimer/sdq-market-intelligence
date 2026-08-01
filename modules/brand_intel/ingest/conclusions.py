"""Las conclusiones del proveedor, leídas del mazo y guardadas como objeto.

Hasta aquí la ingesta extraía **cifras**. Con cifras se puede describir un mercado, y eso
es exactamente lo que el proveedor ya hizo: un informe que repite la descripción no aporta
nada y no se puede cobrar. Lo que SDQ puede añadir es *explicar* — pero para explicar algo
hay que tener ese algo guardado. De ahí este módulo: la conclusión del proveedor deja de
ser prosa dentro de un PDF y pasa a ser una fila contra la que se puede contrastar.

**Por qué esto NO pasa por confirmación humana, y las cifras sí.**
La regla del módulo —el sistema propone, una persona adopta— está calibrada para cifras:
un número mal leído entra en la serie, y desde ese momento ningún gráfico ni veredicto
puede distinguirlo de uno bueno. Una conclusión no se comporta así. No alimenta ninguna
aritmética, se contrasta contra la lámina en cualquier momento, y si sale torcida se ve
leyéndola. Aplicarle el mismo portón sería copiar la regla sin su motivo.

El riesgo real es otro y es peor: escribir «el proveedor concluye X» cuando nunca dijo X
pone palabras en boca del socio en un documento que llega a su cliente. La salvaguarda
frente a eso no es un humano aprobando de a una — es que la conclusión se guarde **con su
texto literal y su lámina**. Así el recibo existe siempre. Pero vive en el registro, no en
la prosa: el informe del cliente lee «el proveedor concluye que…» y se lee natural, y la
lámina sale en la vista interna y en el documento que se discute con el proveedor.

**Coste cero.** Las conclusiones son texto, y un mazo de estudio trae capa de texto en
todas sus láminas. No hace falta visión: una sola llamada sobre el texto del mazo entero.
Las cifras sí necesitan visión —viven dentro de los gráficos— y por eso siguen costando
una llamada por lámina.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.config.settings import settings

logger = logging.getLogger("sdq.brand_intel.conclusions")

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

# Un mazo de 59 láminas trae ~58k caracteres. El tope existe para que un documento
# anómalo no dispare el coste, no porque un mazo normal se acerque a él.
MAX_CHARS = 240_000

KINDS = ("hallazgo", "recomendacion", "contexto")
DIRECTIONS = ("sube", "baja", "estable", "")

CONCLUSIONS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "conclusions": {
            "type": "array",
            "description": "Una entrada por afirmación que el estudio sostiene.",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "La afirmación TAL COMO ESTÁ ESCRITA en el mazo, "
                                       "literal. Si ocupa varias frases, la frase que la "
                                       "sostiene. Nunca reescrita ni resumida.",
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "Lámina en la que está escrita.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(KINDS),
                        "description": "hallazgo: afirma algo sobre el mercado o la marca. "
                                       "recomendacion: propone una acción al cliente. "
                                       "contexto: metodología, muestra, definiciones.",
                    },
                    "subjects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Las marcas de las que trata, cada una tal como "
                                       "está impresa. Lista vacía si trata de la "
                                       "categoría entera y no de marcas concretas.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "De qué habla en pocas palabras: 'lugar favorito', "
                                       "'satisfacción', 'delivery', 'precio'.",
                    },
                    "metric_code": {
                        "type": "string",
                        "description": "El código del diccionario de métricas cuyo "
                                       "indicador afirma la frase, si el diccionario está "
                                       "en las instrucciones y alguno corresponde. Vacío "
                                       "si ninguno corresponde o si hay duda.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": list(DIRECTIONS),
                        "description": "El movimiento que afirma: sube, baja o estable. "
                                       "Vacío si no afirma movimiento alguno.",
                    },
                    "wave_label": {
                        "type": "string",
                        "description": "La ola a la que se refiere, tal como está impresa. "
                                       "Vacío si no la nombra.",
                    },
                    "confident": {
                        "type": "boolean",
                        "description": "true solo si la afirmación está escrita de forma "
                                       "explícita. false si hubo que deducirla.",
                    },
                },
                "required": ["claim", "page_number", "kind", "subjects", "topic",
                             "metric_code", "direction", "wave_label", "confident"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["conclusions"],
    "additionalProperties": False,
}

_PROMPT = """Eres un analista leyendo el texto de un estudio de mercado, lámina por lámina.
Tu tarea es recoger LAS AFIRMACIONES QUE EL ESTUDIO SOSTIENE — sus conclusiones — no las
cifras que las acompañan.

Una afirmación es una frase que dice algo sobre el mercado, una marca o el consumidor:
«mantiene el liderazgo como marca favorita», «es el competidor más dinámico», «pierde su
tendencia creciente». Los titulares de sección, los resúmenes ejecutivos y las páginas de
cierre son donde más abundan.

REGLAS, y la primera manda sobre todas:

1. `claim` va LITERAL. Copia la frase tal como está escrita, con sus palabras. No la
   reescribas, no la resumas, no la suavices, no la completes. Este texto se va a citar
   ante quien escribió el estudio: si no está escrito así, es falso.
2. No infieras conclusiones a partir de las cifras. Si una lámina solo trae un gráfico y
   sus números, no tiene conclusión: no inventes la que "se deduce".
3. Marca `confident: false` cuando la frase esté a medias, cortada por el salto de lámina,
   o cuando no estés seguro de haberla leído entera.
4. Distingue `hallazgo` de `recomendacion`. «Transformar la neutralidad en preferencia
   activa» es una recomendación al cliente, no un hallazgo sobre el mercado.
5. `direction` solo si la frase afirma movimiento. «Mantiene el liderazgo» es estable;
   «incrementa su última visita de 30% a 43%» sube; «cae» baja. Si solo describe un nivel
   sin movimiento, déjalo vacío.
6. Descarta el relleno: portadas, agradecimientos, nombres del equipo, índices.
7. Si las instrucciones traen un DICCIONARIO DE MÉTRICAS, rellena `metric_code` con el
   código del indicador que la frase afirma — solo si corresponde con claridad. Ante la
   duda, déjalo vacío: un código equivocado es peor que ninguno.

Devuelve las afirmaciones en el orden en que aparecen."""


def _system_prompt(vocab: Any = None) -> str:
    """El prompt, con el diccionario del encargo cuando lo hay.

    Quien nombra el indicador es el lector, que tiene la frase completa delante — no un
    calce de cadenas después, que es adivinar con menos información. El guardado luego
    solo valida que el código exista en el diccionario. Es el mismo reparto que ya usa la
    extracción de cifras.
    """
    if vocab is None or not getattr(vocab, "metrics", None):
        return _PROMPT
    lines = "\n".join(f"- `{m.code}`: {m.label}" for m in vocab.metrics)
    return f"{_PROMPT}\n\nDICCIONARIO DE MÉTRICAS:\n{lines}"


@dataclass(frozen=True)
class Conclusion:
    """Una afirmación del proveedor, con el recibo pegado."""

    claim: str
    page_number: int
    kind: str
    subjects: Tuple[str, ...]
    topic: str
    metric_code: str
    direction: str
    wave_label: str
    confident: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim, "page_number": self.page_number, "kind": self.kind,
            "subjects": list(self.subjects), "topic": self.topic,
            "metric_code": self.metric_code, "direction": self.direction,
            "wave_label": self.wave_label, "confident": self.confident,
        }


def _numbered(page_texts: Sequence[str], first: int, last: int) -> str:
    """Un tramo del mazo como un solo texto, con cada lámina rotulada.

    El número de lámina va en el propio texto porque es lo que el modelo debe devolver en
    `page_number`, y una lámina mal atribuida rompe el recibo — que es lo único que
    sostiene poder citar al proveedor.
    """
    parts = []
    for n in range(first, last + 1):
        cleaned = (page_texts[n - 1] or "").strip()
        if cleaned:
            parts.append(f"--- Lámina {n} ---\n{cleaned}")
    return "\n\n".join(parts)[:MAX_CHARS]


def read_conclusions(
    page_texts: Sequence[str], client: Any = None, vocab: Any = None,
) -> List[Conclusion]:
    """Lee las conclusiones del mazo a partir de su capa de texto.

    Devuelve lista vacía —no lanza— cuando el mazo no trae capa de texto: un mazo
    escaneado como imágenes es un caso legítimo, y su ingesta de cifras debe seguir
    funcionando aunque de él no se puedan sacar conclusiones.
    """
    import anthropic

    n_pages = len(page_texts)
    if not any((t or "").strip() for t in page_texts):
        logger.info("El mazo no trae capa de texto: no hay conclusiones que leer.")
        return []

    if client is None:
        key = settings.ANTHROPIC_API_KEY
        if not key:
            raise RuntimeError(
                "Falta la clave de Anthropic: la lectura de conclusiones no está disponible."
            )
        client = anthropic.Anthropic(api_key=key)

    found = _read_range(client, page_texts, 1, n_pages, vocab=vocab)

    # Un mazo reexpone la misma conclusión en su resumen y en su lámina de detalle. Al
    # partir por tramos eso no cambia, pero conviene no guardar la frase dos veces: el
    # informe la explicaría dos veces.
    seen: set = set()
    out: List[Conclusion] = []
    for c in found:
        mark = (c.page_number, c.claim.strip().lower())
        if mark not in seen:
            seen.add(mark)
            out.append(c)
    out.sort(key=lambda c: c.page_number)
    return out


def _read_range(
    client: Any, page_texts: Sequence[str], first: int, last: int, vocab: Any = None,
) -> List[Conclusion]:
    """Lee un tramo, y si la respuesta se corta lo parte en dos y reintenta.

    Cuántas conclusiones trae un mazo no se sabe antes de leerlo, así que ningún tope de
    salida es el correcto para todos: el de Ipsos desborda 8k tokens y el siguiente estudio
    puede desbordar 16k. Subir el tope y confiar deja el fallo latente — cuando ocurra,
    el JSON llega truncado y se pierde la lectura entera, que es exactamente como se
    descubrió esto.

    Partir por láminas es exacto: cada tramo se lee con su numeración real, así que la
    lámina que acompaña a cada frase sigue siendo la verdadera. El coste es una llamada
    más solo en los mazos que lo necesitan.
    """
    body = _numbered(page_texts, first, last)
    if not body.strip():
        return []

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_system_prompt(vocab),
        output_config={
            "format": {"type": "json_schema", "schema": CONCLUSIONS_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": [{"type": "text",
                         "text": f"{body}\n\n¿Qué afirmaciones sostiene este estudio?"}],
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("La lectura de conclusiones fue rechazada.")

    if response.stop_reason == "max_tokens":
        if first >= last:
            # Una sola lámina que no cabe. Es patológico —una lámina no tiene tantas
            # conclusiones— y partirla más no es posible: se dice y se sigue.
            logger.warning("La lámina %s desborda la respuesta: se omite.", first)
            return []
        mid = (first + last) // 2
        logger.info("Respuesta cortada en las láminas %s-%s: se parte en %s-%s y %s-%s.",
                    first, last, first, mid, mid + 1, last)
        return (_read_range(client, page_texts, first, mid, vocab=vocab)
                + _read_range(client, page_texts, mid + 1, last, vocab=vocab))

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("Respuesta vacía al leer las conclusiones.")

    n_pages = len(page_texts)
    out: List[Conclusion] = []
    for row in json.loads(text).get("conclusions") or []:
        parsed = _parse(row, n_pages)
        if parsed is not None:
            out.append(parsed)
    return out


def store_conclusions(
    db: Any, engagement_id: str, found: Sequence[Conclusion],
    extraction_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Guarda las conclusiones de una entrega, resolviéndolas contra el encargo.

    Idempotente por entrega: releer el mismo documento reemplaza sus conclusiones en vez
    de duplicarlas. Un tracker se relee cuando se corrige, y dos copias de la misma
    afirmación harían que el informe la explicara dos veces.

    Resolver marca, ola y métrica es lo que convierte la frase en algo contrastable: una
    conclusión con `subject_slugs` y `metric_code` puede compararse contra las cifras
    confirmadas, y ahí es donde aparece una discrepancia con el proveedor. La que no
    resuelve se guarda igual —sigue siendo una afirmación citable— simplemente no entra
    en ese contraste.
    """
    from modules.brand_intel.engines.metrics import TRACKER_VOCABULARY
    from modules.brand_intel.ingest.pdf_pipeline import _LabelResolver, _norm
    from modules.brand_intel.models.models import (
        BrandConclusion,
        BrandEntity,
        BrandWave,
    )

    brands = db.query(BrandEntity).filter(
        BrandEntity.engagement_id == engagement_id).all()
    waves = db.query(BrandWave).filter(
        BrandWave.engagement_id == engagement_id).all()
    resolver = _LabelResolver(brands, waves)

    try:
        from modules.brand_intel import service as svc
        vocab = svc.vocabulary_for(db, engagement_id)
    except Exception:  # noqa: BLE001 — sin vocabulario propio manda el del tracker
        vocab = TRACKER_VOCABULARY
    by_label = {_norm(m.label): m.code for m in vocab.metrics}

    q = db.query(BrandConclusion).filter(
        BrandConclusion.engagement_id == engagement_id)
    q = (q.filter(BrandConclusion.extraction_id == extraction_id) if extraction_id
         else q.filter(BrandConclusion.extraction_id.is_(None)))
    for old in q.all():
        db.delete(old)

    resueltas = 0
    for c in found:
        slugs = [s for s in (resolver.brand(name) for name in c.subjects) if s]
        wave_code = resolver.wave(c.wave_label) if c.wave_label else None
        # El lector nombra el indicador con la frase delante; aquí solo se valida que el
        # código exista. El calce por etiqueta queda de respaldo para lecturas viejas.
        metric_code = (c.metric_code if vocab.get(c.metric_code) else None) or \
                      (by_label.get(_norm(c.topic)) if c.topic else None)
        if slugs and metric_code:
            resueltas += 1
        db.add(BrandConclusion(
            engagement_id=engagement_id, extraction_id=extraction_id,
            page_number=c.page_number, claim=c.claim, kind=c.kind,
            subjects=list(c.subjects) or None, subject_slugs=slugs or None,
            topic=c.topic or None, metric_code=metric_code,
            direction=c.direction or None,
            wave_label=c.wave_label or None, wave_code=wave_code,
            confident=c.confident,
        ))

    hallazgos = sum(1 for c in found if c.kind == "hallazgo")
    return {
        "guardadas": len(found),
        "hallazgos": hallazgos,
        "recomendaciones": sum(1 for c in found if c.kind == "recomendacion"),
        "contrastables": resueltas,
    }


def _parse(row: Dict[str, Any], n_pages: int) -> Optional[Conclusion]:
    """Una fila del modelo a conclusión, o ``None`` si no se sostiene.

    Se descarta lo que no tiene recibo: sin texto no hay nada que citar, y una lámina
    fuera del mazo significa que el modelo perdió la cuenta — atribuir la frase a la
    lámina equivocada es peor que no guardarla.
    """
    claim = (row.get("claim") or "").strip()
    if len(claim) < 15:
        return None

    try:
        page = int(row.get("page_number") or 0)
    except (TypeError, ValueError):
        return None
    if not 1 <= page <= n_pages:
        logger.warning("Conclusión con lámina fuera de rango (%s): se descarta.", page)
        return None

    kind = (row.get("kind") or "").strip().lower()
    if kind not in KINDS:
        kind = "hallazgo"
    direction = (row.get("direction") or "").strip().lower()
    if direction not in DIRECTIONS:
        direction = ""

    subjects = tuple(
        s.strip() for s in (row.get("subjects") or []) if isinstance(s, str) and s.strip()
    )
    return Conclusion(
        claim=claim,
        page_number=page,
        kind=kind,
        subjects=subjects,
        topic=(row.get("topic") or "").strip(),
        metric_code=(row.get("metric_code") or "").strip().lower(),
        direction=direction,
        wave_label=(row.get("wave_label") or "").strip(),
        confident=bool(row.get("confident")),
    )
