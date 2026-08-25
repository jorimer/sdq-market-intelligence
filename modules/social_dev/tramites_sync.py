"""Serie del Registro Único de trámites: cuántos publican lo que la norma les exige.

Persiste tres cifras del catálogo del Portal Único de Servicios (gob.do), leídas por
`shared.data.gobdo_tramites`:

    tramites_catalogados                   cuántos trámites publica el Estado
    tramites_con_tiempo_declarado          cuántos dicen cuánto tardan
    tramites_pct_con_tiempo_declarado      la razón, servida y no derivada

**Por qué es una serie y no una foto.** El catálogo es un sistema vivo: sus filas cambian de
día —se vio `updated_at` moverse entre dos llamadas de la misma sesión—. Lo que importa no es
que hoy tres de 710 declaren su tiempo, sino si esa cifra sube. Una foto no contesta eso, y
la obligación del artículo 39 de la Ley 167-21 es continua: se cumple o se incumple todos los
días, no en una fecha.

**El período es el MES de la lectura, no el año.** Con período anual, dos lecturas del mismo
año se pisarían y la serie perdería justo el movimiento que existe para mostrar. `YYYY-MM`
mantiene la trayectoria y sigue dando el año a quien lo extraiga de los primeros cuatro
caracteres, que es lo que hacen el semáforo y la proyección del eje de leyes.

**Qué obligación mide, y cuál NO.** La Ley 167-21 (art. 39) obliga a publicar los
procedimientos en el Registro Único, y su artículo 40 le pone consecuencia: solo se puede
exigir lo que esté registrado. **La ley no nombra el «tiempo de respuesta»** — eso lo fija la
Resolución 142-2024 del MAP, dictada al amparo del artículo 42, que manda al ministerio
emitir los lineamientos de incorporación. Son dos normas de rango distinto y el informe tiene
que decir cuál es cuál: atribuirle a la ley una exigencia que puso una resolución es
refutable leyendo la ley.

**La ausencia no se rellena.** Un catálogo que no se pudo leer no persiste un cero: levanta.
Un cero persistido diría que el Estado dejó de publicar trámites, que es una afirmación
enorme y falsa.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Callable, Dict, Optional

from modules.social_dev.models.models import SocialIndicator
from shared.database.session import SessionLocal

logger = logging.getLogger("sdq.social_dev.tramites")

#: Nombre de la operación en el console.
OPERACION = "tramites-registro-unico"

ENTIDAD = "nacional"

#: Los tres temas que se persisten. La clave nombra su población: `pct_con_tiempo` sin decir
#: sobre qué se computa deja que quien lo lea elija el denominador, y acá conviven dos.
TEMA_TOTAL = "tramites_catalogados"
TEMA_CON_TIEMPO = "tramites_con_tiempo_declarado"
TEMA_PCT = "tramites_pct_con_tiempo_sobre_los_catalogados"

TEMAS = (TEMA_TOTAL, TEMA_CON_TIEMPO, TEMA_PCT)

UNIDADES = {
    TEMA_TOTAL: "trámites",
    TEMA_CON_TIEMPO: "trámites",
    TEMA_PCT: "% de los catalogados",
}

#: Por debajo de esto, lo que se leyó no es el catálogo del Estado. El portal publicaba 710
#: trámites de 91 instituciones el 2026-08-25; una lectura de veinte significa que la API
#: cambió de forma o que la paginación se cortó, y persistir eso sería publicar un desplome
#: que no ocurrió.
MINIMO_PLAUSIBLE = 200


class TramitesSyncError(RuntimeError):
    """No se pudo leer el catálogo. NUNCA se persiste un cero."""


def periodo_de(hoy: Optional[_dt.date] = None) -> str:
    """El período de la lectura: `YYYY-MM`.

    Se computa de la fecha y no se recibe como parámetro por comodidad: una lectura fechada
    a mano deja de decir cuándo se leyó, que es la mitad de lo que esta serie afirma.
    """
    d = hoy or _dt.date.today()
    return f"{d.year:04d}-{d.month:02d}"


def _upsert(db: Any, tema: str, periodo: str, valor: float, fuente: str,
            licencia: str) -> None:
    fila = (db.query(SocialIndicator)
            .filter_by(entity_key=ENTIDAD, theme=tema, period=periodo).first())
    if fila is None:
        fila = SocialIndicator(theme=tema, entity_key=ENTIDAD, period=periodo)
        db.add(fila)
    fila.value = valor
    fila.unit = UNIDADES[tema]
    fila.disaggregation = "nacional"
    fila.source = fuente[:40]
    fila.license = licencia[:120]
    fila.published_at = _dt.date.today()


def run_tramites(force: bool = False,
                 progreso: Optional[Callable[[str], None]] = None,
                 limite: Optional[int] = None) -> Dict[str, Any]:
    """Lee el catálogo completo y persiste las tres cifras del período.

    *force* re-escribe el período aunque ya exista: el catálogo cambia dentro del mismo mes y
    a veces se quiere la lectura de hoy sobre la de hace dos semanas.
    *limite* recorta el catálogo — solo para pruebas de humo; con límite la cifra NO se
    persiste, porque un porcentaje sobre una muestra no es el porcentaje del catálogo.
    """
    from shared.data.gobdo_tramites import LICENSE, SOURCE, fetch, resumen

    avisar = progreso or (lambda _m: None)
    avisar("leyendo el catálogo del Portal Único de Servicios…")
    tramites = fetch(con_detalle=True, limite=limite)
    r = resumen(tramites)
    total = int(r["tramites_en_el_catalogo"] or 0)

    if limite is not None:
        avisar(f"muestra de {total}: NO se persiste (un % sobre muestra no es el del catálogo)")
        return {"persistido": False, "motivo": "muestra", **r}

    if total < MINIMO_PLAUSIBLE:
        raise TramitesSyncError(
            f"el catálogo devolvió {total} trámites y el mínimo plausible es "
            f"{MINIMO_PLAUSIBLE}: la API cambió de forma o la paginación se cortó. No se "
            f"persiste — un cero diría que el Estado dejó de publicar trámites.")

    periodo = periodo_de()
    db = SessionLocal()
    try:
        ya = {f.theme for f in db.query(SocialIndicator)
              .filter_by(entity_key=ENTIDAD, period=periodo).all()
              if f.theme in TEMAS}
        if ya and not force:
            avisar(f"{periodo} ya está persistido ({len(ya)} temas); usá force para reescribir")
            return {"persistido": False, "motivo": "ya_existe", "periodo": periodo, **r}
        valores = {
            TEMA_TOTAL: float(total),
            TEMA_CON_TIEMPO: float(r["declaran_su_tiempo_de_respuesta"] or 0),
            TEMA_PCT: float(r["pct_declaran_sobre_los_del_catalogo"] or 0.0),
        }
        for tema, valor in valores.items():
            _upsert(db, tema, periodo, valor, SOURCE, LICENSE)
        db.commit()
    finally:
        db.close()

    avisar(f"{periodo}: {valores[TEMA_CON_TIEMPO]:.0f} de {total} declaran su tiempo "
           f"({valores[TEMA_PCT]}%)")
    logger.info("[tramites] %s persistido: %s", periodo, valores)
    return {"persistido": True, "periodo": periodo, "valores": valores, **r}
