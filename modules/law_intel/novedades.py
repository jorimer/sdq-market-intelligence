"""Lo que entró este mes al marco normativo de la ley evaluada (Fase 8, vía JurisAI).

**Por qué es texto EN VIVO y no narrativa.** La lista cambia cuando JurisAI ingiere una norma, no
cuando cambia el expediente. Si viajara en el payload, la huella de la caché del informe entero
rotaría con cada ingesta; si se escribiera en la narrativa, quedaría congelada en una caché sin
TTL. Se redacta en CÓDIGO al servir (`completar_en_vivo`) sobre un marcador que la narrativa deja.

**El veredicto del mes se computa una vez** (`veredicto_del_mes`) y lo leen la sección y la señal
del panel del operador, para que no puedan contradecirse. La cobertura la declara el emisor en
`alcance.vacio_es_concluyente`: sus corridas de ingesta cubrieron —o no— el mes completo en todas
las fuentes. Cuatro estados:

* ``completo`` — hubo normas que citan la ley y la cobertura es concluyente: la lista es TODO lo
  que entró. Se listan con su fecha de ingreso al corpus.
* ``sin_novedades`` — no hubo, y el vacío es concluyente: se publica la negativa, con esa palabra.
* ``indeterminado`` — la cobertura NO es concluyente, haya o no normas. Sin normas, se dice que no
  se puede afirmar que no las hubo; con normas, se listan y se declara que la lista puede no estar
  completa. Hasta el 2026-09-14 este segundo caso salía como una lista sin salvedad —agosto de 2026
  en prod, con cuatro resoluciones— y se leía como todo lo que había entrado.
* ``no_consultado`` — la fuente no respondió: la sección no afirma nada.

Callar un mes indeterminado haría pasar un hueco de la ingesta por un mes sin novedades (o por una
lista completa), y eso es una afirmación sobre el Estado.

Se filtra por fecha de INGESTA, no de promulgación: una norma vieja recién incorporada es novedad.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

SECCION_NOVEDADES = "novedades_normativas"

#: Los estados del veredicto de un mes. Ver el docstring del módulo.
COMPLETO = "completo"
SIN_NOVEDADES = "sin_novedades"
INDETERMINADO = "indeterminado"
NO_CONSULTADO = "no_consultado"

#: Lo que la narrativa deja en la sección para que `completar_en_vivo` lo reemplace al servir. Si
#: alguna vez llega al cliente sin reemplazar, dice la verdad: no se pudo consultar.
MARCADOR_NOVEDADES = ("La consulta a la base normativa sobre lo que entró este mes al marco de "
                      "esta ley no se pudo completar al generar esta entrega.")

FRASE_CONCLUYENTE = ("En {mes} no entró a la base normativa ninguna norma que cite la {norma}, y "
                     "esto es concluyente: todas las fuentes normativas se revisaron sobre el mes "
                     "completo.")
FRASE_NO_CONCLUYENTE = ("En {mes} la base normativa no registra normas nuevas que citen la "
                        "{norma}, pero no se puede afirmar que no las hubo: la revisión de las "
                        "fuentes no cubrió el mes completo, así que {mes} queda indeterminado.")
#: La salvedad de un mes CON normas cuya cobertura no es concluyente. Va debajo de la lista.
FRASE_LISTA_INDETERMINADA = ("La lista puede no estar completa: la revisión de las fuentes no "
                             "cubrió el mes completo, así que {mes} queda indeterminado.")
FRASE_NO_CONSULTABLE = ("No se pudo consultar la base normativa sobre {mes}, así que esta entrega "
                        "no afirma nada sobre lo que entró al marco de la {norma} ese mes.")

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")
_RE_NORMA = re.compile(r"^\s*(ley|decreto|reglamento|resoluci[oó]n)\s+(?:n[oº°]\.?\s*)?(\d+-\d+)\s*$",
                       re.IGNORECASE)


def referencia_de_norma(norma: str) -> Optional[str]:
    """«Ley 1-12» → `ley:1-12`. Sin forma reconocible, `None`: no se inventa una referencia."""
    m = _RE_NORMA.match(str(norma or ""))
    if not m:
        return None
    tipo = m.group(1).lower().replace("ó", "o")
    return f"{tipo}:{m.group(2)}"


def ventana_del_mes_cerrado(hoy: date) -> Tuple[date, date]:
    """El último mes COMPLETO antes de *hoy*: el mes en curso todavía se está ingiriendo."""
    fin = hoy.replace(day=1) - timedelta(days=1)
    return fin.replace(day=1), fin


def _mes_en_prosa(d: date) -> str:
    return f"{_MESES[d.month - 1]} de {d.year}"


def veredicto_del_mes(respuesta: Optional[Dict[str, Any]]) -> str:
    """El estado del mes según la cobertura que declara el emisor. `None` = no respondió.

    La cobertura decide, no la presencia de resultados: una lista con normas sobre un mes que el
    emisor no cubrió entero es tan indeterminada como un mes vacío en esa misma condición.
    """
    if respuesta is None:
        return NO_CONSULTADO
    if not bool((respuesta.get("alcance") or {}).get("vacio_es_concluyente")):
        return INDETERMINADO
    return COMPLETO if respuesta.get("resultados") else SIN_NOVEDADES


def texto_de_novedades(respuesta: Optional[Dict[str, Any]], *, desde: date, norma: str) -> str:
    """Prosa determinista de la sección. `respuesta=None` = la fuente no respondió."""
    mes = _mes_en_prosa(desde)
    estado = veredicto_del_mes(respuesta)
    if respuesta is None:
        return FRASE_NO_CONSULTABLE.format(mes=mes, norma=norma)
    resultados = list(respuesta.get("resultados") or [])
    if not resultados:
        return (FRASE_CONCLUYENTE if estado == SIN_NOVEDADES
                else FRASE_NO_CONCLUYENTE).format(mes=mes, norma=norma)
    lineas = [f"En {mes} entraron a la base normativa {len(resultados)} "
              f"{'norma' if len(resultados) == 1 else 'normas'} que citan la {norma}:"]
    for r in resultados:
        tipo = str(r.get("tipo") or "norma").capitalize()
        numero = r.get("numero") or "s/n"
        titulo = str(r.get("titulo") or "").strip().rstrip(".")
        ingreso = r.get("fecha_de_ingesta")
        lineas.append(f"- {tipo} {numero}" + (f" — {titulo}" if titulo else "")
                      + (f" (ingresó el {ingreso})" if ingreso else ""))
    if respuesta.get("truncado"):
        lineas.append("La lista está recortada: la base registra más normas que las mostradas.")
    if estado == INDETERMINADO:
        lineas.append(FRASE_LISTA_INDETERMINADA.format(mes=mes))
    return "\n".join(lineas)


def consultar_novedades(db: Any, *, norma: str, hoy: Optional[date] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """`(texto, respuesta)` de la sección para el mes cerrado. Nunca lanza."""
    from shared.data.jurisai_client import JurisAIUnavailable, novedades
    from shared.settings.service import get_sector_api_base_url, get_sector_api_key

    desde, hasta = ventana_del_mes_cerrado(hoy or date.today())
    ref = referencia_de_norma(norma)
    if ref is None:
        return FRASE_NO_CONSULTABLE.format(mes=_mes_en_prosa(desde), norma=norma), None
    try:
        respuesta = novedades(get_sector_api_base_url(db, "jurisai"), get_sector_api_key(db, "jurisai"),
                              desde=desde.isoformat(), hasta=hasta.isoformat(), cita_a=ref)
    except JurisAIUnavailable:
        respuesta = None
    return texto_de_novedades(respuesta, desde=desde, norma=norma), respuesta
