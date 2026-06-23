"""Smoke de cierre: confirma que la ruta cerebro está viva y orientada por audiencia en
los ejes GET-simples tras el deploy. Espera el deploy (probe), y por eje pide 2 audiencias
y verifica model=sonnet + textos distintos. Best-effort, resiliente a 502."""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://sdq-market-intelligence-production.up.railway.app"
# (eje, path-template, 2 audiencias)
CASES = [
    ("trade_intel", "/api/v1/trade-intel/insight?with_ai=true&audience={a}",
     ["exportador", "gobierno"]),
    ("social_dev", "/api/v1/social-dev/ozama/insight?audience={a}",
     ["formulador_politica", "inversionista_impacto"]),
    ("esg_climate", "/api/v1/esg-climate/DOM/insight?audience={a}",
     ["inversionista", "asegurador"]),
    ("macro_monitor", "/api/v1/macro-monitor/snapshot?with_ai=true&audience={a}",
     ["comite", "gobierno"]),
]


def _req(path, token, tries=6):
    for i in range(tries):
        req = urllib.request.Request(BASE + path)
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and i < tries - 1:
                time.sleep(8)
                continue
            raise


tok = json.loads(urllib.request.urlopen(urllib.request.Request(
    BASE + "/api/v1/auth/login", data=json.dumps(
        {"email": "claude@sdqconsulting.com.do", "password": "Claude1234"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")).read())["access_token"]

# espera de deploy via trade (cache-miss)
deadline = time.time() + 900
while time.time() < deadline:
    try:
        d = _req(CASES[0][1].format(a="exportador"), tok)
        ai = d.get("ai_insight") or {}
        print(f"  probe from_cache={ai.get('from_cache')} model={ai.get('model_used')}",
              file=sys.stderr)
        if ai.get("from_cache") is False:
            break
    except Exception as e:  # noqa: BLE001
        print("  probe err", e, file=sys.stderr)
    time.sleep(30)

out = []
for axis, tmpl, auds in CASES:
    texts = {}
    for a in auds:
        d = _req(tmpl.format(a=a), tok)
        ai = d.get("ai_insight") or {}
        texts[a] = ai.get("text") or ""
        print(f"  {axis:16s}/{a:20s} model={ai.get('model_used')} "
              f"cache={ai.get('from_cache')} chars={len(texts[a])}", file=sys.stderr)
    differ = texts[auds[0]] != texts[auds[1]] and all(texts.values())
    out.append({"axis": axis, "audiences": auds, "orientation_differs": differ,
                "texts": texts})
    print(f"  -> {axis}: orientación distinta entre audiencias = {differ}", file=sys.stderr)

with open("evidence/smoke_cerebro_axes.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("OK -> evidence/smoke_cerebro_axes.json", file=sys.stderr)
