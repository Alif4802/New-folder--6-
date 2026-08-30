import logging
from pathlib import Path
from app.core.config import settings

logger = logging.getLogger("nctb.storage")


def init_storage_directories() -> None:
    """Safely ensure configured storage directories exist on startup."""
    try:
        settings.storage_pdfs_dir.mkdir(parents=True, exist_ok=True)
        settings.storage_images_dir.mkdir(parents=True, exist_ok=True)
        settings.storage_staging_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Storage directories initialized at: {settings.STORAGE_ROOT}")
    except Exception as exc:
        logger.error(f"Failed to initialize storage directories: {exc}", exc_info=True)
        raise

