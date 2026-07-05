from __future__ import annotations

import pytest

from data.seed_db import seed_database


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> str:
    db_path = str(tmp_path_factory.mktemp("db") / "test_vrm.db")
    seed_database(db_path)
    return db_path
