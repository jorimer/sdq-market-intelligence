"""Catálogo de disparadores — QUÉ puede hacer sonar una alerta.

**En la fase A esto es declarativo y nada más.** Las funciones de regla llegan en la fase B
(`docs/SPEC_ALERTA_ACCIONABLE.md` §4). Existe ahora porque la watchlist necesita validar
``rule_codes`` contra un vocabulario cerrado: aceptar códigos libres hoy deja filas que el
motor de mañana no va a honrar, y esa vigilancia no falla — DESAPARECE.

**Por qué cada entrada declara ``implementado``.** Un código en catálogo sin motor detrás es
una vigilancia que nunca suena. Se puede suscribir (el cliente declara su interés y no hay
que pedírselo dos veces), pero la API lo DICE y la UI lo muestra. Un disparador mudo que se
presenta como activo se lee como «no pasó nada», que es la lectura opuesta a la verdadera.

**``basis`` no es decorado.** Es por qué la regla existe: la lección, la doctrina o el motor
que la ancla. Viaja al evento y de ahí al texto que lee el cliente — una alerta que no puede
decir por qué es una regla que sonó porque sí.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Severidades, de mayor a menor. El orden es el dato: ``min_severity`` filtra por posición.
SEVERIDADES: Tuple[str, ...] = ("alta", "media", "baja")


def severidad_alcanza(severidad: str, minima: str) -> bool:
    """¿*severidad* es al menos tan grave como *minima*? Desconocidas no alcanzan nunca:
    ante una severidad que no está en el vocabulario, no entregar es el lado seguro."""
    if severidad not in SEVERIDADES or minima not in SEVERIDADES:
        return False
    return SEVERIDADES.index(severidad) <= SEVERIDADES.index(minima)


@dataclass(frozen=True)
class Disparador:
    """Una clase de evento que puede levantar una alerta."""

    codigo: str
    label: str
    descripcion: str
    basis: str
    # ¿Exige un sujeto nombrado? Un cambio de banda es de una entidad; una publicación
    # nueva es del eje entero. Lo usa la validación de la watchlist.
    requiere_sujeto: bool
    # ¿Tiene motor detrás HOY? Ver el docstring del módulo.
    implementado: bool = False


CATALOGO: Tuple[Disparador, ...] = (
    Disparador(
        codigo="umbral",
        label="Cruce de umbral",
        descripcion=("Una métrica vigilada cruzó un umbral declarado en doctrina "
                     "(p. ej. cobertura de provisiones por debajo de 100%)."),
        basis=("Reglas de monitoreo ancladas a lecciones documentadas del sector; en banca, "
               "a los precursores de la crisis RD 2003 "
               "(modules/banking_score/early_warning.py)."),
        requiere_sujeto=False,
    ),
    Disparador(
        codigo="banda",
        label="Cambio de banda",
        descripcion="El sujeto cambió de banda o tier entre dos períodos consecutivos.",
        basis="Bandas del motor de índices explicable (shared/indices).",
        requiere_sujeto=True,
    ),
    Disparador(
        codigo="posicion",
        label="Cambio de posición",
        descripcion=("El sujeto se movió en el ranking de su universo comparable. Solo "
                     "ordena lo comparable: un score armado sobre 3 de 5 dimensiones no "
                     "rankea contra uno de 5."),
        basis="shared.narrative.derived.universo_comparable — doctrina de comparabilidad.",
        requiere_sujeto=True,
    ),
    Disparador(
        codigo="brecha",
        label="Brecha de dato",
        descripcion=("Una dimensión que tenía dato dejó de tenerlo, o al revés. Que un eje "
                     "haya perdido su dato es noticia para quien lo vigila."),
        basis="Doctrina de datos: la brecha se declara, nunca se rellena.",
        requiere_sujeto=False,
    ),
    Disparador(
        codigo="frescura",
        label="Validación vencida",
        descripcion=("El insumo que produjo una credencial de validación cambió después de "
                     "calcularla: el reporte quedó huérfano."),
        basis=("shared.validation.frescura — huella del insumo. Sin esto, producción sirvió "
               "19 días un Gini calculado con un score que ya no existía."),
        requiere_sujeto=False,
    ),
    Disparador(
        codigo="publicacion",
        label="Publicación nueva",
        descripcion="Entró una edición nueva de una fuente recurrente del eje.",
        basis=("Detector ya existente en shared/operations/freshness.py::_audit_publications, "
               "hoy dirigido solo a administradores."),
        requiere_sujeto=False,
    ),
)

POR_CODIGO: Dict[str, Disparador] = {d.codigo: d for d in CATALOGO}
CODIGOS: Tuple[str, ...] = tuple(d.codigo for d in CATALOGO)


def implementados() -> List[str]:
    """Códigos con motor detrás hoy. En la fase A es la lista vacía, y eso es correcto:
    la watchlist existe antes que el motor a propósito, para que la fase B tenga contra
    qué disparar el día que arranca."""
    return [d.codigo for d in CATALOGO if d.implementado]


def serializar(d: Disparador) -> Dict[str, object]:
    return {
        "codigo": d.codigo, "label": d.label, "descripcion": d.descripcion,
        "basis": d.basis, "requiere_sujeto": d.requiere_sujeto,
        "implementado": d.implementado,
    }


def desconocidos(codigos: Optional[List[str]]) -> List[str]:
    """Los códigos de *codigos* que no están en el catálogo (para el error de validación)."""
    if not codigos:
        return []
    return [c for c in codigos if c not in POR_CODIGO]
