import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to path so we can import our modules
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config.settings import settings
from shared.database.base import Base

# Import all models so Alembic can detect them
from shared.auth.models import User  # noqa: F401
from shared.notifications.service import Notification  # noqa: F401
from shared.settings.models import AppSetting, SectorApiConfig  # noqa: F401
from shared.publications.models import Publication  # noqa: F401
from shared.operations.models import OperationRun, OperationSchedule  # noqa: F401
from shared.products.models import ProductActivation, ProductReadiness, Subscription  # noqa: F401
from shared.billing.models import Tariff  # noqa: F401
from modules.banking_score.models.models import (  # noqa: F401
    Bank, BankingData, RatingResult, RatingAction, Report,
)
from modules.macro_political_risk.models.models import (  # noqa: F401
    Country, IRMPSnapshot, DimensionScore,
)
from modules.macro_monitor.models.models import (  # noqa: F401
    ExcelFileReport, MacroSeries, MacroSnapshot,
)
from modules.trade_intel.models.models import (  # noqa: F401
    TradeFlow, TradeScore,
)
from modules.sector_intel.models.models import (  # noqa: F401
    Sector, SectorVariable, SectorScore,
)
from modules.social_dev.models.models import (  # noqa: F401
    SocialIndicator, DevelopmentScore,
)
from modules.esg_climate.models.models import (  # noqa: F401
    EnvIndicator, ESGScore,
)
from modules.energy_intel.models.models import EnergyScore  # noqa: F401
from modules.free_zones_intel.models.models import FreeZoneScore  # noqa: F401
from modules.telecom_intel.models.models import TelecomScore  # noqa: F401
from modules.pension_intel.models.models import (  # noqa: F401
    PensionEntity, PensionRating, PensionSeries, PensionSnapshot,
)
from modules.insurance_intel.models.models import (  # noqa: F401
    InsuranceEntity, InsuranceRating, InsuranceSeries, InsuranceSnapshot,
)
# Solo la clase mapeada (los enums Sector/DealType no van aquí: 'Sector' colisiona
# con sector_intel y Alembic solo necesita la tabla).
from modules.deal_scoring.models.models import HistoricalDeal  # noqa: F401

config = context.config

# Override sqlalchemy.url from settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
