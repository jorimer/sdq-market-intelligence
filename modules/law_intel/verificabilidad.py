"""Quién produce la evidencia con la que se juzga a la ley — y si el juzgado es el mismo.

**Por qué existe esta sección.** El resto del motor responde *qué dice el dato*. Ésta
responde *de dónde salió*, que es la pregunta que decide cuánto pesa un veredicto. Un
incumplimiento sostenido en una cifra que publica el propio obligado no es refutable por el
número: es refutable por la fuente, y ese es el flanco por el que se pierde un informe
entero.

**El emisor no es el productor, y confundirlos es el error que esta sección impide.** Una
serie del Banco Mundial parece evidencia de tercero y en la mayoría de los casos retransmite
la cifra que produjo el Estado evaluado. El logo cambia; la medición no. Por eso `emisor` y
`origen` son dos campos distintos y el informe publica los dos: el contraste ENTRE ellos es
el hallazgo, y con un solo campo desaparece.

**Todo se declara por binding y nada se infiere del `id` de la fuente.** El WDI publica a la
vez estimaciones propias (mortalidad de menores, subalimentación) y retransmisiones (usuarios
de internet, mujeres en Diputados). Graduar por emisor le pondría la misma etiqueta a las dos
y la cifra de independencia saldría inflada — en la dirección que le conviene a quien vende
el informe, que es exactamente cuando hay que ser más estricto.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from modules.law_intel.bindings import Binding, cargar_bindings
from modules.law_intel.obligaciones import Obligacion, cargar_obligaciones
from modules.law_intel.registro import Indicador, cargar

#: De dónde sale la evidencia. Conjunto CERRADO: una etiqueta libre acá volvería opinable la
#: única cifra del informe que habla de sí mismo.
#:
#: El orden es la escalera de independencia, de más a menos, y no es decorativo: la sección
#: publica el reparto en este orden y un lector lo lee como un ranking.
ORIGENES = {
    "instrumento_de_tercero": (
        "un tercero APLICA el instrumento y produce la medición. La cifra existe sin que el "
        "evaluado la declare: los alumnos rinden la prueba, el evaluador puntúa el marco."),
    "acto_en_registro_publico": (
        "el hecho es un ACTO que consta en un registro público —la Gaceta Oficial— y no una "
        "afirmación del obligado sobre su propio desempeño. Se dictó o no se dictó."),
    "estimacion_de_tercero_sobre_dato_del_evaluado": (
        "un tercero estima con MÉTODO PROPIO, pero sus insumos los produce el evaluado. El "
        "método es independiente; el insumo no."),
    "declarado_por_el_evaluado": (
        "la cifra —o el cumplimiento— lo produce y lo declara el propio evaluado, lo publique "
        "él o lo retransmita un emisor internacional."),
}

#: Los que puede declarar un BINDING. `acto_en_registro_publico` queda fuera a propósito: un
#: indicador se mide, no se dicta, y admitirlo dejaría que alguien declarara una serie
#: estadística como si fuera un acto registral — la etiqueta más independiente del conjunto,
#: puesta sobre la evidencia más débil.
ORIGENES_DE_INDICADOR = frozenset(set(ORIGENES) - {"acto_en_registro_publico"})

#: Los dos orígenes que NO dependen de que el evaluado declare nada. Es la frontera que la
#: sección mide, y está deliberadamente alta: una estimación de tercero sobre insumos
#: nacionales sigue heredando lo que el evaluado reportó.
INDEPENDIENTES = frozenset({"instrumento_de_tercero", "acto_en_registro_publico"})

#: Qué origen le corresponde a una obligación, computado de lo que el expediente ya declara.
#: No se vuelve a declarar por obligación: `verificacion_normativa` ya dice que el
#: cumplimiento se comprueba contra la Gaceta, y `sin_consulta_normativa` ya dice por qué no.
#: Pedir un campo más sería pedir que alguien repita —y algún día contradiga— lo que el
#: expediente afirma en otro lado.
_SIN_NADA_QUE_VERIFICAR = frozenset({"no_exigible"})


@dataclass(frozen=True)
class Evidencia:
    """Una cosa que el informe afirma, con quién produjo la evidencia que la sostiene."""
    sujeto: str
    nombre: str
    clase: str                      # "indicador" | "obligacion"
    origen: str
    productor: str
    emisor: Optional[str] = None    # id de la fuente admitida; None en obligaciones
    emisor_del_evaluado: Optional[bool] = None

    @property
    def independiente(self) -> bool:
        return self.origen in INDEPENDIENTES

    @property
    def emisor_externo_sin_medicion_propia(self) -> bool:
        """El caso que la sección existe para contar: sello de afuera, medición de adentro.

        Es la lectura que un informe descuidado publica al revés — «lo dice el Banco
        Mundial» — y la que un contradictor desarma en una línea.
        """
        return self.emisor_del_evaluado is False and not self.independiente


def _orden(indicador_id: str) -> tuple:
    """Ordena `2.7` antes que `2.19`.

    El orden alfabético los invierte, y estas listas de ids se publican para que alguien las
    lea contra el articulado: un `2.7` metido entre `2.46` y `3.13` se lee como un error de
    la tabla, no del ordenamiento.
    """
    partes = indicador_id.split(".")
    return tuple(int(x) if x.isdigit() else x for x in partes)


def _emisores(expediente_id: str) -> Dict[str, Dict[str, Any]]:
    exp = cargar(expediente_id)
    return {f["id"]: f for f in (exp.meta.get("fuentes_admitidas") or [])}


def evidencia_de_indicadores(expediente_id: str,
                             solo_medidos: bool = True) -> List[Evidencia]:
    """La cadena de evidencia de cada indicador con binding.

    Por defecto solo los MEDIDOS: son los únicos cuya procedencia llega a un informe. Con
    ``solo_medidos=False`` entran también los descartados, que es como se cuenta lo que la
    ley perdió.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    por_id: Dict[str, Indicador] = {i.id: i for i in exp.indicadores}
    emisores = _emisores(expediente_id)
    out: List[Evidencia] = []
    for ind_id, b in sorted(bs.items(), key=lambda kv: _orden(kv[0])):
        if solo_medidos and not b.cuenta:
            continue
        ind = por_id.get(ind_id)
        emisor = emisores.get(b.fuente)
        out.append(Evidencia(
            sujeto=ind_id, nombre=ind.nombre if ind else ind_id, clase="indicador",
            origen=b.origen or "", productor=b.productor or "", emisor=b.fuente,
            emisor_del_evaluado=(None if emisor is None
                                 else bool(emisor.get("del_evaluado"))),
        ))
    return out


