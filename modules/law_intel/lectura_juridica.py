"""Qué significan, en derecho, los artículos que este informe mide.

La tabla de obligaciones dice **qué** manda cada artículo y en qué estado está. No dice lo
otro: qué rango tiene la disposición, de dónde sale una exigencia que la ley no nombra, y
qué consecuencia jurídica trae incumplirla. Eso no se deduce de la tabla y es lo que un
lector externo necesita para saber si el informe mide lo que dice medir.

**El caso que obligó a escribir esto.** La Ley 167-21 manda publicar los procedimientos
(art. 39) y encomienda al MAP emitir los lineamientos (art. 42). El «tiempo de respuesta»
—la cifra central del informe— lo exige la Resolución 142-2024 del ministerio, dictada al
amparo de ese artículo, **NO la ley**. Un informe que atribuya a la ley una exigencia que
puso una resolución es refutable leyendo la ley, y se cae entero. La distinción estaba
escrita en un comentario del expediente, donde ningún lector la ve.

**Va en el expediente y no en el código.** Es contenido jurídico de UNA norma. Un
`if expediente == "..."` en el renderizador lo vuelve invisible para quien audite el
expediente, y la ley siguiente heredaría la lectura de la anterior o ninguna.

**Y cada nota se ancla a un artículo que la tabla muestra.** El guard exige que el artículo
citado exista entre las obligaciones del expediente: una lectura sobre un artículo que el
documento no consigna deja al lector con una referencia que no puede seguir, y es la forma
más fácil de que se cuele una cita inventada.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.law_intel.registro import RAIZ, ExpedienteInvalido

logger = logging.getLogger("sdq.law_intel.lectura_juridica")

ARCHIVO = "lectura_juridica.yaml"


@dataclass(frozen=True)
class Nota:
    """Lo que significa un artículo, más allá de lo que ordena."""

    articulo: int
    #: La lectura, en prosa corrida y sin andamiaje de método: va en un documento externo.
    dice: str
    #: De dónde sale, para que el lector pueda contrastarla. Un texto legal se cita.
    fuente: str
    #: La norma de rango inferior que desarrolla el artículo, si la hay. Es el campo que
    #: existe para no atribuirle a la ley lo que puso una resolución.
    desarrollada_por: Optional[str] = None


def _validar(notas: List[Nota], articulos_del_expediente: set) -> None:
    vistos = set()
    for n in notas:
        if n.articulo in vistos:
            raise ExpedienteInvalido(
                f"artículo {n.articulo}: dos lecturas del mismo artículo. Se consolidan en "
                f"una — dos notas sobre el mismo texto se contradicen tarde o temprano.")
        vistos.add(n.articulo)
        for campo in ("dice", "fuente"):
            if not str(getattr(n, campo) or "").strip():
                raise ExpedienteInvalido(
                    f"artículo {n.articulo}: sin `{campo}`. Una afirmación jurídica sin "
                    f"cita no se publica en un documento abierto.")
        if articulos_del_expediente and n.articulo not in articulos_del_expediente:
            raise ExpedienteInvalido(
                f"artículo {n.articulo}: la lectura cita un artículo que el expediente no "
                f"consigna entre sus obligaciones. El lector no puede seguir la referencia, "
                f"y es así como se cuela una cita que nadie verificó.")


def cargar(expediente_id: str) -> List[Nota]:
    """Las notas del expediente. Lista vacía si no las declara — no es un error."""
    import yaml  # type: ignore[import-untyped]

    from modules.law_intel.obligaciones import cargar_obligaciones

    ruta = RAIZ / expediente_id.replace("/", "") / ARCHIVO
    if not ruta.exists():
        return []
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    notas = [Nota(**n) for n in (doc.get("lectura") or [])]
    _validar(notas, {int(o.articulo) for o in cargar_obligaciones(expediente_id)
                     if str(o.articulo or "").strip().isdigit()})
    return notas


def prosa(expediente_id: str) -> Optional[str]:
    """Las notas en prosa corrida, en orden de artículo, o `None` si no hay ninguna.

    Ordenadas por ARTÍCULO y no por importancia: el lector viene de la tabla de obligaciones,
    que está ordenada así, y un orden distinto lo obliga a buscar.
    """
    notas = cargar(expediente_id)
    if not notas:
        return None
    partes = []
    for n in sorted(notas, key=lambda x: x.articulo):
        p = f"**Artículo {n.articulo}.** {n.dice.strip()}"
        if n.desarrollada_por:
            p += (f" La disposición se desarrolla en {n.desarrollada_por}, de rango inferior "
                  f"a la ley: lo que esa norma exige no lo exige el texto legal.")
        partes.append(f"{p} ({n.fuente})")
    return "\n\n".join(partes)


def publicable(expediente_id: str) -> Dict[str, Any]:
    """Lo que viaja a la API."""
    notas = cargar(expediente_id)
    return {
        "total": len(notas),
        "lectura": [{"articulo": n.articulo, "dice": n.dice, "fuente": n.fuente,
                     "desarrollada_por": n.desarrollada_por}
                    for n in sorted(notas, key=lambda x: x.articulo)],
    }
