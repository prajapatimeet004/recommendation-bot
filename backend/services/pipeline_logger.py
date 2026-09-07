import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.settings import settings

LOG_DIR = Path(settings.LOG_DIR_PATH)
LOG_DIR.mkdir(exist_ok=True)

_LOG_FILE = LOG_DIR / "pipeline.log"
_MAX_LOG_BYTES = settings.LOG_MAX_BYTES
_LOG_BACKUP_COUNT = settings.LOG_BACKUP_COUNT

_logger_initialized = False


def get_pipeline_logger() -> logging.Logger:
    global _logger_initialized

    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)

    if _logger_initialized:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    fh = RotatingFileHandler(str(_LOG_FILE), maxBytes=_MAX_LOG_BYTES, backupCount=_LOG_BACKUP_COUNT, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Reconfigure stdout to handle Unicode (Windows cp1252 workaround)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except AttributeError:
        pass  # older Python or non-TTY stdout

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    _logger_initialized = True

    logger.info("=" * 60)
    logger.info("Pipeline logger started — log file: %s (max %d MB, %d backups)", _LOG_FILE, _MAX_LOG_BYTES // (1024 * 1024), _LOG_BACKUP_COUNT)
    logger.info("=" * 60)

    return logger


_apify_logger_initialized = False
_APIFY_LOG_FILE = LOG_DIR / "apify.log"


def get_apify_logger() -> logging.Logger:
    global _apify_logger_initialized

    logger = logging.getLogger("apify")
    logger.setLevel(logging.DEBUG)

    if _apify_logger_initialized:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    fh = RotatingFileHandler(str(_APIFY_LOG_FILE), maxBytes=_MAX_LOG_BYTES, backupCount=_LOG_BACKUP_COUNT, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    _apify_logger_initialized = True

    logger.info("=" * 60)
    logger.info("Apify logger started — log file: %s", _APIFY_LOG_FILE)
    logger.info("=" * 60)

    return logger
