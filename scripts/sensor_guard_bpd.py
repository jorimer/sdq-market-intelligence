"""Re-test del caso exacto que falló en el sensor previo: Banco Popular Dominicano
(4997e543) — las 4 audiencias, foco en supervisor (citaba 83.42 vs real 82.42).
"""
import json
import sys
import urllib.request

BASE = "https://sdq-market-intelligence-production.up.railway.app"
BID = "4997e543-d846-4600-a5de-a07355f1a756"
AUDIENCES = ["comite_credito", "entidad", "inversionista", "supervisor"]


def _req(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


token = _req("POST", "/api/v1/auth/login",
             body={"email": "claude@sdqconsulting.com.do", "password": "Claude1234"})["access_token"]
ctx = _req("GET", f"/api/v1/banking-score/{BID}/insight?with_ai=false", token)
ctx.pop("ai_insight", None)
out = [{"entity": "banco_popular_dominicano", "name": ctx.get("bank_name"), "context": ctx}]
for aud in AUDIENCES:
    ai = _req("GET", f"/api/v1/banking-score/{BID}/insight?with_ai=true&audience={aud}", token)
    ins = ai.get("ai_insight") or {}
    out.append({"entity": "banco_popular_dominicano", "name": ctx.get("bank_name"),
                "bank_id": BID, "audience": aud, "text": ins.get("text"),
                "model_used": ins.get("model_used"), "from_cache": ins.get("from_cache")})
    print(f"  {aud:16s} -> model={ins.get('model_used')} cache={ins.get('from_cache')} "
          f"chars={len(ins.get('text') or '')}", file=sys.stderr)

with open("evidence/sensor_guard_bpd_dump.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("OK -> evidence/sensor_guard_bpd_dump.json", file=sys.stderr)
