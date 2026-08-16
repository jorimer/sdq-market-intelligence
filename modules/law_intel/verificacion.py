"""Comprueba cada binding contra las series REALES, ahí donde viven.

**Por qué existe como endpoint y no como script.** El mapeo indicador↔serie solo se puede
comprobar donde están los datos, y en desarrollo no están: la base local tiene un puñado de
series. Esperar un token para correr un script a mano deja la cobertura bloqueada en una
credencial. El motor expone la comprobación y la ejecuta el entorno que tiene los datos.

**No muta el expediente.** Devuelve el veredicto por binding y el YAML se actualiza por PR.
El estado de un binding es un hecho comiteado y auditable, no algo que cambie en caliente: si
la cobertura pudiera subir sola en tiempo de ejecución, la cifra de portada dejaría de ser
verificable contra el repositorio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from modules.law_intel.bindings import Binding, aplicar_transformacion, cargar_bindings

# Antigüedad máxima tolerada para considerar viva una serie, en años respecto del corte. Una
# serie que existe pero se congeló no mide el presente — y publicarla como medición vigente
# es lo que produce un informe que afirma cobertura sobre datos de hace una década.
ANTIGUEDAD_MAXIMA_ANIOS = 3

RESULTADOS = {
    "verificable": "la serie existe y devuelve dato reciente",
    "congelada": "la serie existe y su último dato es demasiado viejo para medir el corte",
    "vacia": "la serie existe y no devuelve observaciones",
    "inexistente": "no hay ninguna serie con ese código",
}


@dataclass(frozen=True)
class Comprobacion:
    indicador: str
    serie: str
    estado_actual: str
    resultado: str
    ultimo_periodo: Optional[str] = None
    n_observaciones: int = 0
    comparabilidad_sin_resolver: bool = False
    # El valor ya llevado a la magnitud del indicador. Reportar el crudo dejaría al operador
    # comparando la variable contra la meta y concluyendo cualquier cosa.
    ultimo_valor: Optional[float] = None
    transformacion: Optional[str] = None

    @property
    def existe(self) -> bool:
        """La serie existe y devuelve dato reciente. NO dice que mida el indicador."""
        return self.resultado == "verificable"

    @property
    def promueve(self) -> bool:
        """¿Este binding puede pasar a `verificado` en el próximo PR?

        Exige DOS cosas, y la primera versión solo comprobaba una. Que la serie exista no
        dice que mida lo que el indicador afirma medir — es la distinción que sostiene todo
        este módulo, y la había perdido justo en la función que decide qué se publica.

        El caso que lo destapó: el indicador 2.19 es ANALFABETISMO y la variable del panel es
        alfabetización. La serie existe, devuelve dato de 2024 y la comprobación la daba por
        promovible; promoverla habría publicado el complemento — el valor invertido, que es
        el defecto más repetido de esta plataforma.
        """
        return (self.existe and self.estado_actual == "propuesto"
                and not self.comparabilidad_sin_resolver)


# Firma del proveedor de series: dado un código, devuelve [(período, valor)] ordenado.
Proveedor = Callable[[str], Sequence[Tuple[str, float]]]


def comprobar(bindings: Dict[str, Binding], proveedor: Proveedor,
              corte: str) -> List[Comprobacion]:
    out: List[Comprobacion] = []
    for b in bindings.values():
        if b.estado == "descartado":
            continue                      # ya se evaluó y no mide lo que el eje afirma
        try:
            obs = list(proveedor(b.serie))
        except Exception:                 # noqa: BLE001 — una serie ausente no rompe el barrido
            obs = []
        # Una nota de comparabilidad declarada es una duda ABIERTA sobre si la serie mide el
        # indicador. Mientras esté, el binding no promueve por más que la serie exista.
        duda = bool((b.nota_comparabilidad or "").strip())
        if not obs:
            # No se distingue «no existe» de «existe vacía» sin consultar el catálogo; se
            # reporta como vacía y el catálogo lo desambigua. Afirmar inexistencia sin
            # comprobarla sería el mismo error que el registro de obligaciones prohíbe.
            out.append(Comprobacion(b.indicador, b.serie, b.estado, "vacia",
                                    comparabilidad_sin_resolver=duda))
            continue
        obs = [(p, aplicar_transformacion(b, v)) for p, v in obs]
        ultimo = max(p for p, _ in obs)
        viva = int(ultimo[:4]) >= int(corte) - ANTIGUEDAD_MAXIMA_ANIOS
        out.append(Comprobacion(b.indicador, b.serie, b.estado,
                                "verificable" if viva else "congelada",
                                ultimo_periodo=ultimo, n_observaciones=len(obs),
                                comparabilidad_sin_resolver=duda,
                                ultimo_valor=dict(obs)[ultimo],
                                transformacion=b.transformacion))
    return out


def informe(expediente_id: str, proveedor: Proveedor, corte: str) -> Dict[str, Any]:
    cs = comprobar(cargar_bindings(expediente_id), proveedor, corte)
    por_resultado: Dict[str, int] = {}
    for c in cs:
        por_resultado[c.resultado] = por_resultado.get(c.resultado, 0) + 1
    promovibles = [c.indicador for c in cs if c.promueve]
    frenados = [c.indicador for c in cs if c.existe and c.comparabilidad_sin_resolver]
    return {
        "corte": corte,
        "comprobados": len(cs),
        "por_resultado": dict(sorted(por_resultado.items())),
        # Lo accionable: qué escribir en el próximo PR del expediente.
        "promovibles_a_verificado": sorted(promovibles),
        "ganancia_de_cobertura": len(promovibles),
        # La serie existe pero hay una duda declarada sobre si mide el indicador. NO suma
        # cobertura: resolver la duda es trabajo de análisis, no de conexión.
        "existen_pero_con_comparabilidad_sin_resolver": sorted(frenados),
        "comprobaciones": [{
            "indicador": c.indicador, "serie": c.serie, "estado_actual": c.estado_actual,
            "resultado": c.resultado, "ultimo_periodo": c.ultimo_periodo,
            "n_observaciones": c.n_observaciones, "promueve": c.promueve,
            "comparabilidad_sin_resolver": c.comparabilidad_sin_resolver,
            "ultimo_valor": c.ultimo_valor, "transformacion": c.transformacion,
        } for c in cs],
        "resultados": RESULTADOS,
        "nota": ("Esta comprobación NO muta el expediente. El estado de un binding es un hecho "
                 "comiteado: si la cobertura pudiera subir en caliente, la cifra de portada "
                 "dejaría de ser verificable contra el repositorio."),
        "que_significa_verificable": (
            "Que la serie EXISTE y devuelve dato reciente. No dice que mida lo que el "
            "indicador afirma medir: eso lo decide resolver la nota de comparabilidad, y "
            "hasta entonces el binding no promueve."),
    }
