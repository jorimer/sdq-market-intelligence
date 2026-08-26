"""Catálogo de trámites del Estado dominicano (Portal Único de Servicios, gob.do).

El portal publica **710 trámites de 91 instituciones**, cada uno con su institución, su
área, sus canales de atención, su costo, sus requisitos y cuántas veces se consultó. Esa es
la base: hoy no existe en ningún lado un inventario de los servicios del Estado que se pueda
cruzar por institución.

**Y trae una medición que el catálogo no sabe que tiene.** La Resolución 142-2024 del MAP
—la guía de identificación, estandarización y registro de trámites— exige que cada ficha
declare su **tiempo de respuesta**. La API no tiene un campo para eso. Cuando el tiempo
aparece, aparece dentro de la PROSA de `info_process` o `info_requirement`, en HTML libre:

    «REGULAR: el tiempo de entrega es de 5 días laborables.»

De los 710 trámites del catálogo, **3 lo declaran**. El 0,4 %. Esa cifra —y no la lista— es
lo que este módulo existe para medir: hay una obligación con artículo (Ley 167-21, art. 39),
un campo normado con resolución (142-2024), y un cumplimiento de tres casos.

**La gramática es CERRADA y está ANCLADA, y esto no es un detalle de implementación.** Una
primera versión buscaba «un número seguido de una unidad de tiempo» en la prosa y devolvía
23 %. Eran multas —«seis meses, con un monto de CIEN MIL PESOS»—, vigencias de documentos y
condiciones de agenda: cifras de tiempo que no son el tiempo del trámite. Publicar ese 23 %
habría sido publicar un número que mide otra cosa, que es exactamente lo que este
repositorio persigue. La cifra solo cuenta si está pegada a una señal de RESPUESTA del
trámite (`ANCLAS`), y todo lo demás se descarta sin contarse.

**El instrumento se comprueba contra un positivo conocido antes de creerle a un cero.** La
versión anclada devolvió 0 sobre una muestra de 60, y ese cero era cierto; pero solo se supo
después de verificar que el patrón SÍ encontraba el caso del CNZFE. Un barrido que no
encuentra nada y un barrido roto se ven igual. Lo cubre
`test_el_ancla_encuentra_el_positivo_conocido`.

**La ausencia es el dato, y por eso se declara y no se rellena.** Un trámite sin tiempo no
es `0` ni un promedio: es `None` con su motivo, y el resumen publica cuántos son. Confundir
«no lo declara» con «tarda cero» invertiría el hallazgo.

**Acceso.** La API responde sin autenticación y no declara términos propios; el portal
publica condiciones de uso del SITIO, que no son una licencia del dato. `robots.txt` dice
`User-agent: * / Allow: /`. Se aplica la regla del repositorio para un emisor público
dominicano —se presume reutilizable con atribución y lo que se declara es la excepción—: acá
no hay excepción, porque el catálogo de trámites y la institución responsable de cada uno son
actos de la Administración. La licencia está registrada en `shared.data.licenses`, leída el
2026-08-25.
"""
from __future__ import annotations

import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("sdq.data.gobdo_tramites")

SOURCE = "Portal Único de Servicios del Gobierno Dominicano (gob.do) — OGTIC"
LICENSE = ("gob.do (OGTIC) — catálogo de trámites del Portal Único de Servicios. Información "
           "pública dominicana: reutilizable con atribución por Ley 200-04, Decreto 103-22 y "
           "NORTIC A3. `robots.txt` permite el rastreo completo (Allow: /).")

#: El listado paginado. `per_page` llega hasta 100; por debajo de eso son 60 páginas de 12.
API_LISTADO = "https://gob-do-api.www.gob.do/api/v2/portals/services"

#: El detalle, que es donde vive la prosa. El sufijo `/slug` es parte de la ruta, no un
#: parámetro: la API distingue así la búsqueda por slug de la búsqueda por id.
API_DETALLE = "https://gob-do-api.www.gob.do/api/v1/portals/services/{slug}/slug"

#: El prefijo `/api` NO es opcional y no está en el bundle del portal: sin él la API responde
#: 404 con «Ruta Incorrecta o no ha iniciado sesion», que parece un problema de permisos y es
#: un problema de ruta. Queda escrito para que nadie vuelva a perder el rato ahí.
PREFIJO_OBLIGATORIO = "/api"

