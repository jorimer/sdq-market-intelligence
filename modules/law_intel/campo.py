"""El estado del CAMPO: que ninguno de los indicadores de la ley quede en silencio.

**Cobertura y cierre del campo son dos cifras distintas.** La cobertura cuenta cuántos
indicadores se miden. El cierre del campo cuenta cuántos están DECLARADOS: con veredicto, o
con un motivo dicho. Un informe se vuelve publicable con la segunda mucho antes que con la
primera, y es la segunda la que el alcance promete.

**«Buscamos y no hay» y «no hemos buscado» son estados distintos**, y el motor se niega a
confundirlos. Es la misma disciplina que separa `incumplida` de `sin_registro_publico` en las
obligaciones: la primera afirma algo del mundo y exige evidencia; la segunda afirma algo de
nuestro trabajo y no la exige. Un campo cerrado con todo declarado «pendiente» está cerrado y
no dice nada, y esa composición se publica al lado de la cifra para que nadie la lea al revés.

**Lo que un estado definitivo exige.** Los cuatro que afirman algo sobre el mundo —que nadie
publica la magnitud, que el instrumento se discontinuó, que el emisor no publica en formato
procesable, que el emisor publica otras cosas y ésta no— llevan evidencia con su fecha. Sin
ella se degradan a pendiente: afirmar que una fuente no existe sin haberla buscado es la
versión de este módulo de acusar sin pruebas.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.registro import RAIZ, ExpedienteInvalido, cargar

#: Por qué un indicador de la ley no tiene veredicto. Conjunto CERRADO: un motivo libre
#: convierte el cierre del campo en una casilla que siempre se puede marcar.
ESTADOS_DEL_CAMPO = {
    # ── Lo impide la propia ley ────────────────────────────────────────────────────────
    "sin_meta_legal": "la ley numera el indicador y no le fija meta",
    "meta_no_interpretable": ("la meta está en prosa, o compone dos condiciones que no se "
                              "pueden juzgar por separado"),
    # ── El instrumento ─────────────────────────────────────────────────────────────────
    "instrumento_discontinuado": ("el emisor que la ley eligió dejó de producir la medición "
                                  "en términos comparables con las metas"),
    # ── La fuente ──────────────────────────────────────────────────────────────────────
    "sin_fuente_conocida": "se buscó y ningún emisor publica la magnitud",
    "fuente_no_procesable": ("el emisor publica, y en un formato del que no se puede extraer "
                             "la serie sin inventar procedencia"),
    "magnitud_no_publicada": ("el emisor existe y publica otras cosas de su competencia; "
                              "ésta no"),
    # ── Hay candidato y algo falta ─────────────────────────────────────────────────────
    "candidato_descartado": ("se evaluó una serie concreta y mide otra cosa; el motivo cuelga "
                             "del binding"),
    "candidato_sin_verificar": ("hay serie y una duda de comparabilidad abierta; la nota "
                                "cuelga del binding"),
    # ── El que no cierra es el instrumento LEGAL, y eso es un hallazgo, no una tarea ──
    "linea_base_no_reproduce": ("el emisor publica la magnitud con el término de la ley y su "
                                "serie NO reproduce la línea base que la ley fija"),
    "termino_legal_sin_fuente": ("la ley nombra la magnitud con un término que ningún emisor "
                                 "publica, y las lecturas vecinas se probaron sin cerrar"),
    "pendiente_de_derivacion": ("la serie existe y falta definir la derivación, el "
                                "denominador o la convención de anualización"),
    # ── Nosotros ───────────────────────────────────────────────────────────────────────
    "pendiente_de_busqueda": "no se ha buscado fuente todavía",
}

#: Los motivos cuya causa está en el INSTRUMENTO LEGAL o en el aparato estadístico del
#: Estado evaluado, no en nuestro trabajo pendiente.
#:
#: **Para qué existe esta lista.** El gate de readiness de la plataforma pregunta «¿qué
#: fracción de tu índice tiene dato real?» — una pregunta sobre nuestro cableado. Aplicada a
#: una ley, la misma aritmética responde «¿qué fracción de las metas que la ley se fijó son
#: medibles?», que es una pregunta sobre la LEY. Con la primera lectura, cuanto peor
#: redactada esté la norma menos «listo» parece nuestro producto: el eje quedaba castigado
#: por su propio hallazgo de venta, y su techo real caía por debajo del umbral de
#: publicación. Estos motivos salen del DENOMINADOR de esa cobertura efectiva.
#:
#: **Lo que esta lista NO puede volverse.** Una puerta trasera para esconder deuda propia.
#: Nada de lo que depende de nosotros entra: `pendiente_de_busqueda`, `candidato_descartado`,
#: `candidato_sin_verificar`, `pendiente_de_derivacion` y `fuente_no_procesable` siguen
#: pesando en el denominador aunque duelan. `fuente_no_procesable` en particular es tentadora
#: —el emisor publica en un formato incómodo— y se queda adentro: un formato difícil es
#: trabajo, no una imposibilidad de la ley.
#:
#: Y lo excluido **se LISTA en el informe**, en la sección de brechas. Sacarlo del gate sin
#: nombrarlo sería exactamente el veto silencioso que esta plataforma persigue.
IMPOSIBLES_POR_EL_INSTRUMENTO = frozenset({
    # Lo impide el texto de la ley.
    "sin_meta_legal", "meta_no_interpretable",
    "linea_base_no_reproduce", "termino_legal_sin_fuente",
    # Lo impide el aparato estadístico del Estado evaluado.
    "instrumento_discontinuado", "sin_fuente_conocida", "magnitud_no_publicada",
})

#: Los motivos que dependen de NOSOTROS y siguen contando en el denominador del gate.
#: Se declara explícito, y no como «todo lo demás», para que un motivo nuevo tenga que
#: clasificarse a mano en vez de caer por defecto del lado que conviene.
DEPENDEN_DE_NOSOTROS = frozenset({
    "fuente_no_procesable", "candidato_descartado", "candidato_sin_verificar",
    "pendiente_de_derivacion", "pendiente_de_busqueda",
})


def imposibles_por_el_instrumento(expediente_id: str) -> int:
    """Cuántos indicadores de la ley no puede medir NADIE, por defecto del instrumento."""
    return sum(1 for c in campo(expediente_id).values()
               if c.estado in IMPOSIBLES_POR_EL_INSTRUMENTO)


#: Los que AFIRMAN algo sobre el mundo. Exigen evidencia con fecha, por la misma razón que una
#: obligación `incumplida` la exige: sin ella, «no existe fuente» es una conjetura publicada.
_EXIGEN_EVIDENCIA = frozenset({
    "sin_fuente_conocida", "fuente_no_procesable", "magnitud_no_publicada",
    "instrumento_discontinuado",
    # Estos dos afirman algo sobre la LEY —que su línea base no reproduce, o que su término
    # no lo publica nadie— y es lo más fuerte que este producto dice. Con más razón exigen la
    # medición y la fecha: es la diferencia entre un hallazgo y una opinión sobre el legislador.
    "linea_base_no_reproduce", "termino_legal_sin_fuente",
})

#: Los que se computan del registro y del binding, sin declaración humana. Declararlos a mano
#: sería tener dos verdades sobre el mismo hecho.
_COMPUTADOS = frozenset({
    "sin_meta_legal", "meta_no_interpretable", "candidato_descartado",
    "candidato_sin_verificar",
})

#: Cerrado NO es lo mismo que resuelto. Se publican por separado a propósito.
_PENDIENTES = frozenset({"pendiente_de_busqueda", "pendiente_de_derivacion"})


@dataclass(frozen=True)
class Casilla:
    """El estado declarado de un indicador que no tiene veredicto."""
    indicador: str
    estado: str
    detalle: str
    evidencia: Optional[str] = None
    verificado_el: Optional[str] = None

    @property
    def resuelto(self) -> bool:
        """¿La casilla cierra la pregunta, o solo la declara?"""
        return self.estado not in _PENDIENTES


def _meta_interpretable(ind) -> bool:
    from modules.law_intel.scoring.semaforo import leer_rotulado, leer_umbral

    return any(isinstance(v, (int, float)) or leer_umbral(v) or leer_rotulado(v)
               for v in ind.metas.values())


@lru_cache(maxsize=8)
def _declarado(expediente_id: str) -> Dict[str, Dict[str, Any]]:
    import yaml  # type: ignore[import-untyped]

    ruta = RAIZ / expediente_id.replace("/", "") / "campo.yaml"
    if not ruta.exists():
        return {}
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return {str(m["indicador"]): m for m in (doc.get("motivos") or [])}


def campo(expediente_id: str) -> Dict[str, Casilla]:
    """`{indicador: Casilla}` para todo indicador numerado SIN veredicto disponible.

    Lo que se puede computar se computa; lo que no, se lee de la declaración. Un indicador que
    no cae en ninguna de las dos vías levanta excepción: ese silencio es exactamente lo que
    este módulo existe para impedir.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    dec = _declarado(expediente_id)
    out: Dict[str, Casilla] = {}

    for ind in exp.numerados:
        b = bs.get(ind.id)
        if b is not None and b.cuenta:
            continue                                  # tiene veredicto: no es del campo
        # ── computados ──
        if not ind.metas:
            out[ind.id] = Casilla(ind.id, "sin_meta_legal",
                                  "La ley lo numera y no le fija meta en el articulado.")
            continue
        if not _meta_interpretable(ind):
            out[ind.id] = Casilla(
                ind.id, "meta_no_interpretable",
                f"La meta es de escala '{ind.escala}' y ninguna de las cuatro se puede leer "
                f"como valor, umbral ni escalar rotulado.")
            continue
        if b is not None:
            # Un binding que DECLARA por qué no produce veredicto no tiene una duda abierta:
            # tiene la respuesta. Derivar `candidato_sin_verificar` para todos borraba esa
            # diferencia y hacía que ocho hallazgos se leyeran como ocho tareas pendientes.
            if b.sin_veredicto_por in ("linea_base_no_reproduce", "termino_legal_sin_fuente"):
                estado = b.sin_veredicto_por
            elif b.sin_veredicto_por == "instrumento_discontinuado":
                estado = "instrumento_discontinuado"
            elif b.estado == "descartado":
                estado = "candidato_descartado"
            else:
                estado = "candidato_sin_verificar"
            detalle = (b.motivo_descarte if b.estado == "descartado"
                       else (b.nota_comparabilidad or b.nota)) or "sin detalle en el binding"
            if b.sin_veredicto_por:
                # La evidencia de estos estados ES la nota del binding, que trae la medición.
                # Se pasa explícita para que el validador la exija igual que a las declaradas.
                out[ind.id] = Casilla(ind.id, estado, detalle, detalle,
                                      b.sin_veredicto_desde)
                continue
            out[ind.id] = Casilla(ind.id, estado, detalle)
            continue
        # ── declarados ──
        d = dec.get(ind.id)
        if d is None:
            raise ExpedienteInvalido(
                f"{ind.id}: sin veredicto y sin motivo declarado. Un indicador en silencio "
                f"es indistinguible de uno que nadie miró; declaralo en campo.yaml.")
        out[ind.id] = Casilla(ind.id, d["estado"], d.get("detalle", ""),
                              d.get("evidencia"), d.get("verificado_el"))
    return out


