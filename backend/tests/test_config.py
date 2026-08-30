from pathlib import Path
from app.core.config import Settings, PROJECT_ROOT


def test_default_settings():
    """Verify default settings load correctly."""
    s = Settings()
    assert s.APP_NAME == "NCTB Intelligence Demo"
    assert s.API_V1_PREFIX == "/api/v1"
    assert "http://localhost:5173" in s.CORS_ORIGINS
    assert s.STORAGE_ROOT.is_absolute()
    assert s.data_dir.is_absolute()
    assert s.storage_pdfs_dir.name == "pdfs"
    assert s.storage_images_dir.name == "images"


def test_cors_origins_json_parsing():
    """Verify CORS_ORIGINS parses JSON array strings."""
    s = Settings(CORS_ORIGINS='["http://example.com", "http://app.local"]')
    assert s.CORS_ORIGINS == ["http://example.com", "http://app.local"]


def test_cors_origins_comma_separated_parsing():
    """Verify CORS_ORIGINS parses comma-separated strings."""
    s = Settings(CORS_ORIGINS="http://foo.com, http://bar.com")
    assert s.CORS_ORIGINS == ["http://foo.com", "http://bar.com"]


def test_relative_storage_root_resolution():
    """Verify relative storage root is resolved relative to PROJECT_ROOT."""
    s = Settings(STORAGE_ROOT="./custom_storage")
    assert s.STORAGE_ROOT == (PROJECT_ROOT / "custom_storage").resolve()


def test_relative_database_url_resolution():
    """Verify relative database URL is converted to absolute SQLite URI."""
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./data/custom.db")
    expected_path = (PROJECT_ROOT / "data" / "custom.db").resolve().as_posix()
    assert s.DATABASE_URL == f"sqlite+aiosqlite:///{expected_path}"
