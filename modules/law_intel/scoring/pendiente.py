"""Lo que la ley todavía tiene por delante: las metas que aún no vencen.

El semáforo juzga contra la meta **ya vencida**. Esta es la otra mitad de la pregunta del
lector: *¿va a llegar?* — y no se contesta con el mismo vocabulario, porque una meta que no
venció **no se puede incumplir**.

**El error que este módulo existe para no cometer.** Correr el semáforo con el corte movido
al horizonte devolvería `no_alcanzada` sobre indicadores cuya meta vence dentro de cinco
años. Sería el reflejo exacto del eufemismo que este producto denuncia: donde el informe
oficial llama «avance moderado» a un incumplimiento, esto llamaría incumplimiento a un plazo
abierto. Las dos cosas son refutables leyendo la ley.

**Y el ritmo se COMPUTA contra el plazo, que es lo que el semáforo no hace.** Su vocabulario
declara un veredicto `en_trayectoria` —«la pendiente llega antes del corte»— que ningún
camino emite: en cuanto hay avance devuelve `no_alcanzara`, sin comparar el ritmo con los
períodos que quedan. Contra una meta ya vencida da igual. Proyectando a un horizonte abierto
sería afirmar que nada se va a cumplir sin haberlo calculado nunca.

**El ritmo se ancla en la LÍNEA BASE de la ley, no en el principio de la serie.** Extrapolar
desde una diferencia interanual sería extrapolar ruido —un rebote de un año decidiría el
veredicto de una década—, pero promediar la serie entera es peor de otra forma: la primera
versión de este módulo midió el ritmo de un indicador **desde 1946**, y 23 de 31 proyecciones
salían ancladas antes de que la ley existiera. La pregunta es si la ley va a llegar a donde
dijo, y el tramo que la contesta es el que va de su línea base a su horizonte. Cuando después
de la línea base no quedan dos observaciones se usa la serie entera y **se declara**, porque
un ritmo anclado antes de la norma responde otra pregunta que la que el informe hace.

**El horizonte lo declara la ley, no este archivo.** Sale de `vigencia_hasta` del expediente.
La END vence en 2030 y el Decreto 337-24 en 2036: un `2030` escrito acá convertiría al
producto en un evaluador de una sola norma.

**El supuesto se declara con el número.** «Al ritmo observado» no es un pronóstico: es una
extrapolación lineal de lo que ya pasó, y el informe la nombra así cada vez. Lo que se
afirma es que el ritmo *observado* no alcanza, no que el país no vaya a llegar — la política
puede cambiar el ritmo, y eso es precisamente lo que un legislador hace con esta información.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from modules.law_intel.bindings import Binding, aplicar_transformacion
from modules.law_intel.registro import Indicador

Observacion = Tuple[str, float]

#: Misma precisión que el semáforo: las dos tablas se leen juntas y una con más decimales
#: que la otra parece medida con otro instrumento.
_DECIMALES = 4

#: Estados de una meta pendiente. **Ninguno dice «incumplida»**: la meta no venció, y el
#: producto no tiene autoridad para adelantar ese juicio.
ESTADOS = {
    "ya_alcanzada": "el dato más reciente ya cumple la meta del horizonte",
    "en_trayectoria": "al ritmo observado, la meta se alcanza antes del horizonte",
    "no_llegara_al_ritmo_actual": ("al ritmo observado no se alcanza; llegar exige acelerar, "
                                   "no continuar"),
    "se_aleja": "el indicador se mueve en dirección contraria a la meta",
    "no_se_mueve": "el indicador no varía, y el horizonte sí se acerca",
    "sin_trayectoria": ("una sola observación: se puede decir a qué distancia está, nunca si "
                        "va a llegar"),
    "sin_medicion": "no hay serie verificada que mida este indicador",
    "no_evaluable": "la meta del horizonte no está en una escala que admita diferencia",
    "sin_meta_al_horizonte": "la ley no le fija meta a ese año",
}

#: Los estados que dependen de una extrapolación y por tanto arrastran el supuesto. Se
#: nombran para que el renderizador pueda exigir la coletilla y no dependa de recordarla.
DEPENDEN_DEL_RITMO = ("en_trayectoria", "no_llegara_al_ritmo_actual")


@dataclass(frozen=True)
class Pendiente:
    """Una meta que aún no vence, con todo lo que hace falta para rehacer la cuenta."""

    indicador: str
    horizonte: str
    estado: str
    #: El nombre que la ley le da al indicador. Viaja con el número SIEMPRE: un `2.35` sin
    #: su nombre hace que el modelo le pegue el más cercano que tenga a mano, y así se
    #: publicó «el acceso a medicamentos antirretrovirales (2.35)» sobre un indicador que
    #: mide acceso a agua de la red pública. Las cifras eran correctas y el sujeto no.
    nombre: str = ""
    meta: Optional[float] = None
    observado: Optional[float] = None
    periodo_observado: Optional[str] = None
    #: Cuánto falta para la meta, firmado como en el semáforo: positivo es déficit.
    falta: Optional[float] = None
    #: Avance medio por año hacia la meta, sobre la serie entera. Negativo = se aleja.
    ritmo_por_anio: Optional[float] = None
    #: Las dos puntas de las que sale el ritmo, para que el lector rehaga la pendiente.
    desde: Optional[str] = None
    #: Si el ritmo se pudo anclar en la línea base de la ley. `False` significa que se midió
    #: sobre un tramo anterior a la norma, y el motivo lo declara.
    anclado_en_la_linea_base: bool = True
    anios_restantes: Optional[int] = None
    motivo: str = ""

    @property
    def depende_del_ritmo(self) -> bool:
        return self.estado in DEPENDEN_DEL_RITMO


def _se_puede_restar(ind: Indicador) -> bool:
    """Si la escala del indicador admite una diferencia, con el MISMO criterio del semáforo.

    `redactada` entra porque la ley escribe ahí escalares perfectamente legibles —«100 al
    2016»— y el semáforo los juzga. `ordinal` no entra: una posición no se resta, y proyectar
    una posición al horizonte sería inventar una métrica que la ley no fijó.
    """
    return ind.admite_delta or ind.escala == "redactada"


def _ritmo(obs: Sequence[Observacion], mejor_menor: bool,
           base_anio: Optional[int] = None) -> Optional[Tuple[float, str, bool]]:
    """Avance medio por año hacia la meta, desde qué período, y si se ancló en la línea base.

    Se recorta a las observaciones desde la línea base de la ley. Si ahí no quedan dos, se
    usa la serie entera y se devuelve `False` en el tercer elemento para que el motivo lo
    declare: un ritmo medido desde 1946 no contesta si una ley de 2012 va a llegar a 2030.

    `None` con menos de dos observaciones o si las dos caen en el mismo año: sin dos puntos
    separados en el tiempo no hay pendiente que calcular, y fabricarla es la falla que vuelve
    refutable una proyección.
    """
    anclado = False
    if base_anio is not None:
        desde_base = [o for o in obs if str(o[0])[:4].isdigit()
                      and int(str(o[0])[:4]) >= base_anio]
        if len(desde_base) >= 2:
            obs, anclado = desde_base, True
    if len(obs) < 2:
        return None
    (p0, v0), (p1, v1) = obs[0], obs[-1]
    try:
        anios = int(str(p1)[:4]) - int(str(p0)[:4])
    except ValueError:
        return None
    if anios <= 0:
        return None
    avance = (v0 - v1) if mejor_menor else (v1 - v0)
    return round(avance / anios, _DECIMALES), str(p0)[:4], anclado


def evaluar(ind: Indicador, binding: Optional[Binding], observaciones: Sequence[Observacion],
            horizonte: str) -> Pendiente:
    """El estado de la meta del horizonte para un indicador.

    Toda rama de retorno lleva el `nombre` del indicador. No es decoración: es la regla del
    sujeto, y el hueco entra siempre por la rama que alguien olvidó.
    """
    nombre = ind.nombre
    meta = ind.metas.get(horizonte)
    if meta is None:
        return Pendiente(ind.id, horizonte, "sin_meta_al_horizonte", nombre=nombre,
                         motivo=f"la ley no le fija meta a {horizonte}")
    if not isinstance(meta, (int, float)) or not _se_puede_restar(ind):
        # Umbrales y escalares rotulados se declaran en vez de interpretarse acá: el semáforo
        # tiene los lectores y duplicarlos haría que las dos superficies pudieran discrepar.
        #
        # Y la ESCALA se consulta además del tipo de la meta. Ocho indicadores de la END son
        # ordinales y el semáforo se niega a restarlos; si alguno trae un número en la celda
        # de 2030, mirar solo el tipo habría hecho que esta superficie proyectara lo que la
        # otra declara imposible de juzgar. Un guard que existe en un motor y falta en el
        # otro es el defecto que este repositorio ya pagó cinco veces en un solo módulo.
        return Pendiente(ind.id, horizonte, "no_evaluable", nombre=nombre,
                         motivo=ESTADOS["no_evaluable"])
    if binding is None or not binding.cuenta or not observaciones:
        return Pendiente(ind.id, horizonte, "sin_medicion", meta=float(meta), nombre=nombre,
                         motivo=ESTADOS["sin_medicion"])

    mejor_menor = binding.mejor == "menor"
    p_obs, valor = observaciones[-1]
    valor = round(valor, _DECIMALES)
    cumple = valor <= meta if mejor_menor else valor >= meta
    falta = round((valor - meta) if mejor_menor else (meta - valor), _DECIMALES)

    if cumple:
        return Pendiente(ind.id, horizonte, "ya_alcanzada", meta=float(meta), observado=valor,
                         periodo_observado=p_obs, falta=falta, nombre=nombre,
                         motivo=(f"el dato de {p_obs} ya cumple la meta de {horizonte}; lo "
                                 f"pendiente es sostenerlo"))

    ritmo = _ritmo(observaciones, mejor_menor, ind.base_anio)
    try:
        restantes = int(horizonte) - int(str(p_obs)[:4])
    except ValueError:
        restantes = None
    if ritmo is None:
        return Pendiente(ind.id, horizonte, "sin_trayectoria", meta=float(meta), nombre=nombre,
                         observado=valor, periodo_observado=p_obs, falta=falta,
                         anios_restantes=restantes, motivo=ESTADOS["sin_trayectoria"])

    por_anio, desde, anclado = ritmo
    comun = dict(meta=float(meta), observado=valor, periodo_observado=p_obs, falta=falta,
                 ritmo_por_anio=por_anio, desde=desde, anios_restantes=restantes,
                 anclado_en_la_linea_base=anclado, nombre=nombre)
    if por_anio == 0:
        return Pendiente(ind.id, horizonte, "no_se_mueve", **comun,   # type: ignore[arg-type]
                         motivo=(f"sin variación entre {desde} y {p_obs}; el horizonte de "
                                 f"{horizonte} sí se acerca"))
    if por_anio < 0:
        return Pendiente(ind.id, horizonte, "se_aleja", **comun,      # type: ignore[arg-type]
                         motivo=(f"entre {desde} y {p_obs} se movió {abs(por_anio):.4g} por "
                                 f"año en contra de la meta"))
    if restantes is None or restantes <= 0:
        return Pendiente(ind.id, horizonte, "sin_trayectoria", **comun,  # type: ignore[arg-type]
                         motivo=(f"el horizonte {horizonte} no es posterior al último dato "
                                 f"({p_obs}): no hay plazo que proyectar"))

    # Si el ritmo no pudo anclarse en la línea base, el informe tiene que decirlo: un tramo
    # anterior a la norma responde otra pregunta que la que se está haciendo.
    salvedad = ("" if anclado else
                f" (el ritmo se mide desde {desde} porque desde la línea base de la ley no "
                f"hay dos observaciones)")
    alcanza = por_anio * restantes >= falta
    # Cuántos años PEDIRÍA la meta al ritmo observado. Es la cifra que convierte el veredicto
    # en una decisión: «le faltan 14 años y tiene 5» dice algo que «no llegará» no dice.
    anios_al_ritmo = falta / por_anio
    return Pendiente(
        ind.id, horizonte,
        "en_trayectoria" if alcanza else "no_llegara_al_ritmo_actual",
        **comun,                                                      # type: ignore[arg-type]
        motivo=(f"avanza {por_anio:.4g} por año desde {desde}; le faltan {falta:.4g} y "
                f"quedan {restantes} años, que al ritmo observado son "
                f"{anios_al_ritmo:.1f} años de recorrido{salvedad}"))


def panel(indicadores: Sequence[Indicador], bindings: Dict[str, Binding],
          series: Dict[str, Sequence[Observacion]], horizonte: str) -> List[Pendiente]:
    """La vista de lo pendiente para todos los indicadores de la ley."""
    out: List[Pendiente] = []
    for i in indicadores:
        b = bindings.get(i.id)
        crudas = series.get(b.serie, ()) if b else ()
        obs = [(p, aplicar_transformacion(b, v)) for p, v in crudas] if b else []
        out.append(evaluar(i, b, obs, horizonte))
    return out


def horizonte_de(meta_del_expediente: Dict[str, object]) -> Optional[str]:
    """El año hasta el que rige la ley, leído del expediente.

    La END vence en 2030 y el Decreto 337-24 en 2036. Un año escrito en el código volvería
    este módulo un evaluador de una sola norma.
    """
    crudo = str(meta_del_expediente.get("vigencia_hasta") or "")[:4]
    return crudo if crudo.isdigit() else None


def resumen(pendientes: Sequence[Pendiente]) -> Dict[str, object]:
    """Conteo por estado, con el universo proyectable separado del total."""
    conteo: Dict[str, int] = {}
    for p in pendientes:
        conteo[p.estado] = conteo.get(p.estado, 0) + 1
    proyectados = [p for p in pendientes if p.estado in DEPENDEN_DEL_RITMO]
    con_meta = sum(1 for p in pendientes if p.estado != "sin_meta_al_horizonte")
    return {
        "total_indicadores": len(pendientes),
        "con_meta_al_horizonte": con_meta,
        "ya_alcanzadas": conteo.get("ya_alcanzada", 0),
        "proyectables": len(proyectados),
        "en_trayectoria": conteo.get("en_trayectoria", 0),
        "no_llegan_al_ritmo_actual": conteo.get("no_llegara_al_ritmo_actual", 0),
        "sin_proyeccion_posible": sum(1 for p in pendientes
                                      if p.estado in ("sin_medicion", "no_evaluable",
                                                      "sin_trayectoria")),
        # Las razones, resueltas y con su denominador en la clave. Sin ellas el redactor las
        # deriva, y una división derivada es una cifra que el guard de respaldo no encuentra
        # en el contexto — vetó un Insight entero por un 48,9% que era 44/90.
        "pct_ya_alcanzadas_sobre_las_que_tienen_meta_al_horizonte": (
            round(100.0 * conteo.get("ya_alcanzada", 0) / con_meta, 1) if con_meta else None),
        "pct_no_llegan_sobre_las_proyectables": (
            round(100.0 * conteo.get("no_llegara_al_ritmo_actual", 0) / len(proyectados), 1)
            if proyectados else None),
        "pct_en_trayectoria_sobre_las_proyectables": (
            round(100.0 * conteo.get("en_trayectoria", 0) / len(proyectados), 1)
            if proyectados else None),
        "por_estado": dict(sorted(conteo.items())),
    }


def publicable(pendientes: Sequence[Pendiente], horizonte: str) -> Dict[str, object]:
    """Lo que viaja al contexto del modelo."""
    return {
        "metas_pendientes_al_horizonte_de_la_ley": {
            "horizonte": horizonte,
            "resumen": resumen(pendientes),
            "por_indicador": [
                {"indicador": p.indicador, "nombre_del_indicador": p.nombre,
                 "estado": p.estado, "meta": p.meta,
                 "observado": p.observado, "periodo_observado": p.periodo_observado,
                 "falta": p.falta, "ritmo_por_anio": p.ritmo_por_anio,
                 "ritmo_medido_desde": p.desde,
                 "ritmo_anclado_en_la_linea_base_de_la_ley": p.anclado_en_la_linea_base,
                 "anios_restantes": p.anios_restantes,
                 "lectura_ya_redactada": p.motivo}
                for p in pendientes if p.estado != "sin_meta_al_horizonte"],
        },
        "vocabulario_de_lo_pendiente": ESTADOS,
        "regla_de_lo_pendiente": (
            "Una meta que no venció NO se puede incumplir. Nunca escribas «incumple», «no "
            "alcanzó» ni «falló» sobre una meta del horizonte: lo que se afirma es si al "
            "ritmo OBSERVADO se llega o no. Y cuando el estado sea `en_trayectoria` o "
            "`no_llegara_al_ritmo_actual`, la frase lleva el supuesto pegado —«al ritmo "
            "observado desde AAAA»— porque es una extrapolación lineal de lo que ya pasó y "
            "no un pronóstico: el ritmo es exactamente lo que una decisión de política "
            "puede cambiar, y decirlo así es lo que vuelve accionable el informe."),
    }
