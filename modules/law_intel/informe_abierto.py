"""El informe ABIERTO de una ley: el tercer entregable, y el único sin destinatario.

El producto emite hoy dos documentos con destinatario —el informe técnico y el dictamen—,
y los dos son confidenciales del cliente que los encarga. Éste es el tercero y es de otra
naturaleza: dice **qué ordena la norma, qué se mide de ella y de dónde sale cada cifra**, sin
publicar el veredicto de cumplimiento, que es lo que el cliente pagó.

**Por qué no es un nivel del producto y sí una superficie propia.** El primer intento fue
convertirlo en el Pulse. El contrato lo rechaza —«Pulse jamás nombra entidades», declarado no
negociable en `shared.products.tiers`— y el contrato tiene razón: el anonimato del Pulse
existe para que la vista abierta de un eje sectorial no filtre el nombre de un banco. Forzar
la excepción para las leyes habría abierto la puerta para todos.

Y al mirarlo de nuevo, el encaje estaba mal de origen: **los tres entregables no son tres
profundidades, son tres documentos.** Los niveles del producto miden cuánto se profundiza;
esto es otra pieza, con otra audiencia y otro registro. Va por su propia ruta.

**Casi todo el documento se COMPUTA.** Las tablas —obligaciones, cobertura, quién produce
cada cifra— salen del expediente y del registro. Eso lo vuelve reproducible y barato: no
depende de una generación de IA y dos lecturas del mismo día dan lo mismo salvo que el dato
haya cambiado.

**Registro EXTERNO.** Sin andamiaje de método: nada de «hallazgo crítico», severidades ni
rótulos internos. El lector está fuera de SDQ y ve la conclusión escrita en prosa, no el
método por su nombre. Lo vigila `test_informe_abierto.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.law_intel.informe_abierto")

#: Marca de agua. Dice lo contrario que la del dictamen a propósito: éste se comparte.
MARCA = "Documento abierto · SDQ Consulting Group"

#: Cómo se dice en prosa cada estado de una obligación. El vocabulario interno
#: —`sin_registro_publico`, `cumplida_tarde`— no sale del expediente: acá se traduce, porque
#: el lector externo no tiene por qué conocer nuestro esquema.
ESTADO_EN_PROSA = {
    "cumplida": "Realizada dentro del plazo",
    "cumplida_tarde": "Realizada fuera del plazo",
    "parcial": "Realizada en parte",
    "incumplida": "No realizada",
    "sin_registro_publico": "Sin registro público localizado",
    "pendiente_no_vencida": "Plazo aún no vencido",
    "no_exigible": "No exigible",
}

#: Y cómo se dice el tipo de deudor. «universo» es jerga nuestra; lo que el lector necesita
#: saber es que la obligación recae sobre cientos de instituciones y no sobre una.
DEUDOR_EN_PROSA = {
    "organo": "Un órgano determinado",
    "universo": "Todos los entes de la Administración",
    "indeterminado": "Sin deudor determinado",
}

#: La advertencia que acompaña SIEMPRE a la tabla de obligaciones. No es un descargo de
#: cortesía: «no se encontró registro» y «no se hizo» son afirmaciones distintas, y publicar
#: la segunda con la evidencia de la primera es lo que vuelve refutable un informe entero.
ADVERTENCIA_DEL_REGISTRO = (
    "«Sin registro público localizado» no afirma un incumplimiento: significa que no se "
    "encontró constancia pública de que la obligación se haya atendido, y esa es una "
    "afirmación sobre la evidencia disponible, no sobre la conducta del obligado. Varias de "
    "estas obligaciones recaen sobre el conjunto de la Administración; establecer si se "
    "atendieron exige revisarlas institución por institución.")

#: Qué operación del console alimenta cada serie de seguimiento declarada por un expediente.
#:
#: **Explícito, y no por coincidencia de cadenas.** El primer intento buscaba el nombre de la
#: serie dentro de la descripción de la operación: funciona hasta que alguien reescribe la
#: descripción, y entonces el informe deja de prometer actualización sin que nadie se entere
#: — un fallo silencioso en la sección que existe para decirle al lector cuándo volver.
#:
#: Es un mapa a mano, y por eso lleva guard: `test_informe_abierto` exige que TODA
#: `serie_de_seguimiento` declarada en cualquier expediente tenga su entrada acá, y que la
#: operación exista de verdad en el registro.
OPERACION_QUE_ALIMENTA = {
    "social_dev:tramites_catalogados": "tramites-registro-unico",
    "social_dev:tramites_con_tiempo_declarado": "tramites-registro-unico",
    "social_dev:tramites_pct_con_tiempo_sobre_los_catalogados": "tramites-registro-unico",
}

_MAX_FILAS_INDICADORES = 60

#: Cómo se dice en prosa cada periodicidad. El vocabulario del expediente es nuestro; el
#: lector externo lee «cada cuatro años», no «cuatrienal».
CADA_CUANTO = {
    "anual": "cada año",
    "semestral": "cada seis meses",
    "cuatrienal": "cada cuatro años",
    "quinquenal": "cada cinco años",
    "continua": "de forma continua",
    "unica": "por única vez",
}


def _fechas_del_plazo(plazo: Optional[Dict[str, Any]]) -> str:
    """Cuándo vence, en prosa y sin jerga de tipos.

    Se imprime la LISTA completa cuando la ley fija fechas ciertas —2016, 2020, 2024, 2028—
    porque ahí está el hallazgo: se ve de un vistazo cuántas pasaron.
    """
    if not plazo:
        return "—"
    tipo, vence = plazo.get("tipo"), plazo.get("vence")
    if tipo == "fecha_anual" and isinstance(vence, str) and "-" in vence:
        mes, dia = vence.split("-")[:2]
        meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                 "septiembre", "octubre", "noviembre", "diciembre")
        try:
            return f"antes del {int(dia)} de {meses[int(mes) - 1]}"
        except (ValueError, IndexError):                   # pragma: no cover - defensivo
            return str(vence)
    if isinstance(vence, (list, tuple)):
        return ", ".join(str(v)[:4] for v in vence)
    return str(vence) if vence else "—"


#: Escalas cuyo «meta» NO es un valor contra el cual juzgar. Una meta REDACTADA —«todos los
#: que la Administración exija»— no fija un corte: es la forma en que un expediente declara
#: que la ley no puso cifra.
_ESCALAS_SIN_CORTE = ("redactada", "sin_meta")


def _cortes_de_las_metas(exp: Any) -> List[str]:
    """Los años en que la ley fija metas JUZGABLES, en orden.

    Salen de las metas de los indicadores y no de una lista escrita: la ley fija sus cortes
    en un anexo, y transcribirlos acá los desincronizaría del día que se corrija uno.

    **Las metas redactadas no cuentan, y el caso lo destapó un test.** La 167-21 tiene un
    único indicador con la misma frase bajo 2025 y 2030 —puesta ahí justamente para declarar
    que la ley NO fijó una cifra—, y contarlas producía «la ley fija sus metas por corte:
    2025 y 2030» sobre una norma que no fija ninguna, seguido de una advertencia sobre
    incumplir un corte que no existe.
    """
    anios = {a for i in getattr(exp, "indicadores", ()) or ()
             if str(getattr(i, "escala", "")) not in _ESCALAS_SIN_CORTE
             for a in (i.metas or {})}
    return sorted(anios)


def _cuando_manda_la_ley_medir(exp: Any, obs: List[Dict[str, Any]]
                               ) -> Optional[Tuple[str, Optional[Tuple[str, List[List[str]]]]]]:
    """Qué calendario de evaluación fijó la propia ley, y si se está cumpliendo.

    **Es la respuesta buena a «cuándo se mide esta ley», y no la agenda de nuestros
    conectores.** El primer intento iba a publicar cada cuánto relee el dato nuestro sync,
    que es un detalle de implementación nuestro: al lector le importa cada cuánto manda la
    NORMA evaluarse, porque eso es exigible y lo otro no.

    Devuelve `None` cuando la ley no fija ninguno —que es información y se dice en otra
    parte, no un hueco que se rellene con nuestra cadencia—.
    """
    hitos = [o for o in obs if o.get("hito_de_medicion")]
    cortes = _cortes_de_las_metas(exp)
    if not hitos and not cortes:
        return None

    partes: List[str] = []
    if cortes:
        partes.append(
            f"La ley fija sus metas por corte: {_lista_en_prosa(cortes)}. La evaluación de "
            f"un indicador se hace contra el corte que corresponda, y no contra el valor "
            f"final: un indicador que va camino a su meta de {cortes[-1]} puede estar "
            f"incumpliendo la de {cortes[-2] if len(cortes) > 1 else cortes[0]}.")
    if hitos:
        cumplidos = [o for o in hitos if o.get("estado") == "cumplida"]
        incumplidos = [o for o in hitos if o.get("estado") == "incumplida"]
        partes.append(
            f"Además, la norma fija {_plural(len(hitos), 'un momento', f'{len(hitos)} momentos')} "
            f"en que debe evaluarse a sí misma, con deudor y con fecha. La tabla siguiente "
            f"los consigna.")
        if incumplidos and cumplidos:
            # El contraste ES el hallazgo y se dice en prosa, no se deja deducir de la tabla.
            #
            # Y el recuento nombra los TRES grupos, incluido el que no está vencido. Una
            # primera versión decía «uno consta cumplido y otro no» sobre tres hitos: el
            # tercero desaparecía de la frase, y un hito que todavía no vence es
            # exactamente el que no hay que dar por perdido.
            otros = len(hitos) - len(cumplidos) - len(incumplidos)
            frase = (f"De {_plural(len(hitos), 'ese momento', f'esos {len(hitos)} momentos')}, "
                     f"{len(cumplidos)} {_plural(len(cumplidos), 'consta cumplido', 'constan cumplidos')} y "
                     f"{len(incumplidos)} no")
            if otros:
                frase += (f"; {_plural(otros, 'el restante todavía no vence', f'los {otros} restantes todavía no vencen')}")
            partes.append(
                frase + ". La distinción entre los dos primeros no es de grado: reportar el "
                "avance y revisar la estrategia son deberes distintos, y el segundo exige "
                "evaluación externa.")

    tabla = None
    if hitos:
        filas: List[List[str]] = [["Artículo", "Qué manda", "Cada cuánto", "Cuándo vence",
                                   "Estado"]]
        for o in sorted(hitos, key=lambda x: int(x.get("articulo") or 0)):
            filas.append([
                str(o.get("articulo") or "—"),
                _recortar(str(o.get("deber") or ""), 58),
                CADA_CUANTO.get(str(o.get("periodicidad") or ""), "por una sola vez"),
                _fechas_del_plazo(o.get("plazo")),
                ESTADO_EN_PROSA.get(str(o.get("estado")), str(o.get("estado"))),
            ])
        tabla = ("Los momentos en que la ley manda evaluarse", filas)
    return ("\n\n".join(partes), tabla)


def _lista_en_prosa(xs: Sequence[Any]) -> str:
    """`a, b y c`. Una lista con «y» final se lee; una separada por comas se escanea."""
    ss = [str(x) for x in xs]
    if len(ss) <= 1:
        return ss[0] if ss else ""
    return ", ".join(ss[:-1]) + " y " + ss[-1]


def _tabla_de_obligaciones(publicable: Dict[str, Any]) -> Optional[Tuple[str, List[List[str]]]]:
    obs = publicable.get("obligaciones") or []
    if not obs:
        return None
    filas: List[List[str]] = [["Artículo", "Qué ordena", "A quién", "Estado", "Consecuencia"]]
    for o in sorted(obs, key=lambda x: int(x.get("articulo") or 0)):
        filas.append([
            str(o.get("articulo") or "—"),
            # Se corta en el último espacio, no a media palabra: esta celda se imprime.
            _recortar(str(o.get("deber") or ""), 74),
            DEUDOR_EN_PROSA.get(str((o.get("deudor") or {}).get("tipo") or ""), "—"),
            ESTADO_EN_PROSA.get(str(o.get("estado")), str(o.get("estado"))),
            "Sí" if o.get("consecuencia") else "No",
        ])
    return ("Qué ordena la norma", filas)


def _recortar(texto: str, limite: int) -> str:
    """Corta en el último espacio antes del límite.

    Un corte a media palabra —«dentro de quinc», «vigencia d»— se imprime tal cual en la
    tabla, y en un documento que se comparte eso dice que nadie lo miró antes de soltarlo.
    """
    t = " ".join(texto.split())
    if len(t) <= limite:
        return t
    return t[:limite].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _tabla_de_medicion(verificabilidad: Dict[str, Any]) -> Optional[Tuple[str, List[List[str]]]]:
    """Qué se mide de la ley y quién produce cada cifra.

    Es la mitad del valor del documento: la otra mitad es la tabla de obligaciones. Un
    inventario que dice «medimos 46» sin decir de dónde sale cada uno no se puede comprobar,
    y un inventario que no se puede comprobar no sirve para lo que este documento existe.
    """
    cadena = verificabilidad.get("cadena_por_sujeto")
    if not isinstance(cadena, list):
        return None
    inds = [c for c in cadena if isinstance(c, dict) and c.get("clase") == "indicador"]
    if not inds:
        return None
    filas: List[List[str]] = [["Indicador", "Qué mide", "Quién produce el dato"]]
    for c in inds[:_MAX_FILAS_INDICADORES]:
        filas.append([str(c.get("sujeto") or "—"),
                      _recortar(str(c.get("nombre") or ""), 58),
                      _recortar(str(c.get("productor") or ""), 58)])
    if len(inds) > _MAX_FILAS_INDICADORES:
        # El truncado se DECLARA. Una tabla cortada en silencio se lee como el inventario
        # completo, y eso convierte una omisión de formato en una cifra falsa.
        filas.append(["…", f"y {len(inds) - _MAX_FILAS_INDICADORES} indicadores más", ""])
    return ("Qué se mide, y quién produce cada cifra", filas)


def _tabla_de_cobertura(cobertura: Dict[str, Any],
                        campo: Dict[str, Any]) -> Tuple[str, List[List[str]]]:
    return ("Alcance de la medición", [
        ["Concepto", "Valor"],
        ["Indicadores que la norma numera", str(cobertura.get("total", "—"))],
        ["Con fuente verificada", str(cobertura.get("medidos", "—"))],
        ["Sin medición, con motivo registrado",
         str(campo.get("declarados_sin_veredicto", "—"))],
        ["Sin motivo registrado", str(campo.get("en_silencio", "—"))],
    ])


#: Cuántas instituciones entran en la tabla. Con 91 la tabla ocupa tres páginas y deja de
#: leerse; con las diez más consultadas se ve quién concentra la espera de la gente.
_TOP_INSTITUCIONES = 12


def _mil(n: Any) -> str:
    """Notación española de miles. El informe entero usa una sola convención."""
    return f"{int(n or 0):,}".replace(",", ".")


def _por_sujeto(db: Any, tema: str, periodo: str) -> Dict[str, float]:
    from modules.social_dev.models.models import SocialIndicator
    filas = (db.query(SocialIndicator)
             .filter(SocialIndicator.theme == tema, SocialIndicator.period == periodo).all())
    return {str(f.entity_key): float(f.value or 0) for f in filas}


def _tiempos_declarados(db: Any, periodo: str) -> Dict[str, Tuple[float, str]]:
    """`{slug: (días, «texto · nivel»)}` de los trámites que declaran su tiempo."""
    from modules.social_dev.models.models import SocialIndicator
    from modules.social_dev.tramites_sync import TEMA_TIEMPO_POR_TRAMITE
    filas = (db.query(SocialIndicator)
             .filter(SocialIndicator.theme == TEMA_TIEMPO_POR_TRAMITE,
                     SocialIndicator.period == periodo).all())
    return {str(f.entity_key): (float(f.value or 0), str(f.disaggregation or ""))
            for f in filas}


def _instituciones_que_declaran(db: Any, periodo: str) -> set:
    """Siglas con al menos un trámite de tiempo declarado, leído del desglose persistido.

    El primer intento tenía una caché que nunca se llenaba: la columna habría dicho «No»
    para todas, afirmando que ninguna institución declara nada. El sync persiste el conteo
    por institución justamente porque el slug del trámite no lleva la sigla.
    """
    from modules.social_dev.tramites_sync import TEMA_CON_TIEMPO_POR_INSTITUCION
    return {s for s, n in _por_sujeto(db, TEMA_CON_TIEMPO_POR_INSTITUCION, periodo).items()
            if n > 0}


#: Cuántos trámites entran en la tabla de los más consultados. Con 710 la tabla es el
#: catálogo entero; con diez se ve qué le pide la gente al Estado.
_TOP_TRAMITES = 10


@dataclass(frozen=True)
class Anexo:
    """Lo que un expediente aporta de propio al informe abierto.

    No son solo tablas. Un dato que se construye con un criterio necesita decir CUÁL —si no,
    el lector no tiene cómo saber si la cifra es seria— y qué NO afirma. Las tres piezas
    viajan juntas porque las tres describen el mismo dato: separarlas es cómo se publica una
    tabla cuyo método quedó en otro documento.
    """

    tablas: List[Tuple[str, List[List[str]]]]
    #: Con qué criterio se obtuvo la cifra, y qué se descartó al aplicarlo.
    metodologia: Optional[str] = None
    #: Qué NO afirma este dato. Se suma al alcance genérico, no lo reemplaza.
    limites: Optional[str] = None
    #: Cuándo se leyó el dato que el anexo publica, `YYYY-MM-DD`. Sale de la SERIE y no de
    #: la agenda: la agenda dice cuándo tocaba correr, el dato dice cuándo se leyó, y una
    #: corrida manual las separa.
    leido_el: Optional[str] = None


def _tabla_de_mas_consultados(db: Any, periodo: str) -> Optional[Tuple[str, List[List[str]]]]:
    """Los trámites que más consulta la gente, con su nombre.

    La tabla por institución dice quién concentra la espera; ésta dice qué le pide la gente
    al Estado, que es otra pregunta. Se imprime el NOMBRE del trámite y no el slug:
    «consultas-superate» no es como nadie lo busca.
    """
    from modules.social_dev.tramites_sync import TEMA_CONSULTAS_POR_TRAMITE
    from modules.social_dev.models.models import SocialIndicator

    filas = (db.query(SocialIndicator)
             .filter(SocialIndicator.theme == TEMA_CONSULTAS_POR_TRAMITE,
                     SocialIndicator.period == periodo).all())
    if not filas:
        return None
    orden = sorted(filas, key=lambda f: -float(f.value or 0))[:_TOP_TRAMITES]
    out: List[List[str]] = [["Trámite", "Institución", "Consultas"]]
    for f in orden:
        partes = [x.strip() for x in str(f.disaggregation or "").split("·")]
        sigla = partes[0] if partes else ""
        nombre = partes[1] if len(partes) > 1 else str(f.entity_key)
        out.append([_recortar(nombre, 62), sigla, _mil(f.value)])
    return (f"Los trámites que más consulta la gente (los {len(orden)} primeros de "
            f"{len(filas)})", out)


def _metodologia_tramites(db: Any, periodo: str, total: float) -> Optional[str]:
    """Con qué criterio se contó, y cuánto se descartó al aplicarlo.

    **La razón se COMPUTA.** La primera versión de este documento decía «un criterio más
    amplio arroja una proporción cinco veces mayor», escrito a mano sobre una medición de
    ese día. En cuanto el criterio estrecho pasó de 3 a 22 la frase quedó falsa, y nadie se
    entera de eso leyendo el documento. El contrafactual se persiste en cada corrida y la
    razón sale de dividir.
    """
    from modules.social_dev.models.models import SocialIndicator
    from modules.social_dev.tramites_sync import (ENTIDAD, TEMA_CIFRA_SIN_ANCLAR,
                                                  TEMA_CON_TIEMPO)

    v = {f.theme: float(f.value or 0) for f in db.query(SocialIndicator)
         .filter(SocialIndicator.entity_key == ENTIDAD,
                 SocialIndicator.period == periodo,
                 SocialIndicator.theme.in_((TEMA_CON_TIEMPO, TEMA_CIFRA_SIN_ANCLAR))).all()}
    base = (
        "El catálogo se lee de la interfaz pública del Portal Único de Servicios, que "
        "permite el rastreo completo: se consulta el listado y la ficha de cada uno de los "
        "trámites publicados. La lectura se repite entera cada vez, de modo que una "
        "institución que deja de publicar desaparece del recuento en lugar de quedar "
        "congelada en su último valor.\n\n"
        "El tiempo de respuesta no tiene campo propio en el catálogo: cuando aparece, "
        "aparece dentro del texto descriptivo de la ficha. Se extrae con un criterio "
        "deliberadamente estrecho: la cifra se admite únicamente cuando está pegada a una "
        "expresión que la identifica como el plazo del trámite —«el tiempo de entrega es "
        "de», «se le entrega en», «este proceso toma»—. Una cifra de tiempo suelta se "
        "descarta sin contarse.")
    estrecho, amplio = v.get(TEMA_CON_TIEMPO), v.get(TEMA_CIFRA_SIN_ANCLAR)
    if estrecho and amplio and amplio > estrecho:
        razon = amplio / estrecho
        # Una décima, y con coma: el documento entero usa la convención española. Y sin el
        # «,0» cuando la razón es entera — «9,0 veces más» se lee como una precisión que la
        # cifra no tiene.
        cuantas = f"{razon:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        base += (
            f"\n\nEl criterio importa y puede medirse cuánto: aceptar cualquier cifra "
            f"seguida de una unidad de tiempo llevaría el recuento de "
            f"{_entero(estrecho)} a {_entero(amplio)} de {_entero(total)} fichas, {cuantas} "
            f"veces más. Esa diferencia no son plazos de trámites: son plazos de multas, "
            f"vigencias de documentos y condiciones de agenda. Publicarla sería publicar "
            f"una magnitud distinta de la que el título anuncia.")
    return base


#: Lo que este dato NO afirma. Va aparte del alcance genérico del informe porque es propio
#: del catálogo: el alcance genérico sirve para cualquier ley, esto solo para ésta.
LIMITES_TRAMITES = (
    "Este recuento consigna lo que el catálogo publica. No audita si el tiempo declarado "
    "por un trámite se cumple en la práctica, ni verifica la exactitud de la información "
    "que cada institución publica sobre sus propios procedimientos.\n\n"
    "Tampoco se estableció institución por institución el cumplimiento de las obligaciones "
    "que la ley impone al conjunto de la Administración. Las afirmaciones se limitan a lo "
    "que consta publicado en el Registro Único.\n\n"
    "Las observaciones sobre este inventario —una ficha que sí declara su tiempo y no fue "
    "detectada, una atribución que corregir— son bienvenidas y se incorporan con crédito.")


def _leido_el(filas: Any, periodo: str) -> Optional[str]:
    """Cuándo se leyó el dato de este período, de la propia serie.

    **La agenda no sirve para esto y por eso se dejó de usar.** El informe decía «la última
    lectura registrada es del 2026-08-25» leyendo el `last_run_at` de la agenda, mientras el
    dato que mostraba se había leído el 26: una corrida manual no mueve la agenda. El lector
    entiende esa frase como «cuándo se leyó este dato», y respondía con otra cosa.

    `None` cuando la serie no lo trae. No se sustituye por la fecha de la agenda: «cuándo
    corrió la operación» y «cuándo se leyó el dato» son afirmaciones distintas, y rellenar
    una con la otra es exactamente lo que produjo el error.

    Se lee de `published_at`, que en el resto de las series del módulo guarda la fecha en
    que el EMISOR publicó. Acá coinciden y no por casualidad: el catálogo de trámites es un
    estado continuo sin fecha de publicación —no hay una edición que el portal cierre—, así
    que la fecha de la lectura es la única fecha que ese dato tiene.
    """
    fechas = [f.published_at for f in filas
              if str(f.period) == periodo and getattr(f, "published_at", None)]
    return max(fechas).isoformat() if fechas else None


def _anexo_tramites(db: Any) -> Anexo:
    """La evidencia del catálogo de trámites: la prueba de la obligación del artículo 39.

    Se lee de la SERIE persistida, no del portal. Un informe que sale del console no puede
    dispararle 711 llamadas a un emisor público cada vez que alguien lo descarga: la serie ya
    la tiene la operación mensual, y usarla mantiene el documento reproducible —dos descargas
    del mismo día dan lo mismo— y barato.
    """
    from modules.social_dev.models.models import SocialIndicator
    from modules.social_dev.tramites_sync import (ENTIDAD, TEMA_CON_TIEMPO,
                                                  TEMA_CONSULTAS_POR_INSTITUCION, TEMA_PCT,
                                                  TEMA_POR_INSTITUCION, TEMA_TOTAL)

    if db is None:
        return Anexo(tablas=[])
    nacionales = (db.query(SocialIndicator)
                  .filter(SocialIndicator.entity_key == ENTIDAD,
                          SocialIndicator.theme.in_((TEMA_TOTAL, TEMA_CON_TIEMPO, TEMA_PCT)))
                  .all())
    if not nacionales:
        return Anexo(tablas=[])
    # El período MÁS RECIENTE, y se nombra en el título: una tabla sin fecha de lectura
    # sobre un catálogo vivo se lee como si fuera de hoy para siempre.
    periodo = max(str(f.period) for f in nacionales)
    v = {f.theme: f.value for f in nacionales if str(f.period) == periodo}
    if TEMA_TOTAL not in v:
        return Anexo(tablas=[])
    tablas: List[Tuple[str, List[List[str]]]] = [(
        f"El catálogo de trámites al {periodo}", [
            ["Concepto", "Valor"],
            ["Trámites publicados en el catálogo", _mil(v[TEMA_TOTAL])],
            ["Instituciones que publican", str(len(_por_sujeto(db, TEMA_POR_INSTITUCION,
                                                              periodo)))],
            ["Consultas ciudadanas acumuladas",
             _mil(sum(_por_sujeto(db, TEMA_CONSULTAS_POR_INSTITUCION, periodo).values()))],
            ["Declaran su tiempo de respuesta", str(int(v.get(TEMA_CON_TIEMPO, 0)))],
            ["Proporción sobre los publicados", f"{v.get(TEMA_PCT, 0)} %".replace(".", ",")],
        ])]

    # Las que más ciudadanos consultan, con cuántos trámites publican y si alguno declara su
    # tiempo. Ordenadas por CONSULTAS y no por número de trámites: una institución con 61
    # trámites y otra con 1,5 millones de consultas no pesan igual para quien espera.
    consultas = _por_sujeto(db, TEMA_CONSULTAS_POR_INSTITUCION, periodo)
    cantidad = _por_sujeto(db, TEMA_POR_INSTITUCION, periodo)
    declaran = _instituciones_que_declaran(db, periodo)
    if consultas:
        filas = [["Institución", "Trámites", "Consultas", "Declara algún tiempo"]]
        for sigla, n in sorted(consultas.items(), key=lambda kv: -kv[1])[:_TOP_INSTITUCIONES]:
            filas.append([sigla, str(int(cantidad.get(sigla, 0))), _mil(n),
                          "Sí" if sigla in declaran else "No"])
        tablas.append(("Las instituciones más consultadas", filas))

    # Y los que sí lo declaran, AGRUPADOS por institución y plazo. Sin agrupar salen catorce
    # filas de pasaporte con el mismo tiempo, que ocupan media página y no dicen nada más que
    # la primera.
    tiempos = _tiempos_declarados(db, periodo)
    if tiempos:
        grupos: Dict[Tuple[str, str, str], int] = {}
        for _slug, (_dias, nota) in tiempos.items():
            partes = [x.strip() for x in nota.split("·")]
            if len(partes) < 3:
                continue
            grupos[(partes[0], partes[1], partes[2])] = grupos.get(
                (partes[0], partes[1], partes[2]), 0) + 1
        filas = [["Institución", "Trámites", "Tiempo que declara la ficha", "Cómo lo dice"]]
        for (sigla, texto, nivel), n in sorted(grupos.items(), key=lambda kv: (-kv[1], kv[0])):
            filas.append([sigla, str(n), texto,
                          "Nombra el campo" if nivel == "explicito" else "Lo dice en prosa"])
        # El numerador sale de la SUMA de las filas, no de `len(tiempos)`: una fila con la
        # nota malformada se salta arriba, y un título que la contara igual afirmaría un
        # total que la tabla debajo no muestra.
        tablas.append((f"Los trámites que declaran cuánto tardan ({sum(grupos.values())} de "
                       f"{_mil(v[TEMA_TOTAL])})", filas))

    mas = _tabla_de_mas_consultados(db, periodo)
    if mas is not None:
        # Va DESPUÉS del catálogo y ANTES de los tiempos: primero qué publica el Estado,
        # después qué le pide la gente, y al final qué se sabe de cuánto tarda.
        tablas.insert(1, mas)
    return Anexo(tablas=tablas,
                 metodologia=_metodologia_tramites(db, periodo, float(v[TEMA_TOTAL])),
                 limites=LIMITES_TRAMITES,
                 leido_el=_leido_el(nacionales, periodo))


#: Anexos de evidencia propios de una ley. Se declaran por expediente y no se deducen: la
#: 167-21 tiene una serie que la sigue y las otras no, y un renderizador que adivinara cuál
#: aplicar acabaría poniéndole a una ley la evidencia de otra.
ANEXOS_POR_EXPEDIENTE = {
    "ley_167_21": _anexo_tramites,
}


def _entero(v: Any) -> int:
    """Un conteo de un resumen, como entero. Los resúmenes se tipan `Dict[str, object]` y de
    ahí no sale ni aritmética ni concordancia comprobables."""
    return int(v) if isinstance(v, (int, float)) else 0


def _plural(n: int, singular: str, plural: str, cero: Optional[str] = None) -> str:
    """Concordancia de número para la prosa del informe.

    «De los 1 indicadores… Los 1 restantes» es lo que sale de interpolar un contador en una
    frase escrita en plural. Se imprime en un documento que se comparte, y le dice al lector
    que nadie lo leyó antes de soltarlo.
    """
    if n == 0 and cero:
        return cero
    return singular if n == 1 else plural


def _prosa_de_declaraciones(dec: Dict[str, Any]) -> str:
    """Lo que el evaluado dijo sobre sus propios datos, en prosa y con su fecha.

    Cada una va con la consecuencia que tiene para lo que se mide. Citar lo que dijo el
    emisor sin decir qué implica deja al lector con una noticia, no con información.
    """
    partes = [
        "Los organismos evaluados han hecho declaraciones sobre la información que manejan. "
        "Se recogen porque cambian lo que puede afirmarse: «no hay dato» y «el organismo "
        "tiene el dato y declaró que no lo publica todavía» son cosas distintas."]
    for d in dec["declaraciones"]:
        cola = (f" El propio organismo indicó su disponibilidad a partir del "
                f"{d['disponible_desde']}." if d.get("disponible_desde") else
                " No se declaró una fecha a partir de la cual esté disponible.")
        partes.append(f"**{d['quien']}, {d['fecha']}.** {' '.join(d['que_declara'].split())}"
                      f"{cola} {' '.join(d['consecuencia_para_la_medicion'].split())}")
    return "\n\n".join(partes)


def _cuando_se_actualiza(expediente_id: str, db: Any,
                         leido_el: Optional[str] = None) -> Optional[str]:
    """Cuándo vuelve a leerse el dato: la CADENCIA de la agenda, la fecha de lectura del DATO.

    No de una frase escrita a mano. Una promesa de actualización redactada en el documento
    envejece en cuanto alguien cambia la cadencia, y el lector no tiene cómo enterarse; la
    agenda es la que manda de verdad y es la que se publica.

    Se resuelve por la `serie_de_seguimiento` que la obligación declara: si ninguna
    obligación de esta ley sigue una serie, el documento no promete ninguna actualización.

    **Cada dato de esta sección viene de donde ese dato vive.** La cadencia y la próxima
    corrida son hechos de la agenda. La ÚLTIMA LECTURA es un hecho del dato, y se recibe
    computada de la serie: usar el `last_run_at` de la agenda para eso publicó una fecha un
    día vieja —una corrida manual no mueve la agenda— y el lector no tenía cómo saberlo.
    """
    from modules.law_intel.obligaciones import cargar_obligaciones

    series = {o.serie_de_seguimiento for o in cargar_obligaciones(expediente_id)
              if o.serie_de_seguimiento}
    if not series or db is None:
        return None
    try:
        from shared.operations.models import OperationSchedule
    except Exception:                                      # pragma: no cover - defensivo
        return None
    nombres = [OPERACION_QUE_ALIMENTA[x] for x in series if x in OPERACION_QUE_ALIMENTA]
    if not nombres:
        logger.info("[informe_abierto] %s sigue %s y ninguna operación la declara alimentar",
                    expediente_id, sorted(series))
        return None
    filas = (db.query(OperationSchedule)
             .filter(OperationSchedule.operation.in_(nombres)).all())
    activas = [f for f in filas if f.enabled and f.interval_hours]
    if not activas:
        return None
    f = min(activas, key=lambda x: x.interval_hours)
    dias = round(f.interval_hours / 24)
    proxima = f.next_run_at.date().isoformat() if f.next_run_at else None
    partes = [f"El dato de este informe se vuelve a leer cada {dias} días."]
    if leido_el:
        partes.append(f"La lectura que se publica acá es del {leido_el}.")
    if proxima:
        partes.append(f"La próxima está prevista para el {proxima}.")
    partes.append(
        "La cadencia sale de la agenda del sistema que hace la lectura, no de una promesa "
        "escrita en este documento: si cambia, cambia acá.")
    return " ".join(partes)


def construir(expediente_id: str, db: Any = None) -> Dict[str, Any]:
    """Las secciones y las tablas del informe abierto de una ley.

    Devuelve la materia prima; el render es de quien llame. Separarlos deja probar el
    contenido sin generar un PDF, que es donde vive la mayor parte de lo que puede salir mal.
    """
    from modules.law_intel.bindings import cobertura as _cobertura
    from modules.law_intel.campo import resumen as _campo
    from modules.law_intel.obligaciones import cargar_obligaciones
    from modules.law_intel.obligaciones import resumen as _resumen_obligaciones
    from modules.law_intel.registro import cargar
    from modules.law_intel.declaraciones import publicable as _declaraciones
    from modules.law_intel.verificabilidad import publicable as _verificabilidad
    from modules.law_intel import lectura_juridica

    exp = cargar(expediente_id)
    cob = _cobertura(expediente_id)
    campo = _campo(expediente_id)
    obs: Dict[str, Any] = {
           "resumen": _resumen_obligaciones(expediente_id),
           "obligaciones": [
               {"articulo": o.articulo, "deber": o.deber, "deudor": o.deudor,
                "estado": o.estado, "consecuencia": o.consecuencia,
                "hito_de_medicion": o.hito_de_medicion, "periodicidad": o.periodicidad,
                "plazo": o.plazo}
               for o in cargar_obligaciones(expediente_id)]}
    ver = _verificabilidad(expediente_id)
    dec = _declaraciones(expediente_id)

    tablas: List[Tuple[str, Sequence[Sequence[str]]]] = [_tabla_de_cobertura(cob, campo)]
    for t in (_tabla_de_obligaciones(obs), _tabla_de_medicion(ver)):
        if t is not None:
            tablas.append(t)
    arma_anexo = ANEXOS_POR_EXPEDIENTE.get(expediente_id)
    anexo = arma_anexo(db) if (arma_anexo is not None and db is not None) else Anexo(tablas=[])
    tablas.extend(anexo.tablas)

    _actualiza = _cuando_se_actualiza(expediente_id, db, leido_el=anexo.leido_el)
    juridica = lectura_juridica.prosa(expediente_id)
    resumen_obs: Dict[str, Any] = obs.get("resumen") or {}
    lista_obs: List[Dict[str, Any]] = list(obs.get("obligaciones") or [])
    _calendario = _cuando_manda_la_ley_medir(exp, lista_obs)
    if _calendario and _calendario[1] is not None:
        # Va pegada a la tabla de obligaciones: las dos hablan de lo mismo y separarlas
        # obliga al lector a volver atrás.
        tablas.insert(min(2, len(tablas)), _calendario[1])
    con_consecuencia = sum(1 for o in lista_obs if o.get("consecuencia"))
    # Enteros explícitos: los resúmenes se tipan como `Dict[str, object]` y de ahí no sale
    # una concordancia comprobable — ni aritmética.
    medidos = _entero(cob.get("medidos"))
    total = _entero(cob.get("total"))
    sin_medicion = _entero(campo.get("declarados_sin_veredicto"))

    secciones = {
        "que_es": (
            f"La {exp.norma} —{exp.titulo}— fija obligaciones a cargo de la Administración "
            f"Pública, y en algunos casos indicadores con metas. Este documento consigna qué "
            f"ordena, qué puede medirse hoy de su cumplimiento y de dónde sale cada cifra. Se "
            f"comparte abierto porque un inventario de fuentes vale más cuando otros pueden "
            f"usarlo y corregirlo.\n\n"
            f"No emite juicio sobre el cumplimiento de las metas. Ese análisis se prepara por "
            f"encargo y no se publica."),
        "lo_que_ordena": (
            f"El instrumento contiene {resumen_obs.get('total', 0)} obligaciones con deudor y "
            f"plazo identificables. La tabla siguiente consigna su estado.\n\n"
            + (
                # El caso CERO se dice como lo que es —un hallazgo sobre la norma— y no
                # interpolando el contador en una frase escrita para el caso general:
                # «0 de ellas tienen una consecuencia… El resto no» no concuerda, y además
                # entierra lo interesante, que es que la ley no trae ningún mecanismo.
                "Ninguna de ellas trae una consecuencia jurídica asignada a su "
                "incumplimiento: la norma manda hacer cosas y no dice qué ocurre si no se "
                "hacen."
                if con_consecuencia == 0 else
                f"{con_consecuencia} de ellas "
                f"{_plural(con_consecuencia, 'tiene', 'tienen')} una consecuencia jurídica "
                f"asignada a su incumplimiento. "
                f"{_plural(resumen_obs.get('total', 0) - con_consecuencia, 'La restante no', 'Las restantes no')}: "
                f"la norma manda hacer algo y no dice qué ocurre si no se hace.")
            + f"\n\n{ADVERTENCIA_DEL_REGISTRO}"),
        # La lectura jurídica va junto a la tabla y no al final: dice de qué rango es cada
        # disposición y de dónde sale lo que exige, y sin eso la tabla se lee como si todo
        # lo que el informe mide lo mandara la ley.
        **({"lectura_juridica": juridica} if juridica else {}),
        "lo_que_se_mide": (
            _plural(total,
                    "La norma numera un solo indicador y "
                    + ("cuenta hoy con fuente verificada. " if medidos
                       else "no cuenta hoy con fuente verificada. "),
                    f"De los {total} indicadores que la norma numera, {medidos} "
                    f"{_plural(medidos, 'cuenta', 'cuentan')} hoy con una fuente "
                    f"verificada. ")
            + _plural(sin_medicion,
                      "El indicador sin medición tiene un motivo registrado.",
                      f"Los {sin_medicion} restantes tienen un "
                      f"motivo registrado y ninguno queda sin explicación.",
                      cero="Ninguno queda sin explicación.")
            + "\n\n"
            "Una serie se admite como medición de un indicador cuando reproduce, en el año "
            "que la norma señala, el valor que la norma fija como línea base. Una "
            "coincidencia de nombre sin coincidencia de valor no identifica la magnitud, y "
            "una coincidencia de valor sin coincidencia de concepto tampoco."),
        **({"lo_que_declara_el_emisor": _prosa_de_declaraciones(dec)} if dec["total"] else {}),
        **({"cuando_manda_la_ley_medir": _calendario[0]} if _calendario else {}),
        **({"como_se_obtuvo": anexo.metodologia} if anexo.metodologia else {}),
        **({"cuando_se_actualiza": _actualiza} if _actualiza else {}),
        "alcance": (
            (anexo.limites + "\n\n" if anexo.limites else "")
            + "Este documento no audita la exactitud de las cifras que publican los organismos "
            "citados ni verifica su conformidad con las metodologías que dichos organismos "
            "declaran. La identificación de un productor no constituye validación de sus "
            "cifras.\n\n"
            "Los valores corresponden al último período publicado a la fecha de emisión y "
            "pueden ser objeto de revisión por sus productores. El inventario se actualiza de "
            "forma continua.\n\n"
            "Las observaciones —una fuente que falte, una atribución que corregir— son "
            "bienvenidas y se incorporan con crédito: info@sdqconsulting.com.do"),
    }
    return {
        "expediente": expediente_id,
        "titulo": f"{exp.titulo} ({exp.norma})",
        "secciones": secciones,
        "tablas": tablas,
        "titulares": {"medidos": medidos, "total": total,
                      "obligaciones": resumen_obs.get("total", 0)},
    }


SECCIONES_EN_ORDEN = ("que_es", "lo_que_ordena", "lectura_juridica",
                      "cuando_manda_la_ley_medir", "lo_que_se_mide",
                      "lo_que_declara_el_emisor", "como_se_obtuvo", "cuando_se_actualiza",
                      "alcance")

TITULOS = {
    "que_es": "Qué es este documento",
    "lo_que_ordena": "Qué ordena la norma",
    "lectura_juridica": "Qué alcance tiene cada disposición",
    "lo_que_se_mide": "Qué se mide, y cómo se verifica",
    "lo_que_declara_el_emisor": "Qué declara el organismo sobre su propia información",
    "como_se_obtuvo": "Cómo se obtuvo la medición",
    # Dos preguntas distintas, y el orden importa: primero cuándo manda la NORMA medir
    # —que es exigible— y después cada cuánto relee el dato esta plataforma, que es un
    # detalle nuestro. El título de la segunda lo dice para que no se confundan.
    "cuando_manda_la_ley_medir": "Cuándo manda la ley que se mida",
    "cuando_se_actualiza": "Cuándo vuelve a leerse el dato de este informe",
    "alcance": "Alcance y limitaciones",
}


def _titular(t: Dict[str, int]) -> str:
    """La cifra de portada, elegida por lo que la norma ES.

    «Mide 0 de 1 indicadores» es cierto y se lee como un fracaso, cuando lo que pasa es que
    la Ley 167-21 no es una ley de metas: son obligaciones. Titular por indicadores a una
    norma que casi no tiene le pone al documento una vara que su objeto no admite.
    """
    medidos, total, obs = t["medidos"], t["total"], t["obligaciones"]
    if medidos:
        return f"Mide {medidos} de {total} indicadores"
    if obs:
        return _plural(obs, "1 obligación con deudor y plazo",
                       f"{obs} obligaciones con deudor y plazo")
    return _plural(total, "1 indicador numerado", f"{total} indicadores numerados")


def render(expediente_id: str, db: Any = None, fmt: str = "pdf",
           output_dir: Optional[str] = None) -> str:
    """Genera el archivo del informe abierto y devuelve su ruta."""
    from shared.products.render import render_product_pdf

    d = construir(expediente_id, db)
    t = d["titulares"]
    return render_product_pdf(
        sector_key="law", display_name="SDQ Evaluación de Leyes",
        title=d["titulo"],
        period="",
        narratives={k: d["secciones"][k] for k in SECCIONES_EN_ORDEN if k in d["secciones"]},
        section_titles=TITULOS,
        tables=d["tablas"], charts=[],
        headline=_titular(t),
        subtitle="Documento abierto — qué ordena la norma y qué puede medirse de ella",
        watermark=MARCA, sample=False, output_dir=output_dir, fmt=fmt)
