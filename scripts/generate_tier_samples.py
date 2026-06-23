"""Genera las 3 muestras comerciales (Pulse / Insight / Deep Dive) con ``Banco Demo, S.A.``.

Sintético y sin DB: construye un ``scoring_result`` realista (alineado a los KPIs del
catálogo) + un agregado de sistema anonimizado, y produce un PDF por nivel con la
estampa de muestra. Corre el sensor de anonimización sobre el Pulse antes de renderizar.

    python scripts/generate_tier_samples.py [--output-dir DIR]
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.products import ProductSnapshot, ProductTier  # noqa: E402
from shared.products.anonymization import enforce_anonymized  # noqa: E402
from modules.banking_score.products import BankingProduct  # noqa: E402

DEMO_NAME = "Banco Demo, S.A."

# scoring_result sintético (KPIs del Anexo del catálogo: CAR ~16.8%, morosidad ~1.9%,
# ROE ~19.4%, eficiencia ~56%, liquidez ~31%). Banda resultante ≈ SDQ-AA- (Fuerte).
DEMO_SCORING = {
    "overall_score": 80.3, "rating_tier": "SDQ-AA-",
    "sub_components": {"solidez": 85, "calidad": 82, "eficiencia": 72,
                       "liquidez": 78, "diversificacion": 62},
    "indicators": {
        "solvencia": {"raw": 16.8, "score": 90, "available": True},
        "morosidad": {"raw": 1.9, "score": 85, "available": True},
        "roe": {"raw": 19.4, "score": 78, "available": True},
        "eficiencia": {"raw": 56.0, "score": 70, "available": True},
        "liquidez": {"raw": 31.0, "score": 80, "available": True},
    },
}

# Agregado de sistema sintético (RD ilustrativo) — sin entidades nombradas.
DEMO_SYSTEM = {"band_distribution": {"Fuerte": 6, "Adecuado": 8, "Vigilancia": 3, "Crítico": 1},
               "n_entities": 18, "system_avg_score": 71.8, "period": "2024-12-31"}

DEMO_PEER = {"metric_label": "Activos", "cr5": 71.2, "cr10": 87.4, "hhi": 1380}
PERIOD = "2024-12-31"


def _snapshot(tier: ProductTier) -> ProductSnapshot:
    if tier == ProductTier.pulse:
        return ProductSnapshot(tier=tier, period=PERIOD, payload=dict(DEMO_SYSTEM),
                               entity_name=None, entity_roster=(DEMO_NAME,))
    return ProductSnapshot(tier=tier, period=PERIOD,
                           payload={"scoring_result": DEMO_SCORING, "peer_block": DEMO_PEER},
                           entity_name=DEMO_NAME)


async def _generate(output_dir: str) -> list:
    product = BankingProduct()  # sin DB — vía sintética
    paths = []
    for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
        snap = _snapshot(tier)
        # Doctrina: el Pulse no puede filtrar identificadores — verificar antes de renderizar.
        if tier == ProductTier.pulse:
            enforce_anonymized(snap.payload, entity_roster=snap.entity_roster)
        narratives = await product.narratives(tier, snap)
        path = await product.render(tier, snap, narratives, sample=True, output_dir=output_dir)
        paths.append((tier.value, path))
        print(f"  {tier.value:10s} → {path}")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera las 3 muestras por nivel (Banco Demo).")
    parser.add_argument("--output-dir", default="samples/tiers",
                        help="Directorio de salida (default: samples/tiers).")
    args = parser.parse_args()
    out = os.path.abspath(args.output_dir)
    os.makedirs(out, exist_ok=True)
    print(f"Generando muestras en {out} …")
    asyncio.run(_generate(out))
    print("Listo: 3 muestras (Pulse · Insight · Deep Dive).")


if __name__ == "__main__":
    main()
