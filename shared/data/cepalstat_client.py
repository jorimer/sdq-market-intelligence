"""CEPALSTAT — participación política de las mujeres en gobiernos locales.

**Por qué esta fuente y no la JCE.** Los indicadores 2.45 (síndicas) y 2.46 (regidoras) de
la Ley 1-12 los produce la Junta Central Electoral, que no publica API ni dataset abierto:
se verificó contra el catálogo nacional (`datos.gob.do`) y no hay nada — «regidores
sindicos» y «elecciones resultados» devuelven cero. El Observatorio de Igualdad de Género de
la CEPAL sí publica la serie para toda la región, con API abierta, recogiendo el dato del
propio organismo electoral de cada país.

**La identificación se hizo por VALOR, no por nombre.** «Alcaldesas» y «concejalas» son los
términos regionales de lo que en RD se llama síndicas y regidoras, así que el nombre no
prueba nada. Lo que lo prueba es la línea base: la ley fija síndicas en 7,7% para 2010 y la
serie da exactamente 7,7 ese año. En regidoras la ley dice 35,0 y la serie 33,3 — 1,7 puntos
de diferencia que hay que declarar, no esconder.

**La serie es ESCALONADA a propósito.** Un cargo electivo no cambia de composición hasta la
próxima elección, así que el valor se repite entre comicios. Eso NO es dato viejo: es la
forma correcta del fenómeno, y confundirlo con una serie estancada llevaría a descartar la
fuente por «no actualizarse».
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Dict, List, Tuple

logger = logging.getLogger("sdq.data.cepalstat")

BASE = "https://api-cepalstat.cepal.org/cepalstat/api/v1/indicator/{ind}/data?format=json&lang=es"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP CEPALSTAT connector)",
            "Accept": "application/json"}

SOURCE = "CEPAL"
LICENSE = ("Observatorio de Igualdad de Género de la CEPAL — uso público con cita; "
           "recoge el dato del organismo electoral de cada país")

#: Indicadores del árbol temático de CEPALSTAT. El id es lo único estable: los nombres
#: cambian de edición y el árbol es grande.
IND_ALCALDESAS = 1617      # → indicador 2.45 de la END (síndicas)
IND_CONCEJALAS = 1708      # → indicador 2.46 de la END (regidoras)

ISO_RD = "DOM"
_SEXO = "Sexo"
_MUJERES = "Mujeres"

# Este conector NO filtra por padrón geográfico sub-nacional: la serie es de país por
# construcción, así que no hay total nacional que se pueda perder en un filtro.
SIN_TOTAL_NACIONAL = (
    "la serie ya es de país: CEPALSTAT publica un valor nacional por año y no hay "
    "desagregación sub-nacional de la que extraer un total."
)


class CepalstatUnavailable(RuntimeError):
    """No se pudo leer la serie. Lleva el motivo, no solo el hecho."""


def parse_serie(payload: dict) -> List[Tuple[int, float]]:
    """Respuesta de CEPALSTAT → ``[(año, valor)]`` de RD, solo mujeres, ascendente.

    Las filas traen ``iso3`` pero los años y el sexo vienen como identificadores de
    dimensión: hay que resolverlos contra ``dimensions`` en vez de asumir posiciones. Pura
    (sin red) para poder fijarla en tests.
    """
    body = payload.get("body") or payload
    dims = body.get("dimensions") or []
    if not dims or not body.get("data"):
        raise CepalstatUnavailable("la respuesta no trae dimensiones o datos")

    anios: Dict[int, str] = {}
    ids_mujeres: set = set()
    for d in dims:
        nombre = d.get("name") or ""
        for m in d.get("members") or []:
            if "os__ESTANDAR" in nombre:        # «Años__ESTANDAR»
                anios[m["id"]] = str(m.get("name") or "")
            elif nombre == _SEXO and m.get("name") == _MUJERES:
                ids_mujeres.add(m["id"])
    if not anios:
        raise CepalstatUnavailable("no se ubicó la dimensión de años")
    if not ids_mujeres:
        # Sin esta comprobación el parser devolvería la serie de HOMBRES —que en estos
        # indicadores es el complemento y también es plausible— sin que nada lo advirtiera.
        raise CepalstatUnavailable("no se ubicó el miembro 'Mujeres' de la dimensión Sexo")

    out: Dict[int, float] = {}
    for r in body["data"]:
        if r.get("iso3") != ISO_RD:
            continue
        if not any(v in ids_mujeres for k, v in r.items() if k.startswith("dim_")):
            continue
        etiqueta = next((anios[v] for k, v in r.items()
                         if k.startswith("dim_") and v in anios), "")
        if not etiqueta.isdigit():
            continue
        try:
            out[int(etiqueta)] = round(float(r["value"]), 2)
        except (TypeError, ValueError, KeyError):
            continue
    if not out:
        raise CepalstatUnavailable(f"no hay filas de {ISO_RD} con valor para mujeres")
    return sorted(out.items())


def fetch_serie(indicador: int) -> List[Tuple[int, float]]:  # pragma: no cover - network I/O
    """Live: descarga un indicador de CEPALSTAT y lo proyecta a la serie de RD."""
    url = BASE.format(ind=indicador)
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001 — se traduce a un error con motivo
        raise CepalstatUnavailable(
            f"no se pudo consultar el indicador {indicador} ({type(e).__name__}: {e})")
    return parse_serie(payload)
