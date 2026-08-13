"""La lectura CRUDA por lámina, para no volver a pagarle al modelo por un error nuestro.

Preguntarle al modelo qué dice una lámina cuesta una llamada de visión; convertir esa
respuesta en celdas es una función pura. Al no guardar la respuesta, cualquier defecto en la
conversión obligaba a releer el mazo entero: pasó dos veces, con la lectura del modelo
correcta las dos. ~360 KB por mazo contra decenas de llamadas.

Revision ID: a2c7e9f14b83
Revises: f3a1c9d5e720
"""
import sqlalchemy as sa
from alembic import op

revision = "a2c7e9f14b83"
down_revision = "f3a1c9d5e720"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_extraction_pages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("extraction_id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chart_title", sa.String(length=300), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=True),
        sa.Column("model_used", sa.String(length=80), nullable=True),
        sa.UniqueConstraint("extraction_id", "page_number",
                            name="uq_brand_extraction_page"),
    )
    op.create_index("ix_brand_extraction_page_job", "brand_extraction_pages",
                    ["extraction_id", "page_number"])


def downgrade() -> None:
    op.drop_index("ix_brand_extraction_page_job", table_name="brand_extraction_pages")
    op.drop_table("brand_extraction_pages")