def _validar(casillas: Dict[str, Casilla]) -> None:
    for c in casillas.values():
        if c.estado not in ESTADOS_DEL_CAMPO:
            raise ExpedienteInvalido(
                f"{c.indicador}: estado del campo desconocido '{c.estado}'; admitidos "
                f"{sorted(ESTADOS_DEL_CAMPO)}")
        if c.estado in _COMPUTADOS and c.evidencia:
            raise ExpedienteInvalido(
                f"{c.indicador}: '{c.estado}' se computa del registro y no se declara a mano. "
                f"Dos verdades sobre el mismo hecho terminan divergiendo.")
        if c.estado in _EXIGEN_EVIDENCIA and not ((c.evidencia or "").strip()
                                                  and (c.verificado_el or "").strip()):
            raise ExpedienteInvalido(
                f"{c.indicador}: '{c.estado}' afirma algo sobre el mundo y no trae evidencia "
                f"con fecha. Sin ella el estado es 'pendiente_de_busqueda': decir que una "
                f"fuente no existe sin haberla buscado es publicar una conjetura.")


def resumen(expediente_id: str) -> Dict[str, Any]:
    """La cifra de cierre del campo, con su composición al lado.

    Se publican juntas a propósito. «El campo está cerrado» con todo declarado pendiente es
    cierto y no dice nada; separar lo resuelto de lo pendiente es lo que impide leer la cifra
    al revés.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    casillas = campo(expediente_id)
    _validar(casillas)

    numerados = exp.numerados
    con_veredicto = [i.id for i in numerados if (b := bs.get(i.id)) and b.cuenta]
    por_estado: Dict[str, int] = {}
    for c in casillas.values():
        por_estado[c.estado] = por_estado.get(c.estado, 0) + 1
    pendientes = [c.indicador for c in casillas.values() if not c.resuelto]

    return {
        "total_indicadores_de_la_ley": len(numerados),
        "con_veredicto": len(con_veredicto),
        "declarados_sin_veredicto": len(casillas),
        "en_silencio": len(numerados) - len(con_veredicto) - len(casillas),
        "campo_cerrado": (len(con_veredicto) + len(casillas)) == len(numerados),
        # La composición, que es lo que impide leer «cerrado» como «resuelto».
        "motivo_resuelto": len(casillas) - len(pendientes),
        "pendientes_de_trabajo_nuestro": {"n": len(pendientes), "ids": sorted(pendientes)},
        "por_estado": dict(sorted(por_estado.items())),
        "estados": ESTADOS_DEL_CAMPO,
        "nota": ("«Cerrado» significa que ningún indicador quedó en silencio, no que todos "
                 "tengan respuesta. La composición de arriba dice cuántos tienen un motivo "
                 "definitivo y cuántos esperan trabajo nuestro."),
    }
