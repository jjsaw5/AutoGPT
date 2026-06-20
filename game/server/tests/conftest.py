from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.state import reset_state


@pytest.fixture
def state():
    """Fresh game state per test."""
    return reset_state()


@pytest.fixture
def client(state):
    """TestClient over a fresh game state."""
    return TestClient(app)
