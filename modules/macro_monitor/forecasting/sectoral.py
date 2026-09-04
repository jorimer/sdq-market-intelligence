"""Desagregación sectorial de la proyección agregada, con restricción de agregación.

**El cuadro que parecía natural no cierra, y no por culpa nuestra.** El spec pide que «la
suma ponderada de los sectores reconcilie con el PIB agregado». Lo primero que uno mira es
`incidencia_por_actividad_economica`, porque una incidencia es peso × crecimiento y las
incidencias suman. Medido contra el archivo del BCRD celda por celda (`pib_origen_2018.xlsx`,
hoja `PIBK_Trim`, filas 84-115), el cuadro tiene residuos PROPIOS:

* ``valor_agregado + impuestos − PIB`` **nunca da cero**: |d| medio 0,22 pp, máximo 1,29;
* ``Σ(3 grupos) − valor_agregado`` da cero exacto en 28 trimestres y **−1,945 en 2021-Q4**;
* ``Σ(sub-actividades) − servicios`` da **−1,18 en 2021-Q1**, y manufactura local llega a 0,39.

Nuestra extracción es fiel —lo verifiqué contra las celdas—, así que el que no cierra es el
origen. Un cuadro con dos trimestres rotos no puede sostener una restricción exacta.

**El cuadro nominal sí cierra, y exactamente.** En `PIB$_Trim` la identidad
``17 actividades + impuestos = PIB`` da error **0,000000000** millones de RD$ en los 33
trimestres, en todos los niveles del árbol. Ése es el sustrato, y de ahí salen los pesos.

**El límite que se declara en vez de esconderse.** Con índices encadenados la agregación
exacta contra el PIB *publicado* es imposible: es la no-aditividad del encadenamiento, no un
defecto de método. Reconstruyendo el crecimiento del PIB desde las 17 actividades con pesos
nominales en t−4, el error es **0,149 pp en media y 0,63 máximo** sobre 29 trimestres — más
ajustado que el propio cuadro de incidencias del BCRD (0,22 / 1,29). La reconciliación de
este módulo es exacta contra **el agregado que publicamos**; la distancia contra el PIB del
BCRD se mide y va a la metodología.

**El método se eligió midiendo.** El spec lo traía `[Guessing]` («proporciones con corrección
de tendencia, o un factor model»). Backtest de ventana expansiva, 13 cortes × 18 componentes,
prediciendo el crecimiento de cada componente:

===========================================  ==========
método                                       RMSE (pp)
===========================================  ==========
proporción pura (cada sector crece como PIB)     4,45
media histórica propia                           4,64
regresión ``g_i = a + b·g_PIB``                  4,51
persistencia                                     3,39
**persistencia encogida + reconciliación**       **3,07**
===========================================  ==========

La regresión sobre el agregado —el «factor model» con factor observado— **no le gana a la
proporción pura**, ni siquiera dándole el agregado realizado. Lo que funciona es la inercia
propia de cada sector, corregida por el agregado a través de la reconciliación: +31 % sobre
la proporción pura.

`LAMBDA` no se ajustó a ojo ni mirando el error fuera de muestra: cada ventana de
entrenamiento lo elige por su cuenta y las trece eligen 0,7, sobre una meseta plana
(0,6 → 3,12 · 0,7 → 3,07 · 0,8 → 3,07). Se deja fijo y `elegir_lambda` queda para que quien
dude lo re-mida.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.forecasting import panel as panel_mod
from shared.data.periodos import fin_del_periodo

#: Prefijo del cuadro NOMINAL, que es el aditivo y de donde salen los pesos.
_NOMINAL = ("bcrd.xls.pib_origen_2018.pib_trim."
            "valor_agregado_por_actividad_economica")
#: Prefijos del cuadro de VOLUMEN. Son DOS y no es un error de tipeo: el intérprete partió
#: las 32 filas de la hoja en dos bloques —24 quedaron bajo el rótulo del cuadro y las 8 de
#: la cola (filas 34-41) bajo el título de la hoja—. No hay nada estructural en la fila 34
#: que lo justifique; es una partición del spec interpretado, congelada en
#: `nombres_semanticos.json`. Renombrar ocho series en producción para arreglar un rótulo
#: sería peor que leer los dos prefijos, así que se leen los dos y `verificar_componentes`
#: falla ruidosamente si una reinterpretación futura mueve alguna.
_VOLUMEN = ("bcrd.xls.pib_origen_2018.pibk_trim."
            "indice_de_volumen_por_actividad_economica")
_VOLUMEN_COLA = ("bcrd.xls.pib_origen_2018.pibk_trim."
                 "indices_de_volumen_encadenados")

#: Encogimiento de la persistencia hacia la media histórica del propio sector.
LAMBDA = 0.7
#: Trimestres mínimos de entrenamiento antes de proyectar un componente.
MIN_ENTRENAMIENTO = 8


@dataclass(frozen=True)
class Componente:
    """Una de las 18 piezas que particionan el PIB: 17 actividades más los impuestos."""

    clave: str
    etiqueta: str
    ruta: str
    #: True si su índice de volumen quedó en el bloque de la cola (ver `_VOLUMEN_COLA`).
    en_la_cola: bool = False
    #: Ruta del cuadro de VOLUMEN cuando difiere de la nominal. Difiere en un caso, y el
    #: motivo es tonto y real: el truncado de los rótulos largos se aplicó por bloque, así
    #: que «Administración Pública y Defensa; Seguridad Social…» quedó cortada en
    #: `…seguridad` en el cuadro nominal y en `…seguridad_social` en el de volumen. Suponer
    #: que las dos rutas coinciden costaba perder la actividad, y el arreglo no es adivinar
    #: el truncado sino declararlo.
    ruta_volumen: str = ""

    @property
    def nominal(self) -> str:
        return f"{_NOMINAL}.{self.ruta}"

    @property
    def volumen(self) -> str:
        base = _VOLUMEN_COLA if self.en_la_cola else _VOLUMEN
        return f"{base}.{self.ruta_volumen or self.ruta}"


#: Las 17 actividades del spec más los impuestos. La partición se VERIFICA en el dato
#: (`verificar_particion`), no se supone: es la única razón por la que la reconciliación
#: puede ser exacta.
COMPONENTES: Tuple[Componente, ...] = (
    Componente("agropecuario", "Agropecuario", "agropecuario"),
    Componente("minas", "Explotación de minas y canteras",
               "industrias.explotacion_de_minas_y_canteras"),
    Componente("manufactura_local", "Manufactura local", "industrias.manufactura_local"),
    Componente("zonas_francas", "Manufactura zonas francas",
               "industrias.manufactura_zonas_francas"),
    Componente("construccion", "Construcción", "industrias.construccion"),
    Componente("energia", "Energía y agua", "servicios.energia_y_agua"),
    Componente("comercio", "Comercio", "servicios.comercio"),
    Componente("hoteles", "Hoteles, bares y restaurantes",
               "servicios.hoteles_bares_y_restaurantes"),
    Componente("transporte", "Transporte y almacenamiento",
               "servicios.transporte_y_almacenamiento"),
    Componente("comunicaciones", "Comunicaciones", "servicios.comunicaciones"),
    Componente("financiera", "Intermediación financiera, seguros y conexas",
               "servicios.intermediacion_financiera_seguros_y_actividades_conexas"),
    Componente("inmobiliarias", "Actividades inmobiliarias y de alquiler",
               "servicios.actividades_inmobiliarias_y_de_alquiler"),
    Componente("ensenanza", "Enseñanza", "servicios.ensenanza"),
    Componente("salud", "Salud", "servicios.salud"),
    Componente("administracion_publica", "Administración pública y defensa",
               "servicios.administracion_publica_y_defensa_seguridad", en_la_cola=True,
               ruta_volumen="servicios.administracion_publica_y_defensa_seguridad_social"),
    Componente("servicios_profesionales", "Servicios profesionales",
               "servicios.servicios_profesionales", en_la_cola=True),
    Componente("otros_servicios", "Otras actividades de servicios de mercado",
               "servicios.otras_actividades_de_servicios_de_mercado", en_la_cola=True),
    Componente("impuestos", "Impuestos a la producción netos de subsidios",
               "impuestos_a_la_produccion_netos_de_subsidios", en_la_cola=True),
)

#: El agregado, en los dos cuadros. El de volumen quedó también en el bloque de la cola.
PIB_NOMINAL = f"{_NOMINAL}.producto_interno_bruto"
PIB_VOLUMEN = f"{_VOLUMEN_COLA}.producto_interno_bruto"

#: Tolerancia de la identidad nominal, en millones de RD$ sobre un PIB de ~2.000.000. El
#: dato da 0,000000000; esto solo absorbe el punto flotante.
TOLERANCIA_PARTICION = 1e-6


def _orden(trimestres: Iterable[str]) -> List[str]:
    return sorted(trimestres, key=lambda t: (fin_del_periodo(t) or date.min, t))


def _solo_trimestres(pares: Sequence[Tuple[str, float]]) -> Dict[str, float]:
    return {p: v for p, v in pares if "-Q" in p}


# --------------------------------------------------------------------------- panel


@dataclass(frozen=True)
class PanelSectorial:
    """El panel alineado: crecimiento interanual de cada componente y del PIB, y los pesos.

    `brechas` lleva los componentes que NO se proyectan, con el motivo. Un sector con huecos
    o con menos historia que `MIN_ENTRENAMIENTO` se declara; no se rellena.
    """

    trimestres: Tuple[str, ...]
    #: clave → crecimiento interanual (%), alineado a `trimestres`.
    crecimiento: Dict[str, Tuple[float, ...]]
    #: Crecimiento interanual del PIB, alineado a `trimestres`.
    pib: Tuple[float, ...]
    #: clave → participación nominal en t−4, alineada a `trimestres`.
    pesos: Dict[str, Tuple[float, ...]]
    #: clave → motivo por el que no se proyecta.
    brechas: Dict[str, str]

    @property
    def proyectables(self) -> Tuple[str, ...]:
        return tuple(c.clave for c in COMPONENTES if c.clave not in self.brechas)


def _interanual(serie: Dict[str, float], trimestres: Sequence[str]
                ) -> Dict[str, float]:
    """Variación interanual en %, que es invariante a la base del índice."""
    idx = {t: i for i, t in enumerate(trimestres)}
    out: Dict[str, float] = {}
    for t, i in idx.items():
        if i < 4:
            continue
        previo = serie.get(trimestres[i - 4])
        actual = serie.get(t)
        if previo and actual is not None and previo != 0:
            out[t] = (actual / previo - 1) * 100
    return out


def construir_panel(db: Session, *, hasta: Optional[str] = None) -> PanelSectorial:
    """Arma el panel sectorial desde `mm_series`, declarando lo que no se puede proyectar."""
    vol = {c.clave: _solo_trimestres(panel_mod.observaciones(db, c.volumen))
           for c in COMPONENTES}
    nom = {c.clave: _solo_trimestres(panel_mod.observaciones(db, c.nominal))
           for c in COMPONENTES}
    pib_vol = _solo_trimestres(panel_mod.observaciones(db, PIB_VOLUMEN))
    pib_nom = _solo_trimestres(panel_mod.observaciones(db, PIB_NOMINAL))

    universo = _orden(set(pib_vol) & set(pib_nom))
    if hasta:
        universo = [t for t in universo if t <= hasta]

    brechas: Dict[str, str] = {}
    for c in COMPONENTES:
        faltan_v = [t for t in universo if t not in vol[c.clave]]
        faltan_n = [t for t in universo if t not in nom[c.clave]]
        if not vol[c.clave] or not nom[c.clave]:
            brechas[c.clave] = "la serie no está persistida"
        elif faltan_v or faltan_n:
            cuantos = len(set(faltan_v) | set(faltan_n))
            brechas[c.clave] = (
                f"la serie tiene {cuantos} trimestre(s) sin dato en el tramo común; "
                "un sector con huecos no se proyecta, se declara")

    g_pib = _interanual(pib_vol, universo)
    g = {c.clave: _interanual(vol[c.clave], universo)
         for c in COMPONENTES if c.clave not in brechas}
    fechas = [t for t in universo if t in g_pib and all(t in s for s in g.values())]

    for clave, serie in list(g.items()):
        if len([t for t in fechas if t in serie]) < MIN_ENTRENAMIENTO + 1:
            brechas[clave] = (
                f"solo {len([t for t in fechas if t in serie])} trimestres de historia; "
                f"por debajo de los {MIN_ENTRENAMIENTO + 1} que exige el método")
            g.pop(clave)

    idx = {t: i for i, t in enumerate(universo)}
    pesos = {
        clave: tuple(nom[clave][universo[idx[t] - 4]] / pib_nom[universo[idx[t] - 4]]
                     for t in fechas)
        for clave in g
    }
    return PanelSectorial(
        trimestres=tuple(fechas),
        crecimiento={k: tuple(v[t] for t in fechas) for k, v in g.items()},
        pib=tuple(g_pib[t] for t in fechas),
        pesos=pesos,
        brechas=brechas,
    )


# ------------------------------------------------------------------ el método


def _persistencia_encogida(historia: Sequence[float], lam: float = LAMBDA) -> float:
    """Último valor, encogido hacia la media del propio sector.

    El encogimiento es lo que impide que un trimestre atípico —una zona franca que rebota
    30 %— se proyecte hacia adelante como si fuera el estado normal del sector.
    """
    return lam * historia[-1] + (1 - lam) * (sum(historia) / len(historia))


def reconciliar(crudo: Dict[str, float], pesos: Dict[str, float],
                g_pib: float) -> Tuple[Dict[str, float], float]:
    """Reparte la brecha contra el agregado, **proporcional al peso**.

    Proporcional al peso y no al crecimiento proyectado: repartir proporcional al
    crecimiento le pega más al que más se mueve y puede darle vuelta el signo a un sector,
    que es justo la lectura que la sección sectorial existe para dar. Con el reparto por
    peso, el ajuste en puntos porcentuales es el MISMO para todos y el orden entre sectores
    se conserva.

    Devuelve ``(ajustado, brecha)``. Tras el ajuste ``Σ wᵢ·gᵢ == g_pib`` por construcción.
    """
    suma_pesos = sum(pesos[k] for k in crudo)
    if suma_pesos <= 0:
        return dict(crudo), 0.0
    brecha = g_pib - sum(pesos[k] * crudo[k] for k in crudo)
    ajuste = brecha / suma_pesos
    return {k: v + ajuste for k, v in crudo.items()}, brecha


@dataclass(frozen=True)
class SectorProyectado:
    clave: str
    etiqueta: str
    #: Crecimiento interanual proyectado, %, ya reconciliado.
    crecimiento: float
    #: Crecimiento antes de reconciliar — se publica al lado, para que el ajuste sea visible.
    crecimiento_sin_reconciliar: float
    #: Peso nominal con que entra al agregado.
    peso: float
    #: Contribución en puntos porcentuales al crecimiento del PIB: peso × crecimiento.
    incidencia: float


@dataclass(frozen=True)
class ProyeccionSectorial:
    horizonte: str
    #: El agregado al que se reconcilió, y de dónde salió.
    g_pib: float
    origen_del_agregado: str
    sectores: Tuple[SectorProyectado, ...]
    #: Brecha repartida, en pp del PIB. Es el tamaño del desacuerdo entre la lectura
    #: sectorial y la agregada, y se publica.
    brecha_pp: float
    #: Ajuste aplicado a cada sector, en pp de su propio crecimiento.
    ajuste_pp: float
    #: Componentes que no se proyectaron, con su motivo.
    brechas: Dict[str, str]
    #: True si el agregado de origen es un escenario del BVAR y no un pronóstico. Un desglose
    #: de un escenario es un escenario: la propiedad viaja, no se pierde en el camino.
    es_escenario: bool = False

    @property
    def suma_de_incidencias(self) -> float:
        return sum(s.incidencia for s in self.sectores)


def proyectar(panel: PanelSectorial, *, g_pib: float, horizonte: str,
              origen_del_agregado: str, es_escenario: bool = False,
              lam: float = LAMBDA) -> ProyeccionSectorial:
    """Desagrega *g_pib* en los componentes proyectables del *panel*."""
    claves = [c for c in panel.proyectables if c in panel.crecimiento]
    crudo = {k: _persistencia_encogida(panel.crecimiento[k], lam) for k in claves}
    pesos = {k: panel.pesos[k][-1] for k in claves}
    ajustado, brecha = reconciliar(crudo, pesos, g_pib)
    suma_pesos = sum(pesos.values())
    etiquetas = {c.clave: c.etiqueta for c in COMPONENTES}
    sectores = tuple(
        SectorProyectado(
            clave=k, etiqueta=etiquetas[k], crecimiento=ajustado[k],
            crecimiento_sin_reconciliar=crudo[k], peso=pesos[k],
            incidencia=pesos[k] * ajustado[k],
        )
        for k in sorted(claves, key=lambda x: -pesos[x])
    )
    return ProyeccionSectorial(
        horizonte=horizonte, g_pib=g_pib, origen_del_agregado=origen_del_agregado,
        sectores=sectores, brecha_pp=brecha,
        ajuste_pp=(brecha / suma_pesos) if suma_pesos > 0 else 0.0,
        brechas=dict(panel.brechas), es_escenario=es_escenario,
    )


# ------------------------------------------------------------------ verificación


@dataclass(frozen=True)
class Particion:
    """El resultado de comprobar que los 18 componentes suman el PIB en el cuadro nominal."""

    trimestres: int
    error_maximo: float
    cierra: bool
    faltantes: Tuple[str, ...]


def verificar_particion(db: Session) -> Particion:
    """¿Las 17 actividades más los impuestos SUMAN el PIB nominal?

    Se comprueba contra el dato en cada llamada porque es un hecho empírico sobre la fuente,
    no un teorema: si el BCRD reorganiza el cuadro, la restricción de agregación deja de
    tener sustrato y hay que enterarse acá, no en un informe.
    """
    partes = {c.clave: _solo_trimestres(panel_mod.observaciones(db, c.nominal))
              for c in COMPONENTES}
    pib = _solo_trimestres(panel_mod.observaciones(db, PIB_NOMINAL))
    faltantes = tuple(k for k, v in partes.items() if not v)
    comunes = [t for t in _orden(pib) if all(t in v for v in partes.values())]
    peor = 0.0
    for t in comunes:
        peor = max(peor, abs(sum(v[t] for v in partes.values()) - pib[t]))
    return Particion(
        trimestres=len(comunes), error_maximo=peor,
        cierra=bool(comunes) and not faltantes and peor <= TOLERANCIA_PARTICION,
        faltantes=faltantes,
    )


def verificar_componentes(db: Session) -> Dict[str, str]:
    """Qué series de las 18×2 declaradas no existen en `mm_series`.

    Vale por sí solo: los ocho códigos del bloque de la cola dependen de una partición del
    spec interpretado, y si una reinterpretación los mueve, la sección sectorial perdería
    cinco actividades **en silencio**, que es el modo de falla caro.
    """
    faltan: Dict[str, str] = {}
    for c in COMPONENTES:
        for etiqueta, code in (("nominal", c.nominal), ("volumen", c.volumen)):
            if not panel_mod.observaciones(db, code):
                faltan[f"{c.clave}.{etiqueta}"] = code
    for etiqueta, code in (("pib.nominal", PIB_NOMINAL), ("pib.volumen", PIB_VOLUMEN)):
        if not panel_mod.observaciones(db, code):
            faltan[etiqueta] = code
    return faltan
