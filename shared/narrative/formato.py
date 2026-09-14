"""Cómo se escribe un número en la prosa de un entregable.

**Por qué existe.** El contexto servía flotantes pelados —`6823.5`, `1239546.0`— y cada
generación elegía cómo escribirlos. En un boletín REAL de 16 páginas convivieron tres
convenciones de miles: 76 cifras con coma («21,594»), 8 con punto («6.823.5») y 4 con espacio
(«2 891.62»). La del punto es además ilegible bajo la convención de casa, que es punto
decimal: «6.823.5» se lee como seis coma ochocientos veintitrés.

El saneador corrige el caso ilegible DESPUÉS de escrito, pero no puede corregir «1.239.546»:
reescribirlo podría equivocar la magnitud por mil, y un saneador que arriesga eso es peor que
la inconsistencia que arregla. La única cura que no adivina es no delegar el formato: el
número se sirve ya escrito, como ya se hace con el encabezado de cada país.

Es la misma regla que gobierna el resto del repo — un hecho que se puede computar no se
delega a quien puede copiarlo mal.
"""
from typing import Optional

#: Convención de casa: coma agrupa los miles, punto separa los decimales. Es la que ya aplica
#: `normalize_number_format` sobre la prosa, y la que usan las tablas.
_MILES = ","
_DECIMAL = "."


def numero_para_prosa(valor: Optional[float], unidad: Optional[str] = None) -> Optional[str]:
    """El número tal como debe aparecer escrito. ``None`` si no hay dato.

    Un ausente devuelve ``None`` y NO una cadena vacía ni un cero: en un indicador inverso el
    cero es una afirmación fuerte y falsa, y este proyecto ya lo publicó una vez.

    La precisión sale de la MAGNITUD y de la unidad, no de cuántos decimales trajo el flotante:
    servir «16.944800000000002 %» invita a que el modelo elija dónde cortar, que es la misma
    delegación que este módulo existe para cerrar.
    """
    if valor is None or isinstance(valor, bool):
        return None
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):   # NaN / infinito
        return None

    if (unidad or "").strip() in ("%", "pp", "puntos porcentuales"):
        dec = 2
    elif abs(v) >= 1000:
        # Una cifra grande no necesita decimales para leerse, y arrastrarlos es ruido: lo que
        # se lee mal de «1239546.0» es la falta de agrupación, no el «.0».
        dec = 0 if abs(v - round(v)) < 0.05 else 1
    else:
        dec = 2 if abs(v - round(v)) >= 0.005 else 0

    entero, _, frac = f"{abs(v):,.{dec}f}".partition(".")
    entero = entero.replace(",", _MILES)
    texto = entero + (f"{_DECIMAL}{frac}" if frac else "")
    return f"-{texto}" if v < 0 else texto


#: Nombres de los meses en castellano, para ESCRIBIR una fecha. Los conectores tienen el mapa
#: inverso (nombre → número) para LEER las del emisor; éste es el que faltaba.
MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
            "septiembre", "octubre", "noviembre", "diciembre")


def mes_largo_es(periodo: Optional[str]) -> Optional[str]:
    """``"2026-06"`` → ``"junio de 2026"``. ``None`` ante un período que no es mensual.

    No adivina: un período trimestral o anual no tiene nombre de mes, y darle uno inventaría
    una precisión que el dato no tiene.
    """
    p = str(periodo or "").strip()
    if len(p) != 7 or p[4] != "-" or not (p[:4].isdigit() and p[5:].isdigit()):
        return None
    mes = int(p[5:])
    if not 1 <= mes <= 12:
        return None
    return f"{MESES_ES[mes - 1]} de {p[:4]}"


def fecha_larga_es(iso: Optional[str]) -> Optional[str]:
    """``"2026-07-21"`` → ``"21 de julio de 2026"``. ``None`` ante una fecha ilegible."""
    t = str(iso or "").strip()[:10]
    if len(t) != 10 or t[4] != "-" or t[7] != "-":
        return None
    try:
        anio, mes, dia = int(t[:4]), int(t[5:7]), int(t[8:10])
    except ValueError:
        return None
    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None
    return f"{dia} de {MESES_ES[mes - 1]} de {anio}"


def de_seguido_de(frase: Optional[str]) -> str:
    """«de» antepuesto a *frase*, contraído si empieza con el artículo «el» en minúscula.

    ``"el CNSS"`` → ``"del CNSS"``; ``"SISALRIL"`` → ``"de SISALRIL"``. Solo contrae el ARTÍCULO:
    ``"El Salvador"`` es un nombre propio y queda ``"de El Salvador"``. Salió de un encabezado
    publicado en prod: «la última edición disponible de el CNSS».
    """
    t = str(frase or "").strip()
    if t.startswith("el "):
        return "del " + t[3:]
    return "de " + t


def mes_siguiente(periodo: Optional[str]) -> Optional[str]:
    """``"2026-06"`` → ``"2026-07"``; ``"2026-12"`` → ``"2027-01"``. ``None`` si no es mensual."""
    p = str(periodo or "").strip()
    if len(p) != 7 or p[4] != "-" or not (p[:4].isdigit() and p[5:].isdigit()):
        return None
    anio, mes = int(p[:4]), int(p[5:])
    if not 1 <= mes <= 12:
        return None
    return f"{anio + (mes == 12):04d}-{1 if mes == 12 else mes + 1:02d}"

