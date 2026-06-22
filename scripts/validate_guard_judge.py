"""Validación LOCAL del juez reforzado (numeric_guard) sobre los 24 textos ya
capturados de prod, reconstruyendo el contexto fiel (ai_context_entity = trend[-12:]).

No prueba el end-to-end (regen) — eso se prueba re-corriendo el sensor en prod tras
deploy. Acá solo confirmo que el juez nuevo (Sonnet) MARCA los 3 defectos conocidos
y no inunda de falsos positivos las cifras de entidad limpias.

Nota: el telón BCRD no está en el contexto volcado, así que cifras macro del telón
(PIB, solvencia sistémica, morosidad sistémica, crecimiento sectorial) pueden salir
marcadas localmente — son ruido del replay, NO un problema de prod. Lo que importa:
¿salen marcados 83.45 (popular/supervisor), 11 puntos (bhd/entidad), 85.79
(reservas/entidad)?

Uso: /opt/anaconda3/bin/python scripts/validate_guard_judge.py
"""
import json
import os
import sys

# cargar .env para ANTHROPIC_API_KEY/GUARD_MODEL
from dotenv import load_dotenv  # type: ignore
load_dotenv()

sys.path.insert(0, os.getcwd())
from modules.banking_score.scoring.entity_insight import ai_context_entity  # noqa: E402
from shared.config.settings import settings  # noqa: E402
from shared.narrative.numeric_guard import verify_figures  # noqa: E402
import anthropic  # noqa: E402

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
GUARD = settings.ANTHROPIC_GUARD_MODEL
print(f"Guard model: {GUARD}", file=sys.stderr)

TARGETS = {
    ("popular", "supervisor"): "83.45",
    ("bhd", "entidad"): "11",
    ("reservas", "entidad"): "85.79",
    ("banco_popular_dominicano", "supervisor"): None,  # control: debe seguir limpio
}


def load(path):
    data = json.load(open(path))
    ctxs = {}
    texts = []
    for x in data:
        if "context" in x:
            ctxs[x["entity"]] = x["context"]
        else:
            texts.append(x)
    return ctxs, texts


def run(path):
    ctxs, texts = load(path)
    rows = []
    for t in texts:
        detail = ctxs[t["entity"]]
        ctx = ai_context_entity(detail)
        ctx_str = json.dumps(ctx, ensure_ascii=False, indent=2, default=str)
        flags = verify_figures(client, GUARD, ctx_str, t["text"])
        rows.append((t["entity"], t["audience"], flags))
        tgt = TARGETS.get((t["entity"], t["audience"]))
        hit = ""
        if tgt is not None:
            caught = any(tgt in f for f in flags)
            hit = f"  [TARGET {tgt}: {'CAUGHT' if caught else 'MISSED!!'}]"
        print(f"{t['entity']:26s}/{t['audience']:16s} flags={len(flags)}{hit}",
              file=sys.stderr)
        for f in flags:
            print(f"      - {f}", file=sys.stderr)
    return rows


print("\n===== sensor_guard_prod_dump.json =====", file=sys.stderr)
run("evidence/sensor_guard_prod_dump.json")
print("\n===== sensor_guard_bpd_dump.json =====", file=sys.stderr)
run("evidence/sensor_guard_bpd_dump.json")
