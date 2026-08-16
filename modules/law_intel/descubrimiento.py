"""Qué fuente pública podría medir cada indicador que hoy no medimos.

**Por qué este eje no usa el término único por eje.** El descubridor de `source_intel` busca
en el catálogo nacional con una consulta por eje (`"energia electricidad"` para energy). Para
una ley eso desperdicia lo mejor que hay: **cada indicador trae su propio nombre**, escrito
por el legislador para describir exactamente lo que quiso medir. Son 76 consultas dirigidas en
vez de una genérica.

**Lo que este módulo NO hace.** No integra nada ni decide nada: produce las consultas y
normaliza lo que el catálogo devuelve. La evaluación y la decisión siguen donde estaban — el
sistema propone, el dueño dispone.

**El costo.** Las búsquedas al catálogo son HTTP y no cuestan. Lo que cuesta es evaluar cada
dataset encontrado, y por eso el barrido acota cuántos propone por corrida en vez de disparar
una evaluación por cada resultado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.registro import Indicador, cargar

# Palabras que no discriminan nada en un catálogo de datos: aparecen en la mitad de los
# nombres de indicador y ensucian la consulta. Se quitan para que queden los términos que
# realmente identifican el fenómeno.
_VACIAS = {
    "porcentaje", "numero", "número", "indice", "índice", "promedio", "poblacion",
    "población", "total", "nacional", "general", "tasa", "razon", "razón", "cantidad",
    "nivel", "grado", "valor", "anual", "mediante", "sobre", "entre", "segun", "según",
    "entidades", "referencia",
}
# Un solo término distintivo SÍ es una consulta útil —«homicidios» encontró dataset en la
# sonda contra el catálogo real—. Lo que no sirve es una consulta VACÍA, que devuelve
# cualquier cosa y ensucia el tablero con propuestas sin relación con el indicador.
MINIMO_TERMINOS = 1


@dataclass(frozen=True)
class Consulta:
    indicador: str
    nombre: str
    eje: int
    terminos: str

    @property
    def util(self) -> bool:
        return len(self.terminos.split()) >= MINIMO_TERMINOS


def terminos_de(ind: Indicador) -> str:
    """Términos de búsqueda tomados del nombre que el legislador le puso al indicador."""
    limpio = re.sub(r"[^\w\sáéíóúñüÁÉÍÓÚÑ]", " ", ind.nombre.lower())
    # `>= 4` y no `> 4`: el umbral de cinco letras se comía «gini», que es justamente el
    # término más discriminante que tiene su indicador.
    palabras = [w for w in limpio.split() if len(w) >= 4 and w not in _VACIAS]
    # Se acota: una consulta larguísima en CKAN devuelve menos, no más.
    return " ".join(dict.fromkeys(palabras))[:70].strip()


def consultas(expediente_id: str) -> List[Consulta]:
    """Una consulta por indicador SIN medición, ordenadas por eje.

    Se excluyen los que ya tienen binding verificado —no hay nada que descubrir— y los
    descartados, porque su problema no es falta de fuente sino que la fuente evaluada no mide
    lo que el eje afirma. Volver a proponerles algo del catálogo sería re-abrir una decisión
    ya tomada y documentada.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    out: List[Consulta] = []
    for ind in exp.numerados:
        b = bs.get(ind.id)
        if b and (b.cuenta or b.estado == "descartado"):
            continue
        out.append(Consulta(ind.id, ind.nombre, ind.eje, terminos_de(ind)))
    return sorted(out, key=lambda c: (c.eje, c.indicador))


def resumen(cs: Sequence[Consulta]) -> Dict[str, object]:
    inutiles = [c.indicador for c in cs if not c.util]
    return {
        "indicadores_sin_medicion": len(cs),
        "consultas_utiles": len(cs) - len(inutiles),
        # Un nombre del que no salen dos términos no produce una búsqueda que discrimine.
        # Se declara en vez de lanzarla igual: una consulta vacía devuelve cualquier cosa y
        # ensucia el tablero con propuestas sin relación con el indicador.
        "sin_terminos_suficientes": inutiles,
        "nota": ("Las búsquedas al catálogo no tienen costo. Lo que cuesta es EVALUAR cada "
                 "dataset encontrado, así que el barrido acota cuántos propone por corrida."),
    }


def barrido(expediente_id: str, buscar, max_por_indicador: int = 2,
            limite: Optional[int] = None) -> List[Dict[str, object]]:
    """Corre las consultas contra un buscador de catálogo y junta los candidatos.

    *buscar* recibe la consulta y devuelve datasets normalizados; se inyecta para que este
    módulo no dependa de un catálogo concreto ni haga red en los tests.
    """
    salida: List[Dict[str, object]] = []
    for c in consultas(expediente_id):
        if limite is not None and len(salida) >= limite:
            break
        if not c.util:
            continue
        for ds in list(buscar(c.terminos))[:max_por_indicador]:
            salida.append({
                "indicador": c.indicador, "nombre_indicador": c.nombre, "eje": c.eje,
                "consulta": c.terminos, "dataset": ds,
            })
    return salida
