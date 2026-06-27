"""Pension Intel (SIPEN) — Dominican pension-system intelligence.

Two faces behind one module (see ``tasks/PLAN_PENSIONES_SIPEN.md``):
  * system/national pulse (afiliados, rentabilidad, patrimonio del fondo), and
  * per-AFP entity series (toward scoring of the fund administrators, F2).

F0 ships the data spine: connector + models + sync + read-only API.
"""
