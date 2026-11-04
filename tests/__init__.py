"""Tests for the Innergrid integration."""

from pathlib import Path


def load_fixture(name: str) -> str:
    """Load a JSON fixture with the payload of a message."""
    return (Path(__file__).parent / "fixtures" / name).read_text()
