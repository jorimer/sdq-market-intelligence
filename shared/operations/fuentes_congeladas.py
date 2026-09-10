"""Sensor de fuente CONGELADA por eje: ¿la fuente que alimenta este eje sigue publicando?

**El fallo que caza.** Un job de sincronización verde no dice nada sobre la fuente. La
sección «Estadísticas» de la SIE lleva años sin edición nueva —el propio slug del portal
lo delata: ``historico-potencia-instalada-1998-2024``, ``reporte-protecom-julio-2023``—
y el sync de energía corre en verde igual, porque descarga el mismo archivo muerto todos
los meses. La medida es la ANTIGÜEDAD DEL DATO; jamás el éxito del job.

**Por qué el período del dato y no ``created_at``.** El auditor de publicaciones del BCRD
(``freshness._audit_publications``) mide ``Publication.created_at`` porque allí una edición
nueva es una fila nueva. En un eje sectorial ese proxy da un FALSO NEGATIVO justo en el caso
que perseguimos: el backfill escribe toda la historia de una vez, así que un eje onboardeado
en 2026 con dato que muere en 2023 tiene ``created_at`` reciente y se leería «al día». Lo que
sí envejece sin excepción es el PERÍODO del dato más nuevo, que cada producto ya computa y
declara en ``data_signals().freshness_days``. Un sync eterno contra una fuente muerta no lo
mueve nunca.

**Por qué hace falta un criterio propio y no alcanza G1.** El readiness escala sus umbrales
por cadencia y para una fuente anual usa ``(730, 2190)`` días
(``products.readiness._CADENCE_THRESHOLDS``): un eje anual congelado hace año y medio puntúa
frescura PLENA —1.0— y el gate lo publica sin una marca. Ese es el mecanismo exacto por el
que una fuente muerta aparenta estar viva. Este sensor mide lo mismo contra un tope de UN
ciclo de publicación más su rezago, y **no toca G1, ni el readiness, ni ``DataHealth.cadence``**:
solo mira y avisa. El sistema avisa; el humano verifica.

**Tres estados, y el tercero no es un detalle.** Un eje cuya antigüedad no se puede medir
—no la declara, no está cableado, o su producto revienta al preguntarle— NO es un eje al día.
Confundir «no sé de cuándo es» con «está al día» es lo que dejó un Gini viejo en producción
durante diecinueve días. Lo indeterminado se LISTA (un veto silencioso se lee como que el eje
no tiene problema); lo que se notifica es lo CONGELADO, que es un hecho.

**Lo que el sensor NO puede afirmar.** Se apoya en que ``data_signals().freshness_days`` es la
antigüedad del dato más nuevo de UNA fuente que publica ediciones. Para un eje cuyo sujeto es
un INSTRUMENTO —una ley— eso no se cumple: la cifra es la del indicador más viejo entre
muchos emisores, y su «fuente» es la norma, que no publica nada. Ahí el número existe y no
mide esto, así que el eje se declara indeterminado con el motivo escrito y se LISTA. Declarar
la brecha, nunca rellenarla.

Cross-eje por diseño: recorre el catálogo de productos, que vive en ``shared``. No importa
ningún módulo — cero cambios en los diecisiete ejes.
"""
from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.operations.fuentes_congeladas")

#: La fuente publicó dentro de su cadencia.
AL_DIA = "al_dia"
#: El dato más nuevo del eje es más viejo que lo que su cadencia tolera.
CONGELADA = "congelada"
#: No se pudo medir. NO es «al día» — es otra cosa, y se lista aparte.
INDETERMINADA = "indeterminada"

#: Cuántos días puede tener el dato más nuevo de un eje antes de que su fuente se declare
#: congelada, por cadencia declarada de la fuente. Es un ciclo de publicación MÁS el rezago
#: legítimo con que se publica ese ciclo: la cifra anual de 2025 no existe en enero de 2026,
#: y castigarla ahí sería un falso positivo que enseña a ignorar el sensor. Deliberadamente
#: MUCHO más estrecho que la curva de readiness (anual: 730/2190 días), que es la que hoy
#: pinta de verde una fuente muerta hace año y medio.
TOPES_POR_CADENCIA: Dict[str, int] = {
    "monthly": 60,      # un mes + un mes de rezago
    "quarterly": 150,   # un trimestre + ~2 meses de rezago
    "annual": 545,      # un año + ~6 meses de rezago
}

#: Re-aviso de un eje congelado: ~mensual. Reusa el dedup de ``freshness._recently_notified``.
_RENOTIFY_HOURS = 24 * 30


