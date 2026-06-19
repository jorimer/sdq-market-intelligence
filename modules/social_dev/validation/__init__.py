"""Gate E — convergent validity for the Social IDM.

A temporal/forward backtest isn't meaningful for the IDM: it's a cross-region
RELATIVE index (min-max per period) whose national-level series are flat across
regions (→ neutral), so the national IDM has no real temporal trajectory. The
honest validation is CONVERGENT VALIDITY: does the IDM rank the 10 development
regions like an established, independent development index — the PNUD regional
HDI (IDHr)? Spearman + bootstrap CI, mirroring the IRMP's convergent-validity
check vs sovereign ratings.
"""
