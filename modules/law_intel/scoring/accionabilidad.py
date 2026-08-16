"""De la brecha a la acción: qué falta, quién debe producirlo, con qué instrumento se exige.

Es la sección que convierte una limitación del informe en una lista que el cliente puede
accionar — y el cliente de este producto no es quien quiere un informe, es quien tiene
legitimación para exigir que el dato exista.

**Por qué la recomendación se CONSTRUYE y no se redacta.** Recomendar la publicación de un
dato es compatible con ser independiente; recomendar política no lo es. Si la recomendación
tuviera un campo de texto libre, esa frontera dependería del criterio de quien escribe cada
informe. Acá no existe ese campo: cada frase se arma de artículo, deber, deudor e instrumento,
todos tomados del registro de obligaciones. **No hay dónde alojar una opinión de política.**

Y el desbloqueo es el mismo cómputo que la sugerencia interna de fuentes con otro
destinatario: hacia adentro dice «conectar esto sube la cobertura»; hacia el cliente, «exigir
que se publique esto sube la cobertura». Un solo join, dos audiencias.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from modules.law_intel.obligaciones import Obligacion
from modules.law_intel.scoring.brecha import Brecha

# Qué clase de acción es. `interna` se publica igual: si el hueco es nuestro, decirlo evita
# imputarle al Estado una brecha de la plataforma.
CLASES = {
    "publicacion": "existe la obligación de publicar y no consta cumplida",
    "dato": "el dato no existe o no es utilizable, y la ley asigna quién debe producirlo",
    "interna": "el hueco es de la plataforma: falta conectar o verificar la fuente",
}

# Orden de fuerza del reclamo. Una obligación incumplida CON evidencia no pide nada nuevo:
# exige lo ya mandado, y es el reclamo más difícil de contestar.
_PESO_ESTADO = {"incumplida": 0, "cumplida_tarde": 1, "parcial": 2,
                "sin_registro_publico": 3, "pendiente_no_vencida": 4}


@dataclass(frozen=True)
class Recomendacion:
    clase: str
    que_falta: str
    base_legal: Optional[str]          # «artículo 42»
    deudor: Optional[str]
    instrumentos: List[str]
    desbloquea: int
    indicadores: List[str]
    estado_obligacion: Optional[str] = None
    verificacion_pendiente: bool = False

    def frase(self) -> str:
        """La recomendación, armada de sus campos. No hay texto de autor en esta cadena."""
        if self.clase == "interna":
            return (f"{self.que_falta}. Es una brecha de la plataforma, no del Estado; "
                    f"cerrarla habilita medir {self.desbloquea} indicador(es).")
        base = self.que_falta.rstrip(".")
        if self.base_legal:
            base += f". Lo manda el {self.base_legal}"
        if self.deudor:
            base += f" y lo asigna a: {self.deudor}"
        if self.instrumentos:
            base += f". Instrumento disponible: {', '.join(self.instrumentos)}"
        if self.desbloquea:
            base += f". Habilita medir {self.desbloquea} indicador(es)"
        if self.verificacion_pendiente:
            base += (". ⚠️ No se afirma incumplimiento: la verificación del registro está "
                     "pendiente y debe cerrarse antes de publicar")
        return base + "."


def _articulo(o: Obligacion) -> str:
    return f"artículo {o.articulo}"


def recomendaciones(brechas_: Sequence[Brecha],
                    obligaciones_: Sequence[Obligacion]) -> List[Recomendacion]:
    """Una lista accionable, ordenada por fuerza del reclamo y por rendimiento."""
    out: List[Recomendacion] = []

    # 1. Brechas de PUBLICACIÓN: la obligación existe y no consta cumplida. Es el reclamo más
    #    fuerte porque no pide nada nuevo — exige lo que la ley ya mandó.
    # No se filtra por `produce`: una obligación puede no generar ningún documento y ser aun
    # así la más accionable de todas. El artículo 51 no produce un informe — habilita al
    # Congreso a citar funcionarios, es competencia propia y no depende del Ejecutivo. Filtrar
    # por producto lo dejaba fuera, que es exactamente al revés de su importancia.
    for o in sorted(obligaciones_, key=lambda x: _PESO_ESTADO.get(x.estado, 9)):
        # `cumplida_tarde` tampoco genera acción: ya se hizo. El artículo 54 se cumplió con
        # 21 meses de retraso y eso es evidencia para el expediente, no algo que se pueda
        # exigir hoy. Mezclar lo consumado con lo pendiente le quita fuerza a la lista.
        if o.estado in ("cumplida", "cumplida_tarde", "no_exigible"):
            continue
        out.append(Recomendacion(
            clase="publicacion",
            que_falta=f"Falta el cumplimiento verificable de: {o.deber.strip().rstrip('.')}",
            base_legal=_articulo(o), deudor=o.deudor.get("nombre"),
            instrumentos=list(o.habilita_exigir), desbloquea=0, indicadores=[],
            estado_obligacion=o.estado,
            verificacion_pendiente=o.requiere_verificacion_antes_de_publicar))

    # 2. Brechas de DATO cuya responsabilidad es del Estado.
    del_estado = [b for b in brechas_ if b.responsable == "estado"]
    for b in del_estado:
        out.append(Recomendacion(
            clase="dato",
            que_falta=(f"El indicador {b.indicador} no tiene fuente admisible "
                       f"({b.nombre.strip()})"),
            base_legal=None, deudor=None, instrumentos=[],
            desbloquea=1, indicadores=[b.indicador]))

    # 3. Lo que es NUESTRO se publica igual, agrupado. Sin esto el informe le imputa al Estado
    #    huecos de la plataforma, y esa es una forma de inflar el reclamo.
    internas = [b for b in brechas_ if b.responsable == "sdq"]
    if internas:
        con_serie = [b for b in internas if b.serie_candidata]
        if con_serie:
            out.append(Recomendacion(
                clase="interna",
                que_falta=f"Verificar {len(con_serie)} serie(s) candidata(s) ya identificada(s)",
                base_legal=None, deudor=None, instrumentos=[], desbloquea=len(con_serie),
                indicadores=sorted(b.indicador for b in con_serie)))
        sin_serie = [b for b in internas if not b.serie_candidata]
        if sin_serie:
            out.append(Recomendacion(
                clase="interna",
                que_falta=f"Identificar fuente para {len(sin_serie)} indicador(es)",
                base_legal=None, deudor=None, instrumentos=[], desbloquea=len(sin_serie),
                indicadores=sorted(b.indicador for b in sin_serie)))
    return out


def resumen(recs: Sequence[Recomendacion]) -> Dict[str, object]:
    por_clase: Dict[str, int] = {}
    for r in recs:
        por_clase[r.clase] = por_clase.get(r.clase, 0) + 1
    return {
        "total": len(recs),
        "por_clase": dict(sorted(por_clase.items())),
        "desbloqueo_total": sum(r.desbloquea for r in recs),
        "con_verificacion_pendiente": [r.base_legal for r in recs if r.verificacion_pendiente],
        "alcance": ("Se recomienda la PUBLICACIÓN del dato, nunca la política. Cada frase se "
                    "arma de artículo, deber, deudor e instrumento tomados del registro de "
                    "obligaciones: no hay campo donde alojar una opinión de política."),
    }
