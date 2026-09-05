"""mm_forecast_log gana el horizonte RELATIVO (`h`)

El track record se computa sobre un conjunto de pronósticos comparables, y la clave de ese
conjunto era el trimestre CALENDARIO. Medido: tres años de operación perfecta —doce
trimestres emitidos a un trimestre vista y puntuados— dan `n_oos = 1`, porque cada trimestre
calendario es su propio conjunto de una sola observación. El gate exige 12.

O sea: **la proyección no habría anclado nunca**, y el motivo que el lector vería sería «1
observación fuera de muestra», indistinguible del estado honesto del día uno. Un guard que
siempre dice que no y parece que todavía no.

La pregunta que el track record responde es «¿qué tan bien pronosticamos a UN trimestre
vista?», y esa se acumula a lo largo de los trimestres. El horizonte relativo es la clave del
conjunto; el calendario sigue siendo el de la fila, porque es contra él que se puntúa.

Revision ID: c3f7a2d9e814
Revises: b2e9f4a71c85
"""
import sqlalchemy as sa
from alembic import op

revision = "c3f7a2d9e814"
down_revision = "b2e9f4a71c85"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: las filas anteriores no lo tienen y no se puede inventar. `track_record`
    # las excluye del conjunto en vez de adivinarles un horizonte, que sería fabricar
    # track record — exactamente lo que este ledger existe para impedir.
    op.add_column("mm_forecast_log", sa.Column("h", sa.Integer(), nullable=True))
    op.create_index("ix_mm_forecast_log_h", "mm_forecast_log", ["h"])


def downgrade() -> None:
    op.drop_index("ix_mm_forecast_log_h", table_name="mm_forecast_log")
    op.drop_column("mm_forecast_log", "h")
