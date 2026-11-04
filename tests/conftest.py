import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rentradar import build  # noqa: E402
from rentradar.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory):
    """Build the synthetic fixture database once per test session."""
    path = tmp_path_factory.mktemp("db") / "fixtures.sqlite"
    build.build(path, fixtures=True, today=date(2026, 10, 27), log=lambda *a: None)
    return path


@pytest.fixture(scope="session")
def store(fixture_db):
    return Store(fixture_db)
