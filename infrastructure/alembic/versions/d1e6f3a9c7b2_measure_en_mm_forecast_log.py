"""mm_forecast_log declara EN QUÉ MEDIDA está su punto

El ledger puntuaba suponiendo dos cosas que no eran ciertas: que `target_series` nombraba una
serie observable, y que `point` era directamente comparable con el valor de esa serie.

* El BVAR registraba ``target_series = "pib_real"``, que es el nombre de la variable DENTRO
  del bloque. No existe ninguna serie con ese código —verificado en producción:
  ``GET /api/v1/macro-monitor/series/pib_real`` devuelve ``observations: []``—, así que sus
  filas quedaban `pending` para siempre y la sección de desempeño lo publicaba como
  «ninguna alcanzó su período de cierre»: paciencia reportada donde había una rotura.
* El punto de los dos motores es un Δlog en % (~0,4) y la serie contra la que se compara es
  el índice de volumen del PIB (~133). Un nowcast puntuado habría dado
  ``abs_error ≈ 132,75``, publicado como RMSE en un informe que se vende.

Es la misma causa raíz que `shared/data/series_nature.py` cerró un nivel más arriba: la
magnitud se DECLARA junto al dato en vez de adivinarse al leerlo.

**El backfill llega hasta donde se puede VERIFICAR, y ni un paso más.**

Ninguna fila está puntuada —verificado en el readiness de `macro_forecast`: «0 conjunto(s)
con backtest puntuado»—, así que no hay ningún error ya calculado que corregir.

* **`bridge_imae_pib.*` (el nowcast) → `dlog_pct`.** Se puede afirmar: `nowcast.estimar`
  regresa sobre `panel._dlog` y multiplica el resultado por 100, y ninguna de las dos cosas
  cambió nunca. Es la variación contra el trimestre ANTERIOR, siempre lo fue.

* **`bvar_minnesota.*` → se queda en NULL, a propósito.** El mismo día en que se escribieron
  estas filas, otra rama cambió la transformación de `pib_real` en el bloque de `DLOG`
  (variación trimestral) a `INTERANUAL` (contra el mismo trimestre del año anterior), y el
  cambio se desplegó entre medias — hubo diecinueve despliegues ese día. `as_of` es una FECHA
  sin hora, así que la fila **no registra** con cuál de las dos versiones se produjo, y las
  dos difieren en puntos porcentuales enteros: el QoQ promedia +1,13 % y el YoY +4,54 %.
  Declararle una medida que no se puede verificar sería fabricar exactamente lo que este
  ledger existe para impedir. Queda NULL, no se puntúa, y `ledger.no_puntuables` la LISTA con
  su causa para que la ausencia se vea en vez de leerse como paciencia.

El `target_series` sí se normaliza en las dos: que `"pib_real"` no es un `series_code` no
depende de ninguna versión del código.

Revision ID: d1e6f3a9c7b2
Revises: 7babe43b4afd

Re-apuntada al mergear main. Nació como hija de `c3f7a2d9e814`, y `7babe43b4afd` —que en el
momento de escribir ésta colgaba de `b2e9f4a71c85`— fue re-apuntada al mismo padre en
`3e295505`. Resultado: dos cabezas otra vez, que es lo que rompe el job de reversibilidad.
Se linealiza en vez de crear una revisión de merge, igual que hizo aquel commit: las dos son
independientes —aquélla crea `rb_country_aggregates`, ésta agrega una columna a
`mm_forecast_log`— y el repo mantiene una cadena sin ramas.
"""
import sqlalchemy as sa
from alembic import op

revision = "d1e6f3a9c7b2"
down_revision = "7babe43b4afd"
branch_labels = None
depends_on = None

#: El `series_code` observable del PIB. Se escribe literal y no se importa: una migración
#: tiene que seguir diciendo lo mismo dentro de un año, cuando la constante del módulo
#: quizá ya se llame de otra forma.
PIB_CODE = "bcrd.xls.pib_2018.serie_original_indice"


#: El backfill, en constantes para que un test pueda EJECUTARLAS contra una base de juguete y
#: comprobar que el `where` es tan angosto como dice el docstring. Una migración de datos que
#: nadie corre antes de producción es una apuesta.
BACKFILL_MEASURE = (
    "update mm_forecast_log set measure = 'dlog_pct' "
    "where measure is null and model_id like 'bridge_imae_pib.%'"
)
BACKFILL_TARGET_SERIES = (
    "update mm_forecast_log set target_series = :pib "
    "where target_series = 'pib_real' and model_id like 'bvar_minnesota.%'"
)


def upgrade() -> None:
    # Nullable: una fila que no declara su medida no se puntúa. El default habría sido peor
    # que la ausencia — suponerle «nivel» a un punto que es una tasa es exactamente el
    # defecto, y lo habría aplicado a todo lo que no se pudiera identificar.
    op.add_column("mm_forecast_log", sa.Column("measure", sa.String(length=16),
                                               nullable=True))
    op.execute(sa.text(BACKFILL_MEASURE))
    op.execute(sa.text(BACKFILL_TARGET_SERIES).bindparams(pib=PIB_CODE))


def downgrade() -> None:
    # El `target_series` NO se revierte: volver a poner `"pib_real"` reintroduciría filas que
    # no se pueden puntuar contra nada. Un downgrade de esquema no tiene por qué re-romper
    # los datos.
    op.drop_column("mm_forecast_log", "measure")
