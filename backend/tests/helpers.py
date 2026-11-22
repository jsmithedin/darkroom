from pathlib import Path

from alembic.config import Config

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg
