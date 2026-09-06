"""Conclusión y responsabilidad: quién responde por la valuación, con qué versión del método,
con qué estado de validación y desde qué posición frente a la entidad.

Es la novena sección de la estructura pedida para un informe de valuación —conclusión y
firma— y no existía: el informe concluía un valor y nadie lo firmaba. Tres decisiones del
dueño (2026-09-06) la gobiernan: la responsabilidad es INSTITUCIONAL (SDQ Consulting, sin
firmante personal); la independencia se AFIRMA salvo para las entidades declaradas en
`settings.VALUACION_ENTIDADES_CON_RELACION`, donde se declara la relación; y va en insight y
deep dive.

**Todo se computa.** La fecha de emisión es la del snapshot; la versión de la metodología es la
última entrada del registro de cambios del eje (`shared/doctrine/changelog.yaml`); el estado de
validación es el que declara el producto (`validation_state()`); la relación con la entidad
sale de la configuración. Nada se escribe a mano en la prosa: un número o una fecha copiada se
desincroniza, y una firma fabricada es peor que ninguna.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

FIRMANTE = "SDQ Consulting"
PLATAFORMA = "SDQ·MIP"


@dataclass(frozen=True)
class Cierre:
    emitido_el: str
    corte: str
    #: La última entrada del registro de cambios del eje al emitir, o `None` si no hay.
    metodologia_id: Optional[str]
    metodologia_fecha: Optional[str]
    metodologia_titulo: Optional[str]
    validacion_aprobada: bool
    #: Contra qué desenlace se validaría (o se validó) el eje: lo declara `ESTADO_BACKTEST`.
    validacion_desenlace: str
    #: `None` = independiente. Si no, el texto de la relación declarada.
    relacion_declarada: Optional[str] = None


def entidades_con_relacion() -> set:
    """Nombres o ids configurados, normalizados. Vacío si no hay ninguna."""
    from shared.config.settings import settings
    crudo = getattr(settings, "VALUACION_ENTIDADES_CON_RELACION", "") or ""
    return {x.strip().lower() for x in crudo.split(",") if x.strip()}


def leer_cierre(*, entidad: str, bank_id: str, corte: str, validacion_aprobada: bool,
                desenlace: str, hoy: Optional[date] = None) -> Cierre:
    from shared.doctrine.changelog import cambios
    ultimos = cambios("valuation")
    ultimo = ultimos[0] if ultimos else None
    con_relacion = entidades_con_relacion()
    relacion = None
    if entidad.strip().lower() in con_relacion or bank_id.strip().lower() in con_relacion:
        relacion = (f"{FIRMANTE} mantiene una relación profesional con {entidad}")
    return Cierre(
        emitido_el=(hoy or date.today()).isoformat(), corte=corte,
        metodologia_id=str(ultimo["id"]) if ultimo else None,
        metodologia_fecha=str(ultimo["fecha_efectiva"]) if ultimo else None,
        metodologia_titulo=str(ultimo["titulo"]) if ultimo else None,
        validacion_aprobada=validacion_aprobada, validacion_desenlace=desenlace,
        relacion_declarada=relacion)


def a_dict(c: Cierre) -> Dict[str, Any]:
    return {"emitido_el": c.emitido_el, "corte": c.corte,
            "metodologia": (None if c.metodologia_id is None else
                            {"id": c.metodologia_id, "fecha_efectiva": c.metodologia_fecha,
                             "titulo": c.metodologia_titulo}),
            "validacion": {"aprobada": c.validacion_aprobada, "desenlace": c.validacion_desenlace},
            "relacion_declarada": c.relacion_declarada}


def desde_dict(d: Optional[Dict[str, Any]]) -> Optional[Cierre]:
    if not d or not d.get("emitido_el") or not d.get("corte"):
        return None
    m = d.get("metodologia") or {}
    v = d.get("validacion") or {}
    return Cierre(emitido_el=str(d["emitido_el"]), corte=str(d["corte"]),
                  metodologia_id=(str(m["id"]) if m.get("id") else None),
                  metodologia_fecha=(str(m["fecha_efectiva"]) if m.get("fecha_efectiva") else None),
                  metodologia_titulo=(str(m["titulo"]) if m.get("titulo") else None),
                  validacion_aprobada=bool(v.get("aprobada")),
                  validacion_desenlace=str(v.get("desenlace") or ""),
                  relacion_declarada=(str(d["relacion_declarada"]) if d.get("relacion_declarada")
                                      else None))
