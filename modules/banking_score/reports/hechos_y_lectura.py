"""HECHOS Y LECTURA: el código escribe toda cifra y toda relación; el modelo, solo la lectura.

**Por qué existe (2026-09-15).** El Deep Dive 2025 de Banco Múltiple Santa Cruz se regeneró
cinco veces y cada vuelta sacó un error nuevo en una frase con número. La última escribió
«63.49, apenas por encima de donde empezó el año (64.15)»: el cierre estaba POR DEBAJO. Los
guards cazaban la forma anterior y la siguiente vuelta traía otra. El dueño lo resumió: así no
es un producto estable.

**El reparto.** Una sección del año (y del mapa sectorial) se arma con dos partes:

* los HECHOS — :func:`hechos_del_anio` y :func:`hechos_del_mapa` — escritos acá, desde el dato
  servido, con cada relación resuelta en código. Un hecho mal escrito es un bug reproducible
  con un test, no una tirada del modelo;
* la LECTURA — la escribe el modelo desde :func:`contexto_de_la_lectura_del_anio` y
  :func:`contexto_de_la_lectura_del_mapa`, que NO traen números: solo direcciones, rótulos y
  veredictos ya resueltos. Sin números no hay relación entre números que invertir, y un dígito
  que igual aparezca lo repara el motor (`shared.narrative.lectura_sin_cifras`).

:func:`componer` las junta. La estructura del documento (títulos, orden) es del código: los
títulos que escriba el modelo se descartan.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from shared.narrative.lectura_sin_cifras import CLAVE as CLAVE_SIN_CIFRAS

#: Por debajo de esto un movimiento del score no se llama movimiento (mismo umbral que los
#: tramos del año, `anio_por_trimestres.UMBRAL_TRAMO`).
UMBRAL_PUNTOS = 0.5

#: Nombre de cada trimestre por el mes en que cierra.
_TRIMESTRE = {"03": "primer trimestre", "06": "segundo trimestre",
              "09": "tercer trimestre", "12": "cuarto trimestre"}

_VEREDICTO = {"favorable": "mejora", "desfavorable": "deterioro",
              "no_aplica": "sin lectura de mejora o deterioro"}

_ATRIBUCION = {
    "idiosincratico_peor": "deterioro propio: su mora supera a la del resto del sistema en el "
                           "mismo sector",
    "idiosincratico_mejor": "mejor que el resto del sistema en el mismo sector",
    "compartido_con_el_sector": "alineado con el resto del sistema en el mismo sector",
}

#: Un indicador de ÓPTIMO INTERMEDIO no tiene «nivel de referencia» que publicar: la vara es el
#: óptimo. El v6 de Santa Cruz publicó «Cierra por encima del nivel de referencia del modelo,
#: -35.00 %» para la exposición inmobiliaria y «5.00 %» para una cartera sobre depósitos que
#: cerró en 72.81 %. La curva devuelve ese número porque se lo pide, no porque signifique algo.
SENTIDO_DE_OPTIMO_INTERMEDIO = "target"
MOTIVO_OPTIMO_INTERMEDIO = (
    "es un indicador de óptimo intermedio: ni subir ni bajar es mejor por sí solo, porque la "
    "vara es el óptimo y no el nivel del resto")

#: Una clave del contexto entre comillas simples dentro de un motivo. El del óptimo intermedio
#: terminaba en «— leé 'posicion_vs_optimo'», y eso salió impreso en un documento de cliente:
#: vocabulario del sistema, que es justo lo que el banco ya había objetado.
_CLAVE_CITADA = re.compile(r"\s*[—–-]?\s*(?:leé|lee|ver)?\s*'[a-z0-9_]+'", re.IGNORECASE)

#: Por debajo de esto un sector no se narra: con el peso redondeado a cero, «Pesca (0.00 % de su
#: cartera, mora -2.00 pp frente al resto)» ocupa el lugar de un hallazgo sin serlo.
PESO_MINIMO_PARA_NARRAR_PCT = 0.01

#: Lo que la lectura del mapa no puede traer porque su contexto no lo sirve. El v5 de Santa
#: Cruz razonó sobre la dolarización del sector hotelero y sobre la inflación de la canasta y la
#: holgura laboral del territorio, ninguna de ellas servida a esa sección.
MOTIVO_NO_SERVIDO_AL_MAPA = (
    "no se sirve en la lectura del mapa sectorial: interpretá solo la atribución, la tasa, la "
    "cobertura, la garantía y la geografía que trae el contexto")
TERMINOS_VETADOS_DEL_MAPA: Dict[str, str] = {
    "dolariz": MOTIVO_NO_SERVIDO_AL_MAPA,
    "inflación": MOTIVO_NO_SERVIDO_AL_MAPA,
    "canasta": MOTIVO_NO_SERVIDO_AL_MAPA,
    "holgura laboral": MOTIVO_NO_SERVIDO_AL_MAPA,
}

#: Títulos de las partes. Viven acá porque la estructura es del código.
TITULO_LECTURA_DEL_ANIO = "Lectura del año"
TITULO_HECHOS_DEL_ANIO = "Los hechos del año"
TITULO_LECTURA_DEL_MAPA = "Lectura del libro de crédito"
TITULO_HECHOS_DEL_MAPA = "Los hechos del libro de crédito"


# ── Formato ──────────────────────────────────────────────────────────────────

def _es_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


#: Los formateadores reciben `Any`: cada llamada ya pasó por `_es_num`, que mypy no ve.
def _n(v: Any) -> str:
    return f"{float(v):.2f}"


def _s(v: Any) -> str:
    return f"{float(v):+.2f}"


def _pct(v: Any) -> str:
    return f"{float(v):.2f} %"


def _cap(texto: str) -> str:
    return texto[:1].upper() + texto[1:] if texto else texto


def _nombre_de_sector(sector: str) -> str:
    """«Y - CONSUMO DE BIENES Y SERVICIOS» → «Consumo de bienes y servicios»."""
    nombre = str(sector or "").split(" - ", 1)[-1].strip()
    return nombre[:1].upper() + nombre[1:].lower()


_MENORES = {"de", "del", "la", "las", "los", "el", "y", "e"}


def _nombre_de_provincia(provincia: str) -> str:
    palabras = str(provincia or "").lower().split()
    return " ".join(p if i and p in _MENORES else p[:1].upper() + p[1:]
                    for i, p in enumerate(palabras))


def _momento(corte: Any, linea_base: Any) -> str:
    """Un corte del año, dicho como momento: «la línea base» o «el cierre del tercer trimestre»."""
    if str(corte) == str(linea_base):
        return "la línea base"
    return f"el cierre del {_TRIMESTRE.get(str(corte)[5:7], str(corte)[:7])}"


def _en(momento: str) -> str:
    """«al cierre del tercer trimestre», «en la línea base»."""
    return "al " + momento[3:] if momento.startswith("el ") else "en " + momento


# ── Números en letras, para la lectura ───────────────────────────────────────

_UNIDADES = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
             "catorce quince dieciséis diecisiete dieciocho diecinueve veinte").split()
_DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta",
            8: "ochenta", 9: "noventa"}


def _en_letras(n: int) -> str:
    if n <= 20:
        return _UNIDADES[n]
    if n < 30:
        return "veinti" + _UNIDADES[n - 20]
    if n < 100:
        d, u = divmod(n, 10)
        return _DECENAS[d] + ("" if u == 0 else " y " + _UNIDADES[u])
    return str(n)


def sin_digitos(texto: str) -> str:
    """Un rótulo servido a la lectura, sin dígitos: «Morosidad >90 días» → «a más de noventa
    días». El contexto de la lectura no lleva números, y un rótulo con dígitos es justo lo que
    el modelo copiaría y el guard le quitaría."""
    t = str(texto or "")
    t = re.sub(r">\s*(\d+)", lambda m: "a más de " + _en_letras(int(m.group(1))), t)
    t = re.sub(r"top-(\d+)", lambda m: "de los " + _en_letras(int(m.group(1))) + " mayores", t)
    t = re.sub(r"\d+", lambda m: _en_letras(int(m.group(0))), t)
    return t


# ── El AÑO: hechos ───────────────────────────────────────────────────────────

def _etiqueta_de_indicador(clave: str) -> str:
    from modules.banking_score.scoring.indicator_detail import INDICATOR_META
    return str((INDICATOR_META.get(clave) or {}).get("label") or clave)


def _etiqueta_de_dimension(clave: str) -> str:
    from modules.banking_score.reports.pdf_generator import _DIMENSION_LABEL
    return _DIMENSION_LABEL.get(str(clave), str(clave))


def _cierre_y_base(dentro: Dict[str, Any]):
    serie = [p for p in (dentro.get("serie") or []) if _es_num(p.get("score_global"))]
    if len(serie) < 2:
        return None, None
    base = next((p for p in serie if p.get("es_linea_base")), serie[0])
    return base, serie[-1]


def _relacion(diferencia: float) -> str:
    if round(diferencia, 2) == 0:
        return "igual a"
    return "por debajo de" if diferencia < 0 else "por encima de"


def _parrafo_del_camino(dentro: Dict[str, Any]) -> List[str]:
    anio = dentro.get("anio")
    base, cierre = _cierre_y_base(dentro)
    frases: List[str] = []
    if base and cierre:
        dif = round(float(cierre["score_global"]) - float(base["score_global"]), 2)
        rel = _relacion(dif)
        frase = (f"El score global cerró {anio} en {_n(cierre['score_global'])}"
                 + ("" if rel == "igual a" else f", {_n(abs(dif))} puntos {rel}")
                 + (" la línea base" if rel != "igual a" else ", igual a la línea base")
                 + f" ({_n(base['score_global'])}, cierre de {str(base.get('corte'))[:4]})")
        if abs(dif) < UMBRAL_PUNTOS:
            frase += (f"; la diferencia es menor que los {_n(UMBRAL_PUNTOS)} puntos con que "
                      "este informe llama movimiento a un cambio")
        frases.append(frase + ".")
    camino = dentro.get("camino") or {}
    linea_base = dentro.get("linea_base") or (base or {}).get("corte")
    pico, valle = camino.get("pico") or {}, camino.get("valle") or {}
    if _es_num(pico.get("score")) and _es_num(valle.get("score")):
        amplitud = _n(camino.get("amplitud", pico["score"] - valle["score"]))
        alto = _en(_momento(pico["corte"], linea_base))
        bajo = _en(_momento(valle["corte"], linea_base))
        if camino.get("valle_intermedio") and cierre:
            rec = round(float(cierre["score_global"]) - float(valle["score"]), 2)
            frases.append(
                f"El punto más bajo fue {_n(valle['score'])}, {bajo}, y no al cierre del año: "
                f"desde ahí el score recuperó {_n(rec)} puntos. El más alto fue "
                f"{_n(pico['score'])}, {alto}; el rango del año es de {amplitud} puntos.")
        else:
            frases.append(f"El punto más alto fue {_n(pico['score'])}, {alto}, y el más bajo "
                          f"{_n(valle['score'])}, {bajo}: un rango de {amplitud} puntos.")
    tramos = dentro.get("tramos") or []
    if tramos:
        cuenta = {d: sum(1 for t in tramos if t.get("direccion") == d)
                  for d in ("al alza", "a la baja", "estable")}
        frases.append(
            f"Trimestres al alza: {cuenta['al alza']}; a la baja: {cuenta['a la baja']}; "
            f"estables (un cambio menor que {_n(UMBRAL_PUNTOS)} puntos): {cuenta['estable']}.")
    mayor = dentro.get("tramo_que_mas_movio") or {}
    if _es_num(mayor.get("cambio")) and _es_num(mayor.get("cuota_del_movimiento_pct")):
        frases.append(
            f"El {mayor['tramo']} fue el que más movió el score: {_s(mayor['cambio'])} puntos, "
            f"el {float(mayor['cuota_del_movimiento_pct']):.1f} % del movimiento del año medido "
            "en valor absoluto.")
    faltantes = dentro.get("cortes_faltantes") or []
    if faltantes:
        frases.append("Faltan los cortes " + ", ".join(str(c) for c in faltantes)
                      + ": los tramos que dependen de ellos no se miden.")
    return frases


def _vinetas_de_los_trimestres(dentro: Dict[str, Any]) -> List[str]:
    contexto = {c.get("tramo"): c for c in (dentro.get("contexto_de_los_tramos") or [])}
    vinetas = []
    for t in dentro.get("tramos") or []:
        if not (_es_num(t.get("score_global_desde")) and _es_num(t.get("score_global_hasta"))
                and _es_num(t.get("cambio"))):
            continue
        linea = (f"- **{_cap(str(t['tramo']))}**: de {_n(t['score_global_desde'])} a "
                 f"{_n(t['score_global_hasta'])} ({_s(t['cambio'])} puntos, {t.get('direccion')}).")
        c = contexto.get(t.get("tramo")) or {}
        if c.get("rotulo"):
            linea += f" Lectura: {c['rotulo']}."
        rango = c.get("rango_historico_del_mismo_trimestre") or {}
        if _es_num(rango.get("minimo")) and _es_num(rango.get("maximo")):
            linea += (f" En sus {rango.get('n_anios')} años anteriores con dato, el mismo "
                      f"trimestre se movió entre {_s(rango['minimo'])} y {_s(rango['maximo'])} "
                      "puntos.")
        elif c.get("frente_a_su_historia") == "historia insuficiente":
            linea += " No hay historia suficiente del mismo trimestre para juzgarlo."
        ref = c.get("sistema_en_el_mismo_trimestre") or {}
        if _es_num(ref.get("la_mitad_central_del_resto_va_desde")):
            linea += (f" En el mismo trimestre, la mitad central del resto de las instituciones "
                      f"de crédito ({ref.get('n_entidades_del_resto')}) se movió entre "
                      f"{_s(ref['la_mitad_central_del_resto_va_desde'])} y "
                      f"{_s(ref['la_mitad_central_del_resto_va_hasta'])} puntos, con mediana "
                      f"{_s(ref['mediana_del_cambio_del_resto'])}.")
        vinetas.append(linea)
    return vinetas


def _vinetas_de_las_dimensiones(dentro: Dict[str, Any]) -> List[str]:
    vinetas, quietas = [], []
    for fila in dentro.get("tramos_por_dimension") or []:
        movs = [m for m in fila.get("por_tramo") or []
                if _es_num(m.get("cambio")) and abs(float(m["cambio"])) >= UMBRAL_PUNTOS]
        nombre = _etiqueta_de_dimension(fila.get("dimension"))
        if not movs:
            quietas.append(nombre)
            continue
        vinetas.append(f"- **{nombre}**: " + "; ".join(
            f"{_s(m['cambio'])} puntos en el {m['tramo']}" for m in movs) + ".")
    if quietas:
        vinetas.append(f"- Sin movimientos de {_n(UMBRAL_PUNTOS)} puntos o más en ningún "
                       f"trimestre: {', '.join(quietas)}.")
    return vinetas


def _valor(v: float, unidad: str) -> str:
    return _pct(v) if unidad == "%" else (_n(v) if unidad in ("", "índice") else f"{_n(v)} {unidad}")


def _cambio(v: float, unidad: str) -> str:
    return f"{_s(v)} pp" if unidad == "%" else (f"{_s(v)} puntos" if unidad == "índice"
                                                else f"{_s(v)}")


def _motivo_del_veredicto(fila: Dict[str, Any]) -> str:
    """El porqué del veredicto, dicho para un lector y sin nombres de claves del contexto."""
    if str(fila.get("sentido_de_la_escala")) == SENTIDO_DE_OPTIMO_INTERMEDIO:
        return MOTIVO_OPTIMO_INTERMEDIO
    return _CLAVE_CITADA.sub("", str(fila.get("veredicto_por_que") or "")).strip()


def _vinetas_del_balance(dentro: Dict[str, Any]) -> List[str]:
    orden = {"desfavorable": 0, "favorable": 1, "no_aplica": 2}
    filas = [f for f in dentro.get("balance") or []
             if _es_num(f.get("apertura")) and _es_num(f.get("cierre"))]
    moviles = sorted((f for f in filas if f.get("veredicto") != "estable"),
                     key=lambda f: orden.get(str(f.get("veredicto")), 3))
    vinetas = []
    for f in moviles:
        u = str(f.get("unidad") or "")
        optimo_intermedio = (str(f.get("sentido_de_la_escala"))
                             == SENTIDO_DE_OPTIMO_INTERMEDIO)
        linea = (f"- **{_etiqueta_de_indicador(f['indicador'])}**: de {_valor(f['apertura'], u)} "
                 f"a {_valor(f['cierre'], u)} ({_cambio(f['cambio'], u)}): "
                 f"{_VEREDICTO.get(str(f.get('veredicto')), str(f.get('veredicto')))}, porque "
                 f"{_motivo_del_veredicto(f)}.")
        if _es_num(f.get("cambio_de_score")):
            linea += (f" Su score pasó de {_n(f['score_apertura'])} a {_n(f['score_cierre'])} "
                      f"({_s(f['cambio_de_score'])}).")
        # El nivel de referencia solo se publica donde SIGNIFICA algo: en un óptimo intermedio
        # la vara es el óptimo, y ese nivel sale de invertir una curva que no lo representa.
        if (not optimo_intermedio and _es_num(f.get("nivel_de_referencia"))
                and f.get("contra_la_referencia")):
            linea += (f" Cierra {f['contra_la_referencia']} del nivel de referencia del modelo, "
                      f"{_valor(f['nivel_de_referencia'], u)}.")
        vinetas.append(linea)
    estables = [_etiqueta_de_indicador(f["indicador"]) for f in filas
                if f.get("veredicto") == "estable"]
    if estables:
        vinetas.append(f"- Sin movimiento material: {', '.join(estables)}.")
    return vinetas


def _parrafo_de_las_moras(dentro: Dict[str, Any]) -> List[str]:
    bloque = dentro.get("morosidad_estresada") or {}
    cierre = bloque.get("cierre") or {}
    if not cierre:
        return []
    if not cierre.get("disponible"):
        return [str(cierre.get("motivo") or "")] if cierre.get("motivo") else []
    frases = []
    total = cierre.get("morosidad_estresada_de_la_entidad_pct")
    if not _es_num(total):
        return []
    conv = cierre.get("morosidad_convencional_publicada_de_la_entidad_pct")
    frases.append(
        "Al cierre del año, "
        + (f"la mora convencional publicada es {_pct(conv)} y " if _es_num(conv) else "")
        + f"la morosidad estresada que publica la SIB es {_pct(total)} de la cartera.")
    no_ve = cierre.get("lo_que_la_mora_convencional_no_ve_pp")
    if _es_num(no_ve):
        frase = (f"Dentro del cuadro de la estresada, lo que la mora convencional no ve suma "
                 f"{_n(no_ve)} puntos porcentuales")
        mayor = cierre.get("mayor_componente_fuera_de_la_vencida")
        pct_mayor = next((c.get("pct_de_la_cartera_de_la_entidad")
                          for c in cierre.get("componentes_de_la_estresada_de_la_entidad") or []
                          if c.get("componente") == mayor), None)
        if mayor and _es_num(pct_mayor):
            frase += (f"; su mayor componente fuera de la cartera vencida son los {mayor} "
                      f"({_pct(pct_mayor)} de la cartera)")
        frases.append(frase + ".")
    apertura = bloque.get("apertura") or {}
    cambio: Any = bloque.get("cambio_de_la_estresada_de_la_entidad_en_el_anio_pp")
    if _es_num(apertura.get("morosidad_estresada_de_la_entidad_pct")) and _es_num(cambio):
        verbo = ("no cambió" if round(float(cambio), 2) == 0
                 else f"{'subió' if cambio > 0 else 'bajó'} {_n(abs(cambio))} puntos "
                      "porcentuales en el año")
        frases.append(f"A la apertura era {_pct(apertura['morosidad_estresada_de_la_entidad_pct'])}: "
                      f"{verbo}.")
    mediana = cierre.get("mediana_estresada_del_resto_del_sistema_pct")
    if _es_num(mediana):
        posicion = str(cierre.get("posicion_frente_a_la_mediana_del_resto") or "")
        frase = (f"Frente a la mediana del resto de las instituciones de crédito "
                 f"({_pct(mediana)}, {cierre.get('n_entidades_del_resto_del_sistema')} "
                 f"entidades, excluida esta), la entidad está "
                 f"{'en línea con ella' if posicion == 'en línea' else posicion}")
        dif = cierre.get("diferencia_con_la_mediana_del_resto_pp")
        veces = cierre.get("veces_la_mediana_del_resto")
        if _es_num(dif):
            frase += f": {_s(dif)} puntos porcentuales"
            if _es_num(veces):
                frase += f", {_n(veces)} veces esa mediana"
        frases.append(frase + ".")
        if _es_num(apertura.get("veces_la_mediana_del_resto")):
            frases.append(f"A la apertura eran {_n(apertura['veces_la_mediana_del_resto'])} "
                          "veces la mediana de entonces.")
    frases.append("La morosidad estresada no entra al score.")
    return frases


def hechos_del_anio(dentro: Optional[Dict[str, Any]]) -> str:
    """Las frases con cifras del año por dentro, en markdown. ``""`` si no hay serie."""
    dentro = dentro or {}
    bloques: List[str] = []
    camino = _parrafo_del_camino(dentro)
    if camino:
        bloques.append(" ".join(camino))
    trimestres = _vinetas_de_los_trimestres(dentro)
    if trimestres:
        bloques.append("**Cada trimestre, en su contexto**\n\n" + "\n".join(trimestres))
    dimensiones = _vinetas_de_las_dimensiones(dentro)
    if dimensiones:
        bloques.append("**Qué dimensión se movió en cada trimestre**\n\n" + "\n".join(dimensiones))
    balance = _vinetas_del_balance(dentro)
    if balance:
        bloques.append("**Apertura contra cierre**\n\n" + "\n".join(balance))
    moras = _parrafo_de_las_moras(dentro)
    if moras:
        bloques.append("**Las dos moras**\n\n" + " ".join(moras))
    return "\n\n".join(bloques)


# ── El AÑO: lo que lee el modelo ─────────────────────────────────────────────

def _multiplo(veces: Any) -> Optional[str]:
    if not _es_num(veces):
        return None
    if veces < 1:
        return "por debajo de la mediana"
    if veces < 2:
        return "menos del doble"
    if veces < 3:
        return "entre el doble y el triple"
    return "el triple o más"


def contexto_de_la_lectura_del_anio(dentro: Optional[Dict[str, Any]],
                                    entidad: Optional[str]) -> Dict[str, Any]:
    """Lo que el modelo lee para interpretar el año: direcciones, rótulos y veredictos, SIN
    ningún número. Todo lo que diga ya está resuelto acá."""
    dentro = dentro or {}
    base, cierre = _cierre_y_base(dentro)
    linea_base = dentro.get("linea_base") or (base or {}).get("corte")
    ctx: Dict[str, Any] = {"entidad": sin_digitos(entidad or dentro.get("entidad") or ""),
                           CLAVE_SIN_CIFRAS: True}
    if base and cierre:
        dif = float(cierre["score_global"]) - float(base["score_global"])
        ctx["cierre_frente_a_la_linea_base"] = ("sin diferencia" if round(dif, 2) == 0
                                               else "por debajo" if dif < 0 else "por encima")
        ctx["la_diferencia_entre_cierre_y_linea_base_es_un_movimiento"] = (
            abs(dif) >= UMBRAL_PUNTOS)
    camino = dentro.get("camino") or {}
    if camino.get("pico") and camino.get("valle"):
        ctx["punto_mas_alto_del_anio"] = _momento(camino["pico"]["corte"], linea_base)
        ctx["punto_mas_bajo_del_anio"] = _momento(camino["valle"]["corte"], linea_base)
        ctx["el_punto_mas_bajo_fue_intermedio_y_no_el_cierre"] = bool(
            camino.get("valle_intermedio"))
    contexto = {c.get("tramo"): c for c in (dentro.get("contexto_de_los_tramos") or [])}
    ctx["cada_trimestre"] = [
        {"trimestre": t.get("tramo"), "direccion": t.get("direccion"),
         "rotulo": (contexto.get(t.get("tramo")) or {}).get("rotulo"),
         "es_hallazgo": bool((contexto.get(t.get("tramo")) or {}).get("se_destaca"))}
        for t in dentro.get("tramos") or []]
    mayor = dentro.get("tramo_que_mas_movio") or {}
    if mayor.get("tramo"):
        ctx["trimestre_que_mas_movio_el_score"] = {
            "trimestre": mayor["tramo"],
            "direccion": ("al alza" if _es_num(mayor.get("cambio")) and mayor["cambio"] > 0
                          else "a la baja")}
    ctx["hay_cortes_faltantes"] = bool(dentro.get("cortes_faltantes"))
    ctx["dimensiones_que_se_movieron"] = [
        {"dimension": _etiqueta_de_dimension(f.get("dimension")),
         "movimientos": [{"trimestre": m["tramo"],
                          "direccion": "al alza" if m["cambio"] > 0 else "a la baja"}
                         for m in f.get("por_tramo") or []
                         if _es_num(m.get("cambio")) and abs(m["cambio"]) >= UMBRAL_PUNTOS]}
        for f in dentro.get("tramos_por_dimension") or []
        if any(_es_num(m.get("cambio")) and abs(m["cambio"]) >= UMBRAL_PUNTOS
               for m in f.get("por_tramo") or [])]
    ctx["balance_apertura_contra_cierre"] = [
        {"indicador": sin_digitos(_etiqueta_de_indicador(f.get("indicador"))),
         "veredicto": _VEREDICTO.get(str(f.get("veredicto")), "sin movimiento material"),
         "por_que": sin_digitos(str(f.get("veredicto_por_que") or "")),
         **({"cierre_frente_al_nivel_de_referencia_del_modelo": f["contra_la_referencia"]}
            if f.get("contra_la_referencia") else {})}
        for f in dentro.get("balance") or []]
    bloque = dentro.get("morosidad_estresada") or {}
    cierre_e = bloque.get("cierre") or {}
    if cierre_e:
        from modules.banking_score.reports.morosidad_estresada import COMO_LEER_LAS_DOS_MORAS
        estresada: Dict[str, Any] = {"disponible": bool(cierre_e.get("disponible")),
                                     "puntua_en_el_score": False}
        if cierre_e.get("disponible"):
            cambio_e: Any = bloque.get("cambio_de_la_estresada_de_la_entidad_en_el_anio_pp")
            estresada.update({
                "como_leer_las_dos_moras": sin_digitos(COMO_LEER_LAS_DOS_MORAS),
                "posicion_frente_a_la_mediana_del_resto":
                    cierre_e.get("posicion_frente_a_la_mediana_del_resto"),
                "multiplo_de_la_mediana_del_resto":
                    _multiplo(cierre_e.get("veces_la_mediana_del_resto")),
                "mayor_componente_fuera_de_la_vencida":
                    sin_digitos(cierre_e.get("mayor_componente_fuera_de_la_vencida") or ""),
                "en_el_anio": (None if not _es_num(cambio_e) else
                               "sin cambio" if round(float(cambio_e), 2) == 0 else
                               "subió" if cambio_e > 0 else "bajó"),
            })
        ctx["morosidad_estresada"] = estresada
    return ctx


# ── El MAPA: hechos ──────────────────────────────────────────────────────────

def _medida(etiqueta: str, mia: Any, resto: Any, brecha: Any = None,
            de_quien: str = "") -> Optional[str]:
    """«mora de 8.37 % contra 4.18 % del resto del sistema en el mismo sector (+4.19 pp)»."""
    if not (_es_num(mia) and _es_num(resto)):
        return None
    txt = f"{etiqueta} de {_pct(mia)} contra {_pct(resto)}" + (f" {de_quien}" if de_quien else "")
    return txt + (f" ({_s(brecha)} pp)" if _es_num(brecha) else "")


def _narrable(sector: Dict[str, Any]) -> bool:
    """¿Este sector es un hallazgo, o ruido? Una celda que la propia tabla marca como no
    material —o cuyo peso redondea a cero— no se narra: ocupa el lugar de un hallazgo."""
    peso: Any = sector.get("peso_en_su_cartera_pct")
    return (sector.get("material") is not False and _es_num(peso)
            and float(peso) >= PESO_MINIMO_PARA_NARRAR_PCT)


def hechos_del_mapa(mapa: Optional[Dict[str, Any]]) -> str:
    """Las frases con cifras del mapa sectorial de la entidad, en markdown."""
    mapa = mapa or {}
    sectores = mapa.get("sectores") or []
    if not sectores:
        return ""
    bloques: List[str] = []
    peso = {s.get("sector"): s.get("peso_en_su_cartera_pct") for s in sectores}
    conc = mapa.get("concentracion_por_sector") or {}
    frases = [f"La cartera clasificada de la entidad se reparte en {len(sectores)} sectores."]
    top2, top3 = conc.get("top2") or {}, conc.get("top3") or {}
    miembros = top2.get("miembros") or []
    if _es_num(top2.get("pct")) and len(miembros) == 2 and all(_es_num(peso.get(m))
                                                              for m in miembros):
        frases.append(
            f"Los dos mayores —{_nombre_de_sector(miembros[0]).lower()} "
            f"({_pct(peso[miembros[0]])}) y {_nombre_de_sector(miembros[1]).lower()} "
            f"({_pct(peso[miembros[1]])})— reúnen el {_pct(top2['pct'])} de su cartera"
            + (f"; los tres mayores, el {_pct(top3['pct'])}" if _es_num(top3.get("pct")) else "")
            + ".")
    resumen = mapa.get("resumen") or {}
    grupos = (("con_deterioro_propio", "con deterioro propio"),
              ("con_mejor_desempeno_que_su_sector", "con mejor desempeño que el resto del "
                                                    "sistema en el mismo sector"),
              ("alineados_con_su_sector", "alineados con el resto del sistema en el mismo "
                                          "sector"))
    partes = [f"sectores {texto}: {resumen[f'sectores_{g}']}, con el "
              f"{_pct(resumen[f'peso_en_su_cartera_de_los_sectores_{g}_pct'])} de su cartera"
              for g, texto in grupos
              if _es_num(resumen.get(f"sectores_{g}"))
              and _es_num(resumen.get(f"peso_en_su_cartera_de_los_sectores_{g}_pct"))]
    if partes:
        frases.append(_cap("; ".join(partes)) + ".")
    bloques.append(" ".join(frases))

    propios = [s for s in sectores if s.get("atribucion") == "idiosincratico_peor"
               and _narrable(s)]
    if propios:
        vinetas = []
        for s in propios:
            medidas = [m for m in (
                _medida("mora", s.get("mora_pct"), s.get("mora_del_resto_del_sector_pct"),
                        s.get("brecha_de_mora_pp"),
                        de_quien="del resto del sistema en el mismo sector"),
                _medida("tasa", s.get("tasa_promedio_ponderada_pct"),
                        s.get("tasa_del_resto_del_sector_pct"), s.get("spread_de_tasa_pp")),
                _medida("cobertura de provisión sobre la cartera vencida",
                        s.get("cobertura_de_provision_sobre_vencida_pct"),
                        s.get("cobertura_del_resto_del_sector_pct")),
                _medida("garantía sobre la deuda", s.get("garantia_sobre_deuda_pct"),
                        s.get("garantia_del_resto_del_sector_pct"))) if m]
            if not medidas:
                continue
            vinetas.append(f"- **{_nombre_de_sector(s['sector'])}** "
                           f"({_pct(s['peso_en_su_cartera_pct'])} de su cartera): "
                           + "; ".join(medidas) + ".")
        if vinetas:
            bloques.append("**Sectores con deterioro propio**\n\n" + "\n".join(vinetas))
    mejores = [s for s in sectores if s.get("atribucion") == "idiosincratico_mejor"
               and _narrable(s)]
    if mejores:
        bloques.append("**Sectores donde le va mejor que al resto del sistema**: " + "; ".join(
            f"{_nombre_de_sector(s['sector'])} ({_pct(s['peso_en_su_cartera_pct'])} de su "
            f"cartera, mora {_s(s['brecha_de_mora_pp'])} pp frente al resto)"
            if _es_num(s.get("brecha_de_mora_pp")) else
            f"{_nombre_de_sector(s['sector'])} ({_pct(s['peso_en_su_cartera_pct'])})"
            for s in mejores) + ".")

    provincias = [p for p in (mapa.get("provincias") or [])
                  if _es_num(p.get("peso_en_su_cartera_pct"))][:3]
    if provincias:
        vinetas = []
        for p in provincias:
            linea = (f"- **{_nombre_de_provincia(p['provincia'])}**: "
                     f"{_pct(p['peso_en_su_cartera_pct'])} de su cartera")
            if _es_num(p.get("peso_de_la_provincia_en_el_pais_pct")):
                linea += f" contra {_pct(p['peso_de_la_provincia_en_el_pais_pct'])} del crédito del país"
                if _es_num(p.get("sobre_representacion_pp")):
                    linea += f" ({_s(p['sobre_representacion_pp'])} pp)"
            # La mora de referencia es la de TODO el crédito del país en esa provincia (la
            # entidad incluida): se nombra así, no como «el resto».
            m = _medida("mora", p.get("mora_pct"),
                        p.get("mora_del_resto_del_pais_en_la_provincia_pct"),
                        p.get("brecha_de_mora_pp"),
                        de_quien="en todo el crédito del país en esa provincia")
            if m:
                linea += f"; {m}"
            vinetas.append(linea + ".")
        bloques.append("**Dónde presta**\n\n" + "\n".join(vinetas))
    return "\n\n".join(bloques)


# ── El MAPA: lo que lee el modelo ────────────────────────────────────────────

def _frente(mia: Any, resto: Any, umbral: float) -> Optional[str]:
    if not (_es_num(mia) and _es_num(resto)):
        return None
    d = float(mia) - float(resto)
    return "similar" if abs(d) < umbral else ("por encima" if d > 0 else "por debajo")


def contexto_de_la_lectura_del_mapa(mapa: Optional[Dict[str, Any]],
                                    entidad: Optional[str]) -> Dict[str, Any]:
    """Lo que el modelo lee para interpretar el libro de crédito: SIN ningún número."""
    from modules.banking_score.reports.mapa_sectorial import BRECHA_MATERIAL_PP

    mapa = mapa or {}
    sectores = mapa.get("sectores") or []
    tres_mayores = {s.get("sector") for s in sectores[:3]}
    relevantes = [s for s in sectores
                  if s.get("atribucion") in _ATRIBUCION and _narrable(s)
                  and (s.get("sector") in tres_mayores
                       or s.get("atribucion") != "compartido_con_el_sector")]
    resumen = mapa.get("resumen") or {}
    crudos: Dict[str, Any] = {g: resumen.get(f"peso_en_su_cartera_de_los_sectores_{g}_pct")
              for g in ("con_deterioro_propio", "con_mejor_desempeno_que_su_sector",
                        "alineados_con_su_sector")}
    pesos: Dict[str, float] = {g: float(v) for g, v in crudos.items() if _es_num(v)}
    return {
        "entidad": sin_digitos(entidad or mapa.get("entidad") or ""),
        CLAVE_SIN_CIFRAS: True,
        "contra_que_se_compara": ("el resto del sistema en el mismo sector, excluida la "
                                  "entidad"),
        "grupo_de_sectores_de_mayor_peso_en_su_cartera": (
            max(pesos, key=lambda g: pesos[g]).replace("_", " ") if pesos else None),
        "sectores": [
            {"sector": sin_digitos(_nombre_de_sector(s.get("sector"))),
             "es_de_los_tres_mayores_de_su_cartera": s.get("sector") in tres_mayores,
             "atribucion": _ATRIBUCION[s["atribucion"]],
             "su_tasa_frente_al_resto": _frente(s.get("tasa_promedio_ponderada_pct"),
                                                s.get("tasa_del_resto_del_sector_pct"),
                                                BRECHA_MATERIAL_PP),
             "su_cobertura_de_provision_frente_al_resto": _frente(
                 s.get("cobertura_de_provision_sobre_vencida_pct"),
                 s.get("cobertura_del_resto_del_sector_pct"), BRECHA_MATERIAL_PP),
             "su_garantia_frente_al_resto": _frente(s.get("garantia_sobre_deuda_pct"),
                                                    s.get("garantia_del_resto_del_sector_pct"),
                                                    BRECHA_MATERIAL_PP)}
            for s in relevantes],
        "provincias_de_mayor_peso_en_su_cartera": [
            {"provincia": sin_digitos(_nombre_de_provincia(p.get("provincia"))),
             "pesa_en_su_cartera_frente_al_pais": _frente(
                 p.get("peso_en_su_cartera_pct"), p.get("peso_de_la_provincia_en_el_pais_pct"),
                 BRECHA_MATERIAL_PP),
             "su_mora_frente_al_credito_del_pais_en_la_provincia": _frente(
                 p.get("mora_pct"), p.get("mora_del_resto_del_pais_en_la_provincia_pct"),
                 BRECHA_MATERIAL_PP)}
            for p in (mapa.get("provincias") or [])[:3]],
    }


# ── Composición ──────────────────────────────────────────────────────────────

def componer(hechos: str, lectura: str, titulo_lectura: str, titulo_hechos: str) -> str:
    """La sección publicada: primero la lectura, después los hechos que la sostienen.

    La lectura va primero porque el comité lee la conclusión antes que la evidencia. Los
    títulos que haya escrito el modelo se descartan: la estructura es del código."""
    lectura = "\n".join(linea for linea in (lectura or "").split("\n")
                        if not re.match(r"^\s*#{1,6}\s", linea)).strip()
    partes = []
    if lectura:
        partes.append(f"### {titulo_lectura}\n\n{lectura}")
    if hechos:
        partes.append(f"### {titulo_hechos}\n\n{hechos}")
    return "\n\n".join(partes)
