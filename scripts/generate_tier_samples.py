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

from shared.products import ProductTier  # noqa: E402
from shared.products.anonymization import enforce_anonymized  # noqa: E402
from modules.banking_score.products import BankingProduct  # noqa: E402


async def _generate(output_dir: str) -> list:
    product = BankingProduct()  # sin DB — vía sintética (sample_snapshot del producto)
    paths = []
    for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
        snap = product.sample_snapshot(tier)  # fuente única del demo (vive en el producto)
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
