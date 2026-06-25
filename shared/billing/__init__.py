"""Billing transversal (monetización Fase B).

Provider-agnóstico: el tarifario (precios gestionados con vigencia por fechas) es la
fuente de verdad que el checkout leerá en B3. Anti-Frankenstein: ``shared/billing`` puede
apoyarse en ``shared/products`` (catálogo) pero NUNCA importa ``modules.*``.
"""
