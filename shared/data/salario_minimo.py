"""Salario mínimo de la República Dominicana — mensual por sector, tamaño de empresa y área.

**Por qué esta fuente.** El salario mínimo lo fija por resolución el Comité Nacional de
Salarios y el portal del Ministerio de Trabajo lo publica como noticias, no como serie: se
verificó (mt.gob.do responde y menciona los aumentos en notas de prensa, sin dataset).
CEPALSTAT tiene API pero su índice de indicadores devuelve 404, así que no hay forma de
localizar el indicador sin conocer su id. El **Ministerio de Hacienda y Economía** publica la
serie completa 2000-2025 en el portal nacional de datos abiertos, con licencia ODbL.

**Por qué importa para el crédito.** La mora de consumo no la mueve la ocupación sino la
CAPACIDAD DE PAGO, y el salario mínimo es su piso. Al ser mensual, cada ajuste aparece como
un ESCALÓN con su fecha: se puede medir la cartera antes y después de un aumento en vez de
correlacionar dos curvas suaves. Y el corte por área conecta con el libro de crédito —
«Hoteles, bares y restaurantes» es el sector H del cubo de la SIB.

**Una serie escalonada envejece sin avisar.** El valor se repite mes a mes hasta el próximo
ajuste, así que una categoría DISCONTINUADA se ve idéntica a una vigente. «Zona franca en
áreas geográficas deprimidas» no cambia desde julio de 2006 y sigue publicando RD$3.600
todos los meses; leerla como el salario mínimo de hoy sería falso. Por eso cada serie viaja
con la fecha de su ÚLTIMO cambio: es el dato que distingue «estable» de «abandonada».
"""
from __future__ import annotations

import csv
import io
from typing import Dict, List, NamedTuple, Optional, Tuple

SOURCE = "MHE"
LICENSE = ("Open Data Commons Open Database License (ODbL) — Ministerio de Hacienda y "
           "Economía, vía datos.gob.do")
CSV_URL = ("https://www.hacienda.gob.do/transparencia/wp-content/uploads/2026/02/"
           "Estadisticas-de-salario-minimo.csv")

#: El CSV viene en latin-1 y con punto y coma: leerlo como UTF-8 rompe las eñes de
#: «TAMAÑO EMPRESA» y la columna deja de encontrarse.
_ENCODING = "latin-1"
_DELIM = ";"

_MESES = {m: i for i, m in enumerate(
    ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
     "Septiembre", "Octubre", "Noviembre", "Diciembre"), start=1)}


class SalarioMinimoUnavailable(RuntimeError):
    """La fuente no se pudo leer o cambió de forma."""


class Serie(NamedTuple):
    """Una combinación (sector, tamaño, área) con sus puntos mensuales."""

    sector: str
    tamano: str
    area: str
    puntos: List[Tuple[str, float]]     # [('YYYY-MM', RD$/mes)] ascendente

    @property
    def ultimo_cambio(self) -> Optional[str]:
        """Período del último ESCALÓN. `None` si la serie nunca cambió.

        Es lo que distingue una categoría estable de una abandonada: sin esto, una serie
        que repite su valor desde 2006 se lee igual que una vigente.
        """
        ultimo = None
        for i, (periodo, valor) in enumerate(self.puntos):
            if i and valor != self.puntos[i - 1][1]:
                ultimo = periodo
        return ultimo

    @property
    def escalones(self) -> List[Tuple[str, float]]:
        """Solo los meses en que el valor CAMBIÓ — los ajustes, con su fecha."""
        return [(p, v) for i, (p, v) in enumerate(self.puntos)
                if i == 0 or v != self.puntos[i - 1][1]]


def _monto(txt: object) -> Optional[float]:
    """`'27,989'` → 27989.0. La coma es separador de MILES, no decimal: leerla como
    decimal convertiría veintiocho mil pesos en veintiocho."""
    if txt is None:
        return None
    s = str(txt).strip().replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_salario_minimo(content: bytes) -> List[Serie]:
    """CSV del MHE → una `Serie` por combinación, con sus puntos mensuales ordenados."""
    texto = content.decode(_ENCODING, errors="replace")
    filas = list(csv.DictReader(io.StringIO(texto), delimiter=_DELIM))
    if not filas:
        raise SalarioMinimoUnavailable("el CSV del salario mínimo vino vacío")

    faltan = [c for c in ("SECTOR", "TAMAÑO EMPRESA", "AREAS", "MES", "AÑO", "SALARIO MINIMO")
              if c not in filas[0]]
    if faltan:
        raise SalarioMinimoUnavailable(
            f"al CSV le faltan columnas {faltan} (¿cambió el layout del MHE?); "
            f"trae {[c for c in filas[0] if c]}")

    acc: Dict[Tuple[str, str, str], List[Tuple[str, float]]] = {}
    for f in filas:
        mes = _MESES.get((f.get("MES") or "").strip())
        monto = _monto(f.get("SALARIO MINIMO"))
        anio = (f.get("AÑO") or "").strip()
        if mes is None or monto is None or not anio.isdigit():
            continue
        clave = ((f.get("SECTOR") or "").strip(), (f.get("TAMAÑO EMPRESA") or "").strip(),
                 (f.get("AREAS") or "").strip())
        acc.setdefault(clave, []).append((f"{int(anio):04d}-{mes:02d}", monto))

    if not acc:
        raise SalarioMinimoUnavailable(
            "el CSV no produjo ninguna serie (¿cambiaron los nombres de los meses?)")
    return [Serie(s, t, a, sorted(p)) for (s, t, a), p in sorted(acc.items())]


def fetch_salario_minimo() -> List[Serie]:  # pragma: no cover - network I/O
    """Baja el CSV del MHE y lo parsea."""
    import httpx

    try:
        r = httpx.get(CSV_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise SalarioMinimoUnavailable(
            f"no se pudo descargar el salario mínimo del MHE ({type(e).__name__}: {e})")
    return parse_salario_minimo(r.content)