@dataclass(frozen=True)
class Veredicto:
    """El estado de la FUENTE de un eje, con el sujeto pegado a cada número.

    ``dias_desde_el_periodo_del_dato`` nombra su población: es la antigüedad del período al
    que pertenece el dato más nuevo del eje, no la del último sync ni la de la última fila
    escrita. ``fuentes`` nombra al emisor, porque «energía está congelada» no es accionable
    y «la SIE no publica desde 2023» sí.
    """

    eje: str
    estado: str
    motivo: str
    cadencia: str
    fuentes: Tuple[str, ...] = ()
    dias_desde_el_periodo_del_dato: Optional[int] = None
    tope_de_dias_de_la_cadencia: Optional[int] = None
    detalle_del_producto: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eje": self.eje,
            "estado": self.estado,
            "motivo": self.motivo,
            "cadencia": self.cadencia,
            "fuentes": list(self.fuentes),
            "dias_desde_el_periodo_del_dato": self.dias_desde_el_periodo_del_dato,
            "tope_de_dias_de_la_cadencia": self.tope_de_dias_de_la_cadencia,
            "detalle_del_producto": self.detalle_del_producto,
        }


def evaluar_fuente(
    *,
    eje: str,
    freshness_days: Optional[int],
    cadence: Optional[str],
    fuentes: Tuple[str, ...] = (),
    detalle: str = "",
) -> Veredicto:
    """El veredicto de UN eje a partir de la antigüedad de su dato y la cadencia de su fuente.

    Función pura: no toca la base ni el reloj. Es el ÚNICO criterio de medición del sensor —
    el caso positivo y el control negativo pasan los dos por acá, porque dos implementaciones
    del mismo criterio es exactamente cómo se cuela un falso.
    """
    cad = (cadence or "").strip().lower()
    tope = TOPES_POR_CADENCIA.get(cad)
    if tope is None:
        return Veredicto(
            eje=eje, estado=INDETERMINADA, cadencia=cad or "sin declarar", fuentes=fuentes,
            detalle_del_producto=detalle,
            motivo=(f"el eje declara la cadencia «{cad or 'sin declarar'}», que no tiene tope "
                    f"de frescura definido; no se le asigna el de otra cadencia"))

    if freshness_days is None:
        return Veredicto(
            eje=eje, estado=INDETERMINADA, cadencia=cad, fuentes=fuentes,
            tope_de_dias_de_la_cadencia=tope, detalle_del_producto=detalle,
            motivo="el eje no declara la antigüedad de su dato más reciente")

    dias = int(freshness_days)
    if dias < 0:
        return Veredicto(
            eje=eje, estado=INDETERMINADA, cadencia=cad, fuentes=fuentes,
            dias_desde_el_periodo_del_dato=dias, tope_de_dias_de_la_cadencia=tope,
            detalle_del_producto=detalle,
            motivo=(f"la antigüedad declarada es negativa ({dias} d): el período del dato "
                    f"está en el futuro y la medición no es interpretable"))

    if dias > tope:
        return Veredicto(
            eje=eje, estado=CONGELADA, cadencia=cad, fuentes=fuentes,
            dias_desde_el_periodo_del_dato=dias, tope_de_dias_de_la_cadencia=tope,
            detalle_del_producto=detalle,
            motivo=(f"el dato más nuevo del eje tiene {dias} días y su fuente ({cad}) debió "
                    f"publicar una edición nueva a los {tope}"))

    return Veredicto(
        eje=eje, estado=AL_DIA, cadencia=cad, fuentes=fuentes,
        dias_desde_el_periodo_del_dato=dias, tope_de_dias_de_la_cadencia=tope,
        detalle_del_producto=detalle,
        motivo=f"dato de hace {dias} días, dentro del tope de {tope} para una fuente {cad}")


