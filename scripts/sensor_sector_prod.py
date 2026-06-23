"""Sensor del Cerebro en el eje sectorial (post-deploy). Espera el deploy (probe
cache-miss, resiliente a 502) y captura, para N sectores × 4 audiencias, el insight +
el /latest (para reconstruir el contexto y auditar). Vuelca a evidence/sensor_sector_prod.json
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://sdq-market-intelligence-production.up.railway.app"
AUDIENCES = ["inversionista", "empresa", "financiador", "formulador_politica"]
N_SECTORS = 4
OUT = "evidence/sensor_sector_prod.json"


def _req(method, path, token=None, body=None, tries=6):
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
                time.sleep(8)
                continue
            raise


token = _req("POST", "/api/v1/auth/login",
             body={"email": "claude@sdqconsulting.com.do", "password": "Claude1234"})["access_token"]
sectors = [s["code"] for s in _req("GET", "/api/v1/sector-intel/sectors", token)["sectors"]
           if s.get("is_active")][:N_SECTORS]
print("sectores:", sectors, file=sys.stderr)


def insight(code, aud):
    return (_req("GET", f"/api/v1/sector-intel/{code}/insight?audience={aud}", token)
            .get("ai_insight") or {})


# espera de deploy
deadline = time.time() + 900
while time.time() < deadline:
    try:
        ins = insight(sectors[0], "inversionista")
        print(f"  probe from_cache={ins.get('from_cache')} model={ins.get('model_used')}",
              file=sys.stderr)
        if ins.get("from_cache") is False:
            print("  deploy vivo", file=sys.stderr)
            break
    except Exception as e:  # noqa: BLE001
        print(f"  probe err {e}", file=sys.stderr)
    time.sleep(30)

out = []
for code in sectors:
    latest = _req("GET", f"/api/v1/sector-intel/{code}/latest", token)
    out.append({"sector": code, "latest": latest})
    for aud in AUDIENCES:
        ins = insight(code, aud)
        out.append({"sector": code, "audience": aud, "text": ins.get("text"),
                    "model_used": ins.get("model_used"), "from_cache": ins.get("from_cache")})
        print(f"  {code:14s}/{aud:20s} model={ins.get('model_used')} "
              f"cache={ins.get('from_cache')} chars={len(ins.get('text') or '')}",
              file=sys.stderr)

with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("OK ->", OUT, file=sys.stderr)
