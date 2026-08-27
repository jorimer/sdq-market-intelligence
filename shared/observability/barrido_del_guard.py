"""Barrido del guard sobre la prosa que el modelo YA escribió en producción.

**El hueco que cierra, y de dónde salió.** El 2026-08-26 cerré la familia «un umbral
prospectivo no es una cita» y la validé contra las frases que ya habían fallado. Al día
siguiente el modelo escribió *«la cobertura **puede cruzar** por debajo del 100 %»* y la regla
no la reconoció: mismo verbo, otra forma. El infinitivo no se me ocurrió, y no tenía por qué —
**el que escribe estas frases es el modelo, no yo**, y validar una regla contra mi propia
imaginación es validarla contra la fuente equivocada.

El dueño lo dijo con precisión: no puede ser que tenga que correr cada entidad para que
aparezca la siguiente omisión. Cada hallazgo así le cuesta una generación real —unos cien
segundos y varias llamadas al modelo— y aparece de a uno.

**Lo que este módulo usa, y estaba ahí desde siempre.** `ProductReportCache` guarda en
Postgres el texto generado de cada informe, sin caducidad: un corpus real de prosa de este
producto. Contra ese corpus la regla se puede barrer **sin generar nada** — cero llamadas al
modelo, cero espera.

**Lo que el barrido responde:** de todas las cifras con unidad que el modelo escribió, ¿cuáles
quedan FUERA de la regla prospectiva, y con qué palabras las introdujo? Las construcciones se
agrupan por las palabras que preceden a la cifra y se ordenan por frecuencia. Una forma
irrealis que la regla no conoce aparece ahí arriba, con su frase, antes de que mate un informe.

**Lo que a propósito NO hace: emitir un veredicto de «sin respaldo».** Eso exige el contexto
de la SECCIÓN, y el contexto es justo lo que la caché no guarda. Juzgar contra
`snapshot.payload` produciría falsos positivos que el motor nunca produjo — es el defecto de
«el guard corría con dos contextos», que ya costó tres informes reales. Acá se barre el
LENGUAJE, que es donde estaba mi hueco, y no se finge un veredicto que no se puede sostener.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.narrative.numeric_guard import _CLAIM_UNIT, _es_umbral_prospectivo

#: Tope de informes leídos. Es una consulta de consola, no un export.
MAX_INFORMES = 1500

#: Ventana previa a la cifra. La MISMA que usa la regla, a propósito: barrer un tramo
#: distinto del que la regla mira daría hallazgos que la regla nunca podría haber usado.
from shared.narrative.numeric_guard import _VENTANA_PROSPECTIVA  # noqa: E402

#: Formas verbales que en español introducen algo que TODAVÍA NO PASÓ. Se buscan por
#: morfología y no por lista de verbos: el hueco de ayer fue una FORMA que no se me ocurrió,
#: así que buscar por lista volvería a preguntarle a mi imaginación.
#:
#: - infinitivo (`cruzar`, `superar`) — la forma que faltaba, y la más común tras un modal;
#: - futuro (`cruzará`, `presionarán`);
#: - condicional (`cruzaría`, `tendería`);
#: - modales, que por sí solos NO eximen pero sí SEÑALAN dónde mirar.
#: El ACENTO es lo que separa el futuro y el condicional de un sustantivo: «cruzará» y
#: «ubicaría» llevan tilde; «cobertura», «estructura» y «factura» no. Sin exigirlo, el
#: ranking se llena de sustantivos y la señal se pierde entre el ruido.
_FORMA_IRREALIS = re.compile(
    r"\b(\w{3,}(?:ar|er|ir)|\w{2,}(?:r[áí]a?n?|r[íi]an)|"
    r"puede[n]?|podr[ií]an?|pudiera[n]?|deber[ií]an?|tender[ií]an?)\b", re.I)

_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def _candidatas(texto: str, pos: int) -> Tuple[List[str], str]:
    """Formas irrealis en la ventana previa a la cifra, y el fragmento legible.

    Se devuelven las formas, no la frase entera: agrupar por la frase daría una fila por
    informe y ninguna señal. Agrupando por la FORMA, un infinitivo que la regla no conoce
    sube solo al tope del ranking.
    """
    previo = texto[max(0, pos - _VENTANA_PROSPECTIVA):pos]
    formas = [m.group(1).lower() for m in _FORMA_IRREALIS.finditer(previo)]
    ini = max(0, pos - 80)
    fin = min(len(texto), pos + 40)
    fragmento = (("…" if ini else "") + texto[ini:fin].replace("\n", " ")
                 + ("…" if fin < len(texto) else ""))
    return formas, fragmento


def barrido_del_guard(db: Session, sector: Optional[str] = None,
                      limite: int = MAX_INFORMES) -> Dict[str, Any]:
    """Corre la regla prospectiva sobre el corpus ya generado. Sin llamadas al modelo."""
    from shared.products.models import ProductReportCache

    q = db.query(ProductReportCache)
    if sector:
        q = q.filter(ProductReportCache.sector_key == sector)
    filas = q.limit(max(1, min(limite, MAX_INFORMES))).all()

    total_cifras = 0
    reconocidas = 0
    sin_forma_irrealis = 0
    fuera: Dict[str, Dict[str, Any]] = {}
    informes_leidos = 0
    secciones_leidas = 0

    for fila in filas:
        narrativas: Dict[str, Any] = (fila.narratives
                                      if isinstance(fila.narratives, dict) else {})
        if not narrativas:
            continue
        informes_leidos += 1
        for seccion, texto in narrativas.items():
            if not isinstance(texto, str) or not texto:
                continue
            secciones_leidas += 1
            for m in _CLAIM_UNIT.finditer(texto):
                total_cifras += 1
                if _es_umbral_prospectivo(texto, m.start()):
                    reconocidas += 1
                    continue
                formas, fragmento = _candidatas(texto, m.start())
                if not formas:
                    # Ninguna forma irrealis cerca: es una cita, y debe quedar fuera de la
                    # regla. Se CUENTA para que el total cuadre — un residuo sin explicar
                    # invita a suponer que el barrido no leyó todo.
                    sin_forma_irrealis += 1
                    continue
                for f in set(formas):
                    e = fuera.setdefault(f, {
                        "forma": f, "veces": 0, "ejemplo": fragmento,
                        "secciones": set(), "sectores": set()})
                    e["veces"] += 1
                    e["secciones"].add(str(seccion))
                    e["sectores"].add(str(fila.sector_key))

    ranking = sorted(fuera.values(), key=lambda e: -int(e["veces"]))
    for e in ranking:
        e["secciones"] = sorted(e["secciones"])[:6]
        e["sectores"] = sorted(e["sectores"])[:6]

    return {
        "sector": sector,
        "informes_leidos": informes_leidos,
        "secciones_leidas": secciones_leidas,
        "cifras_con_unidad": total_cifras,
        "reconocidas_como_umbral": reconocidas,
        "fuera_de_la_regla_con_forma_irrealis": sum(1 for _ in ranking),
        "fuera_sin_forma_irrealis": sin_forma_irrealis,
        "formas": ranking[:60],
        "truncado": len(filas) >= min(limite, MAX_INFORMES),
        "como_leerlo": (
            "Cada fila es una FORMA VERBAL que apareció cerca de una cifra que la regla "
            "prospectiva NO reconoció. Muchas serán inocentes (un infinitivo suelto en una "
            "frase factual). Lo que se busca es la que describe un CRUCE DE NIVEL: "
            "«cruzar», «superar», «descender» tras un modal o en condicional — una de ésas "
            "arriba del ranking es un informe que va a morir vetado. `fuera_sin_forma_"
            "irrealis` son las citas normales y deben ser la mayoría. Esto NO dice si una "
            "cifra tiene respaldo: eso exige el contexto de la SECCIÓN, que la caché no "
            "guarda, y fingirlo repetiría el defecto de juzgar con el contexto equivocado."),
    }