#: Los campos del detalle que pueden contener la prosa donde se declara el tiempo. Se leen
#: los tres: ninguna institución usa el mismo.
CAMPOS_CON_PROSA = ("info_process", "info_requirement", "description")

#: Las señales de que la cifra que sigue es el tiempo DEL TRÁMITE y no otra cosa, en DOS
#: NIVELES. Una cifra sin ancla no se extrae, se descarta.
#:
#: **Por qué dos niveles y no una lista.** Una ficha puede nombrar el campo con todas las
#: letras —«el tiempo de entrega es de 5 días laborables»— y además mencionar otro plazo en
#: una condición de agenda —«si quedan 5 días laborables o menos de la reunión»—. Con una
#: lista plana gana el que aparece primero en el texto, que no es el que nombra el campo. Se
#: buscan primero las FUERTES sobre todo el texto y solo si ninguna aparece se prueban las
#: DÉBILES; el nivel que acertó viaja con el dato.
#:
#: **Y las débiles existen porque la primera versión se perdía 19 de 22.** Medido el
#: 2026-08-25 sobre los 710 trámites del catálogo: detectaba 3 y había 22. Lo que faltaba era
#: cómo escribe la gente —«se LE entrega en 3 horas», «este proceso tiene una DURACIÓN de
#: cinco días», «la preaprobación TOMA 1 día hábil», «dentro de un PLAZO DE quince días»—.
#: Publicar 3 habría sido publicar una cifra siete veces menor que la real.
ANCLAS_FUERTES = (
    # La ficha NOMBRA el campo que la Resolución 142-2024 exige.
    r"tiempo\s+de\s+(?:entrega|respuesta|procesamiento|espera)",
    r"plazo\s+de\s+(?:respuesta|entrega)",
    r"tiempo\s+estimad\w*",
)

ANCLAS_DEBILES = (
    # Perífrasis: dicen lo mismo sin nombrar el campo.
    r"se\s+(?:le\s+)?entrega\s+(?:en|dentro)",
    r"ser[áa]\s+entregad\w*\s+(?:en|dentro)",
    r"estar[áa]\s+list\w*\s+(?:en|dentro)",
    r"(?:este\s+)?(?:proceso|tr[áa]mite|procedimiento)[^.]{0,40}?(?:toma|tarda|tiene\s+una\s+duraci[óo]n\s+de)",
    r"(?:respuesta|resoluci[óo]n|entrega)[^.]{0,30}?dentro\s+de\s+los",
    r"se\s+(?:completa|resuelve|responde)\s+en",
    r"dentro\s+de\s+un\s+plazo\s+(?:m[áa]ximo\s+)?de",
)

#: Se conserva el nombre anterior: es la unión, para quien solo quiera saber qué se busca.
ANCLAS = ANCLAS_FUERTES + ANCLAS_DEBILES

#: Los números que la prosa usa, en cifra o en palabra. La ley y las fichas escriben las dos
#: formas —«tres (3) días»— y quedarse con una pierde la mitad.
NUMEROS_ESCRITOS = {
    "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "quince": 15, "veinte": 20,
    "treinta": 30,
}

#: Cuántos días representa cada unidad. Las horas se convierten sobre una jornada de 8 horas
#: cuando son laborables — «48 horas laborables» son 6 días de trabajo, no 2 de calendario, y
#: tratarlas como 2 subestimaría el trámite en tres veces.
HORAS_POR_JORNADA = 8.0
DIAS_POR_UNIDAD = {"hora": None, "dia": 1.0, "semana": 7.0, "mes": 30.0}

#: Banda de plausibilidad del tiempo de un trámite, en días. Fuera de esto lo que se leyó no
#: es un plazo de respuesta: es una vigencia, una prescripción o un error de lectura.
BANDA_DIAS = (0.04, 365.0)

_TIMEOUT = 60.0
_PAUSA_ENTRE_LLAMADAS = 0.05

_NUM = r"(?:\d{1,3}|" + "|".join(NUMEROS_ESCRITOS) + r")"

