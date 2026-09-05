"""Superintendencia Financiera de Colombia (SFC), vía el portal Socrata `datos.gov.co`.

Solvencia y morosidad del SISTEMA bancario colombiano para el boletín regional. La SFC
publica por ENTIDAD; el agregado nacional es cálculo nuestro, y eso importa dos veces:

  · Metodológicamente: un ratio del sistema NO es el promedio de los ratios de sus
    entidades. Se computa sobre los agregados —Σ patrimonio técnico / Σ activos ponderados
    por riesgo—, porque promediar le da el mismo peso a un banco de dos billones que a uno
    de veinte mil millones.
  · Para la licencia: el dato es CC BY-SA 4.0, cuyo share-alike restringe redistribuir el
    activo VERBATIM. Un agregado calculado por nosotros es obra propia, no reventa del dato
    del emisor (ver `shared.data_api.manifest`, `DERIVATION_DERIVED`).

`www.superfinanciera.gov.co` está detrás de Cloudflare; `datos.gov.co` no. Se usa el portal
de datos abiertos, que además declara la licencia y la atribución por dataset.
"""
import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.sfc")

SOCRATA = "https://www.datos.gov.co/resource"

#: Solvencia individual (2021-01 →). Formato largo: una fila por concepto y entidad.
DATASET_SOLVENCIA = "x586-r5d2"
#: Distribución de cartera por producto, con los buckets de mora (2015-01 →).
DATASET_CARTERA = "rvii-eis8"
#: `snsm-7ynr` NO se usa: se declara mensual y está muerto desde diciembre de 2021.

#: Bancos. El join se hace SIEMPRE por este código y `codigo_entidad`, nunca por nombre:
#: el mismo banco aparece como «Banco De Bogotá S.A.» y «BANCO DE BOGOTA S.A.».
TIPO_ENTIDAD_BANCOS = "1"

#: Los dos datasets nombran distinto sus columnas equivalentes.
CAMPO_FECHA = {DATASET_SOLVENCIA: "fecha", DATASET_CARTERA: "fecha_corte"}

CONCEPTO_PATRIMONIO = "PATRIMONIO TÉCNICO"
CONCEPTO_APNR = "TOTAL ACTIVOS PONDERADOS POR NIVEL DE RIESGO"

#: Desvío tolerado entre el renglón TOTAL de una unidad de captura y la suma de sus
#: componentes. Se midió en 0,000%: si deja de cuadrar, cambió la jerarquía del emisor.
TOLERANCIA_TOTAL = 0.001


class SFCError(RuntimeError):
    """La SFC devolvió algo que no se puede agregar sin inventar."""


