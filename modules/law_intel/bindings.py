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
    origen: Optional[str] = None
    #: El productor, con nombre. Va aparte del origen porque el origen es una categoría y
    #: esto es la cadena concreta que un lector puede ir a comprobar.
    productor: Optional[str] = None

    @property
    def cuenta(self) -> bool:
        return self.estado in CUENTA_COBERTURA


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
        return Binding(**d, candidatos_descartados=tuple(dict(c) for c in cd))

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
    return {
        "denominador": "indicadores numerados de la ley",
        "total": len(numerados),
        "medidos": len(verificados),
        "pct": round(100.0 * len(verificados) / len(numerados), 1) if numerados else 0.0,
        "propuestos_sin_verificar": len(propuestos),
        "nota": ("Los bindings propuestos NO cuentan como cobertura: la serie parece medir el "
                 "indicador y todavía nadie lo comprobó contra la fuente."),
    }
