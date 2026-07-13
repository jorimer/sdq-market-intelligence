"""A/B del juez del guardrail numérico: Sonnet 4.6 (actual) vs Haiku 4.5 (candidato).

Regla del plan de remediación (Ola C, PR-7): el juez solo se cambia a Haiku si la
discrepancia de VEREDICTO con Sonnet sobre 20 narrativas reales de prod es <=5%.
Además Haiku debe cazar los 3 defectos conocidos del sensor del piloto (los
"targets") — son la razón de existir del juez. Nota: la capa DETERMINISTA
(deterministic_unsupported) hoy cubre los modos mecánicos que Haiku falló en el
piloto original, así que este A/B evalúa a Haiku SOLO en su rol semántico.

Corpus: evidence/sensor_guard_prod_dump.json (20 textos con contexto fiel).

Uso: /opt/anaconda3/bin/python scripts/ab_guard_judge_haiku.py
"""
import json
import os
import sys

from dotenv import load_dotenv  # type: ignore

load_dotenv()
sys.path.insert(0, os.getcwd())

from modules.banking_score.scoring.entity_insight import ai_context_entity  # noqa: E402
from shared.config.settings import settings  # noqa: E402
from shared.narrative.numeric_guard import verify_figures  # noqa: E402
import anthropic  # noqa: E402

MODEL_A = "claude-sonnet-4-6"   # juez actual
MODEL_B = "claude-haiku-4-5"    # candidato

# Defectos conocidos capturados por el sensor del piloto (deben salir marcados).
TARGETS = {
    ("popular", "supervisor"): "83.45",
    ("bhd", "entidad"): "11",
    ("reservas", "entidad"): "85.79",
}

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def load(path):
    data = json.load(open(path))
    ctxs, texts = {}, []
    for x in data:
        if "context" in x:
            ctxs[x["entity"]] = x["context"]
        else:
            texts.append(x)
    return ctxs, texts


def main():
    ctxs, texts = load("evidence/sensor_guard_prod_dump.json")
    rows = []
    for t in texts:
        ctx_str = json.dumps(ai_context_entity(ctxs[t["entity"]]),
                             ensure_ascii=False, indent=2, default=str)
        flags_a = verify_figures(client, MODEL_A, ctx_str, t["text"])
        flags_b = verify_figures(client, MODEL_B, ctx_str, t["text"])
        verdict_a, verdict_b = bool(flags_a), bool(flags_b)
        tgt = TARGETS.get((t["entity"], t["audience"]))
        row = {
            "entity": t["entity"], "audience": t["audience"],
            "sonnet_flags": flags_a, "haiku_flags": flags_b,
            "sonnet_verdict": verdict_a, "haiku_verdict": verdict_b,
            "verdict_match": verdict_a == verdict_b,
            "target": tgt,
            "target_caught_sonnet": any(tgt in f for f in flags_a) if tgt else None,
            "target_caught_haiku": any(tgt in f for f in flags_b) if tgt else None,
        }
        rows.append(row)
        print(f"{row['entity']:26s}/{row['audience']:16s} "
              f"S={len(flags_a):2d} H={len(flags_b):2d} "
              f"match={row['verdict_match']} "
              f"tgt={'' if not tgt else ('S:' + str(row['target_caught_sonnet']) + ' H:' + str(row['target_caught_haiku']))}",
              file=sys.stderr)

    n = len(rows)
    mismatches = [r for r in rows if not r["verdict_match"]]
    discrepancy = len(mismatches) / n * 100
    targets_total = sum(1 for r in rows if r["target"])
    targets_haiku = sum(1 for r in rows if r["target"] and r["target_caught_haiku"])
    targets_sonnet = sum(1 for r in rows if r["target"] and r["target_caught_sonnet"])

    summary = {
        "n_texts": n,
        "verdict_mismatches": len(mismatches),
        "discrepancy_pct": round(discrepancy, 1),
        "gate": "<=5% para cambiar a Haiku",
        "targets": {"total": targets_total, "sonnet": targets_sonnet, "haiku": targets_haiku},
        "decision": ("CAMBIAR a Haiku" if discrepancy <= 5.0 and targets_haiku == targets_total
                     else "NO cambiar (queda Sonnet)"),
        "mismatch_detail": [
            {k: r[k] for k in ("entity", "audience", "sonnet_flags", "haiku_flags")}
            for r in mismatches
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    with open("evidence/ab_guard_judge_haiku_result.json", "w") as f:
        json.dump({"summary": summary, "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
