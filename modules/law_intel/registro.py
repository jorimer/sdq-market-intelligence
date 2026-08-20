"""Carga del registro de indicadores de un expediente, con su validación.

**Qué es un expediente.** Una ley expresada como dato: `expedientes/<id>/instrumento.yaml`
más su registro de indicadores. El motor no conoce ninguna ley en particular — evaluar una
segunda es agregar una carpeta, no editar este archivo.

**Qué NO hace este módulo.** No mide nada. Sirve lo que la ley MANDA (línea base y metas por
período); el dato real y la comparación meta-vs-real llegan con los bindings, en la fase
siguiente. Mantenerlos separados es deliberado: lo que la ley exige no cambia con el corte, y
mezclarlo con la observación hace imposible responder «¿cambió la meta o cambió el dato?» —
que es justamente la pregunta que el artículo 20 vuelve interesante, porque permite al órgano
rector mover las metas por vía administrativa.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

RAIZ = Path(__file__).resolve().parent / "expedientes"
ANIOS = ("2015", "2020", "2025", "2030")

Valor = Union[float, str]

# Las seis formas que toma una meta en el articulado. Se declaran por separado porque NO son
# comparables entre sí: un umbral acota, una banda ordena, una meta redactada ni siquiera se
# puede restar. Meterlas todas en «ordinal» las volvería intercambiables, que es exactamente
# el error que la doctrina de comparabilidad prohíbe.
ESCALAS = {
    "numerica":  "valor numérico; admite delta contra el dato real",
    "ordinal":   "banda PEFA A-D; ordena, no resta",
    "umbral":    "acota («< 4%»); cumplir es quedar del lado correcto, no llegar al número",
    "redactada": "meta en palabras («Pertenecer al nivel II»); requiere juicio, no aritmética",
    "compuesta": "varias series apiladas en una celda; no tiene UN valor",
    "sin_meta":  "el indicador existe y la ley no le fija meta propia",
}

# Única escala sobre la que un delta meta-vs-real significa algo. El resto se evalúa, pero no
# se resta — y el motor debe negarse a producir un número en vez de producir uno falso.
ESCALAS_CON_DELTA = frozenset({"numerica"})


class ExpedienteInvalido(RuntimeError):
    """El expediente no cuadra con lo que declara. No se sirve un registro así."""


@dataclass(frozen=True)
class Indicador:
    id: str
    eje: int
    nombre: str
    escala: str
    subfila_de: Optional[str] = None
    base_anio: Optional[int] = None
    base_anio_texto: Optional[str] = None
    base_valor: Optional[Valor] = None
    metas: Dict[str, Valor] = field(default_factory=dict)
    anios_sin_meta_numerica: List[str] = field(default_factory=list)

    @property
    def admite_delta(self) -> bool:
        return self.escala in ESCALAS_CON_DELTA


@dataclass(frozen=True)
class Expediente:
    id: str
    titulo: str
    norma: str
    meta: Dict[str, Any]
    indicadores: List[Indicador]

    @property
    def numerados(self) -> List[Indicador]:
        """Los indicadores que la ley numera, sin las sub-filas que desagregan alguno.

        El denominador de un eje cambia según cuál de los dos se cuente, y esa distinción fue
        una de las verificaciones que el análisis preliminar dejó abiertas: el Eje 1 tiene 8
        indicadores numerados y 13 filas medibles, porque la ley desagrega 1.5 y 1.6 en cinco
        sub-filas. Publicar «3 retrocesos sobre 8» cuando los tres son sub-filas infla el
        porcentaje. Se sirven las dos vistas y cada cifra dice cuál usa.
        """
        return [i for i in self.indicadores if not i.subfila_de]

    def fuente_admitida(self, fuente_id: str) -> bool:
        return any(f["id"] == fuente_id for f in self.meta.get("fuentes_admitidas") or [])


def _valor(txt: str) -> Optional[Valor]:
    if txt == "":
        return None
    try:
        return float(txt)
    except ValueError:
        return txt


def _fila(d: Dict[str, str]) -> Indicador:
    return Indicador(
        id=d["id"], eje=int(d["eje"]), nombre=d["indicador"], escala=d["escala"],
        subfila_de=d["subfila_de"] or None,
        base_anio=int(d["base_anio"]) if d["base_anio"] else None,
        base_anio_texto=d["base_anio_texto"] or None,
        base_valor=_valor(d["base_valor"]),
        metas={a: v for a in ANIOS if (v := _valor(d[f"meta_{a}"])) is not None},
        anios_sin_meta_numerica=[a for a in d["anios_sin_meta_numerica"].split(",") if a],
    )


@lru_cache(maxsize=8)
def cargar(expediente_id: str) -> Expediente:
    """Carga y VALIDA un expediente. Un registro que no cuadra no se sirve."""
    import yaml  # type: ignore[import-untyped]

    base = RAIZ / expediente_id.replace("/", "")
    if not (base / "instrumento.yaml").exists():
        raise ExpedienteInvalido(f"no existe el expediente '{expediente_id}'")
    meta = yaml.safe_load((base / "instrumento.yaml").read_text(encoding="utf-8")) or {}
    with open(base / meta["registro"]["archivo"], encoding="utf-8") as fh:
        indicadores = [_fila(d) for d in csv.DictReader(fh)]
    _validar(meta, indicadores)
    return Expediente(id=meta["id"], titulo=meta["titulo"], norma=meta["norma"],
                      meta=meta, indicadores=indicadores)


def _validar(meta: Dict[str, Any], indicadores: List[Indicador]) -> None:
    """El expediente se contrasta contra lo que él mismo declara.

    Sin esto, una extracción que perdiera indicadores en silencio se serviría igual y el
    informe saldría midiendo un universo más chico sin decirlo — que es exactamente la falla
    que el producto existe para señalarle al Estado.
    """
    ids = [i.id for i in indicadores]
    if len(ids) != len(set(ids)):
        dup = sorted({x for x in ids if ids.count(x) > 1})
        raise ExpedienteInvalido(f"ids repetidos en el registro: {dup}")

    esperado = {int(k): v for k, v in (meta.get("indicadores_por_eje") or {}).items()}
    real: Dict[int, int] = {}
    for ind in indicadores:
        if not ind.subfila_de:
            real[ind.eje] = real.get(ind.eje, 0) + 1
    if real != esperado:
        raise ExpedienteInvalido(
            f"el registro no cuadra con lo declarado por eje: esperado {esperado}, real {real}")

    if (malas := {i.escala for i in indicadores} - set(ESCALAS)):
        raise ExpedienteInvalido(f"escalas desconocidas: {sorted(malas)}")

    # Una sub-fila sin su padre es una fila huérfana: se publicaría como si fuera un indicador.
    conocidos = set(ids)
    if (huerfanas := [i.id for i in indicadores
                      if i.subfila_de and i.subfila_de not in conocidos]):
        raise ExpedienteInvalido(f"sub-filas sin indicador padre: {huerfanas}")

    # Cada fuente admitida declara si es un órgano del Estado EVALUADO. Es lo que permite
    # contrastar emisor contra productor en la sección de verificabilidad, y se declara en
    # vez de inferirse de la nota: la nota es prosa y el contraste es una cifra que se
    # publica. Sin el campo, una fuente nueva entraría sin lado y el informe la contaría
    # como externa por omisión — el sesgo que le conviene a quien vende el informe.
    for f in (meta.get("fuentes_admitidas") or []):
        if not isinstance(f.get("del_evaluado"), bool):
            raise ExpedienteInvalido(
                f"fuente '{f.get('id')}': falta `del_evaluado` (bool). Decí si es un órgano "
                f"del Estado evaluado; de eso depende que el informe pueda distinguir un "
                f"emisor ajeno de una medición ajena.")

    # Coherencia entre la escala declarada y lo que la fila realmente trae.
    for ind in indicadores:
        if ind.escala == "sin_meta" and ind.metas:
            raise ExpedienteInvalido(f"{ind.id}: declara 'sin_meta' y trae metas")
        if ind.escala == "numerica" and any(isinstance(v, str) for v in ind.metas.values()):
            raise ExpedienteInvalido(f"{ind.id}: declara 'numerica' y trae una meta en texto")


def expedientes() -> List[str]:
    return sorted(p.name for p in RAIZ.iterdir()
                  if p.is_dir() and (p / "instrumento.yaml").exists())
