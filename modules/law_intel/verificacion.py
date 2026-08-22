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

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from modules.law_intel.anadas import Anada, Absorcion, absorbe
from modules.law_intel.bindings import Binding, aplicar_transformacion, cargar_bindings
from modules.law_intel.registro import cargar

# Antigüedad máxima tolerada para considerar viva una serie, en años respecto del corte. Una
# serie que existe pero se congeló no mide el presente — y publicarla como medición vigente
# es lo que produce un informe que afirma cobertura sobre datos de hace una década.
ANTIGUEDAD_MAXIMA_ANIOS = 3

#: Margen sobre la cadencia declarada. Un emisor que publica cada 6 años puede atrasarse un
#: ciclo sin que eso sea «dejó de publicar»; dos ciclos ya lo es. El margen se aplica sobre la
#: cadencia y no sobre el umbral anual, así que no afloja nada para las series anuales.
MARGEN_SOBRE_CADENCIA = 1.5


def ventana_de_frescura(b: Binding) -> int:
    """Años de antigüedad tolerados para ESTE binding.

    Sin cadencia declarada rige el umbral anual, que es el caso de casi todo. Con cadencia, la
    ventana se estira lo suficiente para que un emisor de ciclo largo no aparezca congelado por
    publicar a su ritmo — y no más: a los dos ciclos vuelve a marcarse, que es cuando dejar de
    publicar deja de ser cadencia y pasa a ser abandono.
    """
    if not b.cadencia_anios or b.cadencia_anios <= 1:
        return ANTIGUEDAD_MAXIMA_ANIOS
    return max(ANTIGUEDAD_MAXIMA_ANIOS, int(b.cadencia_anios * MARGEN_SOBRE_CADENCIA))

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
    #: El cuarto candado del camino `revision_declarada`, computado contra la serie REAL.
    #: `None` en todo binding que no vaya por ese camino: ahí no hay corrección que absorber.
    absorcion: Optional[Absorcion] = None

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
        if not (self.existe and self.estado_actual == "propuesto"
                and not self.comparabilidad_sin_resolver):
            return False
        # El camino de revisión declarada trae un candado más, y sin él no promueve. Que la
        # serie exista y el emisor haya declarado su revisión no dice nada sobre si el
        # veredicto aguanta la corrección: eso se computa contra el dato, y es el único de
        # los cuatro candados que el expediente no puede cerrar solo.
        if self.absorcion is not None and not self.absorcion.absorbe:
            return False
        return True


# Firma del proveedor de series: dado un código, devuelve [(período, valor)] ordenado.
Proveedor = Callable[[str], Sequence[Tuple[str, float]]]


def _metas_numericas(metas: Dict[str, str]) -> Dict[str, float]:
    """Las metas que son un número, con su año. Los umbrales («>1700») cuentan: lo que decide
    es el valor contra el que se compara, y la dirección la trae el binding."""
    out: Dict[str, float] = {}
    for anio, texto in (metas or {}).items():
        m = re.search(r"-?\d+(?:[.,]\d+)?", str(texto).replace(",", ""))
        if m:
            try:
                out[anio] = float(m.group(0))
            except ValueError:
                continue
    return out


def comprobar_absorcion(b: Binding, indicador: Any,
                        observados: Dict[str, float]) -> Optional[Absorcion]:
    """¿El margen se come la corrección de añada? Se computa acá y no en el expediente.

    Es el candado que `bindings._validar` no puede cerrar, porque necesita las observaciones
    y ésas viven donde están los datos. Transcribirlas al YAML sería copiar justo las cifras
    que el emisor puede volver a revisar.
    """
    if b.verificado_por != "revision_declarada" or indicador.base_valor is None:
        return None
    try:
        anadas = [Anada.desde(a) for a in b.anadas]
    except ValueError:
        return None
    if not anadas:
        return None
    return absorbe(float(indicador.base_valor), anadas, b.mejor, observados,
                   _metas_numericas(indicador.metas))


def comprobar(bindings: Dict[str, Binding], proveedor: Proveedor,
              corte: str, expediente_id: str = "end_2030") -> List[Comprobacion]:
    # El registro solo hace falta para el cuarto candado del camino `revision_declarada`, y
    # se carga solo si algún binding va por ahí. Cargarlo siempre haría que este barrido
    # dependa de un expediente real incluso cuando no tiene nada que comprobar contra él.
    por_id = ({i.id: i for i in cargar(expediente_id).indicadores}
              if any(b.verificado_por == "revision_declarada" for b in bindings.values())
              else {})
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
        viva = int(ultimo[:4]) >= int(corte) - ventana_de_frescura(b)
        ind = por_id.get(b.indicador)
        absorcion = comprobar_absorcion(b, ind, {p[:4]: v for p, v in obs}) if ind else None
        out.append(Comprobacion(b.indicador, b.serie, b.estado,
                                "verificable" if viva else "congelada",
                                ultimo_periodo=ultimo, n_observaciones=len(obs),
                                comparabilidad_sin_resolver=duda,
                                ultimo_valor=dict(obs)[ultimo],
                                transformacion=b.transformacion,
                                absorcion=absorcion))
    return out


def informe(expediente_id: str, proveedor: Proveedor, corte: str) -> Dict[str, Any]:
    cs = comprobar(cargar_bindings(expediente_id), proveedor, corte, expediente_id)
    por_resultado: Dict[str, int] = {}
    for c in cs:
        por_resultado[c.resultado] = por_resultado.get(c.resultado, 0) + 1
    promovibles = [c.indicador for c in cs if c.promueve]
    frenados = [c.indicador for c in cs if c.existe and c.comparabilidad_sin_resolver]
    # Lo vetado se LISTA. Un binding que no promueve porque la corrección de añada da vuelta
    # su veredicto tiene que aparecer diciendo eso; callarlo se lee como que nadie lo miró.
    sin_absorber = [{"indicador": c.indicador, "motivo": c.absorcion.motivo,
                     "factor": round(c.absorcion.factor, 4)}
                    for c in cs if c.absorcion is not None and not c.absorcion.absorbe]
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
        "revision_declarada_que_el_margen_NO_absorbe": sin_absorber,
        "comprobaciones": [{
            "indicador": c.indicador, "serie": c.serie, "estado_actual": c.estado_actual,
            "resultado": c.resultado, "ultimo_periodo": c.ultimo_periodo,
            "n_observaciones": c.n_observaciones, "promueve": c.promueve,
            "comparabilidad_sin_resolver": c.comparabilidad_sin_resolver,
            "ultimo_valor": c.ultimo_valor, "transformacion": c.transformacion,
            "absorcion_de_anada": None if c.absorcion is None else {
                "absorbe": c.absorcion.absorbe,
                "factor_mas_adverso": round(c.absorcion.factor, 4),
                "motivo": c.absorcion.motivo,
                "por_meta": [{"anio": a, "observado": round(o, 2),
                              "corregido": round(k, 2), "meta": m,
                              "cumple_sin_corregir": c1, "cumple_corregido": c2}
                             for a, o, k, m, c1, c2 in c.absorcion.detalle],
            },
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
