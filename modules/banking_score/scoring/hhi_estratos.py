"""Anclas del HHI sectorial POR TIPO DE ENTIDAD — una sola fuente para curva e inversa.

Por qué existe este módulo y no dos constantes. La curva del HHI sectorial vive duplicada:
`engine.calc_hhi_sectorial` la aplica y `sensitivity._CURVES` guarda su inversa, que es la
que alimenta el `nivel_de_referencia` publicado en los informes. Con una curva global el
round-trip de `test_sensitivity` bastaba para fijarlas; con cuatro estratos, dos copias
serían ocho números que se desincronizan de a uno. Acá las anclas se declaran UNA vez y
tanto la curva como su inversa se derivan de ellas, así que no hay nada que sincronizar.

Por qué estratificado. Medido sobre producción (último rating de cada entidad, 43 con
cartera sectorial), el HHI sectorial no ordenaba riesgo: ordenaba TIPO DE ENTIDAD. Con la
curva anterior —las bandas antimonopolio del DOJ, 100 bajo 1500 y 0 sobre 2500— el 62,8%
del panel quedaba clavado en 0, y el reparto delataba la causa: las DIEZ asociaciones de
ahorros y préstamos sacaban cero, y el 93% de los bancos de ahorro y crédito, contra el 12%
de la banca múltiple. Una AAyP presta para vivienda por su objeto social; su cartera está
concentrada por diseño y el indicador la castigaba por cumplir su licencia. Comparar su HHI
contra el de un banco múltiple es ordenar lo que no es comparable.

Las anclas son el p10 y el p90 OBSERVADOS dentro de cada estrato, redondeados a 50 para no
fingir precisión que la muestra no tiene. Se usa una observación por entidad (su último
rating), no la serie histórica: las observaciones de una misma entidad no son independientes
y solo harían parecer más robusto un percentil que siguen decidiendo las mismas entidades.

SALVEDAD DECLARADA. `shared.indices.normalization._MIN_N` fija en 12 el mínimo para que un
cuartil signifique algo, y dos estratos quedan por debajo: `aap` (n=10) y sobre todo
`corporacion_credito` (n=3), donde el p10 y el p90 son poco más que el mínimo y el máximo
interpolados. Se estratifican igual por decisión del dueño del producto (2026-08-28),
prefiriendo un estrato chico a seguir comparando contra un universo que no le aplica. Es una
excepción CONSCIENTE al _MIN_N, no un descuido: si el catálogo de corporaciones de crédito
crece, estas dos anclas son las primeras que hay que recalcular.
"""

from typing import Dict, Optional, Tuple

# p10 y p90 observados por estrato (producción, corte 2026-08-28). El primero puntúa 100;
# el segundo, 0.
ANCLAS: Dict[str, Tuple[float, float]] = {
    "banca_multiple": (1350.0, 2550.0),        # n=16
    "banco_ahorro_credito": (2950.0, 7350.0),  # n=14
    "aap": (2600.0, 4150.0),                   # n=10  — bajo _MIN_N, ver salvedad
    "corporacion_credito": (2550.0, 5200.0),   # n=3   — bajo _MIN_N, ver salvedad
}

# Universo completo (n=43). Lo usa cualquier tipo sin estrato propio, y deja declarado que
# el fallback existe en vez de que un tipo nuevo herede en silencio la curva de otro.
POR_DEFECTO: Tuple[float, float] = (1500.0, 6400.0)


def anclas_de(entity_type: Optional[str]) -> Tuple[float, float]:
    return ANCLAS.get(entity_type or "", POR_DEFECTO)


def score_de(raw: float, entity_type: Optional[str] = None) -> float:
    """Menos concentración es mejor: 100 en el p10 del estrato, 0 en su p90."""
    p10, p90 = anclas_de(entity_type)
    return max(0.0, min(100.0, 100.0 * (p90 - raw) / (p90 - p10)))


def raw_de(score: float, entity_type: Optional[str] = None) -> float:
    """Inversa exacta de ``score_de`` — el raw que haría puntuar ``score`` en ese estrato."""
    p10, p90 = anclas_de(entity_type)
    return p90 - score * (p90 - p10) / 100.0
