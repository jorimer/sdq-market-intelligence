"""Serie del indicador 2.33 de la END: gasto en salud del Gobierno Central sobre el PIB.

**Vive aparte del panel social y corre en el WORKER, y las dos cosas son por lo mismo.**
Leer esta serie son ~400 MB de PDF del emisor —trece documentos de entre 28 y 66 MB, de
hasta 980 páginas— y ese trabajo no va en el proceso que atiende la API. El 2026-08-24 fue
exactamente ahí: el sub-sync corría dentro del panel social, el proceso web murió en el
séptimo documento sin dejar traza —la firma del sistema matando por memoria— y se llevó
puesta la API por unos segundos.

Lo que mata no es un archivo grande: el proceso aguantó seis libros de ~30 MB y murió en
otro del mismo tamaño. Es lo que se acumula entre documento y documento, porque el
asignador no le devuelve al sistema lo que libera. Medido con el libro de 2015, el mismo
que lo tumbó: 310 MB de pico sosteniendo los bytes, 240 MB leyendo del disco y liberando
cada página.

**Cada año se PERSISTE apenas se lee.** El commit al final hacía la operación todo-o-nada
sobre 400 MB de descarga: los seis años ya leídos se perdieron enteros y la corrida
siguiente los volvió a bajar. Ahora lo leído queda y la próxima arranca donde la anterior
murió — la operación es reanudable, que es lo que hace segura una tarea larga.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional

import httpx

from modules.social_dev.models.models import SocialIndicator
from shared.database.session import SessionLocal

logger = logging.getLogger("sdq.social_dev.digepres")

#: Nombre de la operación en el console. Vive acá porque tanto el registro de la operación
#: como la tarea del worker lo necesitan, y una cadena repetida en dos módulos es una cadena
#: que se desincroniza.
OPERACION = "digepres-salud-funcional-sync"

#: Sujeto de la serie. `nacional` porque la magnitud es del país: la ley fija una meta
#: nacional y el proveedor de series del módulo de leyes rechaza —bien— toda variable medida
#: por sujeto.
ENTIDAD = "nacional"
TEMA = "health_spending_central_gov_pct_gdp"

#: PIB nominal en moneda local: el denominador. **Una sola serie para los trece años.** El
#: emisor publica su propio %PIB en cuatro de ellos y queda 6-8% por encima del nuestro,
#: siempre en el mismo sentido, porque dividió por el PIB de su añada y las cuentas
#: nacionales se rebasaron a 2018. Mezclar añadas convierte una revisión de cuentas
#: nacionales en un salto de gasto público.
PIB_NOMINAL_LCU = "NY.GDP.MKTP.CN"

_TIMEOUT_DESCARGA = 900.0
_TROZO = 1 << 20


def anios_persistidos(db) -> set:
    """Los años que ya están en la base. Es lo que hace REANUDABLE a la operación."""
    return {int(r.period) for r in db.query(SocialIndicator)
            .filter_by(entity_key=ENTIDAD, theme=TEMA).all()
            if str(r.period).isdigit()}


def _upsert(db, anio: int, valor: float, fuente: str,
            preliminar: bool = False) -> None:
    fila = (db.query(SocialIndicator)
            .filter_by(entity_key=ENTIDAD, theme=TEMA, period=str(anio)).first())
    if fila is None:
        fila = SocialIndicator(theme=TEMA, entity_key=ENTIDAD, period=str(anio))
        db.add(fila)
    fila.value = valor
    fila.unit = "% del PIB"
    # La marca de PRELIMINAR viaja en la desagregacion porque tiene que llegar a quien
    # lea la cifra: 2025 es una META de la ley y su valor todavia puede moverse.
    fila.disaggregation = "nacional · preliminar" if preliminar else "nacional"
    fila.source = fuente


def run_digepres_salud(force: bool = False,
                       progreso: Optional[Callable[[str], None]] = None) -> Dict:
    """Lee los informes del emisor que falten y persiste la serie, año por año.

    *force* re-lee los años ya persistidos (para cuando el emisor corrige un documento).
    *progreso* recibe una frase por año; el worker la publica y el console la muestra, así
    que una corrida de veinte minutos no se ve como un cuelgue.
    """
    from shared.data import hacienda_cofog
    from shared.data.digepres_funcional import (DOCUMENTOS, SIN_CUADRO_FUNCIONAL, SOURCE,
                                                leer_documento, url_del_documento)
    from shared.data.wdi_client import fetch_wb_indicator

    avisar = progreso or (lambda _f: None)
    db = SessionLocal()
    leidos: List[int] = []
    fallidos: Dict[int, str] = {}
    try:
        # ── VIA PRINCIPAL: la hoja COFOG del Ministerio de Hacienda ──────────────────────
        # Una sola descarga trae 2008-2025 con el %PIB que el propio emisor computa, e
        # incluye 2020 y 2025 — dos METAS de la ley que no aparecen en ningun informe de
        # DIGEPRES. Los PDF quedan de CONTRASTE, no de via principal: son 400 MB para cubrir
        # menos anios y ninguna cifra que la hoja no traiga.
        avisar("serie COFOG del Ministerio de Hacienda")
        de_cofog: Dict[int, Any] = {}
        try:
            for g in hacienda_cofog.fetch():
                de_cofog[g.anio] = g
        except Exception as e:  # noqa: BLE001 — si la hoja falla, quedan los PDF
            logger.warning("[2.33] la hoja COFOG fallo, se cae a los PDF: %s", e)
            fallidos[0] = f"COFOG: {str(e)[:200]}"

        ya_cofog = set() if force else anios_persistidos(db)
        for anio, g in sorted(de_cofog.items()):
            if anio in ya_cofog:
                continue
            _upsert(db, anio, round(g.pct_pib, 3), hacienda_cofog.SOURCE,
                    preliminar=g.preliminar)
            db.commit()
            leidos.append(anio)

        avisar("PIB nominal (denominador del contraste)")
        filas, _ = fetch_wb_indicator(PIB_NOMINAL_LCU, ["DOM"], mrv=40)
        pib = {int(r["date"]): float(r["value"]) for r in filas
               if isinstance(r, dict) and r.get("value") is not None and r.get("date")}
        if not pib:
            raise RuntimeError("sin PIB nominal no hay razón que computar para el 2.33")

        # `force` alcanza a los dos caminos. Los anios que COFOG acaba de escribir se
        # excluyen aparte, en `pendientes`: no hay que volver a bajar 60 MB para reconfirmar
        # lo que la hoja ya cerro en esta misma corrida.
        ya = set() if force else anios_persistidos(db)
        # Solo los anios que la hoja NO trajo. Hoy son cero, y por eso el contraste con
        # los PDF se corre a mano y no en cada sync: 400 MB de descarga para reconfirmar lo
        # que ya cerro contra la hoja es gasto sin hallazgo.
        pendientes = [(a, n) for a, n in sorted(DOCUMENTOS.items())
                      if a not in ya and a not in de_cofog and a in pib]
        for k, (anio, nombre) in enumerate(pendientes, 1):
            avisar(f"{anio} ({k} de {len(pendientes)})")
            ruta = None
            try:
                with httpx.Client(timeout=_TIMEOUT_DESCARGA, follow_redirects=True,
                                  headers={"User-Agent": "sdq-mip/1.0"}) as c:
                    # A DISCO, por trozos. Sostener 66 MB en memoria mientras el parser
                    # arma sus objetos de página es lo que mató al proceso web.
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        ruta = tmp.name
                        with c.stream("GET", url_del_documento(nombre)) as r:
                            r.raise_for_status()
                            for trozo in r.iter_bytes(_TROZO):
                                tmp.write(trozo)
                gasto = leer_documento(ruta, anio, pib[anio])
            except Exception as e:  # noqa: BLE001 — best-effort por año: un año ilegible no
                # puede tumbar los doce que sí se leen, y el motivo viaja al resultado con
                # su año en vez de quedarse en un log que nadie mira.
                logger.warning("[2.33] %s: %s", anio, e)
                fallidos[anio] = str(e)[:300]
                continue
            finally:
                if ruta and os.path.exists(ruta):
                    os.unlink(ruta)
            _upsert(db, anio, round(gasto.pct_pib, 3), SOURCE)
            # COMMIT POR AÑO: lo leído queda aunque el proceso muera en el siguiente.
            db.commit()
            leidos.append(anio)
        return {
            "via_principal": hacienda_cofog.SOURCE if de_cofog else "DIGEPRES (PDF)",
            "anios_de_cofog": sorted(de_cofog),
            "preliminares": sorted(a for a, g in de_cofog.items() if g.preliminar),
            "anios_nuevos": len(leidos),
            "anios": leidos,
            "fallidos": fallidos,
            "persistidos": sorted(anios_persistidos(db)),
            # Los años que el emisor NO publica viajan en el resultado con su motivo. Un
            # hueco callado se lee como que la serie termina ahí, y acá el hueco cae justo
            # sobre dos metas de la ley.
            "sin_cuadro_en_la_fuente": {str(a): m for a, m in SIN_CUADRO_FUNCIONAL.items()},
        }
    finally:
        db.close()
