"""El contexto regional que ve el modelo, y la regla que impide compararlo mal.

**La regla, y de dónde sale.** Los indicadores de cada supervisor nacional se computan bajo
su propia norma contable y NO son comparables entre países. No es una cautela nuestra: la
propia SECMCA lo declara por escrito en la página de su Estadística del Sistema Bancario
—«estos indicadores no están armonizados»— y remite a EMFA para lo que sí lo está. Si el
organismo regional lo dice de su propia región, nosotros no podemos afirmar lo contrario.

**Por qué en el código y no en el manual de estilo.** La disciplina editorial de no hacer
rankings no sobrevive a la edición doce: el ranking es exactamente lo que más se comparte, y
en algún momento alguien lo va a pedir «solo por esta vez». Un test sí sobrevive.

La forma del contexto hace el trabajo pesado: §2 recibe un BLOQUE POR PAÍS, no una tabla
país×métrica, así que ni siquiera está servido de una manera que invite a compararlo. §3
recibe una tabla común, y solo puede recibirla porque sus filas vienen de EMFA.
"""
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.regional_banking.models.models import CountryBankingAggregate

logger = logging.getLogger("sdq.regional_banking.ai_context")

#: Lo único armonizado del boletín, y por lo tanto lo único que admite comparar NIVELES
#: entre países. Es una lista cerrada a propósito: una fuente nueva no se vuelve comparable
#: por parecerlo, entra acá o no compara.
NORMAS_ARMONIZADAS = frozenset({"EMFA armonizado"})

NOMBRE_PAIS = {
    "DOM": "República Dominicana", "COL": "Colombia", "CRI": "Costa Rica",
    "SLV": "El Salvador", "GTM": "Guatemala", "HND": "Honduras",
    "NIC": "Nicaragua", "PAN": "Panamá", "BRA": "Brasil", "CHL": "Chile",
}


class ComparacionNoArmonizada(RuntimeError):
    """Se intentó poner lado a lado métricas computadas bajo normas distintas."""


def exigir_comparable(filas: List[CountryBankingAggregate]) -> List[CountryBankingAggregate]:
    """Devuelve *filas* si se pueden comparar entre países; si no, LEVANTA.

    Fail-closed y no un aviso: en un ensamblado automático «avisar» no es «proteger» —el
    warning se pierde en los logs y el documento sale igual—. Y la comparación inválida no
    se ve rota: se ve como una tabla perfectamente ordenada donde una columna mide otra cosa.
    """
    normas = {f.norma_contable for f in filas}
    paises = {f.iso_code for f in filas}
    if len(paises) <= 1:
        return filas                      # un solo país no compara con nadie
    fuera = normas - NORMAS_ARMONIZADAS
    if fuera:
        raise ComparacionNoArmonizada(
            f"no se pueden comparar {sorted(paises)} entre sí: las normas {sorted(fuera)} no "
            f"están armonizadas. Solo {sorted(NORMAS_ARMONIZADAS)} admite comparar niveles "
            f"entre países; el resto se narra como trayectoria DENTRO de cada sistema.")
    if len(normas) > 1:
        raise ComparacionNoArmonizada(
            f"la tabla mezcla {sorted(normas)}: aunque cada una sea armonizada por su lado, "
            f"no lo son ENTRE sí.")
    return filas


def _valor(fila: CountryBankingAggregate) -> Dict[str, Any]:
    return {
        "metrica": fila.metric,
        # La clave es un identificador; el nombre es lo que el modelo puede escribir. Sin
        # él, «mora_90_consumo: 2,39» se redacta como «consumo, 2,39 %» y el lector no sabe
        # si es el saldo, la mora o la provisión de esa cartera. `None` donde la fuente no
        # lo declara: se prefiere el hueco a inventarle un nombre a la métrica de otro.
        "nombre": (fila.meta or {}).get("nombre"),
        "valor": fila.value,
        "unidad": (fila.meta or {}).get("unit"),
        "corte": fila.period_end.isoformat() if fila.period_end else None,
        # El SUJETO viaja con el número: sin la norma, una cifra de solvencia es solo «una
        # solvencia», y el modelo la va a poner al lado de la de otro país.
        "norma_contable": fila.norma_contable,
        "fuente": fila.source,
        "comparable_entre_paises": bool((fila.meta or {}).get("comparable_entre_paises")),
        "motivo_de_ausencia": (fila.meta or {}).get("reason"),
    }


