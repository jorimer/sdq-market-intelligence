"""Vision extraction — read a slide the way a person reads it.

The alternative was a positional parser per chart layout. It works, and it is brittle in a
specific way: a tracker has six or eight chart shapes, each needs its own rules, and a
redesign between waves breaks whichever one changed. Vision has no per-layout code at all —
the same call reads a funnel, a stacked bar and an attribute table — which is what makes a
second client possible without writing a second parser.

**The model transcribes; it does not estimate.** The prompt says so, the schema gives it
nowhere to record a guess, and every number it returns is checked afterwards against the
structural invariants in ``engines/validation.py``. That ordering is the design: extraction
is allowed to be fallible because nothing it produces is trusted until an invariant or a
human confirms it.

Brand and wave come back as the **labels printed on the slide**, never as internal slugs —
the model cannot invent an identifier it was never shown. Mapping labels to the
engagement's own brands and waves happens in the pipeline, where a failed match is a
visible rejection rather than a silent new entity.
"""
from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from shared.config.settings import settings

from modules.brand_intel.engines.metrics import METRICS

logger = logging.getLogger("sdq.brand_intel.pdf_vision")

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
RENDER_DPI = 140          # legible for dense slides without inflating image tokens

# The schema is deliberately flat and closed: every field the model may return is named,
# and `additionalProperties: false` means it cannot smuggle in a field we do not validate.
EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_title": {"type": "string", "description": "Título impreso en la lámina."},
        "readable": {
            "type": "boolean",
            "description": "false si la lámina no contiene cifras extraíbles (portada, "
                           "índice, foto, texto sin datos).",
        },
        "skip_reason": {
            "type": "string",
            "description": "Por qué no hay cifras, cuando readable es false. Vacío si las hay.",
        },
        "cells": {
            "type": "array",
            "description": "Una entrada por cifra impresa en la lámina.",
            "items": {
                "type": "object",
                "properties": {
                    "metric_code": {
                        "type": "string",
                        "description": "Código del diccionario de métricas provisto.",
                    },
                    "brand_label": {
                        "type": "string",
                        "description": "Nombre de la marca tal como aparece impreso. "
                                       "Vacío si la cifra es de la categoría, no de una marca.",
                    },
                    "wave_label": {
                        "type": "string",
                        "description": "Etiqueta de la ola tal como aparece impresa "
                                       "(por ejemplo «Mar '26»). Vacía si la lámina "
                                       "corresponde a una sola ola sin rotularla.",
                    },
                    "segment": {
                        "type": "string",
                        "description": "Corte al que pertenece la cifra: 'total' salvo que "
                                       "la lámina la atribuya a un subgrupo (una ciudad, "
                                       "un NSE, un rango de edad). Usa la etiqueta impresa.",
                    },
                    "value": {"type": "number", "description": "La cifra impresa."},
                    "base_n": {
                        "type": "integer",
                        "description": "Base (n) de esa celda si la lámina la declara. "
                                       "0 si no aparece.",
                    },
                    "distribution_id": {
                        "type": "string",
                        "description": "Identificador que agrupa cifras que forman UNA "
                                       "distribución y por tanto deben sumar 100 (una "
                                       "pregunta de elección única, una barra apilada). "
                                       "Vacío si la cifra no pertenece a ninguna.",
                    },
                },
                "required": ["metric_code", "brand_label", "wave_label", "segment",
                             "value", "base_n", "distribution_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["chart_title", "readable", "skip_reason", "cells"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class PageExtraction:
    page_number: int
    chart_title: str
    readable: bool
    skip_reason: str
    cells: List[Dict[str, Any]]
    model_used: str


def render_pages(content: bytes, dpi: int = RENDER_DPI,
                 first: Optional[int] = None, last: Optional[int] = None) -> List[bytes]:
    """Render PDF pages to PNG bytes. Requires poppler (already a platform dependency)."""
    from pdf2image import convert_from_bytes

    # pdf2image annotates first_page/last_page as `int` while defaulting both to None;
    # None is its documented "no bound" value, so the annotation is wrong, not the call.
    images = convert_from_bytes(content, dpi=dpi,
                                first_page=first, last_page=last)  # type: ignore[arg-type]
    out: List[bytes] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def _metric_dictionary() -> str:
    lines = []
    for m in METRICS:
        note = f" — {m.description}" if m.description else ""
        lines.append(f"  · {m.code} ({m.kind}): {m.label}{note}")
    return "\n".join(lines)


def _system_prompt(brands: Sequence[str], waves: Sequence[str]) -> str:
    brand_list = ", ".join(brands) if brands else "(el encargo aún no declara marcas)"
    wave_list = ", ".join(waves) if waves else "(el encargo aún no declara olas)"
    return f"""\
Eres un extractor de datos de láminas de estudios de mercado. Tu única tarea es
TRANSCRIBIR las cifras impresas en la imagen. No interpretas, no estimas, no infieres.

REGLAS INNEGOCIABLES
1. Solo transcribes números que están IMPRESOS y legibles en la lámina. Si una barra no
   tiene su cifra rotulada, NO la estimes a partir de su altura: omítela.
2. Si dudas de un dígito, omite la celda. Una celda ausente es recuperable; una celda
   equivocada contamina todo el análisis posterior y ya no se distingue de una correcta.
3. Los sufijos de significancia estadística que acompañan a una cifra (letras como A, B,
   C, D, AB, CD) NO forman parte del número: «12CD» es 12.
4. Devuelves las marcas y las olas con la ETIQUETA IMPRESA en la lámina, no con códigos.
   Nunca inventes un identificador.
5. Si la lámina no contiene cifras extraíbles (portada, índice, sección, foto, texto de
   metodología), devuelve readable=false y explica brevemente por qué.

DICCIONARIO DE MÉTRICAS — usa exclusivamente estos códigos:
{_metric_dictionary()}
Si una cifra no corresponde a ninguna métrica del diccionario, omítela.

CONTEXTO DEL ENCARGO
  Marcas conocidas: {brand_list}
  Olas conocidas: {wave_list}
Si la lámina muestra una marca u ola que no está en estas listas, transcríbela igual con
su etiqueta impresa: el sistema decidirá después qué hacer con ella.

AGRUPACIÓN EN DISTRIBUCIONES
Cuando un conjunto de cifras de la lámina constituye UNA distribución cuyo total debe ser
100 —una pregunta de elección única entre marcas, los segmentos de una barra apilada, un
reparto porcentual— asígnale a todas ellas el mismo distribution_id (un texto corto y
descriptivo que tú elijas). Es la comprobación que permite detectar una serie omitida.
Si una cifra no pertenece a ninguna distribución, deja distribution_id vacío.

SEGMENTOS
Usa 'total' salvo que la lámina atribuya explícitamente la cifra a un subgrupo (una
ciudad, un nivel socioeconómico, un rango de edad). En ese caso usa la etiqueta impresa
del subgrupo."""


def extract_page(
    image_png: bytes,
    page_number: int,
    brands: Sequence[str],
    waves: Sequence[str],
    client: Any = None,
) -> PageExtraction:
    """Read one rendered slide. Raises on API failure so the caller can report the page."""
    import anthropic

    # The key comes from settings, as it does at every other call site in the platform.
    # Letting the SDK pick it up from the ambient environment works in production only
    # because Railway exports it; anywhere the process is started without that export —
    # local dev, a worker, a script — every slide would fail on authentication while the
    # rest of the platform's AI kept working, which reads as "vision is broken".
    if client is None:
        key = settings.ANTHROPIC_API_KEY
        if not key:
            raise RuntimeError(
                "Falta la clave de Anthropic: la lectura de láminas no está disponible."
            )
        client = anthropic.Anthropic(api_key=key)
    b64 = base64.standard_b64encode(image_png).decode("utf-8")

    # `output_config` constrains the response to the schema at decode time, which is what
    # lets the caller treat the reply as parsed data rather than text to be salvaged: the
    # model cannot return a field we do not validate, and cannot omit one we require.
    # This is the SDK's typed parameter, so a malformed config fails here and not on the
    # wire — it requires anthropic>=0.100, which `requirements.lock` pins for every
    # environment.
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_system_prompt(brands, waves),
        output_config={
            "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text",
                 "text": "Transcribe todas las cifras impresas en esta lámina siguiendo "
                         "las reglas. Omite cualquier cifra que no puedas leer con certeza."},
            ],
        }],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"La lectura de la página {page_number} fue rechazada por "
                           "los clasificadores de seguridad.")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError(f"Respuesta vacía al leer la página {page_number}.")

    data = json.loads(text)
    return PageExtraction(
        page_number=page_number,
        chart_title=data.get("chart_title", ""),
        readable=bool(data.get("readable")),
        skip_reason=data.get("skip_reason", ""),
        cells=data.get("cells") or [],
        model_used=response.model,
    )


