"""Qué serie viva mide cada indicador de la ley, y en qué estado está esa afirmación.

**El estado es lo que hace honesta la cobertura.** Un binding `propuesto` es una hipótesis:
la serie parece medir el indicador y nadie lo comprobó. Contarlo como cobertura afirma haber
medido algo que no se midió — y la cobertura de portada es justamente la cifra que el cliente
usa para decidir si el informe le sirve.

**La dirección se COMPUTA de las metas de la ley y el binding la confirma.** Si no coinciden,
el expediente no carga. Es el guard contra el defecto más repetido de esta plataforma: la
cifra correcta con el sentido invertido — que en este dominio significa publicar que un
indicador mejoró cuando empeoró.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from modules.law_intel.registro import RAIZ, Expediente, ExpedienteInvalido, Indicador, cargar

# Solo los verificados cuentan para la cobertura publicada.
ESTADOS = {
    "verificado": "la serie existe, devuelve dato y se contrastó contra la fuente",
    "propuesto": "plausible, sin comprobar — NO cuenta como cobertura",
    "descartado": "se evaluó y no mide lo que el eje afirma medir",
}
CUENTA_COBERTURA = frozenset({"verificado"})

DIRECCIONES = frozenset({"menor", "mayor"})

# Los caminos por los que un binding llega a `verificado`. Conjunto CERRADO, y el que se
# usó viaja hasta la portada: la cifra de cobertura no puede leerse como si todos hubieran
# pasado por el mismo filtro. Eran dos y son tres; abrir uno nuevo es decisión del dueño, no
# una salida para un indicador que no cierra.
#
# `oraculo` es el fuerte y sigue siendo el default: la serie reproduce la LÍNEA BASE que la
# ley declara, en el año que la ley declara. Es una coincidencia de magnitud contra un valor
# que el legislador escribió, y no se puede fabricar.
#
# `identidad_de_concepto` existe porque varias líneas base son de 2008-2010 y ninguna serie
# viva llega tan atrás — el anexo del MEM empieza en 2019. Sin este camino esos indicadores no
# son «dudosos»: son inverificables para siempre, y el informe diría «no lo medimos» sobre un
# dato que el propio Estado publica con el nombre que el legislador le puso.
#
# Lo que NO es: aceptar un parecido de etiqueta. El término tiene que ser el que usa el
# EMISOR en su publicación, y `_identidad_comprobada` lo contrasta contra el nombre del
# indicador en la ley. La declaración no se cree: se comprueba.
#
# `revision_declarada` cubre el caso que los otros dos dejaban afuera: el oráculo CORRE, falla,
# y el emisor publica la causa —revisó su propia metodología—. Sin él, un indicador cuyo
# emisor mejoró su compilación queda inverificable para siempre y el informe diría «no lo
# medimos» sobre una serie que el Estado publica con el nombre exacto que el legislador le
# puso: castigaría al emisor por revisar bien. Sus cuatro candados y por qué cada uno hace
# falta están en `modules.law_intel.anadas`.
VERIFICADO_POR = {
    "oraculo": "la serie reproduce la línea base de la ley en el año que la ley fija",
    "identidad_de_concepto": ("el emisor publica la magnitud con el término del legislador, y "
                              "la línea base de la ley cae fuera del alcance de la serie"),
    "revision_declarada": ("el oráculo corre y falla, el emisor DECLARA la revisión de "
                           "metodología que lo explica, y el margen contra las metas se come "
                           "la corrección"),
}

# Palabras de MEDICIÓN, que nombran la forma y no el fenómeno. Un término que solo coincide
# en éstas no identifica nada: «índice», «tasa» y «número» encabezan medio articulado.
_GENERICAS = frozenset({
    "indice", "indices", "tasa", "tasas", "numero", "porcentaje", "proporcion", "nivel",
    "niveles", "monto", "montos", "razon", "cantidad", "promedio", "valor", "total",
    "anual", "nacional", "general", "sector", "sectores", "electrico", "publico",
})

# Cuántos caracteres tiene que compartir un token del emisor con uno de la ley para contar.
# Cinco deja pasar singular/plural —«cobranzas» contra «cobranza»— sin volver equivalentes a
# dos palabras que solo comparten la raíz corta.
_PREFIJO_MINIMO = 5

# Transformaciones admitidas entre la variable de la plataforma y el indicador de la ley.
# Es un conjunto CERRADO y con nombre, no una expresión libre: una fórmula arbitraria en un
# archivo de datos es código sin revisar, y acá decide qué cifra se publica.
#
# El caso que la motiva: el indicador 2.19 es ANALFABETISMO y la variable del panel es
# alfabetización. Sin declarar la transformación, el binding publicaría el complemento — el
# valor invertido.
TRANSFORMACIONES = {
    "complemento_100": (lambda v: 100.0 - v,
                        "el indicador es el complemento porcentual de la variable"),
    # El GINI: el Banco Mundial lo publica en 0-100 y la END lo fija en 0-1 (línea base
    # 0,49 para 2010). Sin declararlo, el binding contrastaría 47,3 contra una meta de
    # 0,45 y el semáforo diría «no alcanzada» por un factor de cien. Se declara acá y no
    # se divide al ingerir: dividir en la sync guardaría un número que ya no es el que el
    # emisor publica, y el día que alguien coteje contra el Banco Mundial no cuadraría.
    "centesimal": (lambda v: v / 100.0,
                   "el emisor publica en 0-100 y el indicador se fija en 0-1"),
}


def aplicar_transformacion(b: "Binding", valor: float) -> float:
    """Lleva el valor de la variable a la magnitud del indicador."""
    if not b.transformacion:
        return valor
    fn, _ = TRANSFORMACIONES[b.transformacion]
    return float(fn(valor))


@dataclass(frozen=True)
class Binding:
    indicador: str
    serie: str
    fuente: str
    mejor: str
    estado: str
    # Duda ABIERTA sobre si la variable mide el indicador. Mientras esté, no promueve.
    nota_comparabilidad: Optional[str] = None
    # Hallazgo RESUELTO: cómo se comprobó qué mide la variable, o qué salvedad hay que
    # declarar en el informe. No bloquea — documenta. Separarlas importa porque si la única
    # forma de dejar constancia fuera la nota que frena, la gente borraría la constancia
    # para poder promover.
    nota: Optional[str] = None
    motivo_descarte: Optional[str] = None
    # Cuando la variable mide la magnitud complementaria o en otra unidad. Declarada, con
    # nombre de un conjunto cerrado: una transformación sin declarar es una cifra inventada.
    transformacion: Optional[str] = None
    # Período del dato con el que se verificó. Obligatorio al promover, y por una razón que
    # no es burocrática: sin él el producto no puede declarar su frescura y el readiness la
    # penaliza a la mitad — un «no aplica» honesto puntuaba igual que un dato medio rancio.
    # Va como CAMPO y no en la prosa de `nota` porque un dato que hay que parsear de un texto
    # deja de ser un dato.
    periodo_verificado: Optional[str] = None
    # SERIES YA EVALUADAS Y RECHAZADAS para ESTE indicador, cada una con su motivo.
    #
    # `motivo_descarte` cuelga del indicador, pero un descarte es siempre sobre un CANDIDATO
    # concreto. Mientras un indicador tuvo una sola serie evaluada eso no se notaba; al
    # aparecer una mejor, el modelo obligaba a BORRAR el descarte para poder atar la nueva —
    # y con él se iba el registro que impide que alguien vuelva a proponer la mala. Pasó con
    # el 3.26: se había rechazado el ingreso familiar mensual, y la serie que la ley nombra
    # (INB por método Atlas) no podía entrar sin perder esa constancia.
    #
    # Importa más ahora que antes: un barrido automático propone candidatos por lotes, así
    # que el registro de lo ya rechazado tiene que ser ACUMULATIVO, no excluyente.
    candidatos_descartados: Tuple[Dict[str, str], ...] = ()
    # CADENCIA del emisor, en años. Solo se declara cuando NO es anual, y sirve para una cosa:
    # que la regla de frescura no confunda «el emisor dejó de publicar» con «el emisor publica
    # cada seis años».
    #
    # Son situaciones opuestas. La desnutrición infantil está congelada de verdad: la última
    # ENDESA con esos módulos es de 2019 y no hay reemplazo. Las pruebas del LLECE se aplican
    # cada ~6 años —2006, 2013, 2019— así que su dato de 2019 ES el más reciente que existe en
    # el mundo. Con un umbral fijo de 3 años, una prueba hexenal NUNCA puede estar fresca y el
    # informe diría «no lo medimos» sobre la única medición disponible.
    #
    # Se DECLARA por binding y nunca se infiere: aflojar el guard de frescura para todos sería
    # exactamente el error que el guard existe para evitar. Sin declarar, rige el umbral anual.
    cadencia_anios: Optional[int] = None
    # QUIÉN produce la medición, y quién solo la publica. Son dos cosas distintas y el
    # informe cita la primera: una serie del Banco Mundial parece evidencia de tercero y en
    # la mayoría de los casos retransmite la cifra que produjo el Estado evaluado.
    #
    # Se declara POR BINDING y jamás se deduce del `id` de la fuente. El WDI publica a la vez
    # estimaciones propias (mortalidad de menores, subalimentación) y retransmisiones
    # (usuarios de internet, mujeres en Diputados); graduar por emisor le pondría la misma
    # etiqueta a las dos e inflaría la independencia declarada del informe — en la dirección
    # que le conviene a quien lo vende.
    #: Cómo llegó este binding a `verificado`. Ver `VERIFICADO_POR`. Va como CAMPO y no en
    #: la prosa de una nota porque la cifra de cobertura se desagrega por esto: publicar «22
    #: medidos» sin decir cuántos pasaron por cada filtro es publicar una sola cifra sobre dos
    #: poblaciones distintas.
    verificado_por: str = "oraculo"
    #: El término EXACTO con el que el emisor publica la magnitud. Obligatorio cuando se
    #: verifica por identidad de concepto, y no se cree: se contrasta contra el nombre que la
    #: ley le puso al indicador.
    termino_del_emisor: Optional[str] = None
    #: La declaración del emisor sobre su propia revisión, para el camino
    #: `revision_declarada`. Lleva `texto`, `donde` y `verificado_el`: es una afirmación
    #: sobre el mundo y por eso va con evidencia FECHADA, igual que en el campo.
    declaracion_del_emisor: Optional[Dict[str, str]] = None
    #: Los valores que distintas añadas publican para el AÑO BASE de la ley. Se declaran los
    #: INSUMOS y no la conclusión: el factor de corrección y si el margen lo absorbe los
    #: computa `modules.law_intel.anadas`. Una conclusión copiada a mano se desincroniza.
    anadas: Tuple[Dict[str, Any], ...] = ()
    origen: Optional[str] = None
    #: El productor, con nombre. Va aparte del origen porque el origen es una categoría y
    #: esto es la cadena concreta que un lector puede ir a comprobar.
    productor: Optional[str] = None

    @property
    def cuenta(self) -> bool:
        return self.estado in CUENTA_COBERTURA


def _sin_tildes(t: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                   if unicodedata.category(c) != "Mn")


def _tokens(texto: str) -> List[str]:
    return [t for t in re.split(r"[^0-9a-záéíóúñü]+", _sin_tildes(texto)) if len(t) > 2]


def identidad_comprobada(termino: str, nombre_del_indicador: str) -> Tuple[bool, str]:
    """¿El término del emisor identifica al indicador que la ley escribió?

    Dos condiciones, y las dos hacen falta:

    1. **Todos** los tokens significativos del emisor aparecen en el nombre del indicador
       (por prefijo, para tolerar singular/plural). Si el emisor dice algo que la ley no
       dice, no está nombrando lo mismo.
    2. Al menos uno de los que coinciden NO es una palabra de medición. «Índice», «tasa» y
       «nivel» encabezan medio articulado: coincidir solo en ésas es coincidir en la forma,
       no en el fenómeno.

    Devuelve `(vale, motivo)` — el motivo se publica cuando no vale, porque un rechazo sin
    razón manda a adivinar.
    """
    del_emisor = _tokens(termino)
    if not del_emisor:
        return False, "el término del emisor no tiene ninguna palabra significativa"
    de_la_ley = _tokens(nombre_del_indicador)

    def _esta(t: str) -> bool:
        return any(t[:_PREFIJO_MINIMO] == otro[:_PREFIJO_MINIMO] and
                   (t.startswith(otro[:_PREFIJO_MINIMO]) or
                    otro.startswith(t[:_PREFIJO_MINIMO]))
                   for otro in de_la_ley)

    ausentes = [t for t in del_emisor if not _esta(t)]
    if ausentes:
        return False, (f"el término del emisor dice {ausentes}, que no está en el nombre que "
                       f"la ley le puso al indicador")
    if all(t in _GENERICAS for t in del_emisor):
        return False, (f"el término solo coincide en palabras de medición ({del_emisor}): "
                       f"eso identifica la forma, no el fenómeno")
    return True, ""


def direccion_de_metas(ind: Indicador) -> str:
    """Hacia dónde manda mejorar la ley, leído de la propia trayectoria de metas.

    Se computa en vez de creerle a un campo escrito a mano: la serie 24,8 → 20 → 15 → 10 → 4
    dice sola que menos es mejor. Devuelve ``plana`` cuando la ley pide sostener (áreas
    protegidas: 24,4 en los cuatro cortes) y ``ambigua`` cuando la trayectoria no es monótona,
    caso en el que ningún veredicto automático es defendible.
    """
    vals = [v for v in ([ind.base_valor] + list(ind.metas.values()))
            if isinstance(v, (int, float))]
    if len(vals) < 2:
        return "ambigua"
    subes = sum(b > a for a, b in zip(vals, vals[1:]))
    bajas = sum(b < a for a, b in zip(vals, vals[1:]))
    if subes and bajas:
        return "ambigua"
    if subes:
        return "mayor"
    if bajas:
        return "menor"
    return "plana"


@lru_cache(maxsize=8)
def cargar_bindings(expediente_id: str) -> Dict[str, Binding]:
    import yaml  # type: ignore[import-untyped]

    ruta = RAIZ / expediente_id.replace("/", "") / "bindings.yaml"
    if not ruta.exists():
        return {}
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    # El YAML trae la lista de candidatos rechazados como lista de dicts; el dataclass la
    # congela en tupla para que siga siendo inmutable como el resto del binding.
    def _armar(d: Dict[str, Any]) -> Binding:
        d = dict(d)
        cd = d.pop("candidatos_descartados", None) or ()
        an = d.pop("anadas", None) or ()
        return Binding(**d, candidatos_descartados=tuple(dict(c) for c in cd),
                       anadas=tuple(dict(a) for a in an))

    bs = [_armar(b) for b in (doc.get("bindings") or [])]
    _validar(cargar(expediente_id), bs)
    return {b.indicador: b for b in bs}


def _validar(exp: Expediente, bindings: List[Binding]) -> None:
    # El vocabulario de orígenes vive en `verificabilidad`, que es el módulo que razona
    # sobre él, y ese módulo importa de éste. El import va acá adentro para que la
    # dependencia sea en un solo sentido en tiempo de carga: cuando `_validar` corre,
    # este módulo ya terminó de importarse y no hay ciclo.
    from modules.law_intel.verificabilidad import ORIGENES_DE_INDICADOR

    por_id = {i.id: i for i in exp.indicadores}

    # El duplicado es una propiedad del CONJUNTO, no de un binding suelto, y por eso va en
    # una pasada aparte: dentro del bucle, cualquier regla que falle en la primera copia lo
    # tapaba y el mensaje culpaba a otra cosa.
    vistos = set()
    for b in bindings:
        if b.indicador in vistos:
            raise ExpedienteInvalido(f"binding duplicado para {b.indicador}")
        vistos.add(b.indicador)

    for b in bindings:
        if b.indicador not in por_id:
            raise ExpedienteInvalido(f"binding a un indicador inexistente: {b.indicador}")
        if b.estado not in ESTADOS:
            raise ExpedienteInvalido(f"{b.indicador}: estado desconocido '{b.estado}'")
        if b.mejor not in DIRECCIONES:
            raise ExpedienteInvalido(f"{b.indicador}: 'mejor' debe ser menor|mayor")
        if b.transformacion and b.transformacion not in TRANSFORMACIONES:
            raise ExpedienteInvalido(
                f"{b.indicador}: transformación '{b.transformacion}' no está en el conjunto "
                f"admitido {sorted(TRANSFORMACIONES)}. No se aceptan fórmulas libres.")

        # La fuente tiene que estar en la lista blanca del expediente. Es la restricción que
        # sostiene la independencia, y por eso se hace cumplir al cargar y no al redactar.
        # Un binding DESCARTADO se exceptúa: su razón de ser es dejar registrada la fuente
        # que se evaluó y por qué no sirve.
        if b.estado != "descartado" and not exp.fuente_admitida(b.fuente):
            raise ExpedienteInvalido(
                f"{b.indicador}: fuente '{b.fuente}' fuera de la lista blanca del expediente")
        if b.estado == "descartado" and not b.motivo_descarte:
            raise ExpedienteInvalido(f"{b.indicador}: descartado sin motivo declarado")

        ind = por_id[b.indicador]
        computada = direccion_de_metas(ind)
        if computada in DIRECCIONES and b.mejor != computada:
            raise ExpedienteInvalido(
                f"{b.indicador}: el binding dice que mejor es '{b.mejor}' pero las metas de la "
                f"ley van hacia '{computada}'. Una de las dos está mal y el veredicto saldría "
                f"invertido.")

        # Promover sin declarar el período del dato deja al producto sin frescura, y sin
        # frescura el readiness lo penaliza a la mitad. Se exige acá y no se deduce del
        # registro: la promoción es un hecho comiteado y su período también.
        if b.cuenta and not (b.periodo_verificado or "").strip():
            raise ExpedienteInvalido(
                f"{b.indicador}: verificado sin `periodo_verificado`. Poné el período del "
                f"dato con el que se comprobó (lo devuelve /bindings/verificacion).")

        if b.verificado_por not in VERIFICADO_POR:
            raise ExpedienteInvalido(
                f"{b.indicador}: `verificado_por` desconocido '{b.verificado_por}'; "
                f"admitidos {sorted(VERIFICADO_POR)}")

        # El camino de identidad de concepto tiene tres candados, y los tres hacen falta.
        # Sin ellos sería la puerta por la que entra «se parece»: exactamente lo que el
        # oráculo existe para cerrar.
        if b.cuenta and b.verificado_por == "identidad_de_concepto":
            if not (b.termino_del_emisor or "").strip():
                raise ExpedienteInvalido(
                    f"{b.indicador}: verifica por identidad de concepto y no declara el "
                    f"término con el que el emisor publica la magnitud. Sin él no hay nada "
                    f"que comprobar y la identidad sería una afirmación nuestra.")
            vale, motivo = identidad_comprobada(b.termino_del_emisor or "",
                                                por_id[b.indicador].nombre)
            if not vale:
                raise ExpedienteInvalido(f"{b.indicador}: {motivo}")
            if (b.nota_comparabilidad or "").strip():
                raise ExpedienteInvalido(
                    f"{b.indicador}: no se verifica por identidad de concepto con una duda de "
                    f"comparabilidad ABIERTA. O la duda está resuelta y pasa a `nota`, o el "
                    f"binding no promueve.")
            if not (b.nota or "").strip():
                raise ExpedienteInvalido(
                    f"{b.indicador}: verifica por identidad de concepto y no trae `nota`. La "
                    f"salvedad —que el oráculo de la ley no alcanza la serie— tiene que "
                    f"viajar impresa al informe; sin ella la cobertura se lee como si todos "
                    f"hubieran pasado por el filtro fuerte.")

        # El tercer camino: el oráculo corrió, falló, y el emisor declara por qué. Tiene los
        # mismos candados que la identidad de concepto MÁS dos propios, y los dos propios son
        # los que impiden que sea «el oráculo falló, igual lo promuevo».
        if b.cuenta and b.verificado_por == "revision_declarada":
            from modules.law_intel.anadas import Anada, alguna_reproduce_la_base

            if not (b.termino_del_emisor or "").strip():
                raise ExpedienteInvalido(
                    f"{b.indicador}: verifica por revisión declarada y no dice con qué término "
                    f"publica el emisor. Sin identidad de término esto sería aceptar cualquier "
                    f"serie cuya diferencia se pueda explicar con una historia.")
            vale, motivo = identidad_comprobada(b.termino_del_emisor or "",
                                                por_id[b.indicador].nombre)
            if not vale:
                raise ExpedienteInvalido(f"{b.indicador}: {motivo}")

            dec = b.declaracion_del_emisor or {}
            faltan = [k for k in ("texto", "donde", "verificado_el")
                      if not str(dec.get(k, "")).strip()]
            if faltan:
                raise ExpedienteInvalido(
                    f"{b.indicador}: la revisión la tiene que declarar el EMISOR, y falta "
                    f"{', '.join(faltan)} en `declaracion_del_emisor`. Sin texto, sin dónde "
                    f"aparece y sin la fecha en que se comprobó, la revisión es una hipótesis "
                    f"nuestra sobre por qué no cuadra — que es exactamente lo que este camino "
                    f"no puede admitir.")

            try:
                anadas = [Anada.desde(a) for a in b.anadas]
            except ValueError as e:
                raise ExpedienteInvalido(f"{b.indicador}: {e}") from e
            if len(anadas) < 2:
                raise ExpedienteInvalido(
                    f"{b.indicador}: verifica por revisión declarada con {len(anadas)} añada(s). "
                    f"Hacen falta al menos dos: una sola cifra que no cuadra no es una revisión, "
                    f"es una discrepancia sin historia.")

            base = por_id[b.indicador].base_valor
            if base is None:
                raise ExpedienteInvalido(
                    f"{b.indicador}: verifica por revisión declarada y la ley no le fija línea "
                    f"base. Sin base no hubo oráculo que fallara, y este camino existe para "
                    f"un oráculo que falló.")
            reproduce = alguna_reproduce_la_base(float(base), anadas)
            if reproduce is not None:
                raise ExpedienteInvalido(
                    f"{b.indicador}: la añada «{reproduce.fuente}» SÍ reproduce la línea base "
                    f"({reproduce.valor} contra {base}). Entonces el camino es el oráculo "
                    f"contra esa añada, no la revisión declarada. Un camino de excepción que "
                    f"se usa cuando el normal alcanza deja de ser una excepción.")

            # El CUARTO candado —que el margen se coma la corrección— no se puede comprobar
            # acá: necesita las observaciones, y las observaciones viven donde están los
            # datos, no en el YAML. Transcribirlas al expediente sería peor que no tenerlas,
            # porque son justamente las cifras que el emisor puede volver a revisar.
            #
            # Va donde va el oráculo, que tiene el mismo problema y la misma solución:
            # `modules.law_intel.verificacion` lo computa contra la serie real y lo devuelve
            # en `/bindings/verificacion`. Promover sin haberlo corrido es el mismo error que
            # promover sin haber corrido la sonda.

            if (b.nota_comparabilidad or "").strip():
                raise ExpedienteInvalido(
                    f"{b.indicador}: no se verifica por revisión declarada con una duda de "
                    f"comparabilidad ABIERTA. O la duda está resuelta y pasa a `nota`, o el "
                    f"binding no promueve.")
            if not (b.nota or "").strip():
                raise ExpedienteInvalido(
                    f"{b.indicador}: verifica por revisión declarada y no trae `nota`. La "
                    f"salvedad —que la cifra de la ley es de otra añada— tiene que viajar "
                    f"impresa al informe.")

        # De dónde sale la evidencia. Se exige a TODOS los bindings y no solo a los
        # verificados: la sección de verificabilidad cuenta también lo que la ley PERDIÓ, y
        # un descarte sin origen declarado desaparece de esa cuenta en vez de sumar a ella.
        if not (b.origen or "").strip():
            raise ExpedienteInvalido(
                f"{b.indicador}: sin `origen` declarado. Quién produce la medición decide "
                f"cuánto pesa el veredicto y no se deduce del emisor.")
        if b.origen not in ORIGENES_DE_INDICADOR:
            raise ExpedienteInvalido(
                f"{b.indicador}: origen '{b.origen}' fuera del conjunto admitido "
                f"{sorted(ORIGENES_DE_INDICADOR)}.")
        if not (b.productor or "").strip():
            raise ExpedienteInvalido(
                f"{b.indicador}: declara origen y no dice QUIÉN produce la medición. Una "
                f"categoría sin cadena concreta no se puede ir a comprobar.")


def cobertura(expediente_id: str) -> Dict[str, object]:
    """La cifra de portada, con su denominador explícito.

    Se publica sobre los indicadores NUMERADOS de la ley, no sobre las filas medibles: son
    denominadores distintos (90 contra 135) y elegir en silencio infla o desinfla el
    porcentaje según convenga.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    numerados = exp.numerados
    verificados = [i for i in numerados if (b := bs.get(i.id)) and b.cuenta]
    propuestos = [i for i in numerados if (b := bs.get(i.id)) and b.estado == "propuesto"]
    # Desagregada por CAMINO. Una sola cifra de cobertura sobre dos filtros distintos es una
    # cifra sobre dos poblaciones distintas, y la portada es justo donde eso no se puede
    # hacer: el cliente decide con este número si el informe le sirve.
    por_camino = {c: sum(1 for i in verificados if bs[i.id].verificado_por == c)
                  for c in VERIFICADO_POR}
    return {
        "denominador": "indicadores numerados de la ley",
        "total": len(numerados),
        "medidos": len(verificados),
        "medidos_por_camino_de_verificacion": por_camino,
        "que_significa_cada_camino": VERIFICADO_POR,
        "pct": round(100.0 * len(verificados) / len(numerados), 1) if numerados else 0.0,
        "propuestos_sin_verificar": len(propuestos),
        "nota": ("Los bindings propuestos NO cuentan como cobertura: la serie parece medir el "
                 "indicador y todavía nadie lo comprobó contra la fuente."),
    }