def contexto_por_sistema(db: Session, limite_por_pais: int = 40) -> Dict[str, Any]:
    """§2 — un BLOQUE POR PAÍS, cada uno con su norma y su corte.

    Deliberadamente NO es una tabla país×métrica: el dato no se sirve de una forma que
    invite a leerlo en horizontal. Cada país trae además su propio corte porque las plazas
    publican con rezagos muy distintos y una puede venir de un año atrás.
    """
    # El criterio es la COMPARABILIDAD de cada cifra, no la norma de su fuente. Filtrar por
    # norma dejaba el crédito de las siete plazas de EMFA fuera de las dos secciones: no
    # entraba acá por ser «armonizado» y no entraba en §3 por no ser comparable —viene en
    # moneda local, con la unidad sin declarar—. Se perdía en el medio, sin error.
    filas = (db.query(CountryBankingAggregate)
               .order_by(CountryBankingAggregate.iso_code,
                         CountryBankingAggregate.period_end.desc())
               .all())
    por_pais: Dict[str, List] = defaultdict(list)
    for fila in filas:
        if (fila.meta or {}).get("comparable_entre_paises"):
            continue                      # eso va a §3
        # Con valor primero: un cupo gastado en ausencias deja datos reales fuera de lo que
        # el modelo llega a ver, y el resultado no sale mal — sale CORTO, que no se nota.
        if fila.value is None:
            continue
        if len(por_pais[fila.iso_code]) < limite_por_pais:
            por_pais[fila.iso_code].append(fila)

    bloques = []
    for iso, del_pais in sorted(por_pais.items()):
        cortes = [f.period_end for f in del_pais if f.period_end]
        bloques.append({
            "iso3": iso,
            "pais": NOMBRE_PAIS.get(iso, iso),
            "corte": max(cortes).isoformat() if cortes else None,
            "norma_contable": sorted({f.norma_contable for f in del_pais}),
            "series": [_valor(f) for f in del_pais],
        })
    return {
        "bloques_por_pais": bloques,
        "regla": ("Cada país se lee DENTRO de su propio sistema. Estas cifras NO son "
                  "comparables entre países: cada supervisor las computa bajo su norma "
                  "contable. La comparación entre países vive en la sección armonizada."),
    }


def contexto_armonizado(db: Session, limite: int = 120) -> Dict[str, Any]:
    """§3 — la única tabla que cruza países, y solo porque sale de EMFA."""
    filas = (db.query(CountryBankingAggregate)
               .filter(CountryBankingAggregate.norma_contable.in_(
                   tuple(NORMAS_ARMONIZADAS)))
               .order_by(CountryBankingAggregate.period_end.desc())
               .all())
    # Solo lo que la propia fila declara comparable: EMFA armoniza la METODOLOGÍA, no la
    # unidad, y sus saldos de crédito vienen en moneda local con la unidad sin declarar.
    # Con valor primero, por lo mismo que en §2: 110 filas de las cuales la mayoría son
    # ausencias llenan el cupo y empujan fuera las cifras que el modelo necesita para
    # escribir. Las ausencias siguen viajando —al final, con su motivo— pero no desplazan.
    marcadas = [f for f in filas if (f.meta or {}).get("comparable_entre_paises")]
    con_valor = [f for f in marcadas if f.value is not None]
    sin_valor = [f for f in marcadas if f.value is None]
    comparables = (con_valor + sin_valor)[:limite]
    exigir_comparable(comparables)

    cortes: Dict[str, str] = {}
    for fila in comparables:
        if fila.period_end:
            previo = cortes.get(fila.iso_code)
            if previo is None or fila.period_end.isoformat() > previo:
                cortes[fila.iso_code] = fila.period_end.isoformat()
    return {
        "tabla_comparable": [_valor(f) | {"iso3": f.iso_code,
                                          "pais": NOMBRE_PAIS.get(f.iso_code, f.iso_code)}
                             for f in comparables],
        "cortes_por_pais": dict(sorted(cortes.items())),
        "por_que_se_puede_comparar": (
            "Estas cifras vienen de las Estadísticas Monetarias y Financieras Armonizadas "
            "(EMFA) del Consejo Monetario Centroamericano, que es lo único que el propio "
            "organismo regional declara armonizado."),
        "que_NO_se_compara": (
            "Los saldos de crédito, aunque vengan de EMFA: están en moneda local y el cuadro "
            "de origen deja la unidad sin declarar. De ellos se habla por su trayectoria "
            "dentro de cada país."),
    }


def contexto_del_boletin(db: Session) -> Dict[str, Dict[str, Any]]:
    """El contexto de las dos secciones regionales, listo para el motor."""
    return {
        "boletin_sistemas": contexto_por_sistema(db),
        "boletin_armonizado": contexto_armonizado(db),
    }


def paises_cubiertos(db: Session) -> List[str]:
    """Los países con al menos una cifra. Para declarar la cobertura sin adivinarla."""
    return sorted({r[0] for r in db.query(CountryBankingAggregate.iso_code).distinct()})


def contexto_o_nada(db: Session, seccion: str) -> Optional[Dict[str, Any]]:
    """El contexto de una sección regional, o ``None`` si no hay dato.

    Sin dato no hay sección: pedirle al modelo que narre un contexto vacío produce una
    sección hueca, y el boletín está entre los tipos que fallan cerrado ante eso.
    """
    try:
        contexto = contexto_del_boletin(db).get(seccion)
    except ComparacionNoArmonizada:
        raise
    except Exception as e:  # noqa: BLE001 — sin dato se calla, no se inventa
        logger.warning("[boletín] contexto de %s no disponible: %s", seccion, e)
        return None
    if not contexto:
        return None
    if seccion == "boletin_sistemas" and not contexto.get("bloques_por_pais"):
        return None
    if seccion == "boletin_armonizado" and not contexto.get("tabla_comparable"):
        return None
    return contexto
