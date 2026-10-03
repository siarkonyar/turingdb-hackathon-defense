"""Shared move rejection type so the CLI and imported board catch the same exception."""

from __future__ import annotations


class MoveRejected(ValueError):
    """The board could not build a move; the model gets the reason and can retry."""
