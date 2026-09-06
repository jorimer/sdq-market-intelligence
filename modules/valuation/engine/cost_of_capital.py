"""El costo de capital en PESOS. Tres términos, no cuatro, y siempre un rango.

**La moneda es RD$** (decisión del dueño, 2026-09-04), y eso NO es solo una unidad: cambia la
fórmula. La construcción clásica `Rf + β×ERP + CRP` es la de USD —Tesoro americano, prima de
mercado, prima de riesgo país—. Una tasa libre de riesgo **en pesos ya lleva adentro** el
riesgo país y la inflación esperada del peso; sumarle el CRP encima lo cuenta **dos veces**,
infla `Ke` unos 200-400 pb y **subvalúa sistemáticamente a todas las entidades**. Acá son:

    Ke(RD$) = Rf(RD$) + β × ERP

**La beta NO se desapalanca.** Hamada supone que la deuda es financiamiento y que existe un
apalancamiento óptimo separable de la operación. En un banco los depósitos son **materia
prima**: con esa premisa falsa, desapalancar y volver a apalancar produce un número con
apariencia de rigor y sin significado. Se usa la beta de EQUITY de comparables, directa.

**β y ERP son RÚBRICA, no dato.** Son supuestos de comparables latinoamericanos, no
observaciones dominicanas. Viajan declarados y su peso en el resultado se muestra — porque
entre los dos explican la mayor parte de la dispersión de `Ke`.

**`Ke` es un RANGO, nunca un punto.** No es prudencia retórica: el término que más pesa no se
observa. Si el valor de una entidad cambia de SIGNO dentro del rango, eso no es un problema
del modelo — **es el hallazgo**, y va en el resumen ejecutivo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

#: La única moneda de este motor. Existe como constante y no como comentario porque el
#: cruce —`Ke` en USD con `ROE` en RD$— es un error SILENCIOSO: las dos cifras son
#: porcentajes, la resta no falla, y el spread sale mal por la diferencia de inflación
#: esperada entre las dos monedas.
MONEDA = "DOP"

#: El término largo de la curva en pesos: valores subastados del Banco Central, plazo de más
#: de dos años. Es la `Rf` más larga que el emisor publica en moneda nacional — y hay que
#: decir que "más de dos años" no es un punto a diez años.
SERIE_RF = "bcrd.xls.valores_bc_mn.mas_de_dos_anos"

#: Cuántas observaciones recientes forman la `Rf`. Ocho porque el plazo largo no se subasta
#: todos los meses —13 observaciones desde 2024— y una sola lectura queda a merced del mes.
VENTANA_RF = 8

#: β de EQUITY de bancos cotizados latinoamericanos, sin desapalancar. Rango y no punto: es
#: rúbrica, y publicar un punto le daría una precisión que no tiene.
BETA: Tuple[float, float] = (0.85, 1.15)
BETA_EVIDENCIA = (
    "Beta de equity de bancos cotizados en LATAM contra su índice local. NO se desapalanca: "
    "en un banco los depósitos son materia prima y no financiamiento, así que el supuesto de "
    "Hamada —deuda como financiamiento, con un apalancamiento óptimo separable de la "
    "operación— es falso, y desapalancar produce un número con apariencia de rigor y sin "
    "significado. Es RÚBRICA: no hay bancos dominicanos cotizados contra los cuales medirla."
)

#: Prima de riesgo de mercado (equity risk premium) para LATAM. También rúbrica.
ERP: Tuple[float, float] = (5.5, 7.0)
ERP_EVIDENCIA = (
    "Prima de riesgo de mercado de renta variable latinoamericana. RÚBRICA: la República "
    "Dominicana no tiene un mercado accionario con profundidad suficiente para estimarla "
    "localmente, así que se toma de comparables regionales y se declara como supuesto."
)

#: Paso de la tabla de sensibilidad. Cincuenta puntos básicos porque es la escala a la que
#: el resultado de una valuación se mueve de forma perceptible.
PASO_SENSIBILIDAD = 0.50


@dataclass(frozen=True)
class Termino:
    """Un sumando de `Ke`, con su procedencia. La descomposición es auditable o no sirve."""

    nombre: str
    bajo: float
    alto: float
    estado: str          # "real" | "rubric"
    evidencia: str

    @property
    def es_rubrica(self) -> bool:
        return self.estado == "rubric"


@dataclass(frozen=True)
class CostoDeCapital:
    """`Ke` con su rango, su descomposición y su tabla de sensibilidad."""

    moneda: str
    bajo: float
    alto: float
    terminos: Tuple[Termino, ...]
    #: `((ke, etiqueta), …)` en pasos de 50 pb, cubriendo el rango.
    sensibilidad: Tuple[Tuple[float, str], ...]
    n_observaciones_rf: int
    advertencias: Tuple[str, ...] = ()
    #: Primer y último período de las observaciones que armaron la `Rf`. Va al informe: un
    #: rango de tasa sin sus fechas no se puede juzgar.
    ventana_rf: Tuple[str, str] = ("", "")

    @property
    def punto_medio(self) -> float:
        """Existe para graficar, NO para decidir. Quien reporte solo esto pierde justamente
        la información que el rango transporta."""
        return (self.bajo + self.alto) / 2.0

    @property
    def amplitud(self) -> float:
        return self.alto - self.bajo

    @property
    def fraccion_de_rubrica(self) -> float:
        """Cuánto de `Ke` descansa en supuestos y no en dato observado. Se publica: si dos
        tercios del costo de capital son rúbrica, el lector tiene que saberlo."""
        total = sum((t.bajo + t.alto) / 2.0 for t in self.terminos)
        if total <= 0:
            return 0.0
        rub = sum((t.bajo + t.alto) / 2.0 for t in self.terminos if t.es_rubrica)
        return round(rub / total, 4)


def observaciones_al_corte(db: Session, *, serie: str = SERIE_RF,
                           hasta: Optional[date] = None) -> List[Tuple[str, float]]:
    """Las observaciones de la curva PUBLICADAS al corte, en orden cronológico.

    El corte manda: un informe «al 2026-06-30» no puede usar una tasa subastada en julio.
    Un Deep Dive real lo hizo —emitido en septiembre, tomó las últimas ocho vivas sin mirar
    el corte— y el lector no tenía cómo saberlo. Sin `hasta` se devuelve todo, que es lo
    que el readiness y las herramientas de diagnóstico necesitan.
    """
    from modules.macro_monitor.forecasting.panel import observaciones

    from shared.data.periodos import fin_del_periodo
    pares = observaciones(db, serie)
    if hasta is None:
        return pares
    return [(p, v) for p, v in pares if (fin_del_periodo(p) or date.max) <= hasta]


def rf_de_la_curva(db: Session, *, serie: str = SERIE_RF,
                   ventana: int = VENTANA_RF,
                   hasta: Optional[date] = None) -> Tuple[float, float, int, List[str]]:
    """``(bajo, alto, n, advertencias)`` de la tasa libre de riesgo en pesos.

    *hasta* es el corte del informe: solo entran observaciones publicadas hasta esa fecha.
    Para las fechas de la ventana usada, ver `calcular(...).ventana_rf`.

    El rango sale de la DISPERSIÓN observada en la ventana, no de un criterio: la `Rf` es el
    único término real de `Ke`, y darle un punto cuando el dato tiene dispersión escondería
    la única incertidumbre que sí se puede medir.
    """
    pares = observaciones_al_corte(db, serie=serie, hasta=hasta)
    avisos: List[str] = []
    # `observaciones` ya excluye nulos; los ceros hay que excluirlos acá porque son una
    # forma de nulo que el emisor escribe como NÚMERO. El cuadro anota 0 cuando el plazo no
    # se subastó ese mes, con el monto en blanco: son 35 de las 146 observaciones del plazo
    # largo. Un cero no es una tasa baja — es un dato que no existe, y tomarlo como tasa
    # hunde la Rf o, si el cero es reciente, la pone en cero.
    vivos = [(p, v) for p, v in pares if float(v) != 0.0]
    descartados = len(pares) - len(vivos)
    if descartados:
        avisos.append(
            f"{descartados} observación(es) con tasa cero descartadas: el cuadro anota 0 "
            "cuando el plazo no se subastó ese mes, y un cero no es una tasa baja sino un "
            "dato que no existe.")
    if not vivos:
        return 0.0, 0.0, 0, avisos + ["sin observaciones utilizables de la curva en pesos"]
    ultimos = [v for _p, v in vivos[-ventana:]]
    if len(ultimos) < 3:
        avisos.append(
            f"solo {len(ultimos)} observación(es) en la ventana: el plazo largo no se "
            "subasta todos los meses, así que el rango descansa en pocas lecturas.")
    return min(ultimos), max(ultimos), len(ultimos), avisos


def _sensibilidad(bajo: float, alto: float,
                  paso: float = PASO_SENSIBILIDAD) -> Tuple[Tuple[float, str], ...]:
    """La tabla en pasos de 50 pb que cubre el rango, con los extremos SIEMPRE presentes."""
    if alto < bajo:
        bajo, alto = alto, bajo
    puntos: List[float] = []
    x = bajo
    while x < alto - 1e-9:
        puntos.append(round(x, 4))
        x += paso
    puntos.append(round(alto, 4))
    etiquetas = []
    for i, k in enumerate(puntos):
        if i == 0:
            etiquetas.append((k, "extremo favorable"))
        elif i == len(puntos) - 1:
            etiquetas.append((k, "extremo adverso"))
        else:
            etiquetas.append((k, "intermedio"))
    return tuple(etiquetas)


def calcular(db: Session, *, beta: Tuple[float, float] = BETA,
             erp: Tuple[float, float] = ERP,
             serie_rf: str = SERIE_RF, hasta: Optional[date] = None) -> CostoDeCapital:
    """`Ke = Rf + β × ERP`, en pesos, como rango.

    **No hay término de riesgo país.** Ver el docstring del módulo: con una `Rf` en pesos,
    sumarlo lo contaría dos veces.

    *hasta* es el CORTE del informe: la `Rf` se arma solo con observaciones publicadas hasta
    esa fecha, y `ventana_rf` dice cuáles.
    """
    rf_bajo, rf_alto, n, avisos = rf_de_la_curva(db, serie=serie_rf, hasta=hasta)
    vivos = [(p, v) for p, v in observaciones_al_corte(db, serie=serie_rf, hasta=hasta)
             if float(v) != 0.0][-VENTANA_RF:]
    ventana = (vivos[0][0], vivos[-1][0]) if vivos else ("", "")
    prima_baja = beta[0] * erp[0]
    prima_alta = beta[1] * erp[1]
    terminos = (
        Termino("Rf (curva en pesos, >2 años)", rf_bajo, rf_alto, "real",
                f"Valores subastados del Banco Central, plazo de más de dos años; "
                f"{n} observación(es) en la ventana"
                + (f" ({ventana[0]} a {ventana[1]})" if ventana[0] else "")
                + ". Es la Rf más larga que el emisor "
                "publica en moneda nacional: «más de dos años» no es un punto a diez años, "
                "y esa limitación se declara."),
        Termino("β × ERP", prima_baja, prima_alta, "rubric",
                f"β {beta[0]}–{beta[1]} · ERP {erp[0]}–{erp[1]} %. {BETA_EVIDENCIA} "
                f"{ERP_EVIDENCIA}"),
    )
    bajo = rf_bajo + prima_baja
    alto = rf_alto + prima_alta
    return CostoDeCapital(
        moneda=MONEDA, bajo=round(bajo, 4), alto=round(alto, 4), terminos=terminos,
        sensibilidad=_sensibilidad(bajo, alto), n_observaciones_rf=n,
        advertencias=tuple(avisos), ventana_rf=ventana)


class MonedaCruzadaError(ValueError):
    """`Ke` y `ROE` en monedas distintas. Es un error SILENCIOSO si nadie lo veta: las dos
    son porcentajes, la resta no falla, y el spread sale mal por la diferencia de inflación
    esperada entre las dos monedas."""


def spread(ke: CostoDeCapital, roe_pct: float, *, moneda_roe: str) -> float:
    """`ROE − Ke`, la lectura que abre el informe — con la moneda verificada."""
    if moneda_roe != ke.moneda:
        raise MonedaCruzadaError(
            f"el ROE viene en {moneda_roe} y el costo de capital en {ke.moneda}. Restarlos "
            "no falla —las dos son porcentajes— y el resultado está mal por la diferencia de "
            "inflación esperada entre las monedas. Convertí antes de restar.")
    return roe_pct - ke.punto_medio


def cambia_de_signo(ke: CostoDeCapital, roe_pct: float, *, moneda_roe: str) -> bool:
    """¿El spread cambia de signo dentro del rango de `Ke`?

    Cuando pasa, ESO es el hallazgo y va en el resumen ejecutivo: la entidad no tiene una
    respuesta única sobre si crea o destruye valor, y quien decida sobre ella necesita saber
    exactamente eso en vez de recibir un punto medio que esconde la ambigüedad.
    """
    if moneda_roe != ke.moneda:
        raise MonedaCruzadaError(
            f"el ROE viene en {moneda_roe} y el costo de capital en {ke.moneda}.")
    return (roe_pct - ke.bajo) * (roe_pct - ke.alto) < 0


def a_dict(ke: CostoDeCapital) -> Dict[str, object]:
    """Forma serializable, con la descomposición completa. El punto medio viaja NOMBRADO
    como tal para que nadie lo confunda con «el» costo de capital."""
    return {
        "moneda": ke.moneda,
        "rango": [ke.bajo, ke.alto],
        "punto_medio_solo_para_graficar": ke.punto_medio,
        "amplitud_pp": round(ke.amplitud, 4),
        "fraccion_de_rubrica": ke.fraccion_de_rubrica,
        "n_observaciones_rf": ke.n_observaciones_rf,
        "ventana_rf": list(ke.ventana_rf),
        "terminos": [
            {"nombre": t.nombre, "bajo": t.bajo, "alto": t.alto, "estado": t.estado,
             "evidencia": t.evidencia}
            for t in ke.terminos
        ],
        "sensibilidad": [{"ke": k, "etiqueta": e} for k, e in ke.sensibilidad],
        "advertencias": list(ke.advertencias),
        "sin_prima_de_riesgo_pais": (
            "La fórmula tiene TRES términos y no cuatro. Con una tasa libre de riesgo en "
            "pesos, el riesgo país ya está adentro: sumarlo lo contaría dos veces."),
    }