def _origen_de_obligacion(o: Obligacion) -> Optional[str]:
    if o.estado in _SIN_NADA_QUE_VERIFICAR:
        return None
    if o.verificacion_normativa:
        return "acto_en_registro_publico"
    return "declarado_por_el_evaluado"


def evidencia_de_obligaciones(expediente_id: str) -> List[Evidencia]:
    """Cómo se comprueba cada deber de la ley.

    Se COMPUTA de lo que la obligación ya declara. Las que no tienen nada que verificar
    —sin deudor ni término— quedan fuera y no engordan ningún denominador: mezclarlas
    mejoraría la proporción de lo verificable sin que nada sea más verificable.
    """
    out: List[Evidencia] = []
    for o in cargar_obligaciones(expediente_id):
        origen = _origen_de_obligacion(o)
        if origen is None:
            continue
        productor = ("Gaceta Oficial · consulta a la base normativa"
                     if origen == "acto_en_registro_publico"
                     else (o.sin_consulta_normativa or "").strip()
                     or "el propio obligado, por sus publicaciones")
        out.append(Evidencia(sujeto=o.id, nombre=o.deber, clase="obligacion",
                             origen=origen, productor=productor))
    return out


def _reparto(evs: Sequence[Evidencia]) -> Dict[str, int]:
    """Cuenta por origen, en el orden de la escalera y sin omitir los ceros.

    Los ceros van: un origen ausente del reparto se lee como que no aplica al caso, y acá
    significa lo contrario —que ninguna evidencia lo alcanza—, que es el dato.
    """
    return {k: sum(1 for e in evs if e.origen == k) for k in ORIGENES}


