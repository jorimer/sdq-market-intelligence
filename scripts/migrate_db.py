"""Copy all data from one database to another (e.g. local SQLite → prod Postgres).

Reads every table via SQLAlchemy (so types round-trip through Python correctly:
booleans, enums, dates, JSON) and inserts into the target in FK-dependency order.

The TARGET schema must already exist (it's created by the deploy's migrations).
Source defaults to the app's configured DB; target comes from TARGET_DATABASE_URL
so the connection string is never passed on the command line.

    # from the repo root, with the prod Postgres URL in TARGET_DATABASE_URL
    TARGET_DATABASE_URL='postgresql://…' python scripts/migrate_db.py
    # options:
    #   --source sqlite:///./data/sdq_market_intel.db   (override source)
    #   --wipe                                           (delete target rows first)
    #   --only users,banks,banking_data                  (subset of tables)

Refuses to run if a target table already has rows, unless --wipe is given.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, delete, func, select  # noqa: E402

from shared.config.settings import settings  # noqa: E402
from shared.database.base import Base  # noqa: E402

# Import every model so Base.metadata holds all tables (mirrors alembic/env.py).
from shared.auth.models import User  # noqa: F401,E402
from shared.notifications.service import Notification  # noqa: F401,E402
from modules.banking_score.models.models import (  # noqa: F401,E402
    Bank, BankingData, RatingResult, RatingAction, Report,
)
from modules.macro_political_risk.models.models import Country, IRMPSnapshot, DimensionScore  # noqa: F401,E402
from modules.macro_monitor.models.models import MacroSeries, MacroSnapshot  # noqa: F401,E402
from modules.trade_intel.models.models import TradeFlow, TradeScore  # noqa: F401,E402
from modules.sector_intel.models.models import Sector, SectorVariable, SectorScore  # noqa: F401,E402
from modules.social_dev.models.models import SocialIndicator, DevelopmentScore  # noqa: F401,E402
from modules.esg_climate.models.models import EnvIndicator, ESGScore  # noqa: F401,E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sdq.migrate_db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Copiar datos entre bases (SQLite → Postgres)")
    parser.add_argument("--source", default=settings.DATABASE_URL, help="URL de origen")
    parser.add_argument("--wipe", action="store_true", help="Vaciar tablas destino antes de copiar")
    parser.add_argument("--only", help="Lista separada por comas de tablas a copiar")
    args = parser.parse_args()

    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        logger.error("Falta TARGET_DATABASE_URL (URL de la base destino).")
        sys.exit(1)
    if target_url == args.source:
        logger.error("Origen y destino son la misma base.")
        sys.exit(1)

    src = create_engine(args.source)
    tgt = create_engine(target_url)

    tables = list(Base.metadata.sorted_tables)  # FK-safe order
    if args.only:
        wanted = {t.strip() for t in args.only.split(",")}
        tables = [t for t in tables if t.name in wanted]

    logger.info("Origen: %s", args.source)
    logger.info("Destino: %s", target_url.split("@")[-1])

    with src.connect() as sc, tgt.begin() as tc:
        # Safety: target tables must be empty unless --wipe.
        if not args.wipe:
            for t in tables:
                if tc.execute(select(func.count()).select_from(t)).scalar():
                    logger.error("La tabla destino '%s' no está vacía. Usa --wipe para sobrescribir.", t.name)
                    sys.exit(1)
        else:
            for t in reversed(tables):  # children first
                tc.execute(delete(t))

        total = 0
        for t in tables:
            rows = [dict(r._mapping) for r in sc.execute(select(t))]
            if rows:
                tc.execute(t.insert(), rows)
            logger.info("  %-22s %5d filas", t.name, len(rows))
            total += len(rows)
        logger.info("Copia completa: %d filas en %d tablas.", total, len(tables))


if __name__ == "__main__":
    main()
