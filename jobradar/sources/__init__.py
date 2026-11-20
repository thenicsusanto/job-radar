"""Job sources. Each module turns one kind of feed into JobPosting objects."""

from ..models import Board, JobPosting
from . import ashby, greenhouse, lever

BOARD_FETCHERS = {
    "greenhouse": greenhouse.fetch_board,
    "lever": lever.fetch_board,
    "ashby": ashby.fetch_board,
}


def fetch_board(board: Board) -> list[JobPosting]:
    """Fetch every open posting on one company board."""
    return BOARD_FETCHERS[board.ats](board)
