"""Espera a que producción esté sirviendo un commit que CONTENGA un cambio. Y si no, falla.

Existe por dos defectos que se produjeron el mismo día (2026-08-20), los dos generando material
comercial contra una versión de producción que no tenía el arreglo que el documento venía a
corregir:

1. **Se esperaba IGUALDAD con el SHA del merge.** Con otra sesión mergeando en paralelo, el
   deploy que ganó fue el de SU PR — un commit que no contenía mi cambio. La igualdad puede no
   darse nunca; lo que hay que preguntar es si el commit servido **contiene** el cambio.
2. **Al expirar, el lazo seguía igual.** El `for` de shell terminaba y la línea siguiente
   generaba el documento lo mismo. Un artefacto producido después de un timeout se ve idéntico
   a uno correcto, y por eso el error pasó dos veces sin que nadie lo notara.

Este script **no genera nada**: solo espera y devuelve un código de salida. Encadenarlo con
``&&`` vuelve estructural el «abortar en vez de generar»::

    python scripts/esperar_deploy.py <sha> && python scripts/build_catalogo_v4.py

Códigos de salida, y ninguno significa «seguí igual»:

- ``0`` — producción sirve un commit que contiene el cambio.
- ``1`` — expiró el tiempo sin que llegara.
- ``2`` — no se pudo VERIFICAR (el commit servido no se conoce localmente, o el health no
  responde). «No sé» no es «está bien»: es la misma distinción que el ``stale=None`` de los
  reportes de validación.

⚠️ Un `status: ok` NO prueba que el deploy entró: el healthcheck responde por el proceso que
está corriendo, y un deploy fallido deja sirviendo el anterior tan sano como siempre.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import Optional

BASE_POR_DEFECTO = "https://sdq-market-intelligence-production.up.railway.app"
INTERVALO_SEGUNDOS = 30


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def commit_servido(base_url: str, timeout: int = 25) -> Optional[str]:
    """El commit que producción declara estar sirviendo, o ``None`` si no se pudo leer."""
    import httpx

    try:
        r = httpx.get(f"{base_url}/api/v1/health", timeout=timeout, follow_redirects=True)
        return ((r.json() or {}).get("deployment") or {}).get("commit") or None
    except Exception:  # noqa: BLE001 — un blip de red no es un veredicto
        return None


def contiene(cambio: str, servido: str) -> Optional[bool]:
    """¿*servido* contiene a *cambio*? ``None`` si no se puede saber.

    Devolver ``None`` y no ``False`` importa: «el commit servido no lo conozco» y «lo conozco y
    no contiene el cambio» llevan a acciones distintas, y confundirlas hace esperar para
    siempre por algo que ya llegó.
    """
    if not _git("cat-file", "-e", f"{servido}^{{commit}}").returncode == 0:
        _git("fetch", "origin", "--quiet")
        if _git("cat-file", "-e", f"{servido}^{{commit}}").returncode != 0:
            return None
    return _git("merge-base", "--is-ancestor", cambio, servido).returncode == 0


def esperar(cambio: str, base_url: str, minutos: int) -> int:
    limite = time.time() + minutos * 60
    desconocidos = 0
    ultimo = None
    while time.time() < limite:
        servido = commit_servido(base_url)
        if servido != ultimo:
            print(f"  … sirviendo {(servido or '?')[:12]}", flush=True)
            ultimo = servido
        if servido:
            veredicto = contiene(cambio, servido)
            if veredicto is True:
                print(f"✓ producción CONTIENE {cambio[:12]} (sirviendo {servido[:12]})")
                return 0
            desconocidos = desconocidos + 1 if veredicto is None else 0
            if desconocidos >= 5:
                print(f"✗ no puedo verificar: el commit servido {servido[:12]} no se conoce "
                      "localmente ni después de `git fetch`. NO se generó nada.",
                      file=sys.stderr)
                return 2
        time.sleep(INTERVALO_SEGUNDOS)
    print(f"✗ expiró: en {minutos} min producción nunca sirvió un commit con {cambio[:12]} "
          f"(último visto: {(ultimo or '?')[:12]}). NO se generó nada — revisá si hay un "
          "deploy en FAILED: un deploy fallido deja sirviendo el anterior y responde `ok`.",
          file=sys.stderr)
    return 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("commit", nargs="?", default="HEAD",
                   help="El cambio que tiene que estar en producción (default: HEAD).")
    p.add_argument("--base-url", default=BASE_POR_DEFECTO)
    p.add_argument("--minutos", type=int, default=25, help="Cuánto esperar antes de fallar.")
    args = p.parse_args()

    resuelto = _git("rev-parse", args.commit)
    if resuelto.returncode != 0:
        print(f"✗ no puedo resolver «{args.commit}» a un commit.", file=sys.stderr)
        raise SystemExit(2)
    sys.exit(esperar(resuelto.stdout.strip(), args.base_url, args.minutos))


if __name__ == "__main__":
    main()