# ── descubrimiento de métricas ────────────────────────────────────────

#: Lo que el modelo puede devolver al proponer el vocabulario de un estudio. Cerrado como
#: el de extracción: no puede introducir un campo que no validemos.
METRIC_DISCOVERY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["metrics"],
    "properties": {
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "label", "kind", "evidence", "confident"],
                "properties": {
                    "code": {"type": "string",
                             "description": "snake_case, en inglés o español, estable"},
                    "label": {"type": "string",
                              "description": "la etiqueta tal como se imprime"},
                    "kind": {"type": "string",
                             "enum": ["proportion", "index", "currency", "count"]},
                    "evidence": {"type": "string",
                                 "description": "qué se vio que justifica el tipo"},
                    "confident": {"type": "boolean"},
                },
            },
        },
    },
}

_METRIC_DISCOVERY_PROMPT = """Eres un analista de investigación de mercados leyendo una
lámina de un informe. NO transcribas cifras: tu única tarea es decir QUÉ INDICADORES mide
esta lámina, para que una persona los apruebe como vocabulario del estudio.

Por cada indicador distinto que veas, devuelve:
- `label`: la etiqueta tal como está impresa.
- `code`: un identificador snake_case corto y estable ("satisfaccion_t2b", "nps").
- `kind`, que decide qué estadística es legítima después:
  * `proportion` — un porcentaje SOBRE UNA BASE de respondentes (un % con su n).
  * `index`      — un índice o puntuación sobre una escala (100 = promedio, NPS, 1-10).
  * `currency`   — dinero.
  * `count`      — un conteo absoluto.
- `evidence`: qué viste que justifica ese tipo (el símbolo %, la base impresa, la moneda,
  el rango de la escala).
- `confident`: true solo si la evidencia es explícita en la lámina.

REGLA CRÍTICA SOBRE `kind`: solo `proportion` habilita bandas de confianza más adelante.
Si no ves con claridad que la cifra sea un porcentaje sobre una base de respondentes, NO
lo marques como `proportion` — usa `index` o `count` y pon `confident: false`. Equivocarse
hacia `proportion` fabrica intervalos de confianza que el estudio no tiene; equivocarse en
la otra dirección solo hace que una persona lo corrija.

No inventes indicadores que no estén impresos. Si la lámina es una portada, un índice o
metodología, devuelve la lista vacía."""


def discover_metrics_on_page(
    image_png: bytes, page_number: int, client: Any = None,
) -> List[Dict[str, Any]]:
    """Ask what a slide measures, not what it says. Proposes; nothing is created."""
    import anthropic

    if client is None:
        key = settings.ANTHROPIC_API_KEY
        if not key:
            raise RuntimeError(
                "Falta la clave de Anthropic: la lectura de láminas no está disponible."
            )
        client = anthropic.Anthropic(api_key=key)
    b64 = base64.standard_b64encode(image_png).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=_METRIC_DISCOVERY_PROMPT,
        output_config={
            "format": {"type": "json_schema", "schema": METRIC_DISCOVERY_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text",
                 "text": "¿Qué indicadores mide esta lámina?"},
            ],
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"La lectura de la página {page_number} fue rechazada.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError(f"Respuesta vacía al leer la página {page_number}.")
    return list(json.loads(text).get("metrics") or [])
