"""brand_intel: la extracción pasa a ser un TRABAJO reanudable, no una petición

Leer un mazo real son decenas de llamadas de visión —el de Ipsos, 59 láminas— y eso no
cabe en una petición HTTP. La primera versión lo intentaba: moría contra el presupuesto de
tiempo del proxy DESPUÉS de haber pagado todas las llamadas que alcanzó a hacer, sin dejar
ni una cifra.

La fila deja de describir solo el resultado y pasa a ser el trabajo: cuántas láminas lleva
(``pages_done``), cuándo empezó y terminó, por qué falló si falló, el informe completo, y
el propio PDF mientras dura. Con eso la lectura se reanuda por donde iba, la pantalla puede
enseñar "lámina 7 de 59" y ``task_acks_late`` puede reencolar un trabajo muerto sin pagar
dos veces lo ya leído.

``source_pdf`` va en la base y no en un bucket a propósito: es dato privado de un cliente y
``engagement_id`` es lo único que gobierna su acceso en todo el módulo — un bucket
necesitaría su propio control, que es la clase de frontera duplicada que acaba divergiendo.
Se pone a NULL al terminar el trabajo, así que no pesa de por vida.

Revision ID: f2c7a4d9b810
Revises: e8b3d5c1a742
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2c7a4d9b810"
down_revision: Union[str, None] = "e8b3d5c1a742"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("brand_extractions",
                  sa.Column("pages_done", sa.Integer(), nullable=False,
                            server_default="0"))
    op.add_column("brand_extractions", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("brand_extractions", sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.add_column("brand_extractions", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("brand_extractions", sa.Column("report", sa.JSON(), nullable=True))
    op.add_column("brand_extractions",
                  sa.Column("source_pdf", sa.LargeBinary(), nullable=True))
    op.add_column("brand_extractions", sa.Column("max_pages", sa.Integer(), nullable=True))

    # Lo ya leído terminó de una sola vez: sus láminas hechas son todas las que tenía.
    op.execute("UPDATE brand_extractions SET pages_done = COALESCE(n_pages, 0)")


def downgrade() -> None:
    for col in ("max_pages", "source_pdf", "report", "error",
                "finished_at", "started_at", "pages_done"):
        op.drop_column("brand_extractions", col)
