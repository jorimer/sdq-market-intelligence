"""NCF tradicional: fiscal_sequence (dos regímenes) + numeración en billing_transaction

Revision ID: b2d7f4a91c65
Revises: a1f4c7e29b83
Create Date: 2026-08-16

SDQ pasa a cobrar self-serve emitiendo **NCF tradicional** (serie B, rango autorizado por la
DGII) mientras se habilita como Emisor Electrónico. Dos cambios:

1. ``encf_sequence`` → ``fiscal_sequence``: la tabla sirve a los DOS regímenes (columna
   ``regime``) y su columna de tipo deja de llamarse ``ecf_type`` (bajo NCF guardaría un "02",
   indistinguible de un tipo de e-CF para cualquier lectura que no traiga el régimen). La
   tabla está VACÍA en producción (verificado 2026-08-16 vía ``GET /billing/encf/sequences``),
   así que se recrea en vez de migrar filas.
2. ``billing_transaction`` gana los campos del NCF realmente emitido, APARTE de los ``encf_*``
   (cada régimen declara lo suyo; el otro queda en NULL legítimamente), más los índices únicos
   que garantizan que no existan dos comprobantes con el mismo número.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d7f4a91c65"
down_revision: Union[str, None] = "a1f4c7e29b83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Secuencias: tabla nueva con régimen, y baja de la vieja (vacía en prod) ──
    op.create_table(
        "fiscal_sequence",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("regime", sa.String(length=4), nullable=False, server_default="ecf"),
        sa.Column("doc_type", sa.String(length=2), nullable=False),
        sa.Column("range_from", sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column("range_to", sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column("current", sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fiscal_sequence_type", "fiscal_sequence", ["regime", "doc_type"])

    # La tabla vieja nunca llegó a tener filas (el e-CF no se emitió: falta el certificado).
    # Se consulta el inspector porque una instalación anterior a la e-CF puede no tenerla.
    inspector = sa.inspect(op.get_bind())
    if "encf_sequence" in inspector.get_table_names():
        op.drop_index("ix_encf_sequence_type", table_name="encf_sequence")
        op.drop_table("encf_sequence")

    # ── 2. Numeración NCF en la transacción facturable ──
    with op.batch_alter_table("billing_transaction") as batch:
        batch.add_column(sa.Column("ncf_type", sa.String(length=2), nullable=True))
        batch.add_column(sa.Column("ncf_number", sa.String(length=19), nullable=True))
        batch.add_column(sa.Column("ncf_status", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("ncf_issued_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("ncf_valid_until", sa.DateTime(), nullable=True))

    # Un número de comprobante no puede repetirse. El compare-and-swap del asignador lo evita;
    # esto lo garantiza aunque un camino futuro lo asigne por otro lado. (NULL es distinto de
    # NULL en un índice único, así que los cobros sin numerar no colisionan entre sí.)
    op.create_index("uq_billing_transaction_ncf", "billing_transaction",
                    ["ncf_type", "ncf_number"], unique=True)
    op.create_index("uq_billing_transaction_encf", "billing_transaction",
                    ["encf_type", "encf_number"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_billing_transaction_encf", table_name="billing_transaction")
    op.drop_index("uq_billing_transaction_ncf", table_name="billing_transaction")
    with op.batch_alter_table("billing_transaction") as batch:
        batch.drop_column("ncf_valid_until")
        batch.drop_column("ncf_issued_at")
        batch.drop_column("ncf_status")
        batch.drop_column("ncf_number")
        batch.drop_column("ncf_type")

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
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_encf_sequence_type", "encf_sequence", ["ecf_type"])
    op.drop_index("ix_fiscal_sequence_type", table_name="fiscal_sequence")
    op.drop_table("fiscal_sequence")
