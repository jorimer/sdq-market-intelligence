"""El perfil de un sector económico, uniendo fuentes que nadie cruza.

**Qué contesta.** Para un sector del marco BCRD-17 —`construccion`, `turismo`, `energia`…—:
cuánto crédito le da el sistema financiero, a qué tasa, con qué mora y con qué cobertura de
provisiones, y cuánto paga de salario. Son dos registros nacionales distintos, y la única
razón por la que se pueden unir es que `shared/data/sector_crosswalk.py` los lleva a la misma
llave.

**Por qué vive en `shared/`.** Es la lectura que los once ejes sectoriales van a consumir
(fase 3 del plan, `docs/PLAN_ENRIQUECIMIENTO_SECTORIAL.md`). No tiene nada de banca adentro:
el crédito es un dato nacional que la SIB publica sobre todas las supervisadas, y se sirve
AGREGADO — acá no hay ninguna entidad nombrada.

**Las cinco lecturas, y de dónde sale cada una.** Crédito y tasa del cubo de la SIB, costo
laboral de la TSS, actividad (peso y crecimiento real) de las cuentas nacionales del BCRD,
ocupación de la ENCFT y inversión extranjera realizada del cuadro de IED del BCRD. Las tres
últimas se habilitaron el 2026-09-01 al mudar `si_variables` a `shared/reference/`, que era
la decisión de arquitectura que la fase 3 dejó abierta.

**Cada lectura viaja con SU fecha y con su población.** Son cinco registros con calendarios
distintos —el cubo es trimestral, las cuentas nacionales y la IED son anuales, la ENCFT va
por ramas— y ninguna es del corte del informe. Además la fuente agrupa distinto en cada una:
la SIB no separa manufactura local de zonas francas, la ENCFT mete enseñanza, salud e
inmobiliario en «Otros Servicios», y el BCRD junta comercio con industria en su cuadro de
IED. Donde eso pasa, la lectura lo dice y NO se reparte el agregado entre sus miembros.

**Lo que puede faltar.** `encft-empleo-sync` lleva desde junio de 2026 fallando con 403
contra one.gob.do, así que la ocupación puede venir con un período viejo — que es
exactamente por qué viaja con el suyo. Y la IED del BCRD no cubre los 17 sectores: no llega
a agropecuario, construcción, administración pública, enseñanza, salud ni servicios
profesionales, y esos slugs devuelven ``None`` en vez de un cero que afirmaría que no
recibieron inversión.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.data.bcrd_sectors import VAR_GROWTH, VAR_SIZE, sector_catalog
from shared.data.encft_employment import VAR_EMPLOYMENT
from shared.data.ied_bcrd import SERIES as VAR_IED
from shared.data.sector_crosswalk import (ENCFT_BRANCHES, IED_ACTIVITIES, SIB_SECTORS,
                                          sib_members)
from shared.reference.cartera_agregacion import _medidas, _sumar, _vacio
from shared.reference.cartera_sectorial import CarteraSectorial
from shared.reference.sector_variables import (IED_DIMENSION, LABOR_ENCFT_DIMENSION,
                                               SECTOR_DIMENSION, SectorVariable)

logger = logging.getLogger("sdq.perfil_del_sector")

#: Clave del `AppSetting` donde `tss_salario_sync` deja el salario por slug. Se lee de ahí y
#: no se recalcula: el conector de la TSS raspa un Power BI y no puede correr por consulta.
_CLAVE_SALARIO = "sector_operating_cost"

#: slug BCRD-17 → letras CIIU de la SIB que lo alimentan. Se DERIVA del crosswalk en vez de
#: escribirse: una segunda tabla del mismo mapa es como los dos se desincronizan.
_LETRAS_POR_SLUG: Dict[str, List[str]] = {}
for _s in SIB_SECTORS:
    for _m in _s.members:
        _LETRAS_POR_SLUG.setdefault(_m, []).append(_s.key)


def letras_del_slug(slug: str) -> List[str]:
    """Las letras CIIU que alimentan a *slug* (``[]`` si la SIB no lo cubre)."""
    return list(_LETRAS_POR_SLUG.get(slug, ()))


def _slugs_de_las_letras(letras: List[str]) -> List[str]:
    """Todos los slugs que esas letras alimentan — que puede ser MÁS que el pedido."""
    out: set = set()
    for letra in letras:
        out.update(sib_members(letra))
    return sorted(out)


def credito_al_sector(db: Session, slug: str, corte: date) -> Optional[Dict[str, Any]]:
    """Lo que el sistema financiero le presta a *slug* en un corte, agregado.

    **El sujeto viaja con el número y es más sutil de lo que parece.** Varias letras de la
    SIB alimentan a más de un slug: la `D` no separa manufactura local de zonas francas, y la
    `K` agrupa el inmobiliario con los servicios profesionales. Para esos slugs la cifra NO
    es del sector pedido sino del AGREGADO que la fuente publica, y repartirla sería
    fabricar. Por eso la respuesta trae `es_agregado` y `el_agregado_incluye`: quien la use
    tiene que nombrar esa población, no la del slug que pidió.

    ``None`` si la SIB no cubre el slug (`comunicaciones`) o si el corte no tiene desglose.
    """
    letras = letras_del_slug(slug)
    if not letras:
        return None

    etiquetas = [s.label for s in SIB_SECTORS if s.key in letras]
    celdas = (db.query(CarteraSectorial)
              .filter(CarteraSectorial.period_end == corte,
                      CarteraSectorial.sector.in_(etiquetas))
              .all())
    if not celdas:
        return None

    acc = _vacio()
    for c in celdas:
        _sumar(acc, c)
    if not acc["deuda"]:
        return None

    # EL TOTAL DEL CORTE — la cartera clasificada de TODAS las supervisadas, hogares
    # incluidos. Se dice «cartera del sistema» y no «crédito del país» porque es lo que el
    # denominador de verdad es: el cubo de la SIB, no la economía. Se
    # computa acá y el modelo lo copia: pedirle que divida dos cifras es cómo se invierte una
    # relación, y en este repo ya pasó.
    total_pais = (db.query(CarteraSectorial)
                  .filter(CarteraSectorial.period_end == corte).all())
    acc_pais = _vacio()
    for c in total_pais:
        _sumar(acc_pais, c)

    cubiertos = _slugs_de_las_letras(letras)
    es_agregado = len(cubiertos) > 1
    out: Dict[str, Any] = {
        "sector": slug,
        "corte": corte.isoformat(),
        "letras_ciiu_de_la_fuente": sorted(letras),
        "deuda_del_sistema_al_sector": round(acc["deuda"], 2),
        "peso_del_sector_en_la_cartera_del_sistema_pct": (
            round(100.0 * acc["deuda"] / acc_pais["deuda"], 2) if acc_pais["deuda"] else None),
        "entidades_que_le_prestan": len(acc["bancos"]),
        # El SUJETO en cada clave lo pone `_medidas`, que es el mismo cuerpo que usa el mapa
        # sectorial de banca. Un segundo cuerpo acá discreparía en silencio.
        **_medidas(acc),
        "es_agregado": es_agregado,
        "el_agregado_incluye": cubiertos if es_agregado else None,
    }
    if es_agregado:
        out["por_que_es_agregado"] = next(
            (s.note for s in SIB_SECTORS if s.key in letras and s.note), None)
    return out


def salario_del_sector(db: Session, slug: str) -> Optional[Dict[str, Any]]:
    """Salario promedio cotizable del sector (TSS), con su año.

    Es una lectura TRANSVERSAL: discrimina entre sectores y se aplica pareja en el tiempo,
    porque el conector toma el año más reciente publicado. Por eso viaja con `anio` — leerla
    como si fuera del corte del informe sería atribuirle una fecha que no tiene.
    """
    from shared.settings.models import AppSetting
    fila = db.query(AppSetting).filter(AppSetting.key == _CLAVE_SALARIO).first()
    if not fila or not fila.value:
        return None
    try:
        payload = json.loads(str(fila.value))
    except (TypeError, ValueError):
        logger.warning("El salario por sector de la TSS no es JSON legible.")
        return None
    valor = (payload.get("series") or {}).get(slug)
    if valor is None:
        return None
    return {
        "salario_promedio_cotizable_del_sector_dop_mes": round(float(valor), 2),
        "anio": payload.get("year"),
        "unidad": payload.get("unit"),
        "fuente": payload.get("source") or "TSS",
    }


# slug BCRD-17 → rama de la ENCFT / actividad de la IED. Se DERIVAN del crosswalk igual que
# `_LETRAS_POR_SLUG`: una segunda tabla del mismo mapa es como los dos se desincronizan.
_RAMA_POR_SLUG: Dict[str, "Any"] = {m: b for b in ENCFT_BRANCHES for m in b.members}
_ACTIVIDAD_IED_POR_SLUG: Dict[str, "Any"] = {m: a for a in IED_ACTIVITIES for m in a.members}


def _ultimo_anio_hasta(periodos: Dict[str, Any], anio: int) -> Optional[str]:
    """El período más reciente que NO se pasa de *anio* (``None`` si todos son futuros).

    El tope existe porque estas capas se leen desde un informe fechado: servirle a un
    informe de 2024 el crecimiento de 2025 sería contradecir su encabezado con un dato que
    en ese momento no existía. Que el resultado quede viejo es legítimo y por eso viaja.
    """
    candidatos = [p for p in periodos if str(p).isdigit() and int(p) <= anio]
    return max(candidatos, key=int) if candidatos else None


def _serie(db: Session, dimension: str, clave: str, variable: str) -> Dict[str, float]:
    """``{período: valor}`` de una variable para una clave, dentro de SU dimensión.

    La `dimension` no es opcional: en `si_variables` conviven cuatro resoluciones del mismo
    mapa (17 slugs, 10 ramas, 9 sectores ENAE, 9 actividades de IED) y `sector_code` se
    repite entre ellas. Filtrar solo por la clave mezcla poblaciones que la fuente no unió.
    """
    filas = (db.query(SectorVariable)
             .filter(SectorVariable.dimension == dimension,
                     SectorVariable.sector_code == clave,
                     SectorVariable.variable == variable)
             .all())
    return {str(f.period): float(f.value) for f in filas if f.value is not None and f.period}


def _variacion_pct(serie: Dict[str, float], anio: str) -> Optional[float]:
    """Variación de *anio* contra el año anterior, COMPUTADA acá.

    Se computa y no se deja para el modelo por la regla de la casa: el modelo acierta las
    cifras y falla las relaciones. Sin el año previo devuelve ``None`` en vez de cero, que
    se leería como «no se movió».

    **Una BASE NEGATIVA no produce porcentaje, y esto no es teórico.** La IED de
    telecomunicaciones pasó de −32,4 a −44,3 millones de US$ entre 2023 y 2024 —dos años de
    desinversión neta, y el segundo peor que el primero— y la razón daba **+36,73 %**, que se
    lee como una mejora. Es la familia de la relación invertida que este repo ya publicó.
    Con la base en cero o negativa el porcentaje se DECLARA ausente y la dirección viaja por
    el cambio absoluto, que sí conserva el signo.
    """
    previo = serie.get(str(int(anio) - 1))
    actual = serie.get(anio)
    if previo is None or actual is None or previo <= 0:
        return None
    return round(100.0 * (actual / previo - 1.0), 2)


def _cambio_absoluto(serie: Dict[str, float], anio: str) -> Optional[float]:
    """El cambio contra el año anterior en las UNIDADES de la serie.

    Es la relación que sobrevive a una base negativa: −32,4 → −44,3 son −11,9 millones y el
    signo dice lo que pasó, mientras que el porcentaje dice lo contrario. Viaja siempre, no
    solo cuando el porcentaje falta, para que el modelo no tenga que elegir cuál usar.
    """
    previo = serie.get(str(int(anio) - 1))
    actual = serie.get(anio)
    if previo is None or actual is None:
        return None
    return round(actual - previo, 2)


def actividad_del_sector(db: Session, slug: str, anio: int) -> Optional[Dict[str, Any]]:
    """Peso en el valor agregado nacional y crecimiento real del sector (BCRD), con SU año.

    **Los dos valores salen del MISMO año o no salen.** Un peso de 2025 al lado de un
    crecimiento de 2024 se lee como una sola foto y no lo es; si el año más reciente no trae
    los dos, se retrocede hasta uno que sí, y si no hay ninguno se devuelve ``None``.

    Es la lectura que ordena por importancia económica, y es distinta del crédito: un sector
    puede pesar poco en la cartera del sistema y mucho en el valor agregado.
    """
    tam = _serie(db, SECTOR_DIMENSION, slug, VAR_SIZE)
    cre = _serie(db, SECTOR_DIMENSION, slug, VAR_GROWTH)
    comunes = {p for p in tam if p in cre}
    usar = _ultimo_anio_hasta({p: 0.0 for p in comunes}, anio)
    if usar is None:
        return None
    return {
        "anio": usar,
        "peso_del_sector_en_el_valor_agregado_nacional_pct": round(tam[usar], 3),
        "crecimiento_real_del_sector_pct": round(cre[usar], 2),
        "fuente": "BCRD · cuentas nacionales",
    }


def ocupacion_del_sector(db: Session, slug: str, anio: int) -> Optional[Dict[str, Any]]:
    """Ocupados en la rama de actividad a la que la ENCFT asigna el sector, con SU período.

    **El sujeto acá es la RAMA, no el sector.** La ENCFT publica 10 ramas, no los 17 slugs:
    «Otros Servicios» absorbe enseñanza, salud, inmobiliario y servicios profesionales, e
    «Industrias Manufactureras» incluye minas y canteras. Para esos slugs la cifra es de la
    rama y la respuesta lo dice — repartir la rama entre sus miembros sería fabricar.

    El período puede venir viejo: `encft-empleo-sync` falla contra one.gob.do desde junio de
    2026. Por eso viaja con el suyo en vez de heredar el del informe.
    """
    rama = _RAMA_POR_SLUG.get(slug)
    if rama is None:
        return None
    serie = _serie(db, LABOR_ENCFT_DIMENSION, rama.key, VAR_EMPLOYMENT)
    usar = _ultimo_anio_hasta(serie, anio)
    if usar is None:
        return None
    es_agregado = len(rama.members) > 1
    out: Dict[str, Any] = {
        "periodo": usar,
        "ocupados_en_la_rama": round(serie[usar], 0),
        "variacion_de_los_ocupados_vs_anio_anterior_pct": _variacion_pct(serie, usar),
        "rama_de_la_encft": rama.label,
        "fuente": "ONE · ENCFT",
        "es_agregado": es_agregado,
        "el_agregado_incluye": sorted(rama.members) if es_agregado else None,
    }
    if es_agregado:
        out["por_que_es_agregado"] = rama.note
    return out


def inversion_extranjera_del_sector(db: Session, slug: str,
                                    anio: int) -> Optional[Dict[str, Any]]:
    """IED realizada en la actividad del sector (BCRD), con SU año.

    Es el único desenlace de INVERSIÓN que el país publica abierto por actividad, y por eso
    dice algo que ningún indicador propio del eje dice: si el capital extranjero efectivamente
    llegó, no si el sector parecía atractivo.

    **El flujo puede ser NEGATIVO y eso es un dato, no un error**: la IED se mide neta, así
    que un año de desinversión —repatriación por encima de la entrada— sale con signo menos.
    Telecomunicaciones lleva dos así. Por eso el movimiento viaja como CAMBIO ABSOLUTO en
    millones de US$, que conserva el signo, y el porcentaje solo cuando la base es positiva.

    ``None`` para los seis slugs que el cuadro del BCRD no desagrega —agropecuario,
    construcción, administración pública, enseñanza, salud y servicios profesionales—. No es
    un cero: un cero afirmaría que no recibieron inversión, y lo que pasa es que la fuente no
    los publica.
    """
    act = _ACTIVIDAD_IED_POR_SLUG.get(slug)
    if act is None:
        return None
    serie = _serie(db, IED_DIMENSION, act.key, VAR_IED)
    usar = _ultimo_anio_hasta(serie, anio)
    if usar is None:
        return None
    es_agregado = len(act.members) > 1
    out: Dict[str, Any] = {
        "anio": usar,
        "ied_realizada_en_la_actividad_usd_mm": round(serie[usar], 2),
        "cambio_de_la_ied_vs_anio_anterior_usd_mm": _cambio_absoluto(serie, usar),
        "variacion_de_la_ied_vs_anio_anterior_pct": _variacion_pct(serie, usar),
        "actividad_del_cuadro_de_ied": act.label,
        "fuente": "BCRD · flujos de IED por actividad económica",
        "es_agregado": es_agregado,
        "el_agregado_incluye": sorted(act.members) if es_agregado else None,
    }
    if es_agregado:
        out["por_que_es_agregado"] = act.note
    return out


def perfil_del_sector(db: Session, slug: str, corte: date) -> Optional[Dict[str, Any]]:
    """Las lecturas disponibles de un sector, juntas. ``None`` si no hay ninguna.

    Cada lectura falla por su cuenta: media respuesta es mejor que ninguna, y cuál falta lo
    dice la ausencia de su clave. `cobertura` viaja para que el consumidor sepa sobre qué
    está afirmando — es dato interno del contexto, no texto para el informe.
    """
    if slug not in {s for s, _n in sector_catalog()}:
        return None

    anio = corte.year
    bloque: Dict[str, Any] = {}
    for clave, fn in (("credito_del_sistema", lambda: credito_al_sector(db, slug, corte)),
                      ("costo_laboral", lambda: salario_del_sector(db, slug)),
                      ("actividad", lambda: actividad_del_sector(db, slug, anio)),
                      ("ocupacion", lambda: ocupacion_del_sector(db, slug, anio)),
                      ("inversion_extranjera",
                       lambda: inversion_extranjera_del_sector(db, slug, anio))):
        try:
            valor = fn()
        except Exception:  # noqa: BLE001 — ninguna lectura tumba al informe
            logger.exception("Perfil del sector %s: falló %s al %s", slug, clave, corte)
            valor = None
        if valor:
            bloque[clave] = valor
    if not bloque:
        return None

    bloque["sector"] = slug
    # Qué se sirvió y qué NO, para que el consumidor sepa sobre qué está afirmando. Es dato
    # interno del contexto, no texto para el informe: la ausencia no se declara al lector.
    bloque["cobertura"] = {
        "lecturas_servidas": [k for k in bloque if k not in ("sector", "cobertura")],
        "lecturas_sin_dato_para_este_sector": [
            c for c in ("credito_del_sistema", "costo_laboral", "actividad", "ocupacion",
                        "inversion_extranjera") if c not in bloque],
    }
    return bloque


def contexto_del_perfil_del_sector(perfil: Optional[Dict[str, Any]], sufijo: str, *,
                                   omitir: tuple = ()) -> Dict[str, Any]:
    """El perfil, con la forma que consume el contexto del modelo.

    **Se llamaba `contexto_de_financiamiento`** y se renombró el 2026-09-01, cuando dejó de
    emitir solo financiamiento: hoy también viajan la actividad, la ocupación y la inversión
    extranjera. Un nombre que describe una parte del contenido es cómo alguien decide, con
    razón, no buscar acá lo que necesita.

    **Un solo cuerpo para los cuatro ejes.** Nació dentro de `construction_intel` y se subió
    acá al cablear el segundo: cuatro copias de la misma forma es como una se queda atrás, y
    este repo lo pagó el 2026-08-31 con un serializador copiado a mano que borró la tasa de
    38 entidades.

    **El SUJETO en cada clave, y por eso el `sufijo`.** `mora_del_sector_turismo_pct` y no
    `mora_pct`: estos contextos tienen cerca los permisos, los m² o los arribos, y el modelo
    reatribuye una porción al sujeto más próximo — así se publicó «cuatro compañías
    concentran el 87,1%» cuando eran cuatro ramos.

    **Cada capa trae SU fecha.** El crédito su corte, el salario y la IED su año, la
    ocupación su período: son cinco registros con calendarios distintos del índice del eje.
    Sin eso el modelo las fecha en el encabezado.

    **`omitir` existe para no servir DOS VECES el mismo hecho.** `construction_intel` ya
    publica el crecimiento del PIB de construcción del BCRD con su propio nombre; servirle
    además `actividad` pondría en el mismo contexto dos cifras de crecimiento del mismo
    sector con claves distintas —una interanual y una de tres años— y el modelo elige la que
    le cae más cerca. Un eje que ya trae su lectura de cuentas nacionales omite ésta.

    Sin perfil devuelve ``{}``: la clave no existe y el modelo no tiene qué citar. No se
    declara la ausencia — decisión del dueño del 2026-08-31.
    """
    if not perfil:
        return {}
    out: Dict[str, Any] = {}
    c = {} if "credito_del_sistema" in omitir else (perfil.get("credito_del_sistema") or {})
    if c:
        bloque = {
            "corte_de_esta_capa": c.get("corte"),
            f"deuda_del_sistema_al_sector_{sufijo}_dop": c.get("deuda_del_sistema_al_sector"),
            f"peso_del_sector_{sufijo}_en_la_cartera_del_sistema_pct": c.get(
                "peso_del_sector_en_la_cartera_del_sistema_pct"),
            f"entidades_que_le_prestan_al_sector_{sufijo}": c.get("entidades_que_le_prestan"),
            f"mora_del_sector_{sufijo}_pct": c.get("mora_pct"),
            f"mora_temprana_31_90_del_sector_{sufijo}_pct": c.get("mora_temprana_31_90_pct"),
            f"tasa_promedio_ponderada_al_sector_{sufijo}_pct": c.get(
                "tasa_promedio_ponderada_pct"),
            f"cobertura_de_provision_sobre_vencida_del_sector_{sufijo}_pct": c.get(
                "cobertura_de_provision_sobre_vencida_pct"),
            f"garantia_sobre_deuda_del_sector_{sufijo}_pct": c.get("garantia_sobre_deuda_pct"),
            f"credito_promedio_por_operacion_en_el_sector_{sufijo}_dop": c.get(
                "credito_promedio"),
        }
        # EL AVISO DE AGREGADO, y acá no es teórico: `zonas_francas` sale de la letra D, que
        # la SIB no separa de la manufactura local. Sin este aviso el modelo publicaría la
        # cifra del agregado como si fuera solo de zonas francas.
        if c.get("es_agregado"):
            bloque["ojo_la_cifra_es_de_un_agregado_que_incluye"] = c.get("el_agregado_incluye")
            bloque["por_que_la_fuente_no_los_separa"] = c.get("por_que_es_agregado")
        out[f"credito_del_sistema_al_sector_{sufijo}"] = bloque
    sal = {} if "costo_laboral" in omitir else (perfil.get("costo_laboral") or {})
    if sal:
        out[f"costo_laboral_del_sector_{sufijo}"] = {
            f"salario_promedio_cotizable_del_sector_{sufijo}_dop_mes": sal.get(
                "salario_promedio_cotizable_del_sector_dop_mes"),
            "anio_de_esta_capa": sal.get("anio"),
            "fuente": sal.get("fuente"),
        }
    act = {} if "actividad" in omitir else (perfil.get("actividad") or {})
    if act:
        out[f"actividad_del_sector_{sufijo}_en_las_cuentas_nacionales"] = {
            "anio_de_esta_capa": act.get("anio"),
            f"peso_del_sector_{sufijo}_en_el_valor_agregado_nacional_pct": act.get(
                "peso_del_sector_en_el_valor_agregado_nacional_pct"),
            f"crecimiento_real_del_sector_{sufijo}_pct": act.get(
                "crecimiento_real_del_sector_pct"),
            "fuente": act.get("fuente"),
        }
    ocu = {} if "ocupacion" in omitir else (perfil.get("ocupacion") or {})
    if ocu:
        bloque_o = {
            "periodo_de_esta_capa": ocu.get("periodo"),
            f"ocupados_en_la_rama_de_la_encft_del_sector_{sufijo}": ocu.get(
                "ocupados_en_la_rama"),
            f"variacion_de_los_ocupados_de_la_rama_del_sector_{sufijo}_vs_anio_anterior_pct":
                ocu.get("variacion_de_los_ocupados_vs_anio_anterior_pct"),
            "rama_de_la_encft": ocu.get("rama_de_la_encft"),
            "fuente": ocu.get("fuente"),
        }
        # El MISMO aviso que el del crédito, y por la misma razón: acá «Otros Servicios»
        # absorbe enseñanza, salud, inmobiliario y servicios profesionales, y sin este
        # aviso el modelo publicaría los ocupados de la rama como si fueran del sector.
        if ocu.get("es_agregado"):
            bloque_o["ojo_la_cifra_es_de_una_rama_que_incluye"] = ocu.get("el_agregado_incluye")
            bloque_o["por_que_la_fuente_no_los_separa"] = ocu.get("por_que_es_agregado")
        out[f"ocupacion_de_la_rama_del_sector_{sufijo}"] = bloque_o
    ied = ({} if "inversion_extranjera" in omitir
           else (perfil.get("inversion_extranjera") or {}))
    if ied:
        bloque_i = {
            "anio_de_esta_capa": ied.get("anio"),
            f"ied_realizada_en_la_actividad_del_sector_{sufijo}_usd_mm": ied.get(
                "ied_realizada_en_la_actividad_usd_mm"),
            # EL CAMBIO ABSOLUTO PRIMERO, y el porcentaje después. La IED se mide neta y
            # puede ser negativa: con base negativa el porcentaje invierte su sentido, así
            # que ahí viene en `null` y el signo lo lleva esta clave.
            f"cambio_de_la_ied_del_sector_{sufijo}_vs_anio_anterior_usd_mm": ied.get(
                "cambio_de_la_ied_vs_anio_anterior_usd_mm"),
            f"variacion_de_la_ied_del_sector_{sufijo}_vs_anio_anterior_pct": ied.get(
                "variacion_de_la_ied_vs_anio_anterior_pct"),
            "actividad_del_cuadro_de_ied": ied.get("actividad_del_cuadro_de_ied"),
            "fuente": ied.get("fuente"),
        }
        if ied.get("es_agregado"):
            bloque_i["ojo_la_cifra_es_de_una_actividad_que_incluye"] = ied.get(
                "el_agregado_incluye")
            bloque_i["por_que_la_fuente_no_los_separa"] = ied.get("por_que_es_agregado")
        out[f"inversion_extranjera_en_el_sector_{sufijo}"] = bloque_i
    return out


def corte_del_cubo_para_el_anio(db: Session, anio: int) -> Optional[date]:
    """El corte del cubo con que se lee un AÑO — su diciembre, o el último disponible.

    **Por qué existe.** Los ejes sectoriales tienen período anual y el cubo es trimestral, así
    que un año cerrado se lee con su diciembre. Pero un año EN CURSO no tiene diciembre: el
    producto de energía estaba en 2026 y pedía `2026-12-31`, que no existe, así que la capa
    de crédito no viajaba y nunca iba a viajar. El año que viene le pasa a todos.

    La caída al último trimestre disponible del año es legítima porque esta capa **no es del
    índice**: es contexto agregado, y la doctrina de este repo ya dice que esas capas llevan
    el período de SU PROPIA FUENTE, indicado donde se presentan. El bloque viaja con
    `corte_de_esta_capa` y la plantilla exige citarlo, así que el lector nunca la confunde
    con el corte del informe.

    Lo que NO hace: salirse del año. Un informe de 2026 no lee el cubo de 2025 — eso sí sería
    contradecir el encabezado. Sin ningún corte dentro del año devuelve ``None``.
    """
    inicio, fin = date(anio, 1, 1), date(anio, 12, 31)
    return (db.query(func.max(CarteraSectorial.period_end))
            .filter(CarteraSectorial.period_end >= inicio,
                    CarteraSectorial.period_end <= fin)
            .scalar())
