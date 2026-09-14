"""Cada corrida de scoring deja su fila en el registro, sin label, separada del curado.

**El problema.** `HistoricalDeal` solo se poblaba con «Guardar al registro» (`POST /deals`) o con
el seed. La curva de aprendizaje que decide si la rúbrica gradúa a modelo entrenado dependía de
una acción manual opcional: los labels, que son el activo que convierte una rúbrica en IP
defendible, se perdían por defecto.

**Qué se persiste.** Las entradas del deal y el score de la rúbrica, con `closed_successfully` y
`outcome_date` en NULL —la brecha se declara, no se rellena— y `origen="automatico"`. El label
llega después por `PATCH /deals/{deal_name}/outcome?origen=automatico`.

**Una fila por deal, no por corrida.** Scorear dos veces el mismo deal actualiza su fila
automática: la unidad de la curva es el deal, y dos filas del mismo deal inflarían el N de la
validación cruzada con observaciones que no son independientes.

**Nunca se reescribe una fila que ya tiene desenlace.** Scorear un deal después de conocer cómo
terminó y guardar esas entradas como ex-ante sería fuga de información: el modelo aprendería de
datos que no existían al decidir.

**No se inventa lo que falta.** `deal_type`, `sector` y `country` son obligatorios en la tabla. Si
no vienen o no son válidos, la corrida NO se guarda y la respuesta dice por qué. A diferencia de
`POST /deals`, acá el país no se completa con «DO» por defecto.

**Nunca tumba el score.** Un fallo al guardar se registra y se informa; el score se devuelve igual.

**Qué NO cambia.** La rúbrica, sus pesos y lo que se puede decir en material comercial
(`docs/CLAIMS_COMERCIALES.md` sigue prohibiendo «modelo predictivo» hasta que la curva lo
respalde).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from modules.deal_scoring.models.models import (
    DealStage,
    DealType,
    HistoricalDeal,
    LabelConfidence,
    Sector,
)
from modules.deal_scoring.parseo import enum_de, equity_de, num_de

logger = logging.getLogger("sdq.deal_scoring.registro")

ORIGEN_MANUAL = "manual"
ORIGEN_AUTOMATICO = "automatico"
ORIGENES = (ORIGEN_MANUAL, ORIGEN_AUTOMATICO)

_SENALES_DE_ANALISTA = ("promoter_track_record", "financial_quality", "market_validation",
                        "regulatory_readiness")


def _no_guardado(motivo: str) -> Dict[str, Any]:
    return {"guardado": False, "origen": ORIGEN_AUTOMATICO, "motivo": motivo}


def registrar_corrida(db: Session, body: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste (o actualiza) la fila automática del deal. Devuelve qué pasó; nunca lanza."""
    nombre = str(body.get("deal_name") or "").strip()
    tipo = enum_de(DealType, body.get("deal_type"))
    sector = enum_de(Sector, body.get("sector"))
    pais = str(body.get("country") or "").strip().upper()
    faltan = [campo for campo, ok in (("deal_name", bool(nombre)), ("deal_type", tipo is not None),
                                      ("sector", sector is not None),
                                      ("country", len(pais) == 2 and pais.isalpha()))
              if not ok]
    if faltan:
        return _no_guardado(
            "la corrida no se guarda en el registro: faltan o no son válidos "
            + ", ".join(faltan))

    try:
        fila = (db.query(HistoricalDeal)
                .filter(HistoricalDeal.deal_name == nombre,
                        HistoricalDeal.origen == ORIGEN_AUTOMATICO).one_or_none())
        if fila is not None and fila.closed_successfully is not None:
            return _no_guardado(
                "el deal ya tiene su desenlace registrado: guardar estas entradas como previas "
                "al resultado usaría información posterior a él")
        if fila is None:
            fila = HistoricalDeal(deal_name=nombre, origen=ORIGEN_AUTOMATICO,
                                  deal_type=tipo, sector=sector, country=pais,
                                  label_confidence=LabelConfidence.baja)
            db.add(fila)
        dias = num_de(body.get("days_since_first_contact"))
        score = result.get("score")
        confianza = result.get("confidence")
        valores: Dict[str, Any] = {
            "deal_type": tipo,
            "sector": sector,
            "country": pais,
            "deal_stage": enum_de(DealStage, body.get("deal_stage")),
            "deal_size_usd": num_de(body.get("deal_size_usd")),
            "equity_required_pct": equity_de(body.get("equity_required_pct")),
            "days_since_first_contact": None if dias is None else int(max(0, dias)),
            # Ex-ante por construcción: se scoreó antes de conocer el desenlace.
            "retrospective": False,
            "closed_successfully": None,
            "outcome_date": None,
            "score_rubrica": float(score) if isinstance(score, (int, float)) else None,
            "score_confianza": None if confianza is None else str(confianza)[:20],
            "scored_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
        for campo in _SENALES_DE_ANALISTA:
            valor = num_de(body.get(campo))
            valores[campo] = None if valor is None else int(max(0, min(100, valor)))
        # `setattr` y no asignación directa: `HistoricalDeal` es del estilo `Column` y el checker
        # lee `fila.country` como `Column[str]`. Es el ruido que el baseline ya carga en todo el
        # repo, no un error de tipo real, y un dict evita sumarle deuda sin `type: ignore`.
        for campo, valor in valores.items():
            setattr(fila, campo, valor)
        db.commit()
    except Exception as e:  # noqa: BLE001 — guardar la corrida nunca tumba el score
        db.rollback()
        logger.exception("No se pudo registrar la corrida de scoring de «%s»", nombre)
        return _no_guardado(f"no se pudo guardar la corrida: {type(e).__name__}")
    return {"guardado": True, "origen": ORIGEN_AUTOMATICO, "deal_name": nombre}
