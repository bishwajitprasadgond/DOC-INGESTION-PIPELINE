import logging
from logging.handlers import RotatingFileHandler

from ...config import PROJECT_ROOT, LoggingConfig

LOGGER_NAME = "docs_ingestion"


def setup_logging(config: LoggingConfig) -> logging.Logger:
    """Attach a rotating file handler (under the repo's `logs/` folder) and a console
    handler to the shared "docs_ingestion" logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(config.level)

    log_dir = PROJECT_ROOT / config.dir
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_dir / config.filename,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