def _veredicto_del_eje(eje: str, db: Optional[Session]) -> Veredicto:
    """Lee las señales que el producto YA declara y las evalúa. Nunca lanza."""
    from shared.registry.signals import COVERAGE_INSTRUMENT
    from shared.products.registry import get_product, is_implemented

    if not is_implemented(eje):
        return Veredicto(eje=eje, estado=INDETERMINADA, cadencia="sin declarar",
                         motivo="el eje está en el catálogo pero no tiene implementación "
                                "registrada: no hay a quién preguntarle por su fuente")
    try:
        producto = get_product(eje, db)
        if producto is None:
            return Veredicto(eje=eje, estado=INDETERMINADA, cadencia="sin declarar",
                             motivo="la fábrica del producto no devolvió una implementación")
        salud = producto.data_signals()
    except Exception as e:  # noqa: BLE001 — un eje que revienta no aborta el barrido
        logger.warning("no se pudo leer la señal de datos de «%s»: %s", eje, e)
        return Veredicto(eje=eje, estado=INDETERMINADA, cadencia="sin declarar",
                         motivo=f"el producto falló al declarar su salud de datos: {e}")

    fuentes = tuple(getattr(salud, "sources", ()) or ())
    detalle = str(getattr(salud, "detail", "") or "")

    # Un eje cuyo sujeto es un INSTRUMENTO —una ley— tiene el número pero el número no mide
    # esto. Su `freshness_days` es la antigüedad del indicador MÁS VIEJO entre decenas, de
    # decenas de emisores distintos (así lo declara `law_intel`, y a propósito: un informe es
    # tan actual como su componente más rancio). Y su `sources` es la NORMA evaluada, que no
    # publica ediciones. Aplicarle este sensor produce la frase «la fuente Ley 1-12 END 2030
    # debió publicar una edición nueva a los 545 días», que es literalmente falsa.
    #
    # Se excluye por la SEMÁNTICA que el propio producto declara (`coverage_kind`), no por su
    # nombre: un eje de instrumento nuevo queda cubierto sin que nadie se acuerde de esta
    # línea. Y se excluye a INDETERMINADA, que se lista — no desaparece: un eje que se cae
    # del panel en silencio se lee como que no tiene problema.
    if getattr(salud, "coverage_kind", "") == COVERAGE_INSTRUMENT:
        return Veredicto(
            eje=eje, estado=INDETERMINADA,
            cadencia=str(getattr(salud, "cadence", "") or "sin declarar"),
            fuentes=fuentes, detalle_del_producto=detalle,
            motivo=("el sujeto del eje es un INSTRUMENTO: su antigüedad es la del indicador "
                    "más viejo entre muchos emisores y su «fuente» es la norma evaluada, "
                    "que no publica ediciones. La cifra existe y no mide esto"))

    return evaluar_fuente(
        eje=eje,
        freshness_days=getattr(salud, "freshness_days", None),
        cadence=getattr(salud, "cadence", None),
        fuentes=fuentes,
        detalle=detalle,
    )


def leer_fuentes_de_los_ejes(db: Optional[Session] = None) -> List[Veredicto]:
    """El veredicto de CADA eje del catálogo, en orden de catálogo. Solo lee."""
    from shared.products.registry import PRODUCT_CATALOG

    return [_veredicto_del_eje(entrada.sector_key, db) for entrada in PRODUCT_CATALOG]


def resumen_de_fuentes(db: Optional[Session] = None) -> Dict[str, Any]:
    """Lo que sirve la consola: la tabla entera + las dos listas que se miran primero.

    Los indeterminados van en su propia lista y no mezclados con los que están al día: es
    la distinción que el panel tiene que poder pintar de otro color.
    """
    ejes = leer_fuentes_de_los_ejes(db)
    return {
        "ejes": [v.to_dict() for v in ejes],
        "congeladas": [v.eje for v in ejes if v.estado == CONGELADA],
        "indeterminadas": [v.eje for v in ejes if v.estado == INDETERMINADA],
        "topes_por_cadencia": dict(TOPES_POR_CADENCIA),
    }


def auditar_fuentes_de_los_ejes(db: Session, admin_ids: List[str],
                                now: datetime) -> List[str]:
    """AVISA (advisory) los ejes cuya fuente dejó de publicar. Devuelve los ejes avisados.

    Solo se notifica lo CONGELADO, que es un hecho comprobable. Lo INDETERMINADO se lista en
    la consola —y en el retorno de la auditoría— pero no genera un aviso diario por eje sin
    cablear: un canal que avisa siempre se aprende a ignorar, y entonces tampoco avisa lo que
    importa. Deduplica por eje (~mensual), reusando el buzón de la auditoría de frescura.
    """
    from shared.notifications.service import notification_service
    from shared.operations.freshness import (
        _clear_notified, _mark_notified, _recently_notified)

    avisados: List[str] = []
    for v in leer_fuentes_de_los_ejes(db):
        clave = f"fuente:{v.eje}"
        if v.estado != CONGELADA:
            if v.estado == AL_DIA:
                _clear_notified(db, clave)
            continue
        if _recently_notified(db, clave, _RENOTIFY_HOURS):
            continue

        emisor = ", ".join(v.fuentes) or "sin emisor declarado"
        title = f"Fuente sin publicar: {v.eje}"
        body = (f"El dato más nuevo del eje «{v.eje}» tiene ~{v.dias_desde_el_periodo_del_dato} "
                f"día(s); su fuente ({emisor}, cadencia {v.cadencia}) debió publicar una "
                f"edición nueva a los {v.tope_de_dias_de_la_cadencia}. El sync puede estar "
                f"corriendo en verde contra un archivo que ya no se actualiza — conviene "
                f"verificar en el emisor si hay una edición más reciente.")
        try:
            for uid in admin_ids:
                notification_service.create(db, user_id=uid, type="warning", title=title,
                                            body=body, action_url="/datos/operaciones")
            _mark_notified(db, clave)
            avisados.append(v.eje)
        except Exception as e:  # noqa: BLE001 — un fallo por eje no aborta los demás
            db.rollback()
            logger.warning("no se pudo avisar la fuente congelada de %s: %s", v.eje, e)
    return avisados