#: El calificador que puede seguir a la unidad, en lista CERRADA. Antes se capturaban «16
#: caracteres de lo que venga» y salían jirones —«1 día h», «3 horas si es solicitad»— que
#: después se publican tal cual en una tabla. Una cifra que se imprime se recorta a palabras
#: enteras o no se recorta.
_CALIF = r"(?:laborables?|h[áa]bil(?:es)?|calendario|corridos?|continuos?|natural(?:es)?)"
_UNI = r"(?:d[ií]as?|horas?|semanas?|meses?)"
def _compilar(anclas):
    return re.compile(
        r"(?:" + "|".join(anclas) + r")"
        r"[^.<]{0,60}?"
        r"(" + _NUM + r"\s*(?:\(\d+\)\s*)?" + _UNI + r"(?:\s+" + _CALIF + r")?)",
        re.IGNORECASE)


_PATRON_FUERTE = _compilar(ANCLAS_FUERTES)
_PATRON_DEBIL = _compilar(ANCLAS_DEBILES)


class TramitesError(RuntimeError):
    """No se pudo leer el catálogo. NUNCA se degrada a «no hay trámites»."""


@dataclass(frozen=True)
class Tiempo:
    """Un tiempo de respuesta declarado, con el texto del que salió.

    El `texto_original` viaja siempre: es prosa extraída de un HTML de la Administración, y
    quien lea la cifra tiene que poder ver de qué frase salió sin volver a la fuente.
    """

    valor: float
    unidad: str
    laborables: bool
    texto_original: str
    #: `explicito` si la ficha NOMBRA el campo («tiempo de respuesta es de…»); `perifrasis`
    #: si lo dice sin nombrarlo («se le entrega en 3 horas»). No es lo mismo para el informe:
    #: lo primero cumple el campo que la resolución exige, lo segundo lo suple en prosa.
    como_lo_dice: str = "explicito"

    @property
    def dias(self) -> Optional[float]:
        """El tiempo normalizado a días. `None` si la unidad no se pudo normalizar."""
        if self.unidad == "hora":
            base = self.valor / (HORAS_POR_JORNADA if self.laborables else 24.0)
            return round(base, 3)
        factor = DIAS_POR_UNIDAD.get(self.unidad)
        return round(self.valor * factor, 3) if factor else None


@dataclass(frozen=True)
class Tramite:
    """Un trámite del catálogo, con su tiempo si lo declara.

    `tiempo` en `None` significa **que la ficha no lo declara**, no que el trámite sea
    inmediato. La diferencia es el hallazgo entero de este módulo.
    """

    slug: str
    nombre: str
    institucion: str
    institucion_sigla: str
    area: str
    canales: Sequence[str]
    costo_declarado: bool
    visitas: int
    actualizado: Optional[str]
    tiempo: Optional[Tiempo] = None


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t if t is not None else ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def limpiar_prosa(*trozos: object) -> str:
    """La prosa del detalle, sin etiquetas ni entidades y con los espacios colapsados.

    El emisor guarda HTML con `&nbsp;`, saltos de línea dentro de las frases y espacios
    múltiples: «5 días      laborables». Sin colapsar, cualquier patrón se parte a la mitad.
    """
    crudo = " ".join(str(t or "") for t in trozos)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", crudo))).strip()


def _unidad_de(texto: str) -> str:
    n = _norm(texto)
    for clave in ("hora", "semana", "mes", "dia"):
        if clave in n:
            return clave
    return ""


def _valor_de(texto: str) -> Optional[float]:
    """El número, prefiriendo la CIFRA cuando la prosa trae las dos formas.

    «tres (3) días» trae la palabra y el paréntesis. Se toma el paréntesis: es la forma que
    el redactor puso para desambiguar, y confiar en la palabra obliga a un diccionario que
    envejece con cada variante regional.
    """
    entre_parentesis = re.search(r"\((\d{1,3})\)", texto)
    if entre_parentesis:
        return float(entre_parentesis.group(1))
    cifra = re.search(r"\d{1,3}", texto)
    if cifra:
        return float(cifra.group(0))
    for palabra, valor in NUMEROS_ESCRITOS.items():
        if re.search(rf"\b{palabra}\b", _norm(texto)):
            return float(valor)
    return None


