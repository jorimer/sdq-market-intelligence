"""Test OFFLINE del detector determinista contra los 24 textos ya capturados en prod.
Ground truth: debe marcar bdi/comite(15.7), bhd/comite(6.2), popular/supervisor(83.45),
bpd/supervisor(88.96); y minimizar falsos positivos en el resto.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from modules.banking_score.scoring.entity_insight import ai_context_entity  # noqa: E402
from shared.narrative.numeric_guard import deterministic_unsupported  # noqa: E402

EXPECTED = {
    ("bdi", "comite_credito"): "15.7",
    ("bhd", "comite_credito"): "6.2",
    ("popular", "supervisor"): "83.45",
    ("banco_popular_dominicano", "supervisor"): "88.96",
}


def load(path):
    data = json.load(open(path))
    ctxs = {x["entity"]: x["context"] for x in data if "context" in x}
    texts = [x for x in data if "text" in x]
    return ctxs, texts


ctxs, texts = load("evidence/sensor_guard_prod_dump_v2.json")
total_flags = 0
caught = {}
for t in texts:
    ctx = ai_context_entity(ctxs[t["entity"]])
    flags = deterministic_unsupported(ctx, t["text"])
    total_flags += len(flags)
    key = (t["entity"], t["audience"])
    exp = EXPECTED.get(key)
    tag = ""
    if exp:
        hit = any(exp in f for f in flags)
        caught[key] = hit
        tag = f"  [TARGET {exp}: {'CAUGHT' if hit else 'MISSED!!'}]"
    mark = "FLAGS" if flags else "ok"
    print(f"{t['entity']:26s}/{t['audience']:16s} {mark}{tag}")
    for f in flags:
        print(f"      - {f}")

print("\n=== TARGETS ===")
for k, v in caught.items():
    print(f"  {k}: {'CAUGHT' if v else 'MISSED'}")
print(f"\nTargets capturados: {sum(caught.values())}/{len(EXPECTED)}")
print(f"Flags totales (incl. posibles FP): {total_flags}")
