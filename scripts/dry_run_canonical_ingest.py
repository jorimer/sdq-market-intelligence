"""DESCARTABLE — corrida en seco de la ingesta canónica BCRD (fase 0, T-PS-0).

NO ES CÓDIGO PRODUCTIVO. Se escribe para una decisión puntual —si se puede encender
`persist=True` en `ingest_canonical`— y se borra después. No lo importe nadie.

Qué hace y por qué así:

- Llama a `ingest_canonical(db, persist=True)`, NO a `persist=False`. Con `False` no se
  ejercita la rama que se va a encender: se mediría el camino viejo. Ver la corrección C5
  de `tasks/PLAN_PAQUETE_FORWARD_LOOKING.md`.
- Para que `persist=True` no escriba nada real, intercepta `service._upsert_records`: el
  wrapper captura los registros crudos y delega en el `_upsert_records` REAL contra una
  base SCRATCH vacía. Así se conservan el dedupe por (serie, período), el filtro
  `_sin_sujeto` y el `infer_nature` de producción, sin reimplementarlos.
- `db` apunta a una COPIA de la base dev, porque `_upsert_excel_report` (service.py:406)
  escribe `mm_excel_reports` aunque `persist` sea False: la corrida "en seco" del spec no
  es seca.
- Cuenta las llamadas al modelo y su costo interceptando `interpreter.account`.

Salida: un JSON con los registros que se habrían escrito + metadatos de la corrida.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCRATCH_DB = os.environ["DRY_RUN_SCRATCH_DB"]      # base vacía: recibe lo que se escribiría
SALIDA = os.environ["DRY_RUN_OUT"]                  # artefacto JSON


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.database.base import Base
    from shared.database.paths import ensure_sqlite_directory
    from modules.macro_monitor.models.models import MacroSeries  # noqa: F401 — registra la tabla
    from modules.macro_monitor import service
    from shared.data.bcrd_excel import interpreter
    from shared.database.session import SessionLocal

    # ── base scratch: mismo esquema, vacía ────────────────────────────────
    # SQLite no crea el directorio del fichero: sin esto falla toda conexión.
    ensure_sqlite_directory(f"sqlite:///{SCRATCH_DB}")
    scratch_engine = create_engine(f"sqlite:///{SCRATCH_DB}")
    Base.metadata.create_all(scratch_engine, tables=[MacroSeries.__table__])
    ScratchSession = sessionmaker(autocommit=False, autoflush=False, bind=scratch_engine)
    scratch = ScratchSession()

    crudos: list = []
    tocados = {"n": 0}
    real_upsert = service._upsert_records

    caida = {"crudos": 0, "sin_sujeto": 0, "dup_serie_periodo": 0,
             "dup_con_valor_distinto": 0}
    discrepancias: list = []
    conflictivas: dict = {}   # series_code -> nº de veces que un duplicado trajo otro valor

    def upsert_interceptado(db, records):
        """Captura los registros y los escribe con la lógica REAL, en la base scratch."""
        # A dónde se va la diferencia entre crudos y escritos: las dos podas que aplica
        # `_upsert_records` — el filtro `_sin_sujeto` y el dedupe por (serie, período).
        caida["crudos"] += len(records)
        vivos = [r for r in records if not service._sin_sujeto(r.series)]
        caida["sin_sujeto"] += len(records) - len(vivos)
        caida["dup_serie_periodo"] += len(vivos) - len({(r.series, r.period) for r in vivos})
        # Un duplicado intra-lote con DOS valores distintos lo resuelve "último gana" — en
        # silencio y por orden de lectura. No es lo mismo que repetir la misma cifra.
        vistos = {}
        for r in vivos:
            k = (r.series, r.period)
            if r.value is None:
                continue
            if k in vistos and abs(vistos[k] - r.value) > 1e-9:
                caida["dup_con_valor_distinto"] = caida.get("dup_con_valor_distinto", 0) + 1
                conflictivas[k[0]] = conflictivas.get(k[0], 0) + 1
                if len(discrepancias) < 40:
                    discrepancias.append({"series_code": k[0], "period": k[1],
                                          "valor_a": vistos[k], "valor_b": r.value})
            vistos[k] = r.value
        for r in records:
            lin = getattr(r, "lineage", None)
            crudos.append({
                "series": r.series, "period": r.period, "value": r.value, "unit": r.unit,
                "source": getattr(lin, "source", None),
                "published_at": str(getattr(lin, "published_at", None) or ""),
                "license": getattr(lin, "license", None),
            })
        try:
            n = real_upsert(scratch, records)
        except Exception:
            scratch.rollback()
            raise
        tocados["n"] += n
        return n

    service._upsert_records = upsert_interceptado

    # ── contador de llamadas al modelo ────────────────────────────────────
    llm = {"llamadas": 0, "costo_usd": 0.0, "tokens_in": 0, "tokens_out": 0}
    real_account = interpreter.account

    def account_contado(response, **kw):
        costo = real_account(response, **kw)
        u = getattr(response, "usage", None)
        llm["llamadas"] += 1
        llm["costo_usd"] += float(costo or 0.0)
        llm["tokens_in"] += int(getattr(u, "input_tokens", 0) or 0)
        llm["tokens_out"] += int(getattr(u, "output_tokens", 0) or 0)
        return costo

    interpreter.account = account_contado

    # ── la corrida REAL ───────────────────────────────────────────────────
    db = SessionLocal()
    t0 = time.time()
    try:
        resumen = service.ingest_canonical(db, persist=True)
    finally:
        dur = time.time() - t0
        db.close()

    # lo que quedó EFECTIVAMENTE escrito en scratch = lo que se habría escrito en mm_series
    persistidos = [
        {"series_code": r.series_code, "period": r.period, "value": r.value,
         "unit": r.unit, "source": r.source, "nature": r.nature,
         "frequency": r.frequency,
         "published_at": str(r.published_at) if r.published_at else None}
        for r in scratch.query(MacroSeries).all()
    ]
    scratch.close()

    Path(SALIDA).write_text(json.dumps({
        "caida_de_registros": caida,
        "discrepancias_intra_lote": discrepancias,
        "series_conflictivas": conflictivas,
        "corrida": {**resumen, "duracion_s": round(dur, 1),
                    "upsert_touched": tocados["n"],
                    "registros_crudos": len(crudos),
                    "registros_persistibles": len(persistidos)},
        "llm": {**llm, "costo_usd": round(llm["costo_usd"], 4)},
        "persistibles": persistidos,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"[dry-run] {resumen}")
    print(f"[dry-run] crudos={len(crudos)} persistibles={len(persistidos)} "
          f"touched={tocados['n']} dur={dur:.1f}s")
    print(f"[dry-run] caída: {caida}")
    print(f"[dry-run] LLM: {llm['llamadas']} llamadas, US${llm['costo_usd']:.4f}")
    print(f"[dry-run] artefacto: {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
