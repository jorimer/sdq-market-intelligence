"""Crea `cartera_sectorial`: el libro de crédito abierto por sector económico.

El cubo `carteras/creditos` de la SIB trae en cada fila el sector junto a la mora, la mora
temprana de 31 a 90 días, la clasificación, la garantía y la provisión. Se recorría entero
para computar un HHI y el resto se descartaba. Esta tabla lo conserva.

Sin ENUM a propósito. `sector` son las etiquetas CIIU de la fuente («F - CONSTRUCCIÓN»), que
la SIB puede ampliar o renombrar. En Postgres los tipos ENUM viven en un namespace GLOBAL y
declarar uno dentro de un `create_table` ya tumbó un deploy en este repo (`d1c8e4b90735`):
pasó en CI —SQLite, sin namespace que colisionar— y falló en producción. Un VARCHAR no tiene
ese problema y además admite que la fuente cambie sin una migración de tipo.

El downgrade SÍ borra la tabla, y es correcto: a diferencia de un valor de enum, una tabla
creada por esta revisión no existía antes, así que revertirla no destruye nada que no haya
creado ella misma. El dato se reconstruye con un `sib-sync` sobre el rango.

Revision ID: a3f7c2d9e451
Revises: 7c4a2e91b0d3
"""
import sqlalchemy as sa
from alembic import op

revision = "a3f7c2d9e451"
down_revision = "7c4a2e91b0d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cartera_sectorial",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("bank_id", sa.String(), sa.ForeignKey("banks.id"), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("sector", sa.String(length=160), nullable=False),
        sa.Column("provincia", sa.String(length=80), nullable=False,
                  server_default="SIN PROVINCIA"),
        sa.Column("region", sa.String(length=80), nullable=True),
        sa.Column("deuda", sa.Numeric(18, 2), nullable=True),
        sa.Column("vencida", sa.Numeric(18, 2), nullable=True),
        sa.Column("vencida_31_90", sa.Numeric(18, 2), nullable=True),
        sa.Column("cartera_a", sa.Numeric(18, 2), nullable=True),
        sa.Column("garantia", sa.Numeric(18, 2), nullable=True),
        sa.Column("provision", sa.Numeric(18, 2), nullable=True),
        sa.Column("creditos", sa.Numeric(18, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("bank_id", "period_end", "sector", "provincia",
                            name="uq_cartera_sectorial_bank_period_sector_prov"),
    )
    op.create_index("ix_cartera_sectorial_bank_period", "cartera_sectorial",
                    ["bank_id", "period_end"])
    # «Quién está en este sector en este corte» es la lectura transversal del sistema, la que
    # ningún banco puede hacer con su propio libro. Sin este índice barre la tabla entera.
    op.create_index("ix_cartera_sectorial_sector_period", "cartera_sectorial",
                    ["sector", "period_end"])
    op.create_index("ix_cartera_sectorial_prov_period", "cartera_sectorial",
                    ["provincia", "period_end"])


def downgrade() -> None:
    op.drop_index("ix_cartera_sectorial_prov_period", table_name="cartera_sectorial")
    op.drop_index("ix_cartera_sectorial_sector_period", table_name="cartera_sectorial")
    op.drop_index("ix_cartera_sectorial_bank_period", table_name="cartera_sectorial")
    op.drop_table("cartera_sectorial")
