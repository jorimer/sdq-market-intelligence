"""Insurance Intel — SDQ Seguros (SIS · SISALRIL).

Modular, self-contained sector module that mirrors ``pension_intel`` 1:1 (same
SectorProduct 3-tier report standard). It covers the Dominican insurance sector
across two supervisors / sub-sectors:

  * **SIS** (Superintendencia de Seguros, Ley 146-02) — COMMERCIAL insurance
    (life, non-life/generales, reinsurance). ~24 insurers. Market data (premiums
    by line, insurer counts) is live from ``datos.gob.do`` (CKAN, XLSX/CSV);
    entity solvency / audited financials come from the SIS site (Excel per
    company) + InDataRD (Power BI publish-to-web).
  * **SISALRIL** (Ley 87-01) — SOCIAL HEALTH insurance (ARS/ARL, SFS/SRL).
    Phase 2 — REDATAM extraction.

Two natures, like pensions:
  * **Pulse** = NATIONAL market pulse (anonymized): total premiums, growth, mix
    by ramo, market structure — never a single insurer's name.
  * **Insight / Deep Dive** = a NAMED insurer + its ISF (Índice de Solidez de
    Aseguradora — solvency · liquidity · loss ratio · scale · technical result).

Honesty directed by data: the Pulse ships now on real CKAN premium data (F1a).
The entity ISF stays a declared gap until audited financials are ingested (F1b) —
the named tiers report "sin dato" rather than fabricate a rating, exactly as
pensions began relative/partial before the SIPEN solvency backfill.
"""