def publicable(expediente_id: str) -> Dict[str, Any]:
    """La sección de verificabilidad, con cada cifra nombrando su población.

    Ninguna clave dice `pct` a secas ni `independientes` a secas: el expediente tiene tres
    denominadores legítimos —indicadores medidos, indicadores con instrumento de tercero,
    obligaciones verificables— y una clave sin sujeto deja que el modelo elija el que suene
    mejor. Ya pasó en otro eje y se publicó «cuatro compañías concentran el 87,1%» sobre
    cuatro ramos.
    """
    medidos = evidencia_de_indicadores(expediente_id, solo_medidos=True)
    todos = evidencia_de_indicadores(expediente_id, solo_medidos=False)
    obligaciones = evidencia_de_obligaciones(expediente_id)

    indep = [e for e in medidos if e.independiente]
    sello_ajeno = [e for e in medidos if e.emisor_externo_sin_medicion_propia]
    externos = [e for e in medidos if e.emisor_del_evaluado is False]

    # Lo que la ley eligió medir con instrumento de tercero, y cuánto de eso sobrevive.
    # Es la comparación que vuelve un hallazgo lo que si no sería una queja: la ley SÍ
    # previó verificación independiente, y es justo la que dejó de estar disponible.
    con_instrumento = [e for e in todos if e.origen == "instrumento_de_tercero"]
    vivos = {e.sujeto for e in medidos}
    perdidos = [e for e in con_instrumento if e.sujeto not in vivos]

    obl_indep = [e for e in obligaciones if e.independiente]

    return {
        "pregunta": ("Quién produce la evidencia con la que se juzga el cumplimiento de la "
                     "ley, y si es el mismo a quien se juzga."),
        "indicadores_medidos": {
            "total_medidos": len(medidos),
            "con_medicion_independiente_del_evaluado": len(indep),
            "ids_con_medicion_independiente": [e.sujeto for e in indep],
            "reparto_por_origen_sobre_los_medidos": _reparto(medidos),
        },
        # El contraste emisor↔productor. Sin esta clave el informe puede citar «Banco
        # Mundial» y sonar independiente sin serlo.
        "emisor_no_es_productor": {
            "medidos_con_emisor_ajeno_al_evaluado": len(externos),
            "de_esos_cuantos_miden_con_dato_del_evaluado": len(sello_ajeno),
            "ids": sorted((e.sujeto for e in sello_ajeno), key=_orden),
            "lectura": ("Un emisor internacional no es una medición independiente. "
                        "Retransmite, o estima sobre insumos que produce el evaluado."),
        },
        "instrumentos_de_tercero_que_la_ley_eligio": {
            "indicadores_que_se_apoyaban_en_uno": len(con_instrumento),
            "todavia_medibles": len(con_instrumento) - len(perdidos),
            "perdidos": len(perdidos),
            "ids_perdidos": sorted((e.sujeto for e in perdidos), key=_orden),
            "lectura": ("La ley SÍ previó verificación por tercero. Lo que dejó de estar "
                        "disponible es precisamente esa parte."),
        },
        "obligaciones_verificables": {
            "total_con_algo_que_verificar": len(obligaciones),
            "contra_registro_publico": len(obl_indep),
            "ids_contra_registro_publico": [e.sujeto for e in obl_indep],
            "solo_por_declaracion_del_obligado": len(obligaciones) - len(obl_indep),
            "nota": ("Las obligaciones sin deudor ni término quedan FUERA del denominador: "
                     "no hay nada que verificar y contarlas mejoraría la proporción sin "
                     "que nada sea más verificable."),
        },
        "cadena_por_sujeto": [
            {"sujeto": e.sujeto, "nombre": e.nombre, "clase": e.clase, "origen": e.origen,
             "productor": e.productor, "emisor": e.emisor,
             "emisor_del_evaluado": e.emisor_del_evaluado,
             "independiente_del_evaluado": e.independiente}
            for e in list(medidos) + list(obligaciones)],
        "origenes": ORIGENES,
        "regla_de_redaccion": (
            "No escribas que un indicador «lo mide el Banco Mundial» ni «lo mide la CEPAL» "
            "cuando su origen sea `declarado_por_el_evaluado`: el emisor retransmite. "
            "Nombrá al PRODUCTOR, que viaja en el campo `productor`."),
    }
