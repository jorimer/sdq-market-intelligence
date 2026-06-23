"""Re-run del sensor del guardrail en prod TRAS deploy del juez reforzado (#259).

El caché de narrativa es in-process; el deploy reinicia el proceso y lo limpia. Este
script: (1) hace polling de un insight hasta detectar from_cache=False (= proceso
reiniciado = deploy vivo), y (2) dispara el set completo (5 entidades × 4 audiencias +
Banco Popular Dominicano × 4), todo cache-miss → pasa por el guard nuevo. Vuelca a
evidence/sensor_guard_prod_dump_v5.json para auditar.
"""
import json
import sys
import time
import urllib.request

BASE = "https://sdq-market-intelligence-production.up.railway.app"
EMAIL = "claude@sdqconsulting.com.do"
PASSWORD = "Claude1234"
AUDIENCES = ["comite_credito", "entidad", "inversionista", "supervisor"]
WANT = ["popular", "bhd", "santa cruz", "bdi", "reservas"]
BPD = "4997e543-d846-4600-a5de-a07355f1a756"  # Banco Popular Dominicano (caso histórico)


def _req(method, path, token=None, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def login():
    return _req("POST", "/api/v1/auth/login",
                body={"email": EMAIL, "password": PASSWORD})["access_token"]


def get_insight(token, bid, aud):
    ai = _req("GET", f"/api/v1/banking-score/{bid}/insight?with_ai=true&audience={aud}",
              token)
    return ai.get("ai_insight") or {}


def wait_for_deploy(token, probe_bid, max_wait=900):
    """Poll until from_cache=False on a probe insight (process restarted = deploy live)."""
    deadline = time.time() + max_wait
    n = 0
    while time.time() < deadline:
        n += 1
        try:
            ins = get_insight(token, probe_bid, "comite_credito")
            fc = ins.get("from_cache")
            print(f"  probe #{n}: from_cache={fc} model={ins.get('model_used')}",
                  file=sys.stderr)
            if fc is False:
                print("  -> cache-miss detectado: deploy vivo, caché limpio", file=sys.stderr)
                return True
        except Exception as e:  # noqa: BLE001
            print(f"  probe #{n}: error {e} (deploy en curso?)", file=sys.stderr)
        time.sleep(30)
    print("  -> timeout esperando deploy", file=sys.stderr)
    return False


def main():
    token = login()
    cat = _req("GET", "/api/v1/banking-score/banks", token)
    banks = cat if isinstance(cat, list) else cat.get("banks", cat.get("items", []))
    chosen = {}
    for b in banks:
        name = (b.get("name") or b.get("bank_name") or "")
        for w in WANT:
            if w in name.lower() and w not in chosen:
                chosen[w] = {"id": b.get("id"), "name": name}

    # probe = primera entidad elegida
    probe_bid = next(iter(chosen.values()))["id"]
    print("Esperando deploy (polling cache-miss)...", file=sys.stderr)
    wait_for_deploy(token, probe_bid)

    # añadir BPD como 6ta entidad (caso histórico)
    out = []
    targets = list(chosen.items()) + [("banco_popular_dominicano", {"id": BPD, "name": None})]
    for w, info in targets:
        bid = info["id"]
        ctx = _req("GET", f"/api/v1/banking-score/{bid}/insight?with_ai=false", token)
        ctx.pop("ai_insight", None)
        name = info["name"] or ctx.get("bank_name")
        for aud in AUDIENCES:
            ins = get_insight(token, bid, aud)
            out.append({"entity": w, "name": name, "bank_id": bid, "audience": aud,
                        "text": ins.get("text"), "model_used": ins.get("model_used"),
                        "from_cache": ins.get("from_cache")})
            print(f"  {w:26s}/{aud:16s} model={ins.get('model_used')} "
                  f"cache={ins.get('from_cache')} chars={len(ins.get('text') or '')}",
                  file=sys.stderr)
        out.append({"entity": w, "name": name, "context": ctx})

    with open("evidence/sensor_guard_prod_dump_v5.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("OK -> evidence/sensor_guard_prod_dump_v5.json", file=sys.stderr)


if __name__ == "__main__":
    main()
