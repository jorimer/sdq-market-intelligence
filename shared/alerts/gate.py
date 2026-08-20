"""Los seis vetos — el único camino de una regla a la bandeja del cliente.

**Por qué el gate es el centro de este módulo y no el motor.** Una alerta es una afirmación
PUBLICADA con menos revisión humana que ningún otro artefacto de la plataforma, y encima
llega sola: el informe hay que ir a buscarlo, la alerta ya está en la bandeja. Todo lo que
la doctrina de la casa le exige a un informe se lo exige a una alerta con más razón.

Los seis vetos, y de qué defecto real salió cada uno:

1. **Frescura** — ``True`` publica, ``False`` no, y **``None`` tampoco**. Producción sirvió
   19 días un Gini de 0,44 calculado con un score que ya no existía porque nadie distinguió
   «no sé de cuándo es» de «está al día».
2. **Brecha** — ninguna cifra ``None`` sostiene una afirmación. Un dato ausente se declara
   (para eso está el código ``brecha``), no se rellena ni se ignora.
3. **Comparabilidad** — una posición sin universo declarado no se publica. Un score armado
   sobre 3 de 5 dimensiones no rankea contra uno de 5; ya se publicó «7 de 35» así.
4. **Sujeto** — toda porción nombra su población. Se publicó «cuatro compañías concentran
   el 87,1%» cuando eran cuatro RAMOS.
5. **Relación** — si el texto afirma una dirección, tiene que venir COMPUTADA en
   ``relaciones``. La glosa sobrevivió dos veces a corregir el número.
6. **Vocabulario** — una regla de umbral es una señal a monitorear, nunca una probabilidad.
   Lo prohíbe `docs/CLAIMS_COMERCIALES.md` para todo lo que no tenga backtest contra un
   desenlace externo.

**Lo vetado se LISTA, no desaparece.** :func:`juzgar` devuelve siempre un veredicto con su
motivo, y el motor lo persiste. Un veto silencioso se lee como que el eje no tenía nada que
avisar, que es la lectura opuesta a la verdadera.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from shared.alerts.reglas import AlertEvent
from shared.narrative.sujeto import nombra_su_poblacion

# Vocabulario que afirma una dirección. Si aparece en el texto, ``relaciones`` tiene que
# traer la dirección computada — si no, la frase la infirió quien escribió la plantilla.
COMPARATIVOS: Tuple[str, ...] = (
    "por debajo", "por encima", "mayor que", "menor que", "más alto", "más bajo",
    "supera", "cae", "sube", "baja", "pasó de", "empeor", "mejor",
)

# Vocabulario PROHIBIDO: convierte una señal de monitoreo en un pronóstico.
PROHIBIDO: Tuple[str, ...] = (
    "predice", "predicción", "prediccion", "predictivo", "pronostica", "pronóstico",
    "probabilidad de", "riesgo de quiebra", "va a quebrar", "quebrará", "default inminente",
)

# Claves de ``relaciones`` que afirman una POSICIÓN y por lo tanto exigen universo.
POSICIONALES: Tuple[str, ...] = ("posicion", "ranking", "puesto", "de_n", "percentil")


@dataclass(frozen=True)
class Veredicto:
    """Resultado del gate. ``motivo`` es una clave estable (para contar y agrupar);
    ``detalle`` es la explicación legible que se le muestra a quien pregunte por qué."""

    publica: bool
    motivo: Optional[str] = None
    detalle: str = ""


PUBLICA = Veredicto(publica=True)


def veto_frescura(e: AlertEvent) -> Optional[Veredicto]:
    """El tercer estado es el que importa: ``None`` es indeterminado y NO publica."""
    if e.frescura is True:
        return None
    if e.frescura is False:
        return Veredicto(False, "frescura_vencida",
                         "El dato que sostiene esta señal ya no está vigente.")
    return Veredicto(False, "frescura_indeterminada",
                     "No se pudo establecer si el dato que sostiene esta señal está "
                     "vigente. «No sé de cuándo es» no es «está al día».")


def veto_brecha(e: AlertEvent) -> Optional[Veredicto]:
    """Ninguna cifra ausente sostiene una afirmación — salvo en una alerta de brecha, que
    es precisamente la que existe para declararla."""
    if e.codigo == "brecha":
        return None
    faltan = [k for k, v in e.valores.items() if v is None]
    if faltan:
        return Veredicto(False, "cifra_ausente",
                         f"La señal se apoya en cifras sin dato: {', '.join(sorted(faltan))}.")
    return None


def veto_comparabilidad(e: AlertEvent) -> Optional[Veredicto]:
    """Una posición sin universo declarado no se puede publicar: no se sabe contra quién."""
    posicional = any(any(p in str(k).lower() for p in POSICIONALES) for k in e.relaciones)
    if posicional and not e.universo:
        return Veredicto(False, "universo_no_declarado",
                         "La señal afirma una posición sin declarar contra qué universo "
                         "se ordenó. Solo se ordena lo comparable.")
    return None


def veto_sujeto(e: AlertEvent) -> Optional[Veredicto]:
    """Toda clave que afirme una porción tiene que nombrar su población."""
    huerfanas = [k for k in e.valores if not nombra_su_poblacion(str(k))]
    if huerfanas:
        return Veredicto(False, "sujeto_ausente",
                         f"Cifras de porción que no nombran su población: "
                         f"{', '.join(sorted(huerfanas))}. Sin el sujeto, el lector "
                         f"la reatribuye a la población más cercana.")
    return None


def veto_relacion(e: AlertEvent) -> Optional[Veredicto]:
    """Si el texto afirma una dirección, tiene que venir computada."""
    texto = f"{e.titulo} {e.cuerpo}".lower()
    if any(c in texto for c in COMPARATIVOS) and not e.relaciones.get("direccion"):
        return Veredicto(False, "relacion_no_computada",
                         "El texto afirma una dirección que no viene computada en "
                         "`relaciones`. Las relaciones se computan, no se derivan.")
    return None


def veto_vocabulario(e: AlertEvent) -> Optional[Veredicto]:
    """Una señal de monitoreo no se enuncia como pronóstico."""
    texto = f"{e.titulo} {e.cuerpo}".lower()
    hallados = [p for p in PROHIBIDO if p in texto]
    if hallados:
        return Veredicto(False, "vocabulario_predictivo",
                         f"El texto usa vocabulario de pronóstico ({', '.join(hallados)}) "
                         f"para una señal que no tiene backtest contra un desenlace externo.")
    return None


# Orden deliberado: primero lo que invalida la señal entera (frescura, cifras ausentes),
# después lo que invalida cómo se dice. Así el motivo que se reporta es la causa raíz y no
# un síntoma de redacción sobre un dato que además estaba podrido.
VETOS = (veto_frescura, veto_brecha, veto_comparabilidad, veto_sujeto,
         veto_relacion, veto_vocabulario)


def juzgar(e: AlertEvent) -> Veredicto:
    """El único camino a la entrega. Devuelve siempre un veredicto — nunca ``None`` ni una
    excepción: lo vetado se lista con su motivo, no desaparece."""
    for veto in VETOS:
        v = veto(e)
        if v is not None:
            return v
    return PUBLICA
