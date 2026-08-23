"""Sanity checks that the fantasy_analyzer package is installed and importable."""

import fantasy_analyzer


def test_package_imports() -> None:
    """The top-level package should import without error."""
    assert fantasy_analyzer is not None