def tiempo_declarado(prosa: str) -> Optional[Tiempo]:
    """El tiempo de respuesta que la ficha declara, o `None`.

    `None` es la respuesta correcta y frecuente: 707 de los 710 trámites del catálogo no lo
    declaran. No se busca un sustituto ni se estima: la ausencia ES la medición.
    """
    # Primero las FUERTES sobre todo el texto: una ficha que nombra el campo y además
    # menciona otro plazo en una condición de agenda tiene que devolver el que nombra el
    # campo, no el que aparece antes. Con una lista plana ganaba el orden del texto.
    m, nivel = _PATRON_FUERTE.search(prosa), "explicito"
    if not m:
        m, nivel = _PATRON_DEBIL.search(prosa), "perifrasis"
    if not m:
        return None
    bruto = m.group(1).strip()
    unidad = _unidad_de(bruto)
    valor = _valor_de(bruto)
    if not unidad or valor is None:
        return None
    t = Tiempo(valor=valor, unidad=unidad,
               laborables=bool(re.search(r"laborabl|h[áa]bil", _norm(bruto))),
               texto_original=bruto, como_lo_dice=nivel)
    dias = t.dias
    if dias is not None and not (BANDA_DIAS[0] <= dias <= BANDA_DIAS[1]):
        logger.info("[gobdo] tiempo fuera de banda, descartado: %r (%s días)", bruto, dias)
        return None
    return t


