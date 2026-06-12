"""AI-native ingestion engine for the BCRD historical statistics Excel corpus.

The BCRD publishes ~708 historical Excel files (catalog in
``docs/bcrd_estadisticas_catalog.json``), each with a *bespoke* layout: periods
run down rows or across columns, headers span several rows, years sit in a sparse
column, a sparse header row, or only in trailing "Promedio YYYY" subtotal rows.
Hand-writing one parser per file is the anti-pattern this engine replaces.

Instead the engine infers structure once per file and caches an
:class:`~shared.data.bcrd_excel.spec.ExtractionSpec`:

1. ``inference`` — a heuristic reads the grid and emits a spec + a confidence.
2. ``interpreter`` — when confidence is low, Claude reads the first rows×cols and
   emits the spec (cached by a structure hash, so it re-infers only when the
   layout actually changes → self-repairing).
3. ``extract`` — applies the spec to the grid → normalized :class:`Record`s.
4. ``validation`` — the single gate of correctness: monotonic periods, plausible
   units/ranges, and a cross-check of overlapping series against the live API.

Records upsert into ``MacroSeries`` via ``macro_monitor.service._upsert_records``.
"""
