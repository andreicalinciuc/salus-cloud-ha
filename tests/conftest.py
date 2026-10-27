"""Shared fixtures."""

import pytest


@pytest.fixture
def enable_custom(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components (only for tests that set it up)."""
    return None
