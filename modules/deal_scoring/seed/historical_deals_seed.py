"""Seed del registro de deals históricos (estructura ANONIMIZADA).

35 oportunidades del pipeline propio. Los identificadores reales (nombre del
deal, carpeta de origen, notas) **NO se versionan** — el repo es público y son
material de cliente. Viven en el inventario privado
`docs/Modelos Propietarios/SDQ_Deal_Register_Inventario.xlsx` (gitignoreado),
que mantiene el mapping código↔deal real. Aquí solo van las **features
estructurales** del spec (tipo, sector, país, tamaño, equity, etapa) + outcome
+ confianza del label, con código `DEAL-NNN`.

Composición:
  - 5 deals con datos reales extraídos de sus modelos financieros: 3 cerrados
    (DEAL-001/004/005) + 2 negativos explícitos (DEAL-006/007).
  - 30 placeholders del inventario (outcome/scores por confirmar abriendo
    contratos) → label_confidence='baja', closed=None.

Las 4 señales de analista (promoter/financial/market/regulatory) quedan en None:
no existen en data pública; las llena el juicio SDQ (backfill retrospectivo, ver
`scripts/backfill_deal_scores.py`). `closed_successfully` True en capital_raise =
mandato firmado/aceptado (semántica de cierre distinta a 'capital efectivamente
levantado' — ver doc de decisión privado).
"""
from datetime import date

from modules.deal_scoring.models.models import (
    DealStage,
    DealType,
    HistoricalDeal,
    LabelConfidence,
    Sector,
)

# Cada dict son kwargs de HistoricalDeal. Campos omitidos = None (default del
# modelo). source_folder/note se dejan vacíos: la trazabilidad real vive en el
# inventario privado (.xlsx gitignoreado), no en el repo público.
SEED: list[dict] = [
    # ── 5 con datos reales (3 cerrados + 2 negativos explícitos) ──
    dict(deal_name="DEAL-001", deal_type=DealType.capital_raise,
         sector=Sector.mining_energy, country="CO",
         deal_size_usd=14_000_000, equity_required_pct=4.29,
         deal_stage=DealStage.legal, closed_successfully=True,
         outcome_date=date(2025, 1, 1), label_confidence=LabelConfidence.alta),
    dict(deal_name="DEAL-002", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", deal_size_usd=19_560_000, equity_required_pct=30.0,
         deal_stage=DealStage.term_sheet, closed_successfully=None,
         label_confidence=LabelConfidence.media),
    dict(deal_name="DEAL-003", deal_type=DealType.capital_raise,
         sector=Sector.other, country="DO", deal_stage=DealStage.due_diligence,
         closed_successfully=None, label_confidence=LabelConfidence.media),
    dict(deal_name="DEAL-004", deal_type=DealType.capital_raise,
         sector=Sector.other, country="DO", deal_stage=DealStage.legal,
         closed_successfully=True, outcome_date=date(2025, 1, 1),
         label_confidence=LabelConfidence.media),
    dict(deal_name="DEAL-005", deal_type=DealType.capital_raise, sector=Sector.fintech,
         country="DO", deal_stage=DealStage.term_sheet, closed_successfully=True,
         label_confidence=LabelConfidence.media),
    dict(deal_name="DEAL-006", deal_type=DealType.ma_valuation,
         sector=Sector.other, country="DO", deal_stage=DealStage.initial,
         closed_successfully=False, label_confidence=LabelConfidence.alta),
    dict(deal_name="DEAL-007", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", deal_stage=DealStage.initial, closed_successfully=False,
         label_confidence=LabelConfidence.media),

    # ── 30 placeholders (estructura conocida; outcome/scores por confirmar) ──
    dict(deal_name="DEAL-008", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-009", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-010", deal_type=DealType.real_estate,
         sector=Sector.real_estate, country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-011", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-012", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-013", deal_type=DealType.capital_raise, sector=Sector.other,
         country="DO", deal_stage=DealStage.due_diligence, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-014", deal_type=DealType.debt_portfolio, sector=Sector.other,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-015", deal_type=DealType.debt_portfolio, sector=Sector.other,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-016", deal_type=DealType.financing, sector=Sector.other,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-017", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", deal_stage=DealStage.legal, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-018", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", deal_stage=DealStage.due_diligence, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-019", deal_type=DealType.real_estate, sector=Sector.tourism, country="MX",
         deal_stage=DealStage.due_diligence, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-020", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-021", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-022", deal_type=DealType.venture, sector=Sector.other,
         country="DO", deal_stage=DealStage.due_diligence, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-023", deal_type=DealType.venture, sector=Sector.other, country="CO",
         label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-024", deal_type=DealType.venture, sector=Sector.technology, country="CO",
         label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-025", deal_type=DealType.venture, sector=Sector.mining_energy, country="CO",
         label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-026", deal_type=DealType.venture, sector=Sector.fintech, country="CO",
         label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-027", deal_type=DealType.venture, sector=Sector.fintech, country="DO",
         deal_stage=DealStage.due_diligence, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-028", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-029", deal_type=DealType.real_estate, sector=Sector.real_estate, country="DO",
         deal_stage=DealStage.due_diligence, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-030", deal_type=DealType.real_estate, sector=Sector.tourism, country="DO",
         label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-031", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-032", deal_type=DealType.venture, sector=Sector.agriculture, country="DO",
         label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-033", deal_type=DealType.real_estate, sector=Sector.real_estate,
         country="DO", label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-034", deal_type=DealType.venture, sector=Sector.cpg, country="DO",
         deal_stage=DealStage.initial, label_confidence=LabelConfidence.baja),
    dict(deal_name="DEAL-035", deal_type=DealType.real_estate, sector=Sector.real_estate, country="DO",
         label_confidence=LabelConfidence.baja),
]


def load_seed(session, *, only_if_empty: bool = True) -> int:
    """Inserta el seed. Devuelve # de filas insertadas. Idempotente por nombre."""
    if only_if_empty and session.query(HistoricalDeal).count() > 0:
        return 0
    existing = {d.deal_name for d in session.query(HistoricalDeal.deal_name).all()} \
        if not only_if_empty else set()
    inserted = 0
    for row in SEED:
        if row["deal_name"] in existing:
            continue
        session.add(HistoricalDeal(**row))
        inserted += 1
    session.commit()
    return inserted
