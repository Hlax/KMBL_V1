"""Shared pytest fixtures for the KMBL orchestrator test suite.

Centralises common setup (singleton resets, env overrides) so individual
test modules can depend on them instead of re-defining boilerplate.
"""

from __future__ import annotations

import pytest

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests


@pytest.fixture
def _reset_singletons() -> None:
    """Clear cached Settings and the repository singleton between tests.

    Use as a building-block fixture for more specific setup fixtures.
    This runs before the test; cleanup happens via ``monkeypatch.undo()``
    automatically.
    """
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()
