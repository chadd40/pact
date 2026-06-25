import os
import tempfile
from datetime import datetime, timezone

import pytest


@pytest.fixture
def fixed_clock():
    """A FixedClock pinned to a deterministic instant (Task 2 provides FixedClock)."""
    from pact.clock import FixedClock

    return FixedClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture
def repo():
    """A Repository backed by a throwaway on-disk SQLite file (Task 4 provides Repository)."""
    from pact.repository import Repository

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repository = Repository.connect(path)
    repository.init_schema()
    try:
        yield repository
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
