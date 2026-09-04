"""Congela en el paquete los nombres que el modelo le dio a las filas ambiguas.

El `series_code` que sale del nombrado semántico es un CONTRATO: se persiste, se cita y la
Data API lo sirve. Mientras el mapa vivía solo en `data/bcrd_excel/specs.json` —gitignored,
y en Railway el filesystem del contenedor, que cada deploy borra— al modelo se le volvía a
preguntar y reformulaba el mismo encabezado: **40 de 2.103 series cambiaron de código en un
solo deploy** (medido en producción el 2026-09-04). Sin datos perdidos, pero con el contrato
roto.

Este script toma lo que haya en la caché local y lo escribe en
`shared/data/bcrd_excel/nombres_semanticos.json`, que SÍ va al repositorio. El diff es la
revisión: son nombres que viajan al cliente.

    python scripts/congelar_nombres_semanticos.py [caché.json]

Un nombre YA congelado no se pisa: si la caché local trae otro para la misma fila, se
declara y se conserva el congelado. Congelar es una decisión, no un efecto secundario de
haber corrido la ingesta.
"""
from __future__ import annotations

import json
import pathlib
import sys

CACHE = pathlib.Path("data/bcrd_excel/specs.json")
DESTINO = pathlib.Path("shared/data/bcrd_excel/nombres_semanticos.json")


def main() -> int:
    cache_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else CACHE
    if not cache_path.exists():
        print(f"no hay caché en {cache_path}", file=sys.stderr)
        return 2
    local = json.loads(cache_path.read_text(encoding="utf-8"))
    nuevos = {k[len("names:"):]: {str(a): str(b) for a, b in v.items()}
              for k, v in local.items() if k.startswith("names:") and isinstance(v, dict)}

    doc = json.loads(DESTINO.read_text(encoding="utf-8"))
    congelados = doc["nombres"]
    altas = conflictos = 0
    for hoja, filas in nuevos.items():
        destino = congelados.setdefault(hoja, {})
        for fila, nombre in filas.items():
            if fila not in destino:
                destino[fila] = nombre
                altas += 1
            elif destino[fila] != nombre:
                conflictos += 1
                print(f"  se conserva el congelado · hoja {hoja} fila {fila}\n"
                      f"     congelado: {destino[fila]}\n"
                      f"     la caché dice: {nombre}", file=sys.stderr)
    doc["nombres"] = {h: dict(sorted(f.items(), key=lambda kv: int(kv[0])))
                      for h, f in sorted(congelados.items())}
    DESTINO.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
    total = sum(len(v) for v in doc["nombres"].values())
    print(f"{len(doc['nombres'])} hojas · {total} filas congeladas · {altas} alta(s)")
    if conflictos:
        print(f"{conflictos} fila(s) donde el modelo dijo otra cosa: se conservó lo "
              "congelado. Cambiar un nombre ya publicado se hace a mano y se justifica.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
