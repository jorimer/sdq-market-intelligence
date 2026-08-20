"""Qué manda la ley hacer, a quién, con qué plazo — y qué pasa si no.

**La regla que gobierna este módulo.** `incumplida` afirma que algo no se hizo;
`sin_registro_publico` dice que no se encontró rastro. No son lo mismo, y el motor no permite
publicar la primera con la evidencia de la segunda.

El destinatario del informe suele ser el órgano al que la obligación le corresponde. Afirmarle
al Congreso que su comisión nunca se constituyó, sin haber consultado los expedientes de
Cámara y Senado, es refutable con un solo documento — y se lleva puesto el informe entero. La
plataforma ya aprendió que un dato ausente se declara y no se rellena; acá el costo de
rellenarlo no es una cifra mal puesta, es la credibilidad del producto ante quien lo compra.

**`consecuencia: None` es el hallazgo, no un campo vacío.** Ninguno de los mecanismos de
control que la END previó tiene efecto jurídico asignado a su no activación. Se declara
explícitamente para poder contarlo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

from modules.law_intel.registro import RAIZ, ExpedienteInvalido

# El estado dice qué se puede AFIRMAR, no qué creemos que pasó.
ESTADOS = {
    "cumplida": "hay evidencia de que se hizo en plazo",
    "cumplida_tarde": "se hizo fuera del plazo; exige evidencia de ambas fechas",
    "incumplida": "hay evidencia de que NO se hizo",
    "parcial": "se hizo en parte; exige evidencia de qué falta",
    "pendiente_no_vencida": "el plazo no ha llegado",
    "sin_registro_publico": "no se encontró registro — NO es una afirmación de incumplimiento",
    "no_exigible": "la obligación no tiene deudor determinado o carece de término",
}

# Estados que afirman algo en contra de alguien. Exigen evidencia, siempre.
ACUSATORIOS = frozenset({"incumplida", "cumplida_tarde", "parcial"})

# Un deudor indeterminado vuelve la obligación inexigible por construcción: no hay a quién
# requerir ni quién incurre en mora. Es un hallazgo sobre el diseño de la ley.
TIPOS_DEUDOR = frozenset({"organo", "indeterminado"})


@dataclass(frozen=True)
class Obligacion:
    id: str
    articulo: int
    deber: str
    deudor: Dict[str, str]
    estado: str
    consecuencia: Optional[str] = None
    periodicidad: Optional[str] = None
    plazo: Optional[Dict[str, Any]] = None
    evidencia: Optional[str] = None
    produce: List[str] = field(default_factory=list)
    habilita_exigir: List[str] = field(default_factory=list)
    nota_de_diseño: Optional[str] = None
    #: Qué buscar en la base normativa para comprobar esta obligación, cuando su
    #: cumplimiento ES dictar una norma. Se declara en el expediente y no se infiere del
    #: texto del deber: una consulta adivinada que no encuentra nada produce un
    #: `incumplida` sobre una búsqueda mal formulada.
    #:
    #: `desde` y `hasta` son obligatorios para el emisor —sin rango, su alcance nunca es
    #: concluyente y un vacío no autoriza a acusar—, así que van en la declaración.
    verificacion_normativa: Optional[Dict[str, Any]] = None
    #: Por qué esta obligación NO tiene consulta normativa. Obligatorio cuando falta la
    #: consulta, y no es burocracia: sin él, «no hay consulta» es indistinguible de «nadie lo
    #: pensó», que es exactamente la ambigüedad que este expediente existe para no producir.
    #:
    #: Las razones no son la misma, y separarlas importa porque se destraban distinto: un
    #: informe o una convocatoria no dejan rastro en la Gaceta y NUNCA lo dejarán —hace falta
    #: otra fuente—; un acto del Congreso sí consta, pero en expedientes de Cámara y Senado
    #: que todavía no tenemos.
    sin_consulta_normativa: Optional[str] = None

    @property
    def exigible(self) -> bool:
        """Una obligación sin deudor determinado no se le puede requerir a nadie."""
        return self.deudor.get("tipo") == "organo" and self.estado != "no_exigible"

    @property
    def afirma_incumplimiento(self) -> bool:
        return self.estado in ACUSATORIOS

    @property
    def requiere_verificacion_antes_de_publicar(self) -> bool:
        """`sin_registro_publico` se puede publicar como tal, pero nunca como incumplimiento.

        Lo expone el objeto para que el redactor no tenga que acordarse de la distinción: la
        frase que sale al informe se elige de acá, no del criterio de quien escribe.
        """
        return self.estado == "sin_registro_publico"

    def frase_publicable(self) -> str:
        """Cómo se dice esto en un informe sin afirmar de más."""
        if self.estado == "sin_registro_publico":
            return (f"No se localizó registro público de cumplimiento del artículo "
                    f"{self.articulo}. No se afirma incumplimiento: la verificación está "
                    f"pendiente.")
        if self.estado == "no_exigible":
            return (f"El artículo {self.articulo} no tiene deudor determinado ni término, "
                    f"por lo que no es exigible en sus propios términos.")
        return f"Artículo {self.articulo}: {ESTADOS[self.estado]}."


@lru_cache(maxsize=8)
def cargar_obligaciones(expediente_id: str) -> List[Obligacion]:
    import yaml  # type: ignore[import-untyped]

    ruta = RAIZ / expediente_id.replace("/", "") / "obligaciones.yaml"
    if not ruta.exists():
        return []
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    obs = [Obligacion(**o) for o in (doc.get("obligaciones") or [])]
    _validar(obs)
    return obs


def _validar(obs: List[Obligacion]) -> None:
    vistos = set()
    for o in obs:
        if o.id in vistos:
            raise ExpedienteInvalido(f"obligación duplicada: {o.id}")
        vistos.add(o.id)
        if o.estado not in ESTADOS:
            raise ExpedienteInvalido(f"{o.id}: estado desconocido '{o.estado}'")
        if o.deudor.get("tipo") not in TIPOS_DEUDOR:
            raise ExpedienteInvalido(f"{o.id}: tipo de deudor inválido")
        # El guard central: no se acusa sin evidencia.
        if o.afirma_incumplimiento and not (o.evidencia or "").strip():
            raise ExpedienteInvalido(
                f"{o.id}: estado '{o.estado}' afirma un incumplimiento y no trae evidencia. "
                f"Si no hay con qué probarlo, el estado es 'sin_registro_publico'.")


def por_producto(expediente_id: str) -> Dict[str, List[Obligacion]]:
    """Qué obligación produce cada cosa — el resolvedor de destinatario de una brecha.

    Es la pieza que vuelve accionable la sección de huecos: si falta un dato, esta tabla dice
    qué artículo manda producirlo y a quién.
    """
    out: Dict[str, List[Obligacion]] = {}
    for o in cargar_obligaciones(expediente_id):
        for p in o.produce:
            out.setdefault(p, []).append(o)
    return out


def resumen(expediente_id: str) -> Dict[str, Any]:
    obs = cargar_obligaciones(expediente_id)
    por_estado: Dict[str, int] = {}
    for o in obs:
        por_estado[o.estado] = por_estado.get(o.estado, 0) + 1
    sin_consecuencia = [o.id for o in obs if o.consecuencia is None]
    return {
        "total": len(obs),
        "por_estado": dict(sorted(por_estado.items())),
        "exigibles": sum(1 for o in obs if o.exigible),
        "sin_deudor_determinado": [o.id for o in obs if o.deudor.get("tipo") == "indeterminado"],
        # El hallazgo central del expediente, contado en vez de afirmado en prosa.
        "sin_consecuencia_asignada": {
            "n": len(sin_consecuencia), "ids": sin_consecuencia,
            "lectura": ("Ningún mecanismo de control tiene efecto jurídico asignado a su no "
                        "activación: la ley construyó frenos que nadie está obligado a pisar."),
        },
        "pendientes_de_verificar": [o.id for o in obs
                                    if o.requiere_verificacion_antes_de_publicar],
    }
