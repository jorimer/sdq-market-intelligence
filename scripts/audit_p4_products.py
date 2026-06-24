"""Auditoría P4 — verifica end-to-end que los 10 sectores aparecen en /products con
readiness real y gate funcional. READ-ONLY: computa readiness en memoria desde las
señales reales del contrato (que leen la DB dev), sin persistir nada. Correr desde la
raíz del repo: PYTHONPATH=. /opt/anaconda3/bin/python scripts/audit_p4_products.py
"""
from __future__ import annotations

# 1) Disparar el auto-registro de los 10 productos (misma cadena que app/main.py).
import modules.banking_score.products      # noqa: F401  banking
import modules.trade_intel.products        # noqa: F401  trade
import modules.esg_climate.products        # noqa: F401  esg
import modules.sector_intel.products       # noqa: F401  tourism/free_zones/construction/agribusiness
import modules.energy_intel.products       # noqa: F401  energy
import modules.telecom_intel.products      # noqa: F401  telecom
from app import products_macro             # noqa: F401  macro

from shared.database.session import SessionLocal
from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented, registered_sectors
from shared.products.readiness import compute_readiness
from shared.products.activation import ACTIVATION_THRESHOLD, can_activate
from shared.products.tiers import ProductTier


def main() -> None:
    db = SessionLocal()
    try:
        print("=" * 90)
        print("AUDITORÍA P4 — 10 productos sectoriales × 3 niveles (read-only, motor real)")
        print("=" * 90)

        # A) Cobertura del catálogo.
        reg = set(registered_sectors())
        print(f"\n[A] Catálogo: {len(PRODUCT_CATALOG)} sectores · registrados: {len(reg)}/10")
        for e in PRODUCT_CATALOG:
            mark = "OK   " if is_implemented(e.sector_key) else "FALTA"
            print(f"    [{mark}] {e.sector_key:<13} {e.display_name}")

        # B) Readiness real por sector × nivel.
        print(f"\n[B] Umbrales: pulse={ACTIVATION_THRESHOLD[ProductTier.pulse]}  "
              f"insight={ACTIVATION_THRESHOLD[ProductTier.insight]}  "
              f"deep_dive={ACTIVATION_THRESHOLD[ProductTier.deep_dive]}")
        print(f"\n{'sector':<13} {'nivel':<10} {'ready':>6} {'umbral':>6} {'act':<4} "
              f"{'g1':>5}{'g2':>5}{'g3':>5}{'g4':>5}{'g5':>5}  cuello / nota")
        print("-" * 100)

        publishable, wired_not_pub, errors = [], [], []
        for e in PRODUCT_CATALOG:
            product = get_product(e.sector_key, db)
            if product is None:
                print(f"{e.sector_key:<13} (sin producto registrado)")
                continue
            try:
                tiers = product.product_manifest().tiers()
            except Exception as ex:  # noqa: BLE001
                errors.append((e.sector_key, f"manifest: {ex}"))
                print(f"{e.sector_key:<13} ERROR manifest: {ex}")
                continue
            for tier in tiers:
                try:
                    rep = compute_readiness(product, tier)
                except Exception as ex:  # noqa: BLE001
                    msg = str(ex).splitlines()[0][:80]
                    errors.append((e.sector_key, tier.value, msg))
                    print(f"{e.sector_key:<13} {tier.value:<10} ERROR: {msg}")
                    continue
                g = {k: rep[k] for k in ("g1", "g2", "g3", "g4", "g5")}
                r = rep["readiness"]
                thr = ACTIVATION_THRESHOLD[tier]
                ok = can_activate(r, tier)
                bottleneck = min(g, key=g.get)
                g1_note = rep["detail"]["g1"][:46]
                print(f"{e.sector_key:<13} {tier.value:<10} {r:>6.2f} {thr:>6.2f} "
                      f"{'SÍ' if ok else 'no':<4} "
                      + "".join(f"{g[k]:>5.2f}" for k in ("g1", "g2", "g3", "g4", "g5"))
                      + f"  {bottleneck}={g[bottleneck]:.2f} | {g1_note}")
                tag = (e.sector_key, tier.value, r)
                (publishable if ok else wired_not_pub).append(tag)

        # C) Resumen + sanity del gate.
        print("\n[C] Resumen:")
        print(f"    Cableados (registrados): {len(reg)}/10")
        print(f"    Publicables (readiness ≥ umbral): {len(publishable)}")
        for k, t, r in publishable:
            print(f"        + {k}/{t} ({r:.2f})")
        print(f"    Cableados-pero-no-publicables (honesto): {len(wired_not_pub)}")
        for k, t, r in wired_not_pub:
            print(f"        · {k}/{t} ({r:.2f})")
        if errors:
            print(f"\n[!] ERRORES: {len(errors)}")
            for er in errors:
                print(f"        {er}")

        # D) Gate sano: nadie publicable por debajo de su umbral.
        leak = [(k, t, r) for (k, t, r) in publishable if r < ACTIVATION_THRESHOLD[ProductTier(t)]]
        print(f"\n[D] Gate sano: {len(leak)} fugas (publicable con readiness<umbral) — debe ser 0")
        if leak:
            print(f"    FUGA: {leak}")
        print("\nFIN.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
