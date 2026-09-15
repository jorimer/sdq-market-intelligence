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
from typing import Any, Dict, List, Optional, Tuple

#: Clave del contexto: ``{término: motivo}``. El modelo la lee, y el guard también.
CLAVE = "terminos_que_el_texto_no_puede_usar"

AVISO = (
    "\n\nCORRECCIÓN OBLIGATORIA — TÉRMINOS: el texto anterior usó {terminos}, que no "
    "describe(n) las cifras que se te sirvieron (ver '" + CLAVE + "' en el contexto). "
    "Reescribe esas oraciones sin esos términos: si hablas de la posición, cita el puesto tal "
    "como viene en el contexto, con su población."
)

_LETRA = r"[\wáéíóúüñÁÉÍÓÚÜÑ]"
_ORACION = re.compile(r"(?<=[.!?…])\s+")


def terminos_declarados(context: Optional[Dict[str, Any]]) -> List[str]:
    valor = (context or {}).get(CLAVE)
    if isinstance(valor, dict):
        return [str(t) for t in valor if str(t).strip()]
    if isinstance(valor, (list, tuple)):
        return [str(t) for t in valor if str(t).strip()]
    return []


def _patron(termino: str) -> "re.Pattern[str]":
    return re.compile(rf"(?<!{_LETRA}){re.escape(termino)}{_LETRA}*", re.IGNORECASE)


def terminos_en(context: Optional[Dict[str, Any]], texto: str) -> List[str]:
    """Los términos declarados por el contexto que aparecen en *texto*."""
    return [t for t in terminos_declarados(context) if _patron(t).search(texto or "")]


def quitar_oraciones_con(texto: str, terminos: List[str]) -> Tuple[str, List[str]]:
    """``(texto sin las oraciones que usan los términos, oraciones quitadas)``.

    Trabaja por línea para no deshacer el formato: los encabezados y las viñetas se conservan,
    y una línea que se queda sin oraciones desaparece en vez de quedar vacía."""
    patrones = [_patron(t) for t in terminos]
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
