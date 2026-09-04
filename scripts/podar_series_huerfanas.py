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

Cómo decide qué es huérfano, y por qué hacen falta DOS fuentes:

* los códigos que produce el motor corriendo el corpus canónico acá, y
* un inventario del destino tomado **ANTES** de la sincronización (`--antes`).

La segunda no es burocracia. El nombrado semántico de las filas ambiguas lo resuelve el
MODELO, y en producción puede devolver un rótulo distinto del que devolvió acá para la misma
fila: medido el 2026-09-04, 49 códigos del PIB por origen, las llegadas y la balanza de pagos
salieron con nombres distintos en los dos entornos. Comparar el destino contra el motor local
y nada más marcaba esos 49 como huérfanos — y son series recién escritas, correctas.

La regla que lo cierra es observable y no depende del modelo: **un código que no estaba en el
destino antes de la sincronización, lo escribió la sincronización**. Por eso la poda solo
puede tocar códigos que ya estaban antes.

Uso::

    # 1. ANTES de sincronizar, guardar el inventario del destino
    python scripts/podar_series_huerfanas.py --guardar-inventario antes.json
    # 2. desplegar + correr `macro-canonical-sync`
    # 3. ensayo, y recién después el borrado
    python scripts/podar_series_huerfanas.py --antes antes.json
    python scripts/podar_series_huerfanas.py --antes antes.json --confirmar

Limitación declarada: el inventario del destino se lee de `/indicators`, que descarta los
períodos FUTUROS, así que una serie compuesta solo de períodos futuros no aparece y esta
poda no la ve. Sale en la siguiente corrida, cuando esos períodos dejen de ser futuros.
"""
from __future__ import annotations

import argparse
import json
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

    from modules.macro_monitor.service import huerfanas_podables, por_que_no_podar
    from scripts.ops_trigger import DEFAULT_BASE, _credentials

    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("SDQ_OPS_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--confirmar", action="store_true",
                    help="Borra de verdad. Sin esto solo lista.")
    ap.add_argument("--antes", help="JSON con el inventario del destino ANTERIOR a la "
                                    "sincronización. Obligatorio para borrar.")
    ap.add_argument("--guardar-inventario", metavar="ARCHIVO",
                    help="Guarda el inventario actual del destino y termina. Es el paso 1, "
                         "el que hay que correr ANTES de sincronizar.")
    args = ap.parse_args()

    email, password = _credentials()
    if args.guardar_inventario:
        with httpx.Client(base_url=args.base_url, timeout=180,
                          follow_redirects=True) as c:
            tok = c.post("/api/v1/auth/login",
                         json={"email": email, "password": password}).json()["access_token"]
            inv = inventario_del_destino(c, {"Authorization": f"Bearer {tok}"})
        Path(args.guardar_inventario).write_text(
            json.dumps({"codigos": sorted(inv)}, ensure_ascii=False))
        print(f"inventario guardado: {len(inv)} series → {args.guardar_inventario}")
        return 0

    if args.confirmar and not args.antes:
        raise SystemExit(
            "Para borrar hace falta --antes: el inventario del destino ANTERIOR a la "
            "sincronización. Sin él no se puede distinguir un código viejo de uno que la "
            "sincronización acaba de escribir con otro nombre — y borrar el segundo destruye "
            "datos correctos.")

    print("Leyendo los códigos que produce el motor…", flush=True)
    vivos = codigos_que_el_motor_produce()
    print(f"  el motor produce {len(vivos)} series")
    antes = (set(json.loads(Path(args.antes).read_text())["codigos"])
             if args.antes else None)
    with httpx.Client(base_url=args.base_url, timeout=180, follow_redirects=True) as c:
        salud = c.get("/api/v1/health").json()
        print(f"  destino: {args.base_url}  commit {salud['deployment']['commit_short']} "
              f"({salud['deployment']['branch']})")
        tok = c.post("/api/v1/auth/login",
                     json={"email": email, "password": password}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}
        destino = inventario_del_destino(c, headers)

        todas = {s for s in destino if s.startswith(PREFIJO) and s not in vivos}
        if antes is None:
            candidatas = todas
        else:
            candidatas = huerfanas_podables(set(destino), vivos, antes, PREFIJO)
            fuera = sorted(todas - candidatas)
            if fuera:
                print(f"\n  {len(fuera)} códigos NO se tocan: no estaban antes de la "
                      f"sincronización, así que los escribió ella.")
                for s in fuera[:5]:
                    print(f"     (se conserva) {s}")
        huerfanas: List[str] = sorted(candidatas)
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
