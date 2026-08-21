"""Extractor del registro de indicadores desde el articulado de una ley, leído por CELDAS.

Herramienta de mantenimiento: produce el `indicadores.csv` de un expediente. No participa
de la ruta de servicio — prod sirve el CSV ya extraído y verificado.

**Por qué esta versión existe.** La primera leía la salida de `pdftotext -layout`, que aplana
el PDF a una grilla de caracteres y descarta los límites de celda. Reconstruirlos a mano costó
cinco defectos, y los cinco eran del INPUT, no de la lógica:

  · el `4.0` de la columna 2030 aparecía antes que la línea base y quedaba como línea base;
  · `2. 35` con espacio tipográfico hacía creer que la ley se saltea un indicador;
  · la fila de valores de 3.9 iba ARRIBA de su renglón de id, y el indicador salía «sin meta»;
  · las filas PEFA no traen números, así que 3.8 se comía la fila numérica de 3.9;
  · en el Eje 4 los encabezados `Año` y `Valor` están pegados y la línea base se perdía.

`pdfplumber` conserva la caja de cada palabra y devuelve la tabla como celdas. La columna pasa
a ser un ÍNDICE en vez de una distancia, y las cinco fallas se vuelven imposibles de expresar.
No hace falta visión: la estructura ya está en el PDF, lo que fallaba era tirarla al leerlo.
"""
import json
import re
import sys

ANIOS = ("2015", "2020", "2025", "2030")
# El id puede venir pegado al nombre (`2.21Esperanza`) o con un espacio tras el punto (`2. 35`).
ID = re.compile(r"^([1-4])\.\s?(\d{1,2})(?=[^\d.]|$)")
SUBFILA = re.compile(r"^(Masculino|Femenino|Juzgados[^,]*|Cortes de apelación penal)\s*$")
ORD_ = re.compile(r"^[A-D][+-]?$")
# La coma es separador de MILES en este documento y el punto es decimal (`4,460` frente a
# `6,351.8`). Leerla como decimal publicó el Ingreso Nacional Bruto per cápita como 4,46
# dólares en vez de 4.460 — mil veces menos, y con la forma de un dato plausible.
MILES = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
# `421 (Nivel I)` es un valor con su banda al lado; `< 4%` es un UMBRAL, no un valor —
# publicarlo como 4.0 afirma que la meta es llegar a 4 cuando es quedar por debajo.
CON_ETIQUETA = re.compile(r"^(-?\d[\d,]*(?:\.\d+)?)\s*\(([^)]+)\)$")
# Las dos notaciones: el PDF trae `≥` y una transcripción a mano escribe `>=`. El lector del
# semáforo entiende las dos, y este clasificador tiene que entender las mismas o una meta
# queda clasificada de una forma y leída de otra.
UMBRAL = re.compile(r"^(<=|>=|[<>≤≥])\s*-?\d")
# Una celda con varias métricas apiladas (2.17: Matemáticas / Lectura / Ciencias) no tiene
# UN valor. Elegir la primera publica una serie y esconde dos.
COMPUESTA = re.compile(r"(Matem|Lectura|Ciencias)\s*:")


def _num(txt):
    """Número de una celda, o None. Devuelve también la etiqueta si venía con una."""
    if MILES.match(txt):
        return float(txt.replace(",", "")), None
    if NUM.match(txt):
        return float(txt), None
    if (m := CON_ETIQUETA.match(txt)):
        return float(m.group(1).replace(",", "")), m.group(2)
    return None, None


def _norm(c):
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()


def _cols(tabla):
    """Índices de las columnas de datos, leídos del renglón de encabezado.

    Se localizan por el rótulo del año en vez de asumir posiciones: las cuatro tablas no
    tienen el mismo número de columnas ni el mismo orden de `Unidad / Escala`.
    """
    for fila in tabla:
        celdas = [_norm(c) for c in fila]
        if all(a in celdas for a in ANIOS) and "Valor" in celdas:
            col = {a: celdas.index(a) for a in ANIOS}
            col["base_valor"] = celdas.index("Valor")
            col["base_anio"] = celdas.index("Año") if "Año" in celdas else col["base_valor"] - 1
            return col
    return None


