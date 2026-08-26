"""Qué dice el EVALUADO sobre sus propios datos.

Un organismo evaluado declara cosas sobre la información que maneja: que un sistema está en
piloto, que sus cifras son reservadas hasta cierta madurez, que un indicador estará
disponible en tal fecha. Esas declaraciones **cambian lo que el informe puede afirmar** y no
son opinión nuestra: son actos del propio emisor, con fecha y con fuente.

**Por qué van en el expediente y no en el código.** Son hechos del mundo, fechados, que
envejecen. Un `if expediente == "ley_167_21"` en un renderizador los volvería invisibles
para quien audite el expediente, y el día que el MAP levante la reserva habría que buscarlos
en el fuente en vez de en el registro de la ley.

**Y por qué importan tanto en el informe abierto.** «No hay dato» y «el emisor tiene el dato
y declaró que no lo publica todavía» son cosas distintas, y la segunda es la interesante: no
es una brecha de nadie, es una decisión declarada con fecha. Publicar la primera cuando lo
cierto es la segunda le imputa al emisor una omisión que no cometió.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.law_intel.registro import RAIZ, ExpedienteInvalido

logger = logging.getLogger("sdq.law_intel.declaraciones")

ARCHIVO = "declaraciones.yaml"


@dataclass(frozen=True)
class Declaracion:
    """Algo que el evaluado dijo sobre su propia información."""

    id: str
    fecha: str
    quien: str
    que_declara: str
    fuente: str
    #: Qué implica para lo que este informe puede medir. Es la mitad que convierte una cita
    #: en información: sin esto, el lector tiene una noticia y no sabe qué hacer con ella.
    consecuencia_para_la_medicion: str
    #: Cuándo el propio emisor dijo que cambiaría. `None` = no dio fecha, que también se dice.
    disponible_desde: Optional[str] = None


def _validar(ds: List[Declaracion]) -> None:
    vistos = set()
    for d in ds:
        if d.id in vistos:
            raise ExpedienteInvalido(f"declaración duplicada: {d.id}")
        vistos.add(d.id)
        for campo in ("fecha", "quien", "que_declara", "fuente"):
            if not str(getattr(d, campo) or "").strip():
                raise ExpedienteInvalido(
                    f"{d.id}: sin `{campo}`. Una declaración sin fecha, sin autor o sin "
                    f"fuente es un rumor: no se publica en un documento abierto.")
        if not str(d.consecuencia_para_la_medicion or "").strip():
            raise ExpedienteInvalido(
                f"{d.id}: sin `consecuencia_para_la_medicion`. Citar lo que dijo el emisor "
                f"sin decir qué implica deja al lector con una noticia, no con información.")


def cargar(expediente_id: str) -> List[Declaracion]:
    """Las declaraciones del expediente. Lista vacía si no las declara — no es un error."""
    import yaml  # type: ignore[import-untyped]

    ruta = RAIZ / expediente_id.replace("/", "") / ARCHIVO
    if not ruta.exists():
        return []
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    ds = [Declaracion(**d) for d in (doc.get("declaraciones") or [])]
    _validar(ds)
    return ds


def publicable(expediente_id: str) -> Dict[str, Any]:
    """Lo que viaja al informe y a la API."""
    ds = cargar(expediente_id)
    return {
        "total": len(ds),
        "declaraciones": [
            {"id": d.id, "fecha": d.fecha, "quien": d.quien, "que_declara": d.que_declara,
             "fuente": d.fuente, "disponible_desde": d.disponible_desde,
             "consecuencia_para_la_medicion": d.consecuencia_para_la_medicion}
            for d in sorted(ds, key=lambda x: x.fecha, reverse=True)],
        "con_fecha_de_disponibilidad": sum(1 for d in ds if d.disponible_desde),
        "nota": (
            "Son actos del propio evaluado, con fecha y fuente. «No hay dato» y «el emisor "
            "tiene el dato y declaró que no lo publica todavía» son cosas distintas."),
    }
