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

**El backfill, y por qué se puede afirmar lo que afirma.** Las filas que hay son de UNA sola
versión del código: `emision.py` nació el 2026-09-04 (commit `4f7bc0f3`) y esta migración es
del día siguiente. Ninguna está puntuada — verificado en el readiness de `macro_forecast`:
«0 conjunto(s) con backtest puntuado» —, así que no hay ningún error ya calculado que
corregir. Sus dos únicos productores emiten un Δlog en % sobre el índice del PIB:
`bridge_imae_pib.*` (`nowcast.estimar`, que multiplica su Δlog por 100) y `bvar_minnesota.*`
(vía `bloque._transformar`, que aplica ``(log b − log a) × 100``).

No es fabricar track record: es corregir un rótulo cuyo contenido es verificable leyendo el
único commit que lo escribió. Dejarlas inservibles tiraría historial REAL y ganado, en un
ledger que necesita 12 observaciones para anclar y hoy tiene 1. El backfill es ACOTADO a esos
dos prefijos de `model_id`; cualquier otra fila queda con `measure` NULL, no se puntúa, y
`ledger.no_puntuables` la lista para que la ausencia se vea.

Revision ID: d1e6f3a9c7b2
Revises: c3f7a2d9e814
"""
import sqlalchemy as sa
from alembic import op

revision = "d1e6f3a9c7b2"
down_revision = "c3f7a2d9e814"
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
    "where measure is null "
    "  and (model_id like 'bridge_imae_pib.%' or model_id like 'bvar_minnesota.%')"
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