def _escala(vals, metas):
    txt = [v for v in vals if isinstance(v, str)]
    if not metas:
        return "sin_meta"
    if any(v == "compuesta" for v in txt):
        return "compuesta"          # varias series apiladas en una celda (2.17)
    if any(UMBRAL.match(v) for v in txt):
        return "umbral"             # «< 4%»: acota, no fija un punto
    if any(ORD_.match(v) for v in txt):
        return "ordinal"            # bandas PEFA A-D
    if txt:
        return "redactada"          # «Pertenecer al nivel II»
    return "numerica"


def _valor(txt):
    """Valor de una celda, o `None` si no lo hay.

    Lo que NO es un número se devuelve como texto en vez de forzarse: un umbral (`< 4%`), una
    banda PEFA (`B+`) y una meta en palabras («Pertenecer al nivel II») son metas reales, y
    convertirlas a float afirma algo distinto de lo que dice la ley.
    """
    txt = txt.replace("%", "").replace("\xa0", " ").strip()
    if not txt:
        return None
    if ORD_.match(txt):
        return txt
    if COMPUESTA.search(txt):
        return "compuesta"
    if UMBRAL.match(txt):
        return txt
    n, _ = _num(txt)
    if n is not None:
        return n
    # Meta redactada («Pertenecer al nivel II», «Se cumple con tiempos establecidos»).
    return txt if len(txt) > 3 and any(c.isalpha() for c in txt) else None


def parsear(ruta):
    # Import perezoso: `pdfplumber` solo hace falta para RE-EXTRAER el registro desde el PDF,
    # que es mantenimiento y no ruta de servicio. Prod sirve el CSV del expediente y no
    # necesita la dependencia; los tests de las funciones puras tampoco.
    import pdfplumber

    filas, vistos = [], set()
    with pdfplumber.open(ruta) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                col = _cols(tabla)
                if not col:
                    continue                      # no es una tabla de indicadores
                for cruda in tabla:
                    fila = _leer(cruda, col, filas)
                    if fila and fila["id"] not in vistos:
                        vistos.add(fila["id"])
                        filas.append(fila)
    return filas


def _leer(cruda, col, previas):
    celdas = [_norm(c) for c in cruda]
    if max(col.values()) >= len(celdas):
        return None
    etiqueta = celdas[0]
    m, sub = ID.match(etiqueta), SUBFILA.match(etiqueta)
    if not m and not sub:
        return None

    anio = celdas[col["base_anio"]]
    base = _valor(celdas[col["base_valor"]])
    metas = {a: v for a in ANIOS if (v := _valor(celdas[col[a]])) is not None}
    # Un indicador SIN valores propios sigue existiendo: 1.5 y 1.6 solo desagregan en
    # sub-filas y 1.7 fija su meta en palabras. Se emiten declarados, no descartados —
    # omitirlos dejaba el registro en 81 de 90 pareciendo completo.
    if sub:
        if not previas or base is None:
            return None
        padre = previas[-1]["subfila_de"] or previas[-1]["id"]
        ident, nombre, subfila_de = f"{padre}·{etiqueta}", etiqueta, padre
    else:
        ident = f"{m.group(1)}.{m.group(2)}"
        nombre = etiqueta[m.end():].strip(" .")
        subfila_de = None

    vals = [base, *metas.values()]
    return {
        "id": ident, "eje": int(ident[0]), "nombre": nombre, "subfila_de": subfila_de,
        "base_anio": int(anio) if re.fullmatch(r"(19|20)\d\d", anio) else None,
        "base_anio_texto": anio if not re.fullmatch(r"(19|20)\d\d", anio) else None,
        "base_valor": base, "metas": metas,
        # La escala se nombra por lo que la meta ES. Meter en «ordinal» una banda PEFA, un
        # umbral («< 4%») y una meta en palabras las vuelve comparables entre sí, y no lo son:
        # un umbral acota, una banda ordena y una meta redactada ni siquiera se puede restar.
        "escala": _escala(vals, metas),
        # Las metas 2015 y 2025 de los indicadores de aprendizajes (2.12-2.16) están EN
        # PALABRAS. Publicar dos de cuatro sin decirlo deja el registro pareciendo completo
        # justo donde no lo está.
        "anios_sin_meta_numerica": [a for a in ANIOS if a not in metas] if metas else [],
    }


if __name__ == "__main__":
    filas = parsear(sys.argv[1])
    json.dump(filas, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"filas: {len(filas)}")
