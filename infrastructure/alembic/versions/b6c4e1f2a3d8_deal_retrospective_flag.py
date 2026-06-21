"""add 'retrospective' flag to historical_deals

Revision ID: b6c4e1f2a3d8
Revises: d5a1c0b2e9f7
Create Date: 2026-06-21

Marca si un label se etiquetó con el outcome YA conocido (backfill retrospectivo)
o se scoreó ANTES de saberlo (cosecha going-forward, ex-ante). Solo los ex-ante
gradúan el modelo: un AUC alto sobre labels retrospectivos es fuga de información,
no habilidad predictiva (doctrina anti-fabricación, mismo estándar que los Gate E).

Las filas existentes (134 deals importados) quedan en False por server_default; el
re-import del set histórico las marca True (toda curación histórica es retrospectiva).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c4e1f2a3d8"
down_revision: Union[str, None] = "d5a1c0b2e9f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "historical_deals",
        sa.Column("retrospective", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    # Toda fila pre-existente es curación histórica (etiquetada con el outcome ya
    # conocido) → retrospectiva. No debe graduar el modelo. Las nuevas (server_default
    # false) son ex-ante salvo que el import/harvest las marque distinto.
    op.execute(sa.text("UPDATE historical_deals SET retrospective = TRUE"))


def downgrade() -> None:
    op.drop_column("historical_deals", "retrospective")
