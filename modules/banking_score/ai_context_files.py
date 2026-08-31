"""Dónde vive el contexto que ve el modelo, para los DOS productos de banca.

**Por qué es un archivo aparte.** La lista la necesitan `products.py` (el trimestral) y
`products_year_review.py` (el anual), y `products.py` ya importa del anual — así que el anual
no puede importar del trimestral sin ciclo. La alternativa era duplicar la lista, y una lista
duplicada es una lista que se desincroniza: es el mismo defecto de las etiquetas de tipo de
entidad, que llegaron a tener dos formas del mismo estrato.

**Qué pasa si un producto no la declara.** `assembler._contexto_ia_version` busca
`AI_CONTEXT_FILES` en el módulo del producto y, sin ella, cae a `ai_context.py` — que en banca
no existe. Resultado: **huella VACÍA**, y un arreglo de lo que el modelo LEE no invalida nada.
La caché (`ProductReportCache`, Postgres, sin TTL) sigue sirviendo el texto viejo
indefinidamente.

Le pasaba al producto anual desde que lo construí. Se descubrió el 2026-08-27 porque el dueño
preguntó si había que regenerar los trimestres: el anual solo se invalidó ese día por el bump
de `GUARD_VERSION`, o sea por casualidad.
"""

#: Archivos, relativos a `modules/banking_score/`, que construyen el contexto del modelo.
AI_CONTEXT_FILES = (
    "reports/narrative.py", "products.py", "products_year_review.py",
    "etiquetas.py",
    "early_warning.py", "propension_quiebra.py",
    "scoring/indicator_detail.py", "scoring/weights.py",
    "scoring/benchmarks.py", "scoring/sensitivity.py",
    "scoring/support.py", "scoring/market_concentration.py",
    "scoring/system_aggregate.py",
    "reports/anuario.py", "reports/revision_anual.py",
    # Las DOS lecturas del año, separadas el 2026-08-27: el año por dentro (producto
    # trimestral) y el año contra los años (producto anual). Las agregó el test estructural,
    # no yo — que es exactamente para lo que existe.
    "reports/anio_por_trimestres.py", "reports/anio_contra_anios.py",
    # El mapa sectorial: computa la brecha de mora y el spread de tasa contra el RESTO del
    # sector. Todo lo que calcula viaja al contexto del modelo, así que un cambio en cómo
    # se computa una brecha DEBE invalidar las narrativas ya generadas.
    "reports/mapa_sectorial.py",
    # La capacidad de pago del deudor. Vive en `shared/` porque la leen CUATRO ejes —banca,
    # seguros, pensiones y política monetaria— y no tiene nada de banca adentro: son series
    # nacionales del BCRD y del MHE. La ruta empieza en `shared/` a propósito: el
    # ensamblador la resuelve desde la raíz del repo, para que un archivo transversal siga
    # entrando en la huella de caché de cada eje que lo consume.
    "shared/capacidad_de_pago.py",
)
