"""Términos que un texto no puede usar porque no describen las cifras servidas.

**El caso que lo motivó.** El índice sectorial (IAI) ubica un sector por su PUESTO entre los
que tienen dato y por su posición en una escala min-max del panel. Ninguna de las dos cosas es
un percentil. El #1047 lo dejó escrito en la plantilla («NUNCA la llames percentil») y en
producción, el 2026-09-15, el informe de agropecuario publicó igual que la exposición macro
«cae en el percentil inferior de la distribución». Una regla solo de plantilla es una
indicación; esto la vuelve una garantía.

**Cómo funciona.** El CONTEXTO del eje declara los términos, con su motivo, bajo
:data:`CLAVE`. El lazo del guard del motor (`claude_engine._generate_guarded`) los busca en el
texto como palabra (con sus flexiones: «percentiles»), regenera con :data:`AVISO` en el mismo
reintento que ya usa para las cifras, y si el término sobrevive quita las ORACIONES que lo
contienen. Quitar una oración falsa empobrece menos que publicarla.

**Por qué en el contexto y no en la plantilla.** La huella de la caché de productos hashea
TODAS las plantillas: tocar una regenera los informes de los diecinueve ejes. El contexto
entra solo en la huella de su eje, así que declarar el veto rota únicamente lo que lo necesita.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Clave del contexto: ``{término: motivo}``. El modelo la lee, y el guard también.
CLAVE = "terminos_que_el_texto_no_puede_usar"

#: Clave del contexto: palabras que EMPIEZAN como un término y no lo son. La raíz alcanza las
#: flexiones —«demanda» veta «demandas» y «demandada»—, pero «demandante» es otra palabra. Una
#: excepción cubre también sus flexiones («demandantes»). Solo se declara donde hace falta.
CLAVE_EXCEPCIONES = "palabras_que_no_son_esos_terminos"

#: El aviso lleva el MOTIVO de cada término: es la instrucción de reescritura, y es propia del
#: eje que lo declara. Antes cerraba con «cita el puesto», que es la del IAI, y cuando el año de
#: banca pasó a este mecanismo esa frase le habría pedido un puesto que su contexto no trae.
AVISO = (
    "\n\nCORRECCIÓN OBLIGATORIA — TÉRMINOS: el texto anterior usó términos que no describen "
    "las cifras que se te sirvieron (ver '" + CLAVE + "' en el contexto):\n{terminos}\n"
    "Reescribe esas oraciones sin esos términos, siguiendo el motivo de cada uno: di lo que la "
    "cifra servida sí sostiene, tal como viene en el contexto y con su población."
)

_LETRA = r"[\wáéíóúüñÁÉÍÓÚÜÑ]"
_ORACION = re.compile(r"(?<=[.!?…])\s+")

#: Una vocal del término acepta su forma con y sin tilde: el modelo a veces la pierde, y el veto
#: no puede depender de eso. La «ñ» NO se pliega: «año» y «ano» son palabras distintas.
_VOCALES = {"a": "aá", "e": "eé", "i": "ií", "o": "oó", "u": "uúü"}
_SIN_TILDE = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u"}
#: Entre palabras, cualquier espacio salvo el salto de línea: `quitar_oraciones_con` trabaja por
#: línea, y detectar lo que no puede quitar dejaría el término publicado.
_ENTRE_PALABRAS = r"[^\S\n]+"


def motivos_declarados(context: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """``{término: motivo}`` tal como lo declara el contexto; una lista sin motivos da ``""``."""
    valor = (context or {}).get(CLAVE)
    if isinstance(valor, dict):
        return {str(t): str(m or "") for t, m in valor.items() if str(t).strip()}
    if isinstance(valor, (list, tuple)):
        return {str(t): "" for t in valor if str(t).strip()}
    return {}


def terminos_declarados(context: Optional[Dict[str, Any]]) -> List[str]:
    return list(motivos_declarados(context))


def aviso(context: Optional[Dict[str, Any]], vetados: List[str]) -> str:
    """El :data:`AVISO` para *vetados*, cada término con el motivo que declaró su contexto."""
    motivos = motivos_declarados(context)
    return AVISO.format(terminos="\n".join(
        f"- «{t}»" + (f": {motivos[t]}" if motivos.get(t) else "") for t in vetados))


def excepciones_declaradas(context: Optional[Dict[str, Any]]) -> List[str]:
    valor = (context or {}).get(CLAVE_EXCEPCIONES)
    if isinstance(valor, (list, tuple)):
        return [str(e) for e in valor if str(e).strip()]
    return []


def _sin_tildes(texto: str) -> str:
    palabras = []
    for palabra in texto.split():
        partes = []
        for letra in palabra:
            base = _SIN_TILDE.get(letra.lower(), letra.lower())
            partes.append(f"[{_VOCALES[base]}]" if base in _VOCALES else re.escape(letra))
        palabras.append("".join(partes))
    return _ENTRE_PALABRAS.join(palabras)


def _patron(termino: str, excepciones: Sequence[str] = ()) -> "re.Pattern[str]":
    # La excepción se descarta en la MISMA posición donde empezaría el término, así que una
    # oración con «demandante» y «demanda» sigue marcada por la segunda.
    no_es = "".join(f"(?!{_sin_tildes(e)})" for e in excepciones)
    return re.compile(rf"(?<!{_LETRA}){no_es}{_sin_tildes(termino)}{_LETRA}*", re.IGNORECASE)


def terminos_en(context: Optional[Dict[str, Any]], texto: str) -> List[str]:
    """Los términos declarados por el contexto que aparecen en *texto*."""
    excepciones = excepciones_declaradas(context)
    return [t for t in terminos_declarados(context)
            if _patron(t, excepciones).search(texto or "")]


def quitar_oraciones_con(texto: str, terminos: List[str],
                         excepciones: Sequence[str] = ()) -> Tuple[str, List[str]]:
    """``(texto sin las oraciones que usan los términos, oraciones quitadas)``.

    Trabaja por línea para no deshacer el formato: los encabezados y las viñetas se conservan,
    y una línea que se queda sin oraciones desaparece en vez de quedar vacía. *excepciones* son
    las del contexto (:func:`excepciones_declaradas`): quitar con otro patrón que el que detectó
    se llevaría oraciones limpias."""
    patrones = [_patron(t, excepciones) for t in terminos]
    quitadas: List[str] = []
    lineas: List[str] = []
    for linea in (texto or "").split("\n"):
        if not any(p.search(linea) for p in patrones):
            lineas.append(linea)
            continue
        partes = _ORACION.split(linea)
        quedan = [s for s in partes if not any(p.search(s) for p in patrones)]
        quitadas += [s.strip() for s in partes if any(p.search(s) for p in patrones)]
        nueva = " ".join(quedan).rstrip()
        if nueva.strip():
            lineas.append(nueva)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip(), quitadas
