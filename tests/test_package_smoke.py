"""Foundation checks for installed package metadata and import wiring."""

from importlib.metadata import version

import command_station


def test_installed_package_imports_with_matching_metadata() -> None:
    """The installed distribution exposes the intended import package."""
    assert command_station.__name__ == "command_station"
    assert version("crypto-command-station") == "0.1.0"