def _num(valor: Any) -> Optional[float]:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def agregar_solvencia(filas: Iterable[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Solvencia del SISTEMA a partir de las filas por entidad.

    `Σ patrimonio técnico / Σ activos ponderados por riesgo`, en ese orden. Promediar las
    relaciones de solvencia que la SFC ya publica por entidad daría otro número y le
    asignaría el mismo peso a cada banco sin importar su tamaño.
    """
    patrimonio = apnr = 0.0
    entidades = set()
    for fila in filas:
        valor = _num(fila.get("valor"))
        if valor is None:
            continue
        entidades.add(fila.get("codigo_entidad"))
        concepto = (fila.get("concepto") or "").strip().upper()
        if concepto == CONCEPTO_PATRIMONIO.upper():
            patrimonio += valor
        elif concepto == CONCEPTO_APNR.upper():
            apnr += valor
    if not apnr:
        return {"solvencia_total_sistema_pct": None, "entidades": len(entidades)}
    return {
        "solvencia_total_sistema_pct": round(patrimonio / apnr * 100, 4),
        "patrimonio_tecnico_sistema": patrimonio,
        "activos_ponderados_riesgo_sistema": apnr,
        "entidades": len(entidades),
    }


def _saldos_por_unidad(filas: Iterable[Dict[str, Any]]
                       ) -> Tuple[Dict[str, Tuple[float, float]], List[str]]:
    """`{unidad de captura: (saldo, vigente)}` sin doble conteo, y los avisos.

    Cada unidad de captura es una modalidad DISJUNTA (las 32 no se solapan), pero dentro de
    una hay un renglón TOTAL junto a sus componentes: sumar todo contaría dos veces. Se
    toma el TOTAL cuando existe, y se comprueba contra la suma de sus componentes — si no
    cuadra, la unidad se descarta declarando el motivo en vez de publicar una cifra que ya
    no sabemos leer.
    """
    por_uc: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    for fila in filas:
        uc = str(fila.get("unicap") or "")
        renglon = (fila.get("desc_renglon") or "").upper()
        saldo = _num(fila.get("_1_saldo_de_la_cartera_a")) or 0.0
        vigente = _num(fila.get("_2_vigente")) or 0.0
        grupo = "total" if "TOTAL" in renglon else "componentes"
        por_uc.setdefault(uc, {"total": [], "componentes": []})[grupo].append((saldo, vigente))

    fuera: Dict[str, Tuple[float, float]] = {}
    avisos: List[str] = []
    for uc, grupos in por_uc.items():
        suma_comp = (sum(s for s, _ in grupos["componentes"]),
                     sum(v for _, v in grupos["componentes"]))
        if grupos["total"]:
            suma_total = (sum(s for s, _ in grupos["total"]),
                          sum(v for _, v in grupos["total"]))
            base = suma_total[0]
            if suma_comp[0] and base and abs(base - suma_comp[0]) / base > TOLERANCIA_TOTAL:
                avisos.append(
                    f"unidad de captura {uc}: el renglón TOTAL ({base:,.0f}) no cuadra con "
                    f"la suma de sus componentes ({suma_comp[0]:,.0f}); se descarta")
                continue
            fuera[uc] = suma_total
        else:
            fuera[uc] = suma_comp
    return fuera, avisos


def agregar_cartera(filas: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Cartera y morosidad del SISTEMA.

    La mora se computa como `(saldo - vigente) / saldo` y NO sumando los buckets de
    vencimiento: el cuadro trae tramos que se solapan («vencida 1-2 meses», «vencida 1-3
    meses», «vencida 1-4 meses»), y sumarlos contaría la misma cartera varias veces.
    """
    por_uc, avisos = _saldos_por_unidad(filas)
    saldo = sum(s for s, _ in por_uc.values())
    vigente = sum(v for _, v in por_uc.values())
    if not saldo:
        return {"cartera_bruta_sistema": None, "morosidad_sistema_pct": None,
                "avisos": avisos}
    return {
        "cartera_bruta_sistema": saldo,
        "cartera_vencida_sistema": saldo - vigente,
        "morosidad_sistema_pct": round((saldo - vigente) / saldo * 100, 4),
        "unidades_de_captura": len(por_uc),
        "avisos": avisos,
    }


# ── El conector ───────────────────────────────────────────────────────────────────────
LICENSE = ("SFC Colombia vía datos.gov.co — CC BY-SA 4.0 (Atribución + CompartirIgual): "
           "exige citar a la Superintendencia Financiera de Colombia y la fecha de "
           "actualización del dato.")


def consultar(dataset: str, corte: str, limite: int = 50000,
              timeout: int = 180) -> List[Dict[str, Any]]:  # pragma: no cover - network I/O
    """Filas de *dataset* para un corte, solo bancos.

    Se filtra SIEMPRE por corte: un agregado sobre la tabla completa —110.969 filas en el
    de cartera— excede el tope de 120 s de Socrata.
    """
    import httpx

    campo = CAMPO_FECHA[dataset]
    where = f"tipo_entidad='{TIPO_ENTIDAD_BANCOS}' AND {campo}='{corte}'"
    resp = httpx.get(f"{SOCRATA}/{dataset}.json",
                     params={"$where": where, "$limit": limite},
                     timeout=timeout, headers={"User-Agent": "sdq-mip/1.0"})
    resp.raise_for_status()
    filas = resp.json()
    if not isinstance(filas, list):
        raise SFCError(f"{dataset}: respuesta inesperada de Socrata ({type(filas).__name__})")
    return filas


def cortes_disponibles(dataset: str, desde: Optional[str] = None,
                       timeout: int = 120) -> List[str]:  # pragma: no cover - network I/O
    """Los cortes que el dataset publica, del más viejo al más nuevo."""
    import httpx

    campo = CAMPO_FECHA[dataset]
    params: Dict[str, Any] = {"$select": campo, "$group": campo, "$order": campo}
    if desde:
        params["$where"] = f"{campo} >= '{desde}'"
    resp = httpx.get(f"{SOCRATA}/{dataset}.json", params=params, timeout=timeout,
                     headers={"User-Agent": "sdq-mip/1.0"})
    resp.raise_for_status()
    return [f[campo] for f in resp.json() if f.get(campo)]


class SFCClient(FixtureBackedClient):
    """Solvencia y morosidad del sistema bancario colombiano, agregadas por nosotros."""

    source = "SFC"
    license = LICENSE
    license_ok = True
    fixture_file = "sfc_colombia.json"
    live_phase = "boletín regional (T-BR-6)"

    NORMA_CONTABLE = "CUIF Colombia (SFC)"
    #: El agregado nacional es cálculo propio, no el valor del emisor servido tal cual: por
    #: eso el share-alike de la fuente no lo retiene (`DERIVATION_DERIVED`).
    DERIVACION = "derived"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        crudo = self._crudo_live(period) if self.mode == "live" else self._crudo_fixture()
        fuera: List[Record] = []
        for corte, bloques in sorted(crudo.items()):
            fuera.extend(self._records_de(corte, bloques))
        if series:
            fuera = [r for r in fuera if r.series == series]
        if period:
            fuera = [r for r in fuera if r.period == period]
        return fuera

    def _crudo_live(self, period: Optional[str]) -> Dict[str, Dict[str, Any]]:  # pragma: no cover - network I/O
        cortes = cortes_disponibles(DATASET_SOLVENCIA)
        if period:
            cortes = [c for c in cortes if c.startswith(period)]
        fuera: Dict[str, Dict[str, Any]] = {}
        for corte in cortes:
            try:
                solvencia = agregar_solvencia(consultar(DATASET_SOLVENCIA, corte))
                cartera = agregar_cartera(consultar(DATASET_CARTERA, corte))
            except Exception as e:  # noqa: BLE001 — un corte que falla no tumba el resto
                logger.warning("[SFC] corte %s no se pudo agregar: %s", corte, e)
                continue
            for aviso in cartera.get("avisos", []):
                logger.warning("[SFC] %s: %s", corte, aviso)
            fuera[corte] = {"solvencia": solvencia, "cartera": cartera}
        return fuera

    def _crudo_fixture(self) -> Dict[str, Dict[str, Any]]:
        fixture = self._load_fixture(self.fixture_file)
        return {k: v for k, v in fixture.items() if not k.startswith("_")}

    def _records_de(self, corte: str, bloques: Dict[str, Any]) -> List[Record]:
        lineage = Lineage(
            source=self.source, license=self.license, fetched_at=date.today(),
            published_at=_fecha(corte),
            url=f"{SOCRATA}/{DATASET_SOLVENCIA}.json",
            note="Agregado del sistema calculado por SDQ sobre el dato por entidad de la SFC")
        metricas = {
            "solvencia_total_sistema_pct": ("%", bloques.get("solvencia", {})),
            "morosidad_sistema_pct": ("%", bloques.get("cartera", {})),
            "cartera_bruta_sistema": ("COP", bloques.get("cartera", {})),
            "patrimonio_tecnico_sistema": ("COP", bloques.get("solvencia", {})),
            "activos_ponderados_riesgo_sistema": ("COP", bloques.get("solvencia", {})),
        }
        fuera: List[Record] = []
        for serie, (unidad, bloque) in metricas.items():
            if serie not in bloque:
                continue
            valor = bloque.get(serie)
            fuera.append(Record(
                series=serie, period=corte[:10],
                value=None if valor is None else float(valor),
                lineage=lineage, unit=unidad, dimension="COL",
                reason=None if valor is not None else "la fuente no publica el insumo",
            ))
        return fuera


def _fecha(corte: str) -> Optional[date]:
    try:
        return date.fromisoformat(corte[:10])
    except ValueError:
        return None


sfc_client = SFCClient()
