"""IPU Parline — mujeres en el SENADO dominicano (indicador 2.43 de la Ley 1-12).

**Por qué esta fuente y no otra.** De los cuatro cargos electivos que la END fija, el
Senado es el único que ninguna otra vía cubre, y se comprobó una por una:

  · el WDI (`SG.GEN.PARL.ZS`) es cámara BAJA por convención de la UIP — da 20,77 en 2010,
    que es Diputados, contra los 9,4 del Senado;
  · CEPALSTAT tiene «Cámara Alta» pero de ORADORES y presidencias de comisión, no de
    composición;
  · la JCE no publica API ni dataset (verificado contra datos.gob.do).

La Unión Interparlamentaria publica cada cámara por separado, y el Senado dominicano es la
entidad ``DO-UC01``.

**Se lee la PÁGINA y no el CSV, a propósito.** Parline ofrece un `export-historical/…/csv`
que sería más robusto, pero está detrás de un desafío de Cloudflare que devuelve una página
de bloqueo. No se esquiva: es una barrera del emisor. La página pública sí responde a un
cliente normal y trae la misma tabla histórica, así que se lee de ahí y se declara la
fragilidad que eso implica.

**La identificación es por VALOR.** La ley fija la línea base del Senado en 9,4% para 2010 y
la tabla da 9,4% en 2010-05. La coincidencia al decimal es lo que prueba que es la cámara
correcta — el nombre de la entidad no alcanzaría, porque `DO-LC01` y `DO-UC01` se parecen
demasiado para confiar en la etiqueta.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from typing import List, Tuple

logger = logging.getLogger("sdq.data.ipu_parline")

SOURCE = "UIP"
LICENSE = "Unión Interparlamentaria (Parline) — uso público con cita"

#: Entidades de la UIP. `UC` = upper chamber, `LC` = lower chamber. Se dejan las dos
#: nombradas aunque solo se use una: es lo que impide que alguien "arregle" un fallo
#: cambiando una letra y termine publicando la cámara equivocada.
SENADO = "DO-UC01"
DIPUTADOS = "DO-LC01"

URL = "https://data.ipu.org/parliament/DO/{entidad}/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP IPU Parline connector)"}

_ANCLA = "Historical data for Percentage of women"
_FILA = re.compile(r"(\d{4})-(\d{2})\s+([\d.]+)\s*%")

# El total nacional no aplica: la cámara ES la unidad, no una desagregación de nada.
SIN_TOTAL_NACIONAL = (
    "no hay desagregación sub-nacional: la unidad es la cámara, que ya es de alcance país."
)


class ParlineUnavailable(RuntimeError):
    """No se pudo leer la serie. Lleva el motivo, no solo el hecho."""


def parse_serie(html: str) -> List[Tuple[int, float]]:
    """Página de una cámara → ``[(año, % de mujeres)]`` ascendente, sin repetir año.

    Se ancla en el rótulo de la tabla histórica y no en una posición: un cambio de layout
    deja la serie VACÍA —visible— en vez de leer otra tabla de la misma página, que es lo
    que haría un índice fijo. La página trae varias tablas con porcentajes.

    Pura (sin red) para poder fijarla en tests.
    """
    i = html.find(_ANCLA)
    if i < 0:
        raise ParlineUnavailable(
            f"no se encontró la tabla «{_ANCLA}» (¿cambió el layout de Parline?)")
    texto = " ".join(re.sub(r"<[^>]+>", " ", html[i:i + 6000]).split())
    por_anio: dict = {}
    for anio, _mes, valor in _FILA.findall(texto):
        try:
            v = float(valor)
        except ValueError:
            continue
        if not 0.0 <= v <= 100.0:
            continue
        # Una elección por año: si hubiera dos entradas del mismo año, gana la primera,
        # que en esta tabla es la más reciente.
        por_anio.setdefault(int(anio), round(v, 2))
    if not por_anio:
        raise ParlineUnavailable("la tabla histórica no trajo ninguna fila utilizable")
    return sorted(por_anio.items())


def fetch_senado() -> List[Tuple[int, float]]:  # pragma: no cover - network I/O
    """Live: descarga la página del Senado dominicano y proyecta su serie histórica."""
    url = URL.format(entidad=SENADO)
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=90) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raise ParlineUnavailable(
            f"no se pudo descargar {url} ({type(e).__name__}: {e})")
    return parse_serie(html)
