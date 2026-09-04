"""el ledger de pronósticos macro — mm_forecast_log

Revision ID: b2e9f4a71c85
Revises: a4c7e1b9d302
Create Date: 2026-09-04

El track record es parte del producto, no un subproducto: cada proyección emitida se registra
con su corte point-in-time y se puntúa cuando llega el observado.

La clave única tiene CINCO campos, `revision` incluido. Con cuatro —modelo, serie, horizonte,
corte— una corrección de un pronóstico ya emitido no se puede escribir, colisiona, y el único
camino queda ser actualizar la fila original: reescribir la historia. `tpm_forecast_log`, el
ledger anterior, no tiene restricción de unicidad alguna; éste no repite esa omisión.

`status` es SOLO el ciclo de vida de la puntuación (`pending`/`scored`) y el linaje vive en
`superseded_by`, en su propia columna. Poner `superseded` como estado sacaría la revisión 0
del track record —que se computa sobre revisión 0 y `scored`— y corregir un pronóstico habría
borrado el original del historial.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2e9f4a71c85"
down_revision: Union[str, None] = "a4c7e1b9d302"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mm_forecast_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("target_series", sa.String(length=255), nullable=False),
        sa.Column("horizon", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("point", sa.Float(), nullable=False),
        sa.Column("intervals", sa.JSON(), nullable=False),
        sa.Column("lo_80", sa.Float(), nullable=True),
        sa.Column("hi_80", sa.Float(), nullable=True),
        sa.Column("lo_90", sa.Float(), nullable=True),
        sa.Column("hi_90", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="pending"),
        sa.Column("superseded_by", sa.String(length=36), nullable=True),
        sa.Column("realized", sa.Float(), nullable=True),
        sa.Column("realized_period_end", sa.String(length=10), nullable=True),
        sa.Column("abs_error", sa.Float(), nullable=True),
        sa.Column("sq_error", sa.Float(), nullable=True),
        sa.Column("interval_hit_80", sa.Boolean(), nullable=True),
        sa.Column("interval_hit_90", sa.Boolean(), nullable=True),
        sa.Column("scored_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("model_id", "target_series", "horizon", "as_of", "revision",
                            name="uq_mm_forecast_log_key"),
    )
    op.create_index("ix_mm_forecast_log_model_id", "mm_forecast_log", ["model_id"])
    op.create_index("ix_mm_forecast_log_target_series", "mm_forecast_log", ["target_series"])
    op.create_index("ix_mm_forecast_log_status", "mm_forecast_log", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mm_forecast_log_status", table_name="mm_forecast_log")
    op.drop_index("ix_mm_forecast_log_target_series", table_name="mm_forecast_log")
    op.drop_index("ix_mm_forecast_log_model_id", table_name="mm_forecast_log")
    op.drop_table("mm_forecast_log")
