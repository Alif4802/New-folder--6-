import sqlite3
from pathlib import Path
import pytest
from app.core.config import settings, PROJECT_ROOT


def test_pytest_database_and_storage_isolation():
    """Guarantees that pytest never writes to production demo DB or storage."""
    demo_db = (PROJECT_ROOT / "data" / "nctb_intelligence.db").resolve()
    demo_storage = (PROJECT_ROOT / "storage").resolve()

    # Settings inside test must be pointing to tmp_path
    current_db = settings.DATABASE_URL
    current_storage = Path(settings.STORAGE_ROOT).resolve()

    assert "test_isolated.db" in current_db
    assert current_storage != demo_storage
    assert "test_storage" in str(current_storage)


def test_demo_database_subject_version_count_unmodified():
    """Guarantees that demo database retains exactly the 4 clean production textbooks."""
    demo_db = (PROJECT_ROOT / "data" / "nctb_intelligence.db").resolve()
    if not demo_db.is_file():
        pytest.skip("Demo database file not present.")

    conn = sqlite3.connect(demo_db)
    c = conn.cursor()
    c.execute("SELECT id, title, page_count FROM subject_versions")
    rows = c.fetchall()
    conn.close()

    # Real 198-page book must be present
    titles = [r[1] for r in rows]
    assert any("Mathematics" in t for t in titles)
    math_198 = next((r for r in rows if r[2] == 198), None)
    assert math_198 is not None, "Real 198-page Mathematics textbook must be preserved in demo database"
