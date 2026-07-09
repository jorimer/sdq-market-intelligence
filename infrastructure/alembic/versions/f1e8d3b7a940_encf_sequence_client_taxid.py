"""e-CF: encf_sequence (rangos e-NCF DGII) + users.tax_id (RNC/cédula del cliente)

Revision ID: f1e8d3b7a940
Revises: e7c3a1f9b204
Create Date: 2026-07-09

e-CF Slices 2 y 3. Tabla ``encf_sequence`` (rango de secuencia e-NCF autorizado por la DGII por
tipo de e-CF, con vencimiento y correlativo actual) y columna ``users.tax_id`` (RNC/cédula del
cliente, define tipo 31 crédito fiscal vs 32 consumo). Aditivo, parity SQLite↔Postgres.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1e8d3b7a940"
down_revision: Union[str, None] = "e7c3a1f9b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tax_id", sa.String(length=20), nullable=True))

    op.create_table(
        "encf_sequence",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("ecf_type", sa.String(length=2), nullable=False),
        sa.Column("range_from", sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column("range_to", sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column("current", sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_encf_sequence_type", "encf_sequence", ["ecf_type"])


def downgrade() -> None:
    op.drop_index("ix_encf_sequence_type", table_name="encf_sequence")
    op.drop_table("encf_sequence")
    op.drop_column("users", "tax_id")