def leer_listado(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Las filas de una página del listado, con su forma comprobada."""
    filas = payload.get("data")
    if not isinstance(filas, list):
        raise TramitesError(
            "el listado no trae `data`: la API cambió de forma y leer lo que quede serviría "
            "un catálogo parcial sin avisar")
    return filas


def tramite_de(fila: Dict[str, Any], detalle: Optional[Dict[str, Any]] = None) -> Tramite:
    """Un `Tramite` desde la fila del listado, más el detalle si se pidió.

    El listado NO trae la prosa: sin el detalle, `tiempo` es siempre `None` — que es una
    afirmación distinta de «no lo declara». Por eso el detalle no es opcional para medir, y
    quien llame sin él no puede publicar la cifra de cumplimiento.
    """
    canales = [c for c, activo in (("en_linea", fila.get("is_web_mode")),
                                   ("telefonico", fila.get("is_phone_mode")),
                                   ("presencial", fila.get("is_person_mode"))) if activo]
    area = fila.get("area_service") or {}
    prosa = limpiar_prosa(*(( detalle or {}).get(c) for c in CAMPOS_CON_PROSA))
    return Tramite(
        slug=str(fila.get("slug") or ""),
        nombre=str(fila.get("service_name") or (detalle or {}).get("name") or ""),
        institucion=str(fila.get("institution_name") or ""),
        institucion_sigla=str(fila.get("institution_acronym") or ""),
        area=str(area.get("name") or "") if isinstance(area, dict) else "",
        canales=tuple(canales),
        costo_declarado=bool(fila.get("price")),
        visitas=int(fila.get("visited") or 0),
        actualizado=(str(fila.get("updated_at")) if fila.get("updated_at") else None),
        tiempo=tiempo_declarado(prosa) if detalle is not None else None,
    )


def resumen(tramites: Sequence[Tramite]) -> Dict[str, Any]:
    """Cuántos trámites declaran su tiempo, que es la pregunta que este módulo contesta.

    El porcentaje nombra su denominador en la propia clave, y el complemento viaja al lado:
    quien redacte va a necesitar los dos, y la razón que falte la va a calcular él.
    """
    total = len(tramites)
    con = [t for t in tramites if t.tiempo is not None]
    por_institucion: Dict[str, int] = {}
    for t in con:
        por_institucion[t.institucion_sigla] = por_institucion.get(t.institucion_sigla, 0) + 1
    return {
        "tramites_en_el_catalogo": total,
        "instituciones_en_el_catalogo": len({t.institucion_sigla for t in tramites}),
        "declaran_su_tiempo_de_respuesta": len(con),
        # Cómo lo dicen, que no es un matiz: la Resolución 142-2024 exige un CAMPO, y una
        # perífrasis en la prosa lo suple sin cumplirlo. El catálogo no expone ese campo, así
        # que hoy ninguna ficha puede cumplirlo en forma — solo decirlo.
        "lo_nombran_explicitamente": sum(1 for t in con if t.tiempo
                                         and t.tiempo.como_lo_dice == "explicito"),
        "lo_dicen_en_perifrasis": sum(1 for t in con if t.tiempo
                                      and t.tiempo.como_lo_dice == "perifrasis"),
        "no_declaran_su_tiempo_de_respuesta": total - len(con),
        "pct_declaran_sobre_los_del_catalogo": (
            round(100.0 * len(con) / total, 1) if total else None),
        "pct_no_declaran_sobre_los_del_catalogo": (
            round(100.0 * (total - len(con)) / total, 1) if total else None),
        "por_institucion_que_declara": dict(sorted(por_institucion.items())),
        "obligacion": (
            "La Resolución 142-2024 del MAP exige que la ficha de cada trámite registrado "
            "declare su tiempo de respuesta, y la Ley 167-21 (art. 39) obliga a los entes a "
            "publicar sus procedimientos en el Registro Único de Mejora Regulatoria."),
        "nota": (
            "«No declara su tiempo» NO significa que el trámite sea inmediato. Es la ficha la "
            "que no lo dice, y esa ausencia es la medición."),
    }


def fetch_listado() -> List[Dict[str, Any]]:  # pragma: no cover - red
    """Todas las filas del catálogo, recorriendo la paginación hasta agotarla."""
    import httpx

    filas: List[Dict[str, Any]] = []
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": "sdq-mip/1.0", "Accept": "application/json"}) as c:
        pagina = 1
        while True:
            r = c.get(API_LISTADO, params={"per_page": 100, "page": pagina})
            r.raise_for_status()
            lote = leer_listado(r.json())
            if not lote:
                break
            filas.extend(lote)
            pagina += 1
            if pagina > 100:                       # cinturón: la API declara ~8 páginas
                raise TramitesError(
                    "la paginación no termina: se cortó en la página 100 para no quedar en "
                    "un bucle contra el emisor")
    vistos = {f.get("slug") for f in filas}
    if len(vistos) != len(filas):
        logger.info("[gobdo] el listado trajo %d filas y %d slugs distintos",
                    len(filas), len(vistos))
    return filas


def fetch_detalle(slug: str) -> Dict[str, Any]:  # pragma: no cover - red
    """El detalle de un trámite, que es donde vive la prosa con el tiempo."""
    import httpx

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": "sdq-mip/1.0", "Accept": "application/json"}) as c:
        r = c.get(API_DETALLE.format(slug=slug))
        r.raise_for_status()
        d = r.json().get("data")
    if not isinstance(d, dict):
        raise TramitesError(f"el detalle de «{slug}» no trae `data`")
    return d


def fetch(con_detalle: bool = True,
          limite: Optional[int] = None) -> List[Tramite]:  # pragma: no cover - red
    """El catálogo completo. Con `con_detalle=False` no se puede medir el tiempo.

    Se pide el detalle de a uno con una pausa breve: son ~710 llamadas contra un portal
    público y no hay ninguna prisa que justifique golpearlo en paralelo.
    """
    import time

    filas = fetch_listado()
    if limite is not None:
        filas = filas[:limite]
    out: List[Tramite] = []
    for fila in filas:
        detalle = None
        if con_detalle:
            try:
                detalle = fetch_detalle(str(fila.get("slug") or ""))
            except Exception as e:                 # noqa: BLE001 — se declara y se sigue
                logger.info("[gobdo] sin detalle para %s: %s", fila.get("slug"), e)
            time.sleep(_PAUSA_ENTRE_LLAMADAS)
        out.append(tramite_de(fila, detalle))
    return out


def como_filas(tramites: Iterable[Tramite]) -> List[Dict[str, Any]]:
    """La tabla plana, para persistir o para el contexto de un informe."""
    return [{
        "slug": t.slug, "tramite": t.nombre,
        "institucion": t.institucion, "sigla": t.institucion_sigla, "area": t.area,
        "canales": list(t.canales), "declara_costo": t.costo_declarado,
        "consultas_del_portal": t.visitas, "actualizado": t.actualizado,
        "tiempo_declarado": t.tiempo.texto_original if t.tiempo else None,
        "tiempo_en_dias": t.tiempo.dias if t.tiempo else None,
    } for t in tramites]
