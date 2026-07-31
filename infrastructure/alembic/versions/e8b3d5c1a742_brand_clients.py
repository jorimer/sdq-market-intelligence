"""brand_intel: el cliente como entidad con código, con varios estudios colgando

Antes el cliente era texto libre dentro del encargo: dos estudios del mismo cliente no
estaban atados por nada, y "Operador RD" y "Operador R.D." eran clientes distintos.

**No se toca la frontera de aislamiento.** ``brand_engagements.organization_id`` sigue
siendo lo único que gobierna el acceso y el 404-no-403; el cliente es una agrupación
dentro de la organización, y su ``organization_id`` solo sirve para heredarlo al crear un
estudio. Un cliente existe antes de que nadie suyo tenga login — que es el caso de hoy.

El backfill crea un cliente por cada ``client_name`` distinto y engancha sus encargos. El
código sale del nombre y puede editarse después; ante colisión se numera, porque un código
duplicado uniría dos clientes que no son el mismo.

Revision ID: e8b3d5c1a742
Revises: d4a9c2f7b613
"""
import re
import unicodedata
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8b3d5c1a742"
down_revision: Union[str, None] = "d4a9c2f7b613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _code(name: str) -> str:
    """Un código legible a partir del nombre: mayúsculas, sin acentos, con guiones."""
    decomposed = unicodedata.normalize("NFD", name or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^A-Z0-9]+", "-", stripped.upper()).strip("-")
    return (slug or "CLIENTE")[:40]


def upgrade() -> None:
    op.create_table(
        "brand_clients",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_brand_client_code"),
    )
    op.add_column("brand_engagements", sa.Column("client_id", sa.String(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT DISTINCT client_name, organization_id FROM brand_engagements "
        "WHERE client_name IS NOT NULL AND client_name <> ''"
    )).fetchall()

    taken: set = set()
    for client_name, org in rows:
        base = _code(client_name)
        code, n = base, 1
        while code in taken:
            n += 1
            code = f"{base[:36]}-{n}"
        taken.add(code)
        client_id = str(uuid.uuid4())
        conn.execute(
            sa.text("INSERT INTO brand_clients (id, code, name, organization_id, "
                    "is_active) VALUES (:id, :code, :name, :org, :active)"),
            {"id": client_id, "code": code, "name": client_name, "org": org,
             "active": True},
        )
        conn.execute(
            sa.text("UPDATE brand_engagements SET client_id = :cid "
                    "WHERE client_name = :name"),
            {"cid": client_id, "name": client_name},
        )


def downgrade() -> None:
    op.drop_column("brand_engagements", "client_id")
    op.drop_table("brand_clients")
