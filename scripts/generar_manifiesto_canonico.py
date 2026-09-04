"""Genera —y RATCHEA— el manifiesto de integridad de T-PS-4 desde una base sincronizada.

El manifiesto (`modules/macro_monitor/tests/manifiesto_persistencia_canonica.json`) es el
contrato que congela qué serie produce cada entrada canónica y con cuánta historia. Se
regenera después de cada cambio del extractor:

    python scripts/generar_manifiesto_canonico.py <base.db> <manifiesto.json>

**`min_obs` es un TRINQUETE: nunca baja.** El BCRD no retira historia, así que una serie con
menos observaciones que la última vez es una lectura truncada — el defecto que más veces
apareció en este corpus. Si el generador aceptara el número nuevo, regenerar el manifiesto
sería exactamente el gesto que borra la evidencia del defecto que el manifiesto existe para
detectar. Cuando baja, el generador lo DECLARA, conserva el máximo y sale con código 1.

Bajar el piso a propósito (el emisor rehízo la serie, cambió de base) se hace a mano y se
justifica en el commit.
"""
import json
import pathlib
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from shared.data.bcrd_excel import canonical
from shared.data.bcrd_excel.extract import default_prefix
from shared.data.series_cadence import cadencia_de_periodo

def siguiente(p, cad):
    if cad == "annual":
        return str(int(p) + 1)
    if cad == "quarterly":
        a, q = int(p[:4]), int(p[-1])
        return f"{a + 1}-Q1" if q == 4 else f"{a}-Q{q + 1}"
    if cad == "monthly":
        a, m = int(p[:4]), int(p[5:7])
        return f"{a + 1}-01" if m == 12 else f"{a}-{m + 1:02d}"
    return None

con = sqlite3.connect(sys.argv[1])
obs = defaultdict(list)
for c, p in con.execute("select series_code, period from mm_series "
                        "where series_code like 'bcrd.xls.%'"):
    obs[c].append(p)

manifiesto = {}
for e in canonical.registry():
    if not e.excel_series_suffix:
        continue
    # El sufijo identifica DENTRO de su archivo, no en todo el corpus: `serie_original_indice`
    # existe en el PIB y en el IMAE, y `quintil_3` en el IPC y en el costo de la canasta.
    pref = default_prefix(e.source_file) + "."
    hits = sorted(c for c in obs
                  if c.startswith(pref) and c.endswith(e.excel_series_suffix))
    if len(hits) != 1:
        print(f"!! {e.key}: el sufijo resuelve a {len(hits)} series", file=sys.stderr)
        continue
    code = hits[0]
    per = sorted(obs[code])
    cads = {cadencia_de_periodo(p) for p in per}
    cad = cads.pop() if len(cads) == 1 else "mixta"
    huecos = 0
    if cad in ("annual", "quarterly", "monthly"):
        vistos = set(per)
        p = per[0]
        while p != per[-1]:
            p = siguiente(p, cad)
            if p is None:
                break
            if p not in vistos:
                huecos += 1
    manifiesto[e.key] = {"code": code, "cadencia": cad, "min_obs": len(per),
                         "primero": per[0], "huecos": huecos}

# Trinquete: el mínimo conocido nunca baja por regenerar.
previo = {}
destino = pathlib.Path(sys.argv[2])
if destino.exists():
    previo = json.loads(destino.read_text()).get("series", {})
bajaron = []
for clave, nuevo in manifiesto.items():
    antes = previo.get(clave, {}).get("min_obs")
    if antes is not None and nuevo["min_obs"] < antes:
        bajaron.append(f"{clave}: {antes} → {nuevo['min_obs']}")
        nuevo["min_obs"] = antes

salida = {
    "_generado": "2026-09-04",
    "_fuente": ("corrida canónica completa contra la base de dev, espejo verificado de "
                "producción (2.103 series del motor Excel en las dos)"),
    "series": dict(sorted(manifiesto.items())),
}
destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n")
print(f"{len(manifiesto)} entradas con puente")
if bajaron:
    print("\n!! El piso de observaciones BAJÓ en estas series. El BCRD no retira historia:",
          file=sys.stderr)
    for x in bajaron:
        print(f"   {x}", file=sys.stderr)
    print("   Se conservó el máximo conocido. Si la baja es real (el emisor rehízo la "
          "serie), bajalo a mano y justificalo en el commit.", file=sys.stderr)
    sys.exit(1)
