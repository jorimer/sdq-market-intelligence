"""Captura resiliente del sensor (sin probe; deploy ya confirmado vivo). Reintenta
errores transitorios (502/503) y vuelca a evidence/sensor_guard_prod_dump_v6.json.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://sdq-market-intelligence-production.up.railway.app"
AUDIENCES = ["comite_credito", "entidad", "inversionista", "supervisor"]
WANT = ["popular", "bhd", "santa cruz", "bdi", "reservas"]
BPD = "4997e543-d846-4600-a5de-a07355f1a756"
OUT = "evidence/sensor_guard_prod_dump_v6.json"


def _req(method, path, token=None, body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    for i in range(tries):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and i < tries - 1:
                print(f"  {e.code} transitorio, reintento {i + 1}", file=sys.stderr)
                time.sleep(8)
                continue
            raise


token = _req("POST", "/api/v1/auth/login",
             body={"email": "claude@sdqconsulting.com.do", "password": "Claude1234"})["access_token"]
cat = _req("GET", "/api/v1/banking-score/banks", token)
banks = cat if isinstance(cat, list) else cat.get("banks", cat.get("items", []))
chosen = {}
for b in banks:
    name = (b.get("name") or b.get("bank_name") or "")
    for w in WANT:
        if w in name.lower() and w not in chosen:
            chosen[w] = {"id": b.get("id"), "name": name}

out = []
targets = list(chosen.items()) + [("banco_popular_dominicano", {"id": BPD, "name": None})]
for w, info in targets:
    bid = info["id"]
    ctx = _req("GET", f"/api/v1/banking-score/{bid}/insight?with_ai=false", token)
    ctx.pop("ai_insight", None)
    name = info["name"] or ctx.get("bank_name")
    for aud in AUDIENCES:
        ai = _req("GET", f"/api/v1/banking-score/{bid}/insight?with_ai=true&audience={aud}",
                  token).get("ai_insight") or {}
        out.append({"entity": w, "name": name, "bank_id": bid, "audience": aud,
                    "text": ai.get("text"), "model_used": ai.get("model_used"),
                    "from_cache": ai.get("from_cache")})
        print(f"  {w:26s}/{aud:16s} cache={ai.get('from_cache')} chars={len(ai.get('text') or '')}",
              file=sys.stderr)
    out.append({"entity": w, "name": name, "context": ctx})

with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("OK ->", OUT, file=sys.stderr)
