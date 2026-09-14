"""DGCP — obra pública adjudicada por mes, del OCDS de Contrataciones Públicas (Fase 7).

La Dirección General de Contrataciones Públicas publica sus procesos en el estándar OCDS con
licencia ODbL. La API propia daba 502 el 2026-09-07; se lee el **mirror de Open Contracting
Partnership** (publicación 22 del registro, `data.open-contracting.org/en/publication/22`), que
recupera la fuente una vez al mes y la publica en archivos anuales de *compiled releases*.

**Qué es una obra.** `tender.mainProcurementCategory == "works"`, que la DGCP puebla en TODOS sus
releases (comprobado el 2026-09-14 sobre 2025 y 2026 completos). **No se filtra por modalidad**:
«Comparación de Precios» también cubre obras menores y la obra grande va por licitación, así que
un corte por modalidad sería un número inventado con cara de medición.

**Qué se cuenta, y por qué así.**
* Una adjudicación ACTIVA (`awards[].status == "active"`) con fecha, en el mes de su
  `awards[].date`. Una cancelada o pendiente no es obra adjudicada.
* El monto no viene en la adjudicación: en la DGCP `awards[].value` está vacío en el 100 % de
  los casos, y el monto vive en `contracts[].value` (DOP). Se suma el de los contratos que
  cuelgan de cada adjudicación (`contracts[].awardID`). Un mes con adjudicaciones y sin ningún
  contrato con monto deja el monto en `None`, no en cero.
* El año del archivo es el del PROCESO, no el de la adjudicación: el de 2025 trae adjudicaciones
  de 2026. Se leen los dos últimos años.
* El último mes que se publica es el último COMPLETO antes de la recuperación del mirror
  (`Last-Modified` del archivo): un mes a medio recuperar se leería como una caída.

**El sector eléctrico, por entidad y no por patrón.** Las adjudicaciones de las empresas
eléctricas del Estado se cuentan aparte, por el identificador de la unidad de compra en la
DGCP. Un patrón de texto se equivoca: «Acueducto» contiene «cued», y un regex por CUED metía a
las corporaciones de acueductos en el sector eléctrico.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shared.data.base_client import Mode, Record, SourceClient
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.dgcp_ocds")

URL_ANUAL = "https://data.open-contracting.org/en/publication/22/download?name={anio}.jsonl.gz"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

SERIE_OBRAS = "dgcp.obras.adjudicaciones"
SERIE_MONTO = "dgcp.obras.monto_contratado_dop"
SERIE_OBRAS_ELECTRICAS = "dgcp.obras.sector_electrico.adjudicaciones"
SERIE_MONTO_ELECTRICO = "dgcp.obras.sector_electrico.monto_contratado_dop"

#: Unidades de compra del sector eléctrico, por su identificador en la DGCP. Verificadas el
#: 2026-09-14 contra los releases de obras de 2025 y 2026.
UNIDADES_SECTOR_ELECTRICO: Dict[str, str] = {
    "DO-UC-815": "Empresa Distribuidora de Electricidad del Sur",
    "DO-UC-698": "Empresa de Distribución Eléctrica del Norte",
    "DO-UC-718": "Empresa Distribuidora de Electricidad del Este, S.A.",
    "DO-UC-612": "Empresa de Transmisión Eléctrica Dominicana",
    "DO-UC-916": "Ministerio de Energía y Minas",
}


@dataclass(frozen=True)
class RecuperacionDGCP:
    ultimo_mes_completo: str        # "YYYY-MM"
    recuperado_el: Optional[date]   # Last-Modified del mirror


def _mes(fecha: Any) -> Optional[str]:
    t = str(fecha or "")
    return t[:7] if len(t) >= 7 and t[4] == "-" else None


#: Días que tienen que haber pasado desde el FIN de un mes hasta la recuperación del mirror para
#: publicar ese mes. Las unidades de compra registran la adjudicación con rezago: con la
#: recuperación del 7 de septiembre, agosto salía con la mitad de las obras de junio y julio.
#: No se midió el rezago real —el OCDS compilado no guarda cuándo se registró cada adjudicación—,
#: así que el margen es conservador y está declarado, no calibrado.
MARGEN_DE_REGISTRO_DIAS = 30


def ultimo_mes_publicable(recuperado: date) -> str:
    """El último mes cuyo fin quedó al menos `MARGEN_DE_REGISTRO_DIAS` antes de la recuperación."""
    from datetime import timedelta

    y, m = recuperado.year, recuperado.month
    while True:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        fin = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
        if (recuperado - fin).days >= MARGEN_DE_REGISTRO_DIAS:
            return f"{y}-{m:02d}"


def agregar(releases: Iterable[Dict[str, Any]], hasta: str) -> Dict[str, Dict[str, Optional[float]]]:
    """``{serie: {"YYYY-MM": valor}}`` de las obras adjudicadas, hasta el mes *hasta* incluido."""
    conteo: Dict[str, Dict[str, float]] = {SERIE_OBRAS: defaultdict(float),
                                           SERIE_OBRAS_ELECTRICAS: defaultdict(float)}
    monto: Dict[str, Dict[str, float]] = {SERIE_MONTO: defaultdict(float),
                                          SERIE_MONTO_ELECTRICO: defaultdict(float)}
    con_monto: Dict[str, set] = {SERIE_MONTO: set(), SERIE_MONTO_ELECTRICO: set()}
    vistos: set = set()
    for rel in releases:
        tender = rel.get("tender") or {}
        if tender.get("mainProcurementCategory") != "works":
            continue
        ocid = rel.get("ocid")
        if ocid in vistos:        # un proceso no se cuenta dos veces si aparece en dos archivos
            continue
        vistos.add(ocid)
        electrica = any(
            "procuringEntity" in (p.get("roles") or [])
            and (p.get("identifier") or {}).get("id") in UNIDADES_SECTOR_ELECTRICO
            for p in rel.get("parties") or [])
        contratos: Dict[str, List[float]] = defaultdict(list)
        for c in rel.get("contracts") or []:
            v = (c.get("value") or {})
            if v.get("amount") is not None and (v.get("currency") or "DOP") == "DOP":
                contratos[str(c.get("awardID"))].append(float(v["amount"]))
        for a in rel.get("awards") or []:
            if a.get("status") != "active":
                continue
            mes = _mes(a.get("date"))
            if mes is None or mes > hasta:
                continue
            series = [(SERIE_OBRAS, SERIE_MONTO)]
            if electrica:
                series.append((SERIE_OBRAS_ELECTRICAS, SERIE_MONTO_ELECTRICO))
            for s_conteo, s_monto in series:
                conteo[s_conteo][mes] += 1
                montos = contratos.get(str(a.get("id")))
                if montos:
                    monto[s_monto][mes] += sum(montos)
                    con_monto[s_monto].add(mes)
    salida: Dict[str, Dict[str, Optional[float]]] = {}
    meses = sorted(conteo[SERIE_OBRAS])
    if not meses:
        return {s: {} for s in (SERIE_OBRAS, SERIE_MONTO, SERIE_OBRAS_ELECTRICAS, SERIE_MONTO_ELECTRICO)}
    # Un mes del rango sin ninguna adjudicación del sector eléctrico es un CERO medido: la fuente
    # entera se leyó y no hubo ninguna. Para el total pasa lo mismo desde el primer mes con dato.
    todos = _rango(meses[0], hasta)
    salida[SERIE_OBRAS] = {m: conteo[SERIE_OBRAS].get(m, 0.0) for m in todos}
    salida[SERIE_OBRAS_ELECTRICAS] = {m: conteo[SERIE_OBRAS_ELECTRICAS].get(m, 0.0) for m in todos}
    salida[SERIE_MONTO] = {m: (monto[SERIE_MONTO][m] if m in con_monto[SERIE_MONTO]
                               else (0.0 if salida[SERIE_OBRAS][m] == 0 else None)) for m in todos}
    salida[SERIE_MONTO_ELECTRICO] = {
        m: (monto[SERIE_MONTO_ELECTRICO][m] if m in con_monto[SERIE_MONTO_ELECTRICO]
            else (0.0 if salida[SERIE_OBRAS_ELECTRICAS][m] == 0 else None)) for m in todos}
    return salida


def _rango(desde: str, hasta: str) -> List[str]:
    y, m = (int(x) for x in desde.split("-"))
    fin = tuple(int(x) for x in hasta.split("-"))
    out = []
    while (y, m) <= fin:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class DGCPOCDSClient(SourceClient):
    source = "DGCP (Contrataciones Públicas, OCDS vía Open Contracting Partnership)"
    license = ("DGCP — datos de contrataciones públicas en OCDS, publicados bajo Open Data "
               "Commons Open Database License (ODbL) v1.0 (declarada por el registro de OCP para "
               "la publicación 22): exige el aviso de atribución, y el share-alike alcanza a las "
               "bases DERIVADAS; un informe es «Produced Work» y no lo dispara.")
    license_ok = True

    def __init__(self, mode: Mode = "live") -> None:
        super().__init__(mode)

    def _releases(self, anio: int) -> Tuple[Iterable[Dict[str, Any]], Optional[date]]:
        import urllib.request

        r = urllib.request.urlopen(urllib.request.Request(URL_ANUAL.format(anio=anio), headers=_HEADERS),
                                   timeout=900)
        recuperado = None
        try:
            recuperado = parsedate_to_datetime(r.headers["Last-Modified"]).astimezone(timezone.utc).date()
        except (KeyError, TypeError, ValueError):
            pass

        def _iter():
            with r, gzip.GzipFile(fileobj=r) as gz:
                for linea in io.TextIOWrapper(gz, encoding="utf-8"):
                    try:
                        yield json.loads(linea)
                    except ValueError:
                        continue
        return _iter(), recuperado

    def leer(self, hoy: Optional[date] = None) -> Tuple[List[Record], RecuperacionDGCP]:
        self.check_license()
        hoy = hoy or date.today()
        actual, recuperado = self._releases(hoy.year)
        previo, _ = self._releases(hoy.year - 1)
        hasta = ultimo_mes_publicable(recuperado or hoy)
        def _encadenado():
            yield from actual
            yield from previo
        series = agregar(_encadenado(), hasta)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        unidades = {SERIE_OBRAS: "adjudicaciones", SERIE_OBRAS_ELECTRICAS: "adjudicaciones",
                    SERIE_MONTO: "RD$", SERIE_MONTO_ELECTRICO: "RD$"}
        registros = [Record(series=s, period=p, value=v, lineage=lineage, unit=unidades[s])
                     for s, puntos in series.items() for p, v in sorted(puntos.items())]
        return registros, RecuperacionDGCP(ultimo_mes_completo=hasta, recuperado_el=recuperado)

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        registros, _ = self.leer()
        return [r for r in registros
                if (series is None or r.series == series) and (period is None or r.period == period)]
