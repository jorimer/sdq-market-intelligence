"""¿Qué entidad tiene estados suficientes para sostener una calificación?

**La decisión ya estaba tomada, y a medias.** `docs/PROPUESTA_CAMBIARIAS_FIDUCIARIAS.md` §0
(2026-06-08) resolvió el alcance de intermediación cambiaria así: construir el submodelo para
los **6 agentes de remesas (ARC)** —que tienen balances reales— y para los **agentes de cambio
(AC) por encima de un umbral mínimo de activos**, porque *«calificar las 35 AC completas añade
ruido: muchas ventanillas pequeñas, balances cercanos a cero»*. Las de abajo **se listan**,
marcadas «sin rating significativo». La v1 salió con las 42 y el umbral quedó sin calibrar.

**Por qué importa más de lo que parecía.** Medido el 2026-08-19
(`docs/DIAGNOSTICO_COMPOSICION_SOLIDEZ.md`), esas entidades son **794 de las 1.693
observaciones del backtest (47 %)** y aportan el **63 % de los eventos**; su activo mediano es
1.390 veces menor que el de un banco múltiple y su `solidez` mediana es 92,7/100 porque están
sobrecapitalizadas por diseño del negocio. Son las que dan vuelta el signo de la dimensión de
mayor peso del score.

**El subtipo ARC/AC no existe en nuestro modelo**: `sib_sync` mapea los dos códigos del SIB a
un mismo `BankType.cambiaria`. Por eso la regla se expresa por MATERIALIDAD del balance, que es
lo que la propuesta quería separar de todos modos: los ARC son precisamente los que tienen
balance material.

Este módulo hoy **solo mide**: produce la evidencia con la que se fija el piso. Fijar un número
sin haber visto la distribución sería exactamente lo que la propuesta dejó pendiente, con otra
firma.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, BankingData

#: Tipos cuyo alcance la propuesta acotó por materialidad. Los demás entran completos.
TIPOS_CON_UMBRAL = ("cambiaria",)

#: Cuánto puede despegarse el ÚLTIMO activo de la mediana de la propia entidad antes de que
#: deje de ser un tamaño y pase a ser una anomalía de esa serie. El activo total es un STOCK:
#: una entidad que opera no lo multiplica ni lo divide por cinco de un trimestre al otro. Si
#: lo hace, su último estado es un cierre de operaciones o un defecto de parseo — y en los dos
#: casos no puede definir una clase de tamaño.
#: Salió de la corrida real (2026-08-20): Placidoiv tiene mediana RD$8,3 MM y último RD$48,7 M
#: —170× contra sí misma— y era el ÚNICO «escalón» del panel. Calibrar el piso ahí habría sido
#: calibrarlo sobre un artefacto.
FACTOR_ANOMALIA = 5.0

#: Cuánto tiene que valer un salto entre entidades consecutivas para llamarlo ESCALÓN y no
#: simplemente la siguiente entidad más chica. Menos de un orden de magnitud entre vecinas es
#: la misma población a otra escala; la propuesta afirmaba dos clases —un puñado con balance
#: real y una cola de ventanillas vacías— y esa afirmación necesita un corte que se vea.
RAZON_MINIMA_ESCALON = 10.0

ESCALERA_CONTINUA = (
    "no hay escalón: entre entidades vecinas no aparece ningún salto que separe dos clases, "
    "así que el panel es una sola población a distintas escalas y cualquier piso lo elegiría "
    "una persona, no el dato"
)
ESCALERA_CON_ESCALON = (
    "hay escalón: un salto entre vecinas separa dos clases de tamaño, y el piso sale de ahí "
    "sin que nadie lo elija"
)


def _percentiles(valores: List[float], cortes=(10, 25, 50, 75, 90)) -> Dict[str, float]:
    if not valores:
        return {}
    v = sorted(valores)
    return {f"p{c}": v[min(len(v) - 1, int(c / 100 * len(v)))] for c in cortes}


def perfil_de_materialidad(db: Session, tipo: str = "cambiaria") -> Dict:
    """Distribución del activo total por entidad de *tipo*, para calibrar el piso.

    Devuelve una fila POR ENTIDAD —con su activo mediano, su último activo y su cuota del
    sistema de su tipo— además de los percentiles del panel. La fila por entidad es el punto:
    un percentil solo no muestra si hay un salto natural entre las que tienen balance y las
    ventanillas casi vacías, que es justamente lo que la propuesta afirmaba sin medir.
    """
    ids = {str(b.id): b.name for b in db.query(Bank).filter(Bank.bank_type == tipo).all()}
    if not ids:
        return {"ok": False, "motivo": f"no hay entidades de tipo `{tipo}` en el catálogo"}

    por_entidad: Dict[str, List[float]] = {}
    ultimo: Dict[str, float] = {}
    for d in (db.query(BankingData)
              .filter(BankingData.bank_id.in_(list(ids)))
              .order_by(BankingData.period_end).all()):
        if d.activos_totales is None:
            continue
        valor = float(d.activos_totales)
        por_entidad.setdefault(str(d.bank_id), []).append(valor)
        ultimo[str(d.bank_id)] = valor  # ordenado por período: el último gana

    if not por_entidad:
        return {"ok": False,
                "motivo": f"ninguna entidad de tipo `{tipo}` tiene activo total cargado"}

    def _mediana(xs: List[float]) -> float:
        s = sorted(xs)
        m = len(s)
        return s[m // 2] if m % 2 else (s[m // 2 - 1] + s[m // 2]) / 2.0

    medianas = {k: _mediana(v) for k, v in por_entidad.items()}
    total = sum(ultimo.values()) or 1.0
    # El orden y la aritmética viven sobre valores NUMÉRICOS; las filas de salida se arman
    # después. Mezclar el nombre de la entidad con sus cifras en el mismo dict y ordenar por
    # una de sus claves es lo que vuelve el tipo una unión y esconde un error real de suma.
    orden = sorted(por_entidad, key=lambda k: -ultimo.get(k, 0.0))
    tamanos: List[float] = [ultimo.get(k, 0.0) for k in orden]
    filas: List[Dict[str, object]] = [
        {"entidad": ids.get(k, k),
         "activos_mediana": round(medianas[k], 2),
         "activos_ultimo": round(ultimo.get(k, 0.0), 2),
         "cuota_del_sistema_de_su_tipo": round(ultimo.get(k, 0.0) / total, 6),
         "periodos_con_activo": len(por_entidad[k])}
        for k in orden
    ]
    # ANOMALÍAS. Una entidad cuyo último estado se despega de su propia serie no informa un
    # tamaño: informa un problema. Se computa ANTES de buscar el escalón porque, si no, la
    # anomalía ES el escalón — que es exactamente lo que pasó en la primera corrida.
    anomalas: Dict[str, Dict[str, object]] = {}
    for k in orden:
        med, ult = medianas[k], ultimo.get(k, 0.0)
        if med <= 0 or ult <= 0:
            continue
        razon = max(med / ult, ult / med)
        if razon >= FACTOR_ANOMALIA:
            anomalas[k] = {
                "entidad": ids.get(k, k),
                "activos_mediana": round(med, 2),
                "activos_ultimo": round(ult, 2),
                "razon_contra_su_propia_mediana": round(razon, 2),
                "lectura": ("el último estado se despega de la propia serie de la entidad: "
                            "cierre de operaciones o defecto de dato, no una clase de tamaño"),
            }

    # La ESCALERA se recorre sobre la MEDIANA de cada entidad, no sobre su último valor: la
    # mediana es el tamaño estable y no la mueve un trimestre raro. Los pares donde alguna de
    # las dos vecinas es anómala se computan igual, pero marcados, para que no fijen el piso.
    orden_estable = sorted(por_entidad, key=lambda k: -medianas[k])
    saltos: List[Dict[str, object]] = []
    for i in range(len(orden_estable) - 1):
        arriba, abajo = medianas[orden_estable[i]], medianas[orden_estable[i + 1]]
        if abajo <= 0:
            continue
        sospechoso = orden_estable[i] in anomalas or orden_estable[i + 1] in anomalas
        saltos.append({"posicion": i + 1,
                       "entidad_arriba": ids.get(orden_estable[i], orden_estable[i]),
                       "entidad_abajo": ids.get(orden_estable[i + 1], orden_estable[i + 1]),
                       "razon": round(arriba / abajo, 2),
                       "corte_sugerido": round(abajo, 2),
                       "alguna_vecina_es_anomala": sospechoso})
    limpios = [s for s in saltos if not s["alguna_vecina_es_anomala"]]
    mayores = sorted(saltos, key=lambda s: -float(s["razon"]))[:5]  # type: ignore[arg-type]
    mayor_limpio = max(limpios, key=lambda s: float(s["razon"])) if limpios else None  # type: ignore[arg-type]
    hay_escalon = bool(mayor_limpio
                       and float(mayor_limpio["razon"]) >= RAZON_MINIMA_ESCALON)  # type: ignore[arg-type]
    return {
        "ok": True,
        "tipo": tipo,
        "n_entidades": len(filas),
        "percentiles_activos_ultimo": _percentiles(tamanos),
        "percentiles_activos_mediana": _percentiles(sorted(medianas.values(), reverse=True)),
        "por_entidad": filas,
        "anomalias_ultimo_vs_su_propia_mediana": list(anomalas.values()),
        "saltos_mas_grandes": mayores,
        # El veredicto se COMPUTA de la escalera limpia, no se lee de la tabla. Sin esto, el
        # salto más grande se toma por escalón aunque lo produzca una sola serie rota.
        "escalon": {
            "hay_escalon": hay_escalon,
            "razon_minima_exigida": RAZON_MINIMA_ESCALON,
            "mayor_salto_limpio": mayor_limpio,
            "piso_sugerido": (mayor_limpio or {}).get("corte_sugerido") if hay_escalon else None,
            "veredicto": ESCALERA_CON_ESCALON if hay_escalon else ESCALERA_CONTINUA,
        },
        "nota": (
            "El piso se fija con esta evidencia, no a ojo. La escalera se recorre sobre la "
            "MEDIANA de cada entidad —el tamaño estable— y los pares con una vecina anómala "
            "no pueden fijarlo. Fuente de la decisión: "
            "docs/PROPUESTA_CAMBIARIAS_FIDUCIARIAS.md §0."
        ),
    }


def es_material(bank_type: Optional[str], activos: Optional[float],
                piso: Optional[float]) -> bool:
    """True si la entidad sostiene una calificación significativa.

    Sin piso declarado, TODO es material: un umbral a medio aplicar es peor que ninguno —
    filtraría sin que nadie sepa con qué criterio.
    """
    if piso is None or bank_type not in TIPOS_CON_UMBRAL:
        return True
    return activos is not None and float(activos) >= piso
