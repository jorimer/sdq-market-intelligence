"""¿`solidez` ordena al revés, o el panel mezcla poblaciones que no se comparan?

**El hecho.** Medido contra el panel real (`docs/DIAGNOSTICO_DISCRIMINACION_BANCA.md`), la
dimensión de mayor peso del score —`solidez`, 40 %— tiene Gini **−0,1944** con el IC entero
bajo cero: las entidades que más capital muestran son las que más deterioro registran después.

**Las dos explicaciones y por qué no da lo mismo cuál sea.** Si la señal está invertida DENTRO
de cada población, el problema es del indicador y se arregla en la curva o en la definición. Si
está bien orientada dentro de cada población y el signo lo produce mezclarlas, el problema es
del UNIVERSO sobre el que se mide y arreglar la curva no toca la causa — la empeora, porque
cambia un indicador que estaba midiendo bien.

Hay motivo concreto para sospechar de lo segundo, escrito en el propio motor
(`scoring/cambiaria.py`): las entidades de intermediación cambiaria están sobrecapitalizadas
—mediana de patrimonio/activos **91 %**— y eso les deprime el ROA de forma mecánica. «Lo mismo
que las hace puntuar alto en solidez las hace puntuar bajo en rentabilidad». Como el 83 % del
desenlace es la regla de ROA<0 sostenido, un grupo así basta para dar vuelta el signo agregado
sin que `solidez` ordene mal en ningún lado.

**El método: pares comparables.** El Gini es una cuenta de pares (evento vs no-evento). Este
diagnóstico repite la cuenta contando SOLO los pares que comparten estrato —mismo tipo de
entidad, mismo tramo de tamaño, ambos— y compara ese número con el agregado. Es el mismo
principio que la doctrina ya aplica a los rankings: solo se ordena lo comparable. El veredicto
se COMPUTA de los dos intervalos, no se narra.

**Lo que este diagnóstico NO hace:** no toca el score, no persiste nada y no propone pesos. Su
salida es evidencia para decidir, y la decisión es del dueño.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple, cast

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, BankingData, ModelType, RatingResult
from modules.banking_score.scoring.weights import (
    CALIDAD_INDICATORS, DIVERSIFICACION_INDICATORS, EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS, SOLIDEZ_INDICATORS,
)
from modules.banking_score.validation.metrics import (
    gini_bootstrap_ci, gini_estratificado_bootstrap_ci, spearman,
)
from modules.banking_score.validation.outcomes_derivation import HORIZON_Q, derive_observations
from modules.banking_score.validation.report import FAMILIAS_DESENLACE

# El desenlace agregado va PRIMERO y con su nombre real: es la unión de las tres reglas, la
# que produjo el −0,1944 publicado. Se conserva para que la comparación con el informe sea
# directa, pero las familias son las que se leen — el agregado mezcla fenómenos.
_TODAS_LAS_REGLAS = tuple(sorted({r for _c, reglas, _g in FAMILIAS_DESENLACE for r in reglas}))
FAMILIAS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("desenlace_agregado", _TODAS_LAS_REGLAS,
     "la unión de las tres reglas — la cifra publicada, que mezcla fenómenos"),
) + tuple((c, tuple(r), g) for c, r, g in FAMILIAS_DESENLACE)

_INDICADORES_POR_DIMENSION: Dict[str, List[str]] = {
    "solidez": SOLIDEZ_INDICATORS,
    "calidad": CALIDAD_INDICATORS,
    "eficiencia": EFICIENCIA_INDICATORS,
    "liquidez": LIQUIDEZ_INDICATORS,
    "diversificacion": DIVERSIFICACION_INDICATORS,
}

# Debajo de esta cantidad de eventos el Gini de un estrato es demasiado fino para apoyarse en
# él. Mismo umbral que el reporte del backtest: dos superficies que dicen "fino" por lo mismo.
_EVENTOS_FINOS = 30

# Poblaciones que NO otorgan crédito y que por eso no se comparan con un banco: una entidad
# de cambio está sobrecapitalizada por diseño del negocio (mediana patrimonio/activos 91 %) y
# una fiduciaria administra patrimonios ajenos. Puntúan alto en solidez por razones que no
# son prudenciales. Se las nombra para poder medir CON y SIN ellas, no para esconderlas.
_POBLACIONES_SIN_LIBRO_DE_CREDITO = ("cambiaria", "fiduciaria")

# Cuánto de la inversión tiene que sobrevivir para llamarla intrínseca y no parcial. Es un
# corte convencional y por eso está acá con nombre: si al estratificar queda menos de tres
# cuartos de la magnitud, la composición explicaba una parte grande y decir «intrínseca» a
# secas mandaría a arreglar la curva por un defecto que es mayormente de universo.
_RESTO_TRAS_ESTRATIFICAR = 0.75

# La prosa que el informe copia vive en constantes: incrustada en el dict se parte por ancho
# de línea y la frase deja de existir en el fuente.
VEREDICTO_COMPOSICIONAL = (
    "composicional: la inversión NO sobrevive a comparar solo dentro del mismo estrato, así "
    "que la produce mezclar poblaciones distintas en un mismo ordenamiento"
)
VEREDICTO_INTRINSECO = (
    "intrínseca: la inversión sobrevive a comparar solo dentro del mismo estrato, así que es "
    "del indicador y no de la composición del panel"
)
VEREDICTO_PARCIAL = (
    "parcial: estratificar acerca el Gini a cero pero el intervalo sigue sin cruzarlo — la "
    "composición explica parte de la inversión, no toda"
)
VEREDICTO_SIN_INVERSION = (
    "no aplica: el intervalo agregado no está enteramente bajo cero, así que no hay inversión "
    "que explicar"
)
VEREDICTO_SIN_PARES = (
    "no evaluable: estratificar deja sin pares comparables (evento y no-evento en un mismo "
    "estrato), así que la pregunta no se puede responder con este panel"
)


@dataclass(frozen=True)
class _Fila:
    """Una observación del panel con lo que hace falta para estratificarla."""
    dimension: float
    etiquetas: Dict[str, int]
    tipo: str
    activos: Optional[float]
    indicadores: Dict[str, float]


def _gini(scores: Sequence[float], labels: Sequence[int], n_boot: int) -> Dict:
    g, lo, hi = gini_bootstrap_ci(list(scores), list(labels), n_boot=n_boot)
    if g is None:
        return {"gini": None, "gini_ci": None, "invertida": False, "concluyente": False}
    ci = None if lo is None or hi is None else [round(lo, 4), round(hi, 4)]
    return {
        "gini": round(g, 4), "gini_ci": ci,
        "invertida": bool(hi is not None and hi < 0),
        "concluyente": bool(lo is not None and lo > 0),
    }


def _gini_dentro(scores: Sequence[float], labels: Sequence[int], estratos: Sequence[str],
                 n_boot: int) -> Dict:
    g, lo, hi, pares = gini_estratificado_bootstrap_ci(
        list(scores), list(labels), list(estratos), n_boot=n_boot)
    if g is None:
        return {"gini": None, "gini_ci": None, "pares_comparables": 0,
                "invertida": False, "concluyente": False}
    ci = None if lo is None or hi is None else [round(lo, 4), round(hi, 4)]
    return {
        "gini": round(g, 4), "gini_ci": ci, "pares_comparables": pares,
        "invertida": bool(hi is not None and hi < 0),
        "concluyente": bool(lo is not None and lo > 0),
    }


def _mediana(valores: List[float]) -> Optional[float]:
    if not valores:
        return None
    v = sorted(valores)
    m = len(v)
    return v[m // 2] if m % 2 else (v[m // 2 - 1] + v[m // 2]) / 2.0


def _veredicto(agregado: Dict, dentro: Dict) -> Dict:
    """Compara los DOS intervalos y devuelve el veredicto computado, no narrado.

    La pregunta es si la inversión sobrevive a comparar solo lo comparable. Sobrevive =
    intrínseca; desaparece = composicional; se achica sin cruzar cero = parcial.
    """
    if not agregado.get("invertida"):
        return {"clave": "sin_inversion", "texto": VEREDICTO_SIN_INVERSION}
    if dentro.get("gini") is None:
        return {"clave": "sin_pares", "texto": VEREDICTO_SIN_PARES}
    g_agg = cast(float, agregado["gini"])
    g_dentro = cast(float, dentro["gini"])
    if not dentro.get("invertida"):
        return {"clave": "composicional", "texto": VEREDICTO_COMPOSICIONAL,
                "gini_agregado": g_agg, "gini_dentro_del_estrato": g_dentro}
    # Sigue invertida dentro del estrato: ¿al menos se achicó?
    clave = "parcial" if abs(g_dentro) < abs(g_agg) * _RESTO_TRAS_ESTRATIFICAR else "intrinseca"
    return {"clave": clave,
            "texto": VEREDICTO_PARCIAL if clave == "parcial" else VEREDICTO_INTRINSECO,
            "gini_agregado": g_agg, "gini_dentro_del_estrato": g_dentro}


def _por_estrato(filas: List[_Fila], familia: str, clave_estrato, n_boot: int,
                 dimension: str) -> List[Dict]:
    """Un Gini por estrato, con su N y sus eventos. Los finos se marcan, no se ocultan."""
    grupos: Dict[str, List[_Fila]] = {}
    for f in filas:
        est = clave_estrato(f)
        if est is not None:
            grupos.setdefault(est, []).append(f)
    salida: List[Dict] = []
    for est, gs in sorted(grupos.items()):
        etiquetas = [g.etiquetas[familia] for g in gs]
        eventos = sum(etiquetas)
        fila: Dict = {
            "estrato": est, "n": len(gs), "eventos": eventos,
            "tasa_de_evento": round(eventos / len(gs), 4) if gs else None,
            f"{dimension}_mediana": _mediana([g.dimension for g in gs]),
            "activos_totales_mediana": _mediana(
                [g.activos for g in gs if g.activos is not None]),
        }
        if eventos == 0 or eventos == len(gs):
            fila.update({"gini": None, "gini_ci": None, "invertida": False,
                         "concluyente": False,
                         "motivo": "una sola clase en el estrato: no hay par que ordenar"})
        else:
            fila.update(_gini([g.dimension for g in gs], etiquetas, n_boot))
        fila["fino"] = bool(0 < eventos < _EVENTOS_FINOS)
        salida.append(fila)
    return salida


def _terciles(valores: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if len(valores) < 3:
        return None, None
    v = sorted(valores)
    return v[len(v) // 3], v[(2 * len(v)) // 3]


def diagnosticar_composicion(db: Session, dimension: str = "solidez",
                             horizon_q: int = HORIZON_Q, n_boot: int = 1000) -> Dict:
    """Mide *dimension* contra cada familia de desenlace, agregada y dentro del estrato."""
    if dimension not in _INDICADORES_POR_DIMENSION:
        return {"ok": False, "motivo": f"dimensión desconocida: {dimension}"}
    obs = derive_observations(db, horizon_q=horizon_q)
    if not obs:
        return {"ok": False, "motivo": "sin panel: no hay observaciones con horizonte"}

    ratings = {(str(r.bank_id), cast(date, r.period_end)): r for r in
               db.query(RatingResult).filter(
                   RatingResult.model_type == ModelType.deterministic).all()}
    financieros = {(str(d.bank_id), cast(date, d.period_end)): d
                   for d in db.query(BankingData).all()}
    tipo_por_banco: Dict[str, str] = {
        str(b.id): (b.bank_type.value if hasattr(b.bank_type, "value") else str(b.bank_type))
        for b in db.query(Bank).all()
    }
    claves_indicador = _INDICADORES_POR_DIMENSION[dimension]

    filas: List[_Fila] = []
    sin_dimension = 0
    sin_tamano = 0
    sin_indicadores = 0
    for o in obs:
        rr = ratings.get((str(o.bank_id), o.period_end))
        valor = None if rr is None else getattr(rr, f"{dimension}_score", None)
        if valor is None:
            sin_dimension += 1
            continue
        bd = financieros.get((str(o.bank_id), o.period_end))
        activos = (float(bd.activos_totales)
                   if bd is not None and bd.activos_totales else None)
        if activos is None:
            sin_tamano += 1
        # Los indicadores salen del detalle PERSISTIDO, que es el que produjo el score de esa
        # fecha. Recomputarlos hoy mediría otra cosa: la curva vigente sobre el crudo viejo.
        detalle = getattr(rr, "indicator_details", None) or {}
        indicadores: Dict[str, float] = {}
        for k in claves_indicador:
            d = detalle.get(k) if isinstance(detalle, dict) else None
            if isinstance(d, dict) and d.get("available", True) and d.get("score") is not None:
                indicadores[k] = float(d["score"])
        if not indicadores:
            # Cambiarias y fiduciarias arman sus dimensiones con OTROS indicadores: no tener
            # estas claves no es un hueco de dato, es otra población. Se cuenta y se declara.
            sin_indicadores += 1
        filas.append(_Fila(
            dimension=float(valor),
            etiquetas={clave: (1 if set(o.triggers or ()) & set(reglas) else 0)
                       for clave, reglas, _g in FAMILIAS},
            tipo=tipo_por_banco.get(o.bank_id) or "desconocido",
            activos=activos,
            indicadores=indicadores,
        ))

    if not filas:
        return {"ok": False,
                "motivo": f"ninguna observación del panel tiene `{dimension}`"}

    corte_bajo, corte_alto = _terciles([f.activos for f in filas if f.activos is not None])

    def _tramo(f: _Fila) -> Optional[str]:
        if f.activos is None or corte_bajo is None or corte_alto is None:
            return None
        if f.activos <= corte_bajo:
            return "1-chico"
        return "2-mediano" if f.activos <= corte_alto else "3-grande"

    def _tipo_y_tramo(f: _Fila) -> Optional[str]:
        t = _tramo(f)
        return None if t is None else f"{f.tipo}·{t}"

    dim_valores = [f.dimension for f in filas]
    ajenas_fuera = [f for f in filas if f.tipo not in _POBLACIONES_SIN_LIBRO_DE_CREDITO]
    familias_salida: Dict[str, Dict] = {}
    for clave, _reglas, glosa in FAMILIAS:
        etiquetas = [f.etiquetas[clave] for f in filas]
        eventos = sum(etiquetas)
        if eventos == 0:
            familias_salida[clave] = {
                "que_mide": glosa, "n_observaciones": len(filas), "eventos": 0,
                "evaluable": False,
                "nota": "la regla no disparó en toda la ventana: no hay evidencia, ni a "
                        "favor ni en contra",
            }
            continue
        agregado = _gini(dim_valores, etiquetas, n_boot)
        # Estratificar por tamaño descarta las filas sin activos: se declara con su N.
        con_tamano = [(f, e) for f, e in zip(filas, etiquetas) if _tramo(f) is not None]
        dentro_tipo = _gini_dentro(dim_valores, etiquetas, [f.tipo for f in filas], n_boot)
        dentro_tamano = _gini_dentro(
            [f.dimension for f, _e in con_tamano], [e for _f, e in con_tamano],
            [cast(str, _tramo(f)) for f, _e in con_tamano], n_boot)
        dentro_ambos = _gini_dentro(
            [f.dimension for f, _e in con_tamano], [e for _f, e in con_tamano],
            [cast(str, _tipo_y_tramo(f)) for f, _e in con_tamano], n_boot)
        familias_salida[clave] = {
            "que_mide": glosa,
            "n_observaciones": len(filas),
            "eventos": eventos,
            "evaluable": True,
            "agregado": agregado,
            "dentro_del_tipo_de_entidad": dentro_tipo,
            "dentro_del_tramo_de_tamano": {**dentro_tamano, "n_observaciones": len(con_tamano)},
            "dentro_de_tipo_y_tamano": {**dentro_ambos, "n_observaciones": len(con_tamano)},
            # La pregunta práctica: si la credencial se midiera solo sobre las entidades que
            # SÍ toman riesgo de crédito, ¿qué diría? No es el veredicto —es un universo más
            # chico, con su propio N— pero es la cifra que un lector de banca espera.
            "solo_entidades_con_libro_de_credito": {
                **_gini([f.dimension for f in ajenas_fuera],
                        [f.etiquetas[clave] for f in ajenas_fuera], n_boot),
                "n": len(ajenas_fuera),
                "eventos": sum(f.etiquetas[clave] for f in ajenas_fuera),
                "excluye": list(_POBLACIONES_SIN_LIBRO_DE_CREDITO),
            },
            "veredicto": _veredicto(agregado, dentro_tipo),
            "veredicto_tipo_y_tamano": _veredicto(agregado, dentro_ambos),
            "por_tipo_de_entidad": _por_estrato(
                filas, clave, lambda f: f.tipo, n_boot, dimension),
            "por_tramo_de_tamano": _por_estrato(filas, clave, _tramo, n_boot, dimension),
            # El tamaño puesto a competir COMO score, con la misma convención (más activo =
            # menos riesgo). Si ordena mejor que la dimensión, la dimensión está siendo un
            # proxy malo de algo que el tamaño dice directamente.
            "activos_totales_como_score": _gini(
                [cast(float, f.activos) for f, _e in con_tamano],
                [e for _f, e in con_tamano], n_boot),
            # Cada indicador con SU N: la población no es la misma que la de la dimensión
            # (solo las entidades que usan el set estándar tienen estas claves).
            "por_indicador": {
                k: {**_gini([f.indicadores[k] for f in filas if k in f.indicadores],
                            [f.etiquetas[clave] for f in filas if k in f.indicadores], n_boot),
                    "n": sum(1 for f in filas if k in f.indicadores),
                    "eventos": sum(f.etiquetas[clave] for f in filas if k in f.indicadores)}
                for k in claves_indicador
                if any(k in f.indicadores for f in filas)
            },
        }

    activos_pareados = [(f.dimension, f.activos) for f in filas if f.activos is not None]
    rho = spearman([d for d, _a in activos_pareados],
                   [cast(float, a) for _d, a in activos_pareados])
    return {
        "ok": True,
        "dimension": dimension,
        "panel": {
            "n_observaciones_backtest": len(obs),
            "n_con_dimension": len(filas),
            "n_sin_dimension": sin_dimension,
            "n_sin_tamano": sin_tamano,
            "n_sin_indicadores_de_la_dimension": sin_indicadores,
            "cortes_de_tamano_activos_totales": [corte_bajo, corte_alto],
            "tipos_de_entidad_en_el_panel": sorted({f.tipo for f in filas}),
        },
        "correlacion_dimension_vs_tamano": {
            "spearman": None if rho is None else round(rho, 4),
            "n": len(activos_pareados),
            "lectura": (
                f"rho<0 significa que las entidades con más `{dimension}` son las más "
                "CHICAS, que es el mecanismo que la hipótesis composicional supone"
            ),
        },
        "familias": familias_salida,
        "limite_declarado": (
            "Los estratos de tamaño son terciles del activo total al corte de cada "
            "observación (no el `peer_group` del catálogo, que es estático). El desglose por "
            "indicador sale del detalle persistido y solo existe para las entidades que usan "
            "el set estándar: cambiarias y fiduciarias arman sus dimensiones con otros "
            "indicadores y quedan contadas aparte, no mezcladas."
        ),
    }
