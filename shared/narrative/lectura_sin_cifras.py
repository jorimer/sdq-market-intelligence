"""Una LECTURA que no lleva cifras: la mitad que el modelo escribe en «hechos y lectura».

**El caso que lo motivó.** El Deep Dive 2025 de Banco Múltiple Santa Cruz se regeneró cinco
veces el 2026-09-15 y cada vuelta trajo un error nuevo en una frase con número: el sujeto del
score, «duplica» sobre 1,9 veces, «el 75 %» de la mitad central y, al final, «63.49, apenas por
encima de donde empezó el año (64.15)», que es por debajo. Cada guard cazaba la forma anterior
y la siguiente vuelta traía otra: un guard de FORMA siempre llega tarde.

**La cura es de diseño.** Las frases con cifras y relaciones las escribe el código desde el
dato servido; el modelo recibe un contexto sin números y escribe solo la interpretación. Un
modelo que no ve números no puede invertir una relación entre ellos, y si igual escribe un
dígito, este mecanismo lo detecta sin ambigüedad: cualquier dígito es una falta.

**Cómo funciona.** El contexto declara :data:`CLAVE` en verdadero. El lazo del guard del motor
(`claude_engine._generate_guarded`) busca dígitos en el texto, regenera con :data:`AVISO` en el
mismo reintento que usa para las cifras y los términos, y si el dígito sobrevive quita las
ORACIONES que lo llevan. El juicio es mecánico: no depende de un juez ni de una forma.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: Clave del contexto. El modelo la lee (la plantilla la nombra) y el guard también.
CLAVE = "la_lectura_no_lleva_cifras"

AVISO = (
    "\n\nCORRECCIÓN OBLIGATORIA — CIFRAS EN LA LECTURA: el texto anterior escribió cifras "
    "('" + CLAVE + "' está en verdadero):\n{cifras}\n"
    "Las cifras y sus relaciones ya las escribe el sistema en el mismo informe. Reescribe esas "
    "oraciones SIN números, sin años y sin fechas: di la interpretación con las direcciones, "
    "rótulos y veredictos del contexto, y nombra los trimestres por su nombre."
)

#: Un «token» con al menos un dígito: «63.49», «52,6», «2025», «T2», «+0.66».
_CIFRA = re.compile(r"[^\s()\[\]«»\"]*\d[^\s()\[\]«»\"]*")
_ORACION = re.compile(r"(?<=[.!?…])\s+")


def _limpiar(token: str) -> str:
    return token.rstrip(".,;:'").lstrip("+-−'") or token


def cifras_en(context: Optional[Dict[str, Any]], texto: str) -> List[str]:
    """Las cifras de *texto* si el contexto declara que la lectura no las lleva; si no, ``[]``."""
    if (context or {}).get(CLAVE) is not True:
        return []
    return [_limpiar(t) for t in _CIFRA.findall(texto or "")]


def aviso(cifras: List[str]) -> str:
    return AVISO.format(cifras="\n".join(f"- «{c}»" for c in cifras))


def quitar_oraciones_con_cifras(texto: str) -> Tuple[str, List[str]]:
    """``(texto sin las oraciones que llevan un dígito, oraciones quitadas)``.

    Trabaja por línea, como `terminos_vetados.quitar_oraciones_con`: una línea que se queda sin
    oraciones desaparece y el resto del formato se conserva."""
    quitadas: List[str] = []
    lineas: List[str] = []
    for linea in (texto or "").split("\n"):
        if not re.search(r"\d", linea):
            lineas.append(linea)
            continue
        partes = _ORACION.split(linea)
        quedan = [s for s in partes if not re.search(r"\d", s)]
        quitadas += [s.strip() for s in partes if re.search(r"\d", s)]
        nueva = " ".join(quedan).rstrip()
        if nueva.strip():
            lineas.append(nueva)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip(), quitadas
