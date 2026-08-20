"""Catálogo de disparadores — QUÉ puede hacer sonar una alerta.

**Toda regla es una función PURA**: recibe valores ya resueltos, no toca la base y devuelve
``Optional[AlertEvent]``. Es el patrón que `modules/banking_score/early_warning.py` ya usa en
sus nueve ``rule_*``, y es lo que hace el motor testeable sin montar un panel entero.

**`None` de entrada ⇒ `None` de salida, SIEMPRE.** Un dato ausente no dispara ni deja de
disparar: no se evalúa. Es la doctrina de la brecha aplicada al canal de mayor frecuencia, y
es donde más barato se viola — ``if valor > umbral`` con ``valor=None`` levanta y se nota,
pero ``if (valor or 0) > umbral`` no levanta: publica un umbral que nadie cruzó. Lo vigila
``tests/test_ninguna_entrada_none_dispara.py``, que barre el catálogo entero.

**Por qué cada entrada declara ``implementado``.** Un código en catálogo sin motor detrás es
una vigilancia que nunca suena. Se puede suscribir (el cliente declara su interés y no hay
que pedírselo dos veces), pero la API lo DICE y la UI lo muestra. Un disparador mudo que se
presenta como activo se lee como «no pasó nada», que es la lectura opuesta a la verdadera.

**``basis`` no es decorado.** Es por qué la regla existe: la lección, la doctrina o el motor
que la ancla. Viaja al evento y de ahí al texto que lee el cliente — una alerta que no puede
decir por qué es una regla que sonó porque sí.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Sentinela de «todo el eje»: las reglas cuyo sujeto es el eje entero
# (frescura, publicación) la usan para que el motor las case con las
# vigilancias de eje completo igual que cualquier otra.
from shared.alerts.models import TODO_EL_EJE

# Severidades, de mayor a menor. El orden es el dato: ``min_severity`` filtra por posición.
SEVERIDADES: Tuple[str, ...] = ("alta", "media", "baja")


def severidad_alcanza(severidad: str, minima: str) -> bool:
    """¿*severidad* es al menos tan grave como *minima*? Desconocidas no alcanzan nunca:
    ante una severidad que no está en el vocabulario, no entregar es el lado seguro."""
    if severidad not in SEVERIDADES or minima not in SEVERIDADES:
        return False
    return SEVERIDADES.index(severidad) <= SEVERIDADES.index(minima)


@dataclass(frozen=True)
class Disparador:
    """Una clase de evento que puede levantar una alerta."""

    codigo: str
    label: str
    descripcion: str
    basis: str
    # ¿Exige un sujeto nombrado? Un cambio de banda es de una entidad; una publicación
    # nueva es del eje entero. Lo usa la validación de la watchlist.
    requiere_sujeto: bool
    # ¿Tiene motor detrás HOY? Ver el docstring del módulo.
    implementado: bool = False


CATALOGO: Tuple[Disparador, ...] = (
    Disparador(
        codigo="umbral",
        label="Cruce de umbral",
        descripcion=("Una métrica vigilada cruzó un umbral declarado en doctrina "
                     "(p. ej. cobertura de provisiones por debajo de 100%)."),
        basis=("Reglas de monitoreo ancladas a lecciones documentadas del sector; en banca, "
               "a los precursores de la crisis RD 2003 "
               "(modules/banking_score/early_warning.py)."),
        requiere_sujeto=False,
        implementado=True,
    ),
    Disparador(
        codigo="banda",
        label="Cambio de banda",
        descripcion="El sujeto cambió de banda o tier entre dos períodos consecutivos.",
        basis="Bandas del motor de índices explicable (shared/indices).",
        requiere_sujeto=True,
        implementado=True,
    ),
    Disparador(
        codigo="posicion",
        label="Cambio de posición",
        descripcion=("El sujeto se movió en el ranking de su universo comparable. Solo "
                     "ordena lo comparable: un score armado sobre 3 de 5 dimensiones no "
                     "rankea contra uno de 5."),
        basis="shared.narrative.derived.universo_comparable — doctrina de comparabilidad.",
        requiere_sujeto=True,
        implementado=True,
    ),
    Disparador(
        codigo="brecha",
        label="Brecha de dato",
        descripcion=("Una dimensión que tenía dato dejó de tenerlo, o al revés. Que un eje "
                     "haya perdido su dato es noticia para quien lo vigila."),
        basis="Doctrina de datos: la brecha se declara, nunca se rellena.",
        requiere_sujeto=False,
        implementado=True,
    ),
    Disparador(
        codigo="frescura",
        label="Validación vencida",
        descripcion=("El insumo que produjo una credencial de validación cambió después de "
                     "calcularla: el reporte quedó huérfano."),
        basis=("shared.validation.frescura — huella del insumo. Sin esto, producción sirvió "
               "19 días un Gini calculado con un score que ya no existía."),
        requiere_sujeto=False,
        implementado=True,
    ),
    Disparador(
        codigo="publicacion",
        label="Publicación nueva",
        descripcion="Entró una edición nueva de una fuente recurrente del eje.",
        basis=("Detector ya existente en shared/operations/freshness.py::_audit_publications, "
               "hoy dirigido solo a administradores."),
        requiere_sujeto=False,
        implementado=True,
    ),
)

POR_CODIGO: Dict[str, Disparador] = {d.codigo: d for d in CATALOGO}
CODIGOS: Tuple[str, ...] = tuple(d.codigo for d in CATALOGO)


def implementados() -> List[str]:
    """Códigos con motor detrás hoy. En la fase A es la lista vacía, y eso es correcto:
    la watchlist existe antes que el motor a propósito, para que la fase B tenga contra
    qué disparar el día que arranca."""
    return [d.codigo for d in CATALOGO if d.implementado]


def serializar(d: Disparador) -> Dict[str, object]:
    return {
        "codigo": d.codigo, "label": d.label, "descripcion": d.descripcion,
        "basis": d.basis, "requiere_sujeto": d.requiere_sujeto,
        "implementado": d.implementado,
    }


def desconocidos(codigos: Optional[List[str]]) -> List[str]:
    """Los códigos de *codigos* que no están en el catálogo (para el error de validación)."""
    if not codigos:
        return []
    return [c for c in codigos if c not in POR_CODIGO]


# ── El evento ────────────────────────────────────────────────────────────────

# La prosa vive en CONSTANTES y no incrustada en el cuerpo de la regla: un literal largo se
# parte por ancho de línea y la frase deja de existir en el fuente aunque el valor salga
# bien, así que un test que la busque falla sin motivo (o pasa sin protegerte).
TXT_UMBRAL = ("{metrica} de {sujeto} está en {valor} al {periodo}, "
              "{direccion} del umbral de {umbral}.")
TXT_BANDA = "{sujeto} pasó de banda «{previa}» a «{actual}» al {periodo}."
TXT_BRECHA_PIERDE = "{dimension} dejó de tener dato para {sujeto} al {periodo}."
TXT_BRECHA_RECUPERA = "{dimension} volvió a tener dato para {sujeto} al {periodo}."

# Cómo se dice cada dirección. Se COMPUTA a partir de los números y el texto la copia —
# nunca al revés. Este repo ya publicó una glosa que sobrevivió a corregir el número.
DIRECCION_TXT = {"por_debajo": "por debajo", "por_encima": "por encima"}


@dataclass(frozen=True)
class AlertEvent:
    """Una alerta lista para pasar por el gate. Inmutable: lo que el gate juzga es lo que se
    entrega, sin que un paso intermedio pueda reescribir el texto después del veredicto."""

    codigo: str
    sector_key: str
    subject: str
    periodo: str
    severidad: str
    titulo: str
    cuerpo: str
    basis: str
    # Direcciones, deltas, posiciones y referencias — COMPUTADAS en código. El texto las
    # copia de acá. Si algún día lo redacta el modelo, copia de acá también.
    relaciones: Dict[str, Any] = field(default_factory=dict)
    # Las cifras que sostienen la afirmación. El gate mira sus CLAVES (regla del sujeto) y
    # sus VALORES (ninguno puede ser None fuera de una alerta de brecha).
    valores: Dict[str, Optional[float]] = field(default_factory=dict)
    # {variable: "live"|"rubric"} — la misma procedencia que declara el resto de la casa.
    procedencia: Dict[str, str] = field(default_factory=dict)
    # ¿El dato que sostiene esto está vigente? True publica; False no; **None tampoco**.
    # Ver `gate.veto_frescura`: el tercer estado es el que costó 19 días de producción.
    frescura: Optional[bool] = None
    # Universo sobre el que se ordenó, cuando la alerta afirma una posición.
    universo: Optional[str] = None

    @property
    def clave_dedup(self) -> str:
        """Identidad de la CONDICIÓN, sin el período: dos barridos sobre el mismo problema
        son el mismo aviso. Incluir el período haría que cada trimestre re-avisara aunque
        nada hubiera cambiado, que es exactamente el ruido que mata el producto."""
        metrica = self.relaciones.get("metrica", "")
        return f"{self.sector_key}:{self.subject}:{self.codigo}:{metrica}"


# ── Reglas ───────────────────────────────────────────────────────────────────

def rule_umbral(*, sector_key: str, subject: str, sujeto_label: str, periodo: str,
                metrica: str, metrica_label: str, valor: Optional[float],
                umbral: Optional[float], direccion: str, severidad: str, basis: str,
                unidad: str = "%", procedencia: Optional[Dict[str, str]] = None,
                frescura: Optional[bool] = None,
                clave_valor: Optional[str] = None) -> Optional[AlertEvent]:
    """Una métrica cruzó su umbral declarado.

    ``clave_valor`` permite nombrar la cifra con el sujeto que le corresponde cuando es una
    porción (``concentracion_top10_deudores_pct``): el gate exige esa regla sobre las claves
    de ``valores``, y el nombre correcto lo sabe el productor, no esta función.
    """
    if valor is None or umbral is None:
        return None
    if direccion not in DIRECCION_TXT:
        return None
    cruzo = valor < umbral if direccion == "por_debajo" else valor > umbral
    if not cruzo:
        return None

    # La dirección y la distancia se COMPUTAN acá; el texto las copia.
    relaciones = {
        "metrica": metrica,
        "direccion": direccion,
        "umbral": umbral,
        "valor": valor,
        "distancia": round(abs(valor - umbral), 4),
    }
    cuerpo = TXT_UMBRAL.format(
        metrica=metrica_label, sujeto=sujeto_label, periodo=periodo,
        valor=expresar(valor, unidad), umbral=expresar(umbral, unidad),
        direccion=DIRECCION_TXT[direccion])
    return AlertEvent(
        codigo="umbral", sector_key=sector_key, subject=subject, periodo=periodo,
        severidad=severidad, titulo=f"{metrica_label}: {sujeto_label}",
        cuerpo=cuerpo, basis=basis, relaciones=relaciones,
        valores={(clave_valor or metrica): valor},
        procedencia=procedencia or {}, frescura=frescura)


def rule_banda(*, sector_key: str, subject: str, sujeto_label: str, periodo: str,
               banda_actual: Optional[str], banda_previa: Optional[str],
               orden_bandas: Sequence[str], basis: str,
               procedencia: Optional[Dict[str, str]] = None,
               frescura: Optional[bool] = None) -> Optional[AlertEvent]:
    """El sujeto cambió de banda entre dos períodos consecutivos.

    ``orden_bandas`` va de MEJOR a PEOR y no es opcional: sin él se puede decir «cambió» pero
    no «empeoró», y «cambió de banda» no es accionable. La dirección sale de las posiciones
    en ese orden, nunca de comparar los rótulos entre sí.
    """
    if not banda_actual or not banda_previa or banda_actual == banda_previa:
        return None
    orden = list(orden_bandas)
    if banda_actual not in orden or banda_previa not in orden:
        # Una banda fuera del orden declarado no se puede juzgar. Callar es correcto:
        # inventar la dirección es cómo se publica lo contrario de lo que pasó.
        return None

    empeora = orden.index(banda_actual) > orden.index(banda_previa)
    saltos = abs(orden.index(banda_actual) - orden.index(banda_previa))
    relaciones = {"metrica": "banda", "direccion": "deterioro" if empeora else "mejora",
                  "saltos": saltos, "previa": banda_previa, "actual": banda_actual}
    if empeora:
        severidad = "alta" if saltos > 1 else "media"
    else:
        severidad = "baja"
    return AlertEvent(
        codigo="banda", sector_key=sector_key, subject=subject, periodo=periodo,
        severidad=severidad, titulo=f"Cambio de banda: {sujeto_label}",
        cuerpo=TXT_BANDA.format(sujeto=sujeto_label, previa=banda_previa,
                                actual=banda_actual, periodo=periodo),
        basis=basis, relaciones=relaciones, procedencia=procedencia or {},
        frescura=frescura)


def rule_brecha(*, sector_key: str, subject: str, sujeto_label: str, periodo: str,
                dimension: str, dimension_label: str, tenia_dato: Optional[bool],
                tiene_dato: Optional[bool], basis: str,
                frescura: Optional[bool] = None) -> Optional[AlertEvent]:
    """Una dimensión ganó o perdió su dato.

    Es la única regla cuyo insumo legítimo es la AUSENCIA, y por eso el gate la exime del
    veto de brecha. Pero necesita el estado ANTERIOR: sin él no hay transición que declarar,
    solo una foto sin dato — que no es noticia, es el estado.
    """
    if tenia_dato is None or tiene_dato is None or tenia_dato == tiene_dato:
        return None
    perdio = bool(tenia_dato) and not bool(tiene_dato)
    plantilla = TXT_BRECHA_PIERDE if perdio else TXT_BRECHA_RECUPERA
    return AlertEvent(
        codigo="brecha", sector_key=sector_key, subject=subject, periodo=periodo,
        severidad="media" if perdio else "baja",
        titulo=f"{'Brecha' if perdio else 'Brecha cerrada'}: {dimension_label}",
        cuerpo=plantilla.format(dimension=dimension_label, sujeto=sujeto_label,
                                periodo=periodo),
        basis=basis,
        relaciones={"metrica": dimension, "direccion": "pierde" if perdio else "recupera"},
        procedencia={dimension: "live" if tiene_dato else "brecha"},
        frescura=frescura)


def expresar(valor: float, unidad: str) -> str:
    """Cifra con su unidad, en notación de la casa (punto de miles, coma decimal).

    La notación no es cosmética: los informes ya usan coma decimal y una alerta con punto
    decimal se lee como de otro sistema. Ver docs/REPORT_STANDARD.md.
    """
    entero, _, decimal = f"{valor:,.2f}".partition(".")
    txt = entero.replace(",", ".") + "," + decimal
    return f"{txt}{unidad}" if unidad == "%" else f"{txt} {unidad}".strip()


# ── Reglas de la fase D ──────────────────────────────────────────────────────

TXT_POSICION = ("{sujeto} pasó del puesto {previo} al {actual} de {n} al {periodo}. "
                "{criterio}.")
TXT_FRESCURA = ("La validación de {eje} quedó huérfana de su insumo: {motivo}. "
                "Sus cifras no se publican hasta recalcularla.")
TXT_FRESCURA_INDET = ("No se puede establecer si la validación de {eje} sigue vigente: "
                      "{motivo}. Sus cifras no se publican mientras siga así.")
TXT_PUBLICACION = "Entró una edición nueva de «{publicacion}»: {edicion}."


def rule_posicion(*, sector_key: str, subject: str, sujeto_label: str, periodo: str,
                  rank_actual: Optional[int], rank_previo: Optional[int],
                  n_comparables: Optional[int], criterio: str, basis: str,
                  saltos_minimos: int = 1,
                  procedencia: Optional[Dict[str, str]] = None,
                  frescura: Optional[bool] = None) -> Optional[AlertEvent]:
    """El sujeto se movió en el ranking de su universo COMPARABLE.

    ``criterio`` describe ese universo y **no es opcional**: es lo que el gate exige para
    dejar pasar una posición (``veto_comparabilidad``). Un score armado sobre 3 de 5
    dimensiones no rankea contra uno de 5, y una alerta de ranking es exactamente la
    superficie donde ese defecto se convierte en una afirmación falsa enviada por correo.
    Lo produce ``shared.narrative.derived.rank_comparable``; acá no se reconstruye.

    ``rank_actual=None`` significa que el sujeto NO es comparable este período (cobertura
    parcial). No se publica un movimiento: no hay posición que afirmar, y eso es lo que hay
    que decir — pero por la vía de una alerta de brecha, no torciendo esta.
    """
    if rank_actual is None or rank_previo is None or n_comparables is None:
        return None
    if not criterio:
        return None
    saltos = abs(rank_actual - rank_previo)
    if saltos < max(1, saltos_minimos):
        return None

    # Menor número = mejor puesto. La dirección se COMPUTA de los enteros; el texto la copia.
    empeora = rank_actual > rank_previo
    relaciones = {
        "metrica": "posicion", "direccion": "cae" if empeora else "sube",
        "posicion": rank_actual, "posicion_previa": rank_previo,
        "saltos": saltos, "de_n": n_comparables,
    }
    return AlertEvent(
        codigo="posicion", sector_key=sector_key, subject=subject, periodo=periodo,
        severidad="media" if empeora else "baja",
        titulo=f"Cambio de posición: {sujeto_label}",
        cuerpo=TXT_POSICION.format(sujeto=sujeto_label, previo=rank_previo,
                                   actual=rank_actual, n=n_comparables,
                                   periodo=periodo, criterio=criterio),
        basis=basis, relaciones=relaciones, procedencia=procedencia or {},
        frescura=frescura, universo=criterio)


def rule_frescura(*, sector_key: str, eje_label: str, periodo: str,
                  stale_actual: Optional[bool], stale_previo: Optional[bool],
                  motivo: str, basis: str) -> Optional[AlertEvent]:
    """La validación de un eje dejó de estar vigente.

    **Por qué esta alerta declara ``frescura=True``.** Parece una trampa al veto de frescura
    y no lo es: el hecho que afirma —«la huella del reporte ya no coincide con su insumo»— se
    acaba de computar contra el estado de HOY. Lo que envejeció es el objeto del aviso, no el
    aviso. Si esta regla heredara el ``stale`` del reporte, la única alerta que existe para
    avisar que algo se venció quedaría vetada por estar vencida, que es exactamente el
    silencio que la doctrina prohíbe.

    Dispara solo en la TRANSICIÓN: un eje que ya estaba vencido no vuelve a avisar en cada
    barrido. Y ``None`` (indeterminado) es su propio estado, distinto de ``True``: piden
    acciones distintas —recalcular versus averiguar de cuándo es— y el texto lo dice.
    """
    if stale_actual is False or stale_actual == stale_previo:
        return None
    plantilla = TXT_FRESCURA if stale_actual is True else TXT_FRESCURA_INDET
    estado = "vencida" if stale_actual is True else "indeterminada"
    return AlertEvent(
        codigo="frescura", sector_key=sector_key, subject=TODO_EL_EJE, periodo=periodo,
        severidad="alta" if stale_actual is True else "media",
        titulo=f"Validación {estado}: {eje_label}",
        cuerpo=plantilla.format(eje=eje_label, motivo=motivo or "sin motivo declarado"),
        basis=basis,
        relaciones={"metrica": "validacion", "direccion": "pierde_vigencia",
                    "estado": estado},
        procedencia={"validacion": "live"},
        # Ver el docstring: el hecho se computó contra el estado de hoy.
        frescura=True)


def rule_publicacion(*, sector_key: str, publicacion_label: str, periodo: str,
                     edicion_actual: Optional[str], edicion_previa: Optional[str],
                     basis: str) -> Optional[AlertEvent]:
    """Entró una edición nueva de una fuente recurrente del eje.

    Es el disparador más parecido a lo que hace un monitor de documentos, y por eso conviene
    ser preciso sobre qué avisa: **no** que se publicó algo (eso lo sabe cualquiera con un
    scraper), sino que la plataforma **ya lo ingirió** — o sea, que el dato del eje se movió
    y los informes que salgan desde ahora dicen otra cosa.

    Sin edición previa no hay novedad que declarar: la primera ingestión de una fuente es el
    estado inicial, no una noticia.
    """
    if not edicion_actual or not edicion_previa or edicion_actual == edicion_previa:
        return None
    return AlertEvent(
        codigo="publicacion", sector_key=sector_key, subject=TODO_EL_EJE, periodo=periodo,
        severidad="baja",
        titulo=f"Publicación nueva: {publicacion_label}",
        cuerpo=TXT_PUBLICACION.format(publicacion=publicacion_label,
                                      edicion=edicion_actual),
        basis=basis,
        relaciones={"metrica": "publicacion", "direccion": "entra",
                    "edicion": edicion_actual, "edicion_previa": edicion_previa},
        procedencia={"publicacion": "live"},
        # La edición se acaba de ingerir: el hecho es de hoy por construcción.
        frescura=True)
