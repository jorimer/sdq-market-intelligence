"""Sensor del guardrail numérico (cerebro banking) contra PROD.

Trae, para cada entidad×audiencia, el insight de IA en vivo (pasa por el guard
antes de servirse) + el contexto estructurado (with_ai=false), y vuelca todo a
un JSON para auditar que toda cifra del texto trace al contexto.

Uso: /opt/anaconda3/bin/python scripts/sensor_guard_prod.py
"""
import json
import sys
import urllib.request

BASE = "https://sdq-market-intelligence-production.up.railway.app"
EMAIL = "claude@sdqconsulting.com.do"
PASSWORD = "Claude1234"
AUDIENCES = ["comite_credito", "entidad", "inversionista", "supervisor"]
WANT = ["popular", "bhd", "santa cruz", "bdi", "reservas"]


def _req(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main():
    token = _req("POST", "/api/v1/auth/login",
                 body={"email": EMAIL, "password": PASSWORD})["access_token"]
    cat = _req("GET", "/api/v1/banking-score/banks", token)
    banks = cat if isinstance(cat, list) else cat.get("banks", cat.get("items", []))
    chosen = {}
    for b in banks:
        name = (b.get("name") or b.get("bank_name") or "")
        nl = name.lower()
        for w in WANT:
            if w in nl and w not in chosen:
                chosen[w] = {"id": b.get("id"), "name": name}
    print("Entidades:", json.dumps(chosen, ensure_ascii=False), file=sys.stderr)

    out = []
    for w, info in chosen.items():
        bid = info["id"]
        ctx = _req("GET", f"/api/v1/banking-score/{bid}/insight?with_ai=false", token)
        # quitar ai_insight (None) para dejar solo contexto
        ctx.pop("ai_insight", None)
        for aud in AUDIENCES:
            ai = _req("GET",
                      f"/api/v1/banking-score/{bid}/insight?with_ai=true&audience={aud}",
                      token)
            ins = ai.get("ai_insight") or {}
            out.append({
                "entity": w,
                "name": info["name"],
                "bank_id": bid,
                "audience": aud,
                "text": ins.get("text"),
                "model_used": ins.get("model_used"),
                "from_cache": ins.get("from_cache"),
            })
            print(f"  {w:12s} / {aud:16s} -> model={ins.get('model_used')} "
                  f"cache={ins.get('from_cache')} chars={len(ins.get('text') or '')}",
                  file=sys.stderr)
        # adjuntar el contexto una vez por entidad
        out.append({"entity": w, "name": info["name"], "context": ctx})

    with open("evidence/sensor_guard_prod_dump.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("OK -> evidence/sensor_guard_prod_dump.json", file=sys.stderr)


if __name__ == "__main__":
    main()
