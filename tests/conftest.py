"""Shared pytest configuration for the lairs test suite.

Adds a ``--run-integration`` flag and an ``integration`` marker. Integration
tests are deselected by default so that ``uv run pytest`` exercises only the
fast, dependency-free unit tests; passing ``--run-integration`` opts in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--run-integration`` command-line flag."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests (real IO, optional deps, credentials)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``integration`` marker."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests "
        "(deselected unless --run-integration is given)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: Iterable[pytest.Item],
) -> None:
    """Skip integration tests unless ``--run-integration`` was passed."""
    if config.getoption("--run-integration"):
        return

    skip = pytest.mark.skip(reason="need --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
