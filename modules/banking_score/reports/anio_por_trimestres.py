"""El año POR DENTRO: la serie de sus trimestres y el movimiento de cada tramo.

**Qué lo distingue de la Revisión Anual.** Lo fijó el dueño el 2026-08-27, después de que los
dos productos estuvieran sirviendo el mismo informe:

* **acá** —dentro de «SDQ Banking Intelligence»— el año se arma como SERIE DE SUS TRIMESTRES:
  cómo se comportó el año completo y **las variaciones trimestre a trimestre**;
* en «SDQ Banking · Revisión Anual», el año TOTAL contra los años anteriores y la tendencia.

La diferencia no es de profundidad ni de sujeto: es la **unidad de comparación**. Acá se
compara *dentro* del año; allá, *entre* años.

**Lo que esto responde y la foto de diciembre no:** cuándo se rompió. Amplitud, pico y valle
dicen cuánto se movió el año; el movimiento de cada tramo dice EN QUÉ TRIMESTRE, que es lo que
un comité necesita para saber si el deterioro es reciente o viene de arrastre.

**El cierre del año anterior es la línea base, no un trimestre del año.** Se incluye para que
el primer tramo (dic→marzo) exista: sin él, el año empezaría en marzo y el primer trimestre no
tendría contra qué medirse. Va marcado como tal.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank
from modules.banking_score.reports.trimestre_en_contexto import COMO_LEER_EL_ROTULO

logger = logging.getLogger("sdq.banking.anio_por_trimestres")

#: Por debajo de esto un tramo no se llama movimiento: es ruido. Mismo criterio que el resto
#: del eje.
UMBRAL_TRAMO = 0.5

#: Rótulo de cada tramo, por el mes en que TERMINA. Se declara en vez de derivarse de la
#: fecha: «2025-03» no le dice a nadie que es el primer trimestre.
_TRAMO_LABEL = {3: "primer trimestre", 6: "segundo trimestre",
                9: "tercer trimestre", 12: "cuarto trimestre"}

#: Lenguaje que el dato del AÑO POR DENTRO no sostiene, vigilado en CÓDIGO. El Deep Dive 2025 de
#: Banco Múltiple Santa Cruz regenerado en producción (2026-09-15) atribuyó la oscilación de
#: eficiencia a «intensidad estacional» sobre dos trimestres que el rótulo computado declaraba
#: atípicos frente a su historia, con la plantilla prohibiéndolo; y llamó «umbral mínimo» al
#: nivel de referencia del modelo, que no es el mínimo de nadie. Una nota al modelo no es un guard.
TERMINOS_VETADOS_DEL_ANIO = (r"estacional\w*", r"umbral(?:es)?\s+m[ií]nimos?")

_VETADOS_RE = [re.compile(r"(?<![\wáéíóúñ])" + p, re.IGNORECASE) for p in TERMINOS_VETADOS_DEL_ANIO]

#: Lo que se agrega al contexto en el segundo intento si el texto usó un término vetado.
CORRECCION_DE_TERMINOS_DEL_ANIO = (
    "El texto anterior usó {terminos}. Ese lenguaje no lo sostiene el dato de este año: un "
    "patrón que se repite solo se afirma con el rótulo de 'contexto_de_los_tramos' que lo "
    "respalda, y el nivel de referencia del modelo no es un mínimo. Reescribí sin esos términos: "
    "copiá el rótulo de cada trimestre y nombrá el nivel de referencia como tal.")


def terminos_vetados_en_el_anio(texto: str) -> List[str]:
    """Los términos vetados que aparecen en *texto*, como aparecen, sin repetir."""
    halladas: List[str] = []
    for patron in _VETADOS_RE:
        for m in patron.finditer(texto or ""):
            if m.group(0).lower() not in halladas:
                halladas.append(m.group(0).lower())
    return halladas


def quitar_oraciones_con_terminos_vetados(texto: str) -> str:
    """Quita SOLO las oraciones que contienen un término vetado; conserva párrafos y el resto.

    Es el último recurso, después de regenerar con la corrección: la especulación que el dato
    niega no se publica, pero tampoco se niega un informe entero por una oración."""
    lineas = []
    for linea in (texto or "").split("\n"):
        oraciones = re.split(r"(?<=[.!?])\s+", linea)
        lineas.append(" ".join(o for o in oraciones
                               if not any(p.search(o) for p in _VETADOS_RE)))
    return "\n".join(lineas)


def _tramos(puntos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """El movimiento de CADA tramo, no solo los extremos del año."""
    out: List[Dict[str, Any]] = []
    for antes, despues in zip(puntos, puntos[1:]):
        s0, s1 = antes.get("score"), despues.get("score")
        if s0 is None or s1 is None:
            continue
        delta = round(float(s1) - float(s0), 2)
        corte = str(despues["period_end"])
        mes = int(corte[5:7])
        if abs(delta) < UMBRAL_TRAMO:
            direccion = "estable"
        else:
            direccion = "al alza" if delta > 0 else "a la baja"
        out.append({
            "tramo": _TRAMO_LABEL.get(mes, corte[:7]),
            "desde": str(antes["period_end"]), "hasta": corte,
            # El SUJETO en la clave: servido como `score_desde` el texto publicó «el score de
            # solidez abrió en 64.15» sobre el global (Santa Cruz, 2026-09-15).
            "score_global_desde": round(float(s0), 2),
            "score_global_hasta": round(float(s1), 2),
            "cambio": delta,
            "direccion": direccion,
            # La banda sale del eje de Resiliencia, no del score global. Va su número.
            "resiliencia_desde": antes.get("resiliencia"),
            "resiliencia_hasta": despues.get("resiliencia"),
            "banda_hasta": despues.get("banda_resiliencia"),
        })
    return out


def _tramo_que_mas_movio(tramos: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """El trimestre que más movió el score, con su cuota del movimiento total.

    Es una RELACIÓN y por eso se computa: «el 62 % de la caída del año ocurrió en el tercer
    trimestre» es la frase que el comité usa, y deducirla es exactamente lo que el modelo hace
    mal. La cuota se mide sobre la suma de los movimientos EN VALOR ABSOLUTO — sobre el neto,
    un año que baja y sube daría cuotas por encima del 100 % sin que nada esté mal.
    """
    con_cambio = [t for t in tramos if t.get("cambio") is not None]
    if not con_cambio:
        return None
    total = sum(abs(float(t["cambio"])) for t in con_cambio)
    mayor = max(con_cambio, key=lambda t: abs(float(t["cambio"])))
    return {
        "tramo": mayor["tramo"],
        "cambio": mayor["cambio"],
        "cuota_del_movimiento_pct": (None if total <= 0
                                     else round(abs(float(mayor["cambio"])) / total * 100, 1)),
        "movimiento_total_absoluto": round(total, 2),
        "lectura": ("es el trimestre donde más se movió el score del año; la cuota se mide "
                    "sobre la suma de los movimientos en valor absoluto, no sobre el neto"),
    }


def _tramos_por_dimension(sub: Dict[str, List[Dict[str, Any]]],
                          cortes: List[str]) -> List[Dict[str, Any]]:
    """El mismo corte a corte, por sub-componente: qué dimensión se movió en qué trimestre."""
    filas: List[Dict[str, Any]] = []
    for dim, serie in sorted((sub or {}).items()):
        por_corte = {str(p.get("period_end")): p for p in (serie or []) if isinstance(p, dict)}
        puntos = [por_corte[c] for c in cortes if c in por_corte]
        movimientos = []
        for antes, despues in zip(puntos, puntos[1:]):
            s0, s1 = antes.get("score"), despues.get("score")
            if s0 is None or s1 is None:
                continue
            corte = str(despues["period_end"])
            movimientos.append({
                "tramo": _TRAMO_LABEL.get(int(corte[5:7]), corte[:7]),
                "cambio": round(float(s1) - float(s0), 2)})
        if movimientos:
            filas.append({"dimension": dim, "por_tramo": movimientos})
    return filas


def anio_por_trimestres(db: Session, bank: Bank, anio: int) -> Optional[Dict[str, Any]]:
    """El año de *bank* leído por dentro. ``None`` si el año no cerró o falta panel."""
    from modules.banking_score.reports.revision_anual import (_balance, _bandas_del_anio,
                                                              _camino, _cortes_del_anio,
                                                              _serie_del_anio)
    from modules.banking_score.scoring.amplitude import entity_trajectories

    cortes = _cortes_del_anio(anio)
    cierre = date(anio, 12, 31)
    traj = entity_trajectories(db, bank, n=9, as_of=cierre)
    puntos = _serie_del_anio(traj.get("overall") or [], cortes)
    if not puntos or str(puntos[-1]["period_end"]) != cortes[-1]:
        logger.info("Año por trimestres %s de %s: el año no cerró.", anio, bank.name)
        return None
    if len(puntos) < 2:
        return None

    faltantes = [c for c in cortes if c not in {str(p["period_end"]) for p in puntos}]
    tramos = _tramos(puntos)
    # CADA TRIMESTRE EN SU CONTEXTO (2026-09-15, feedback de Banco Santa Cruz): contra el
    # mismo trimestre de años anteriores y contra el resto del sistema en ese corte. Sin
    # esto, «concentró el 51 % del movimiento» no dice si es un hallazgo o lo de siempre.
    contexto = _contexto_de_los_tramos(db, bank, anio, tramos)
    mayor = _tramo_que_mas_movio(tramos)
    if mayor and contexto:
        del_mayor = next((c for c in contexto if c["tramo"] == mayor["tramo"]), None)
        if del_mayor:
            mayor["rotulo"] = del_mayor["rotulo"]
            mayor["se_destaca"] = del_mayor["se_destaca"]
    return {
        "anio": anio,
        "entidad": bank.name,
        "lectura_del_producto": (
            "Este informe lee el año POR DENTRO: la serie de sus trimestres y el movimiento "
            "de cada tramo. La comparación contra los años anteriores y la tendencia "
            "plurianual son el otro producto, «SDQ Banking · Revisión Anual»."),
        "serie": [{"corte": str(p["period_end"]),
                   "score_global": round(float(p["score"]), 2),
                   "resiliencia": p.get("resiliencia"),
                   "banda": p.get("banda_resiliencia"),
                   "es_linea_base": str(p["period_end"]) == cortes[0]}
                  for p in puntos],
        # El cierre del año anterior es LÍNEA BASE, no un trimestre del año: sin él el primer
        # tramo no existiría, y con él sin marcar el año parecería tener cinco trimestres.
        "linea_base": cortes[0],
        "cortes_faltantes": faltantes,
        "tramos": tramos,
        "tramo_que_mas_movio": mayor,
        "contexto_de_los_tramos": contexto,
        "como_leer_el_contexto_de_los_tramos": COMO_LEER_EL_ROTULO,
        "tramos_por_dimension": _tramos_por_dimension(traj.get("sub") or {}, cortes),
        "camino": _camino(puntos),
        "cambios_de_banda": _bandas_del_anio(puntos),
        "balance": _balance(traj.get("indicators") or {}, cortes),
        # La MOROSIDAD ESTRESADA oficial de la SIB a la apertura y al cierre (2026-09-15): la
        # mora del balance compara mal entre entidades con políticas de castigo distintas.
        "morosidad_estresada": _estresada_del_anio(db, bank, cortes),
    }


def _contexto_de_los_tramos(db: Session, bank: Bank, anio: int,
                            tramos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from modules.banking_score.reports.trimestre_en_contexto import contexto_de_los_tramos
    try:
        return contexto_de_los_tramos(db, bank, anio, tramos)
    except Exception:  # noqa: BLE001 — el año por dentro nunca depende de este bloque
        logger.exception("No se pudo poner en contexto los trimestres de %s", bank.name)
        return []


def _estresada_del_anio(db: Session, bank: Bank, cortes: List[str]) -> Optional[Dict[str, Any]]:
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_del_anio
    try:
        return morosidad_estresada_del_anio(db, bank, cortes)
    except Exception:  # noqa: BLE001 — el año por dentro nunca depende de este bloque
        logger.exception("No se pudo computar la morosidad estresada del año de %s", bank.name)
        return None
