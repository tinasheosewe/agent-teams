"""Shared test fixtures."""

import pytest


@pytest.fixture
def project_dir(tmp_path):
    """Provide a temporary project directory."""
    return tmp_path
