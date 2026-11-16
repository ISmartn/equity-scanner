"""RSS news desk stored in the lab database."""

from .service import build_board, refresh_feeds

__all__ = ["build_board", "refresh_feeds"]
