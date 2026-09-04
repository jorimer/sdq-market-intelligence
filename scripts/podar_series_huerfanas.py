"""Poda las series macro que el extractor DEJÓ DE PRODUCIR. Por defecto NO borra.

Por qué existe. `ingest_canonical` hace upsert por (serie, período) y **nunca poda**: cuando
una corrección del extractor renombra una serie, el código viejo se queda en `mm_series`
sirviendo datos que ya nadie produce. No falla, no avisa y no se nota — es el arrastre de
todo renombrado masivo.

El ORDEN importa y no es negociable:

1. desplegar el código corregido,
2. correr `macro-canonical-sync` (que escribe los códigos nuevos),
3. recién entonces esta poda.

Al revés se borran observaciones que todavía se sirven y no vuelve nada hasta la siguiente
sincronización — que además, con el código viejo desplegado, las repondría con el nombre y el
valor equivocados.

Cómo decide qué es huérfano: compara los códigos VIVOS en el destino contra los que produce
el motor corriendo el corpus canónico acá. No usa una lista escrita a mano: una lista
envejece entre que se calcula y se ejecuta, y lo que está en juego es un `DELETE`.

Uso::

    python scripts/podar_series_huerfanas.py                    # ensayo: lista y no borra
    python scripts/podar_series_huerfanas.py --confirmar        # borra, una por una

Limitación declarada: el inventario del destino se lee de `/indicators`, que descarta los
períodos FUTUROS, así que una serie compuesta solo de períodos futuros no aparece y esta
poda no la ve. Sale en la siguiente corrida, cuando esos períodos dejen de ser futuros.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PREFIJO = "bcrd.xls."


def codigos_que_el_motor_produce() -> Set[str]:
    """Los códigos que salen hoy de correr el corpus canónico. Es la verdad contra la que
    se decide: lo que no está acá, ya nadie lo produce."""
    from shared.data.bcrd_excel import canonical
    from shared.data.bcrd_excel.catalog import find_entry
    from shared.data.bcrd_excel.engine import SpecCache, ingest_excel

    cache = SpecCache()
    vivos: Set[str] = set()
    for archivo in sorted({s.source_file for s in canonical.registry()}):
        entrada = find_entry(archivo)
        if entrada is None:
            continue
        r = ingest_excel(entrada, cache=cache, use_claude=True)
        vivos.update(x.series for x in r.records)
    return vivos


def inventario_del_destino(client, headers) -> Dict[str, int]:
    r = client.get("/api/v1/macro-monitor/indicators", headers=headers)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("text/html"):
        raise SystemExit("El destino devolvió el HTML del SPA: la ruta no existe en ese "
                         "despliegue. Verificá la versión servida antes de seguir.")
    return {i["series_code"]: i.get("n_obs") or 0 for i in r.json()["indicators"]}


def main() -> int:
    import httpx

    from modules.macro_monitor.service import por_que_no_podar
    from scripts.ops_trigger import DEFAULT_BASE, _credentials

    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("SDQ_OPS_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--confirmar", action="store_true",
                    help="Borra de verdad. Sin esto solo lista.")
    args = ap.parse_args()

    print("Leyendo los códigos que produce el motor…", flush=True)
    vivos = codigos_que_el_motor_produce()
    print(f"  el motor produce {len(vivos)} series")

    email, password = _credentials()
    with httpx.Client(base_url=args.base_url, timeout=180, follow_redirects=True) as c:
        salud = c.get("/api/v1/health").json()
        print(f"  destino: {args.base_url}  commit {salud['deployment']['commit_short']} "
              f"({salud['deployment']['branch']})")
        tok = c.post("/api/v1/auth/login",
                     json={"email": email, "password": password}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}
        destino = inventario_del_destino(c, headers)

        huerfanas: List[str] = sorted(
            s for s in destino if s.startswith(PREFIJO) and s not in vivos)
        obs = sum(destino[s] for s in huerfanas)
        print(f"\n  el destino sirve {len(destino)} series "
              f"({sum(1 for s in destino if s.startswith(PREFIJO))} del motor Excel)")
        print(f"  HUÉRFANAS: {len(huerfanas)} series · {obs} observaciones")
        for s in huerfanas[:20]:
            print(f"     {destino[s]:6d} obs  {s}")
        if len(huerfanas) > 20:
            print(f"     … y {len(huerfanas) - 20} más")

        if not huerfanas:
            return 0
        if not args.confirmar:
            print("\n  ENSAYO: no se borró nada. Repetir con --confirmar.")
            return 0

        motivo = por_que_no_podar(vivos, set(destino))
        if motivo:
            raise SystemExit(f"ABORTA: {motivo}")

        borradas = 0
        for s in huerfanas:
            r = c.delete(f"/api/v1/macro-monitor/series/{s}", headers=headers)
            r.raise_for_status()
            borradas += r.json().get("deleted", 0)
            print(f"     borrada {s}", flush=True)
        print(f"\n  {len(huerfanas)} series podadas, {borradas} observaciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
