"""Rubik's cube (3x3x3) scramble tool.

Wraps the `rubiks` package (../rubiks) — a WCA-style scrambler where no
two consecutive moves are on the same axis.
"""

from rubiks import display, get_random_moves

DEFAULT_MOVE_COUNT = 25
MAX_MOVE_COUNT = 100


def get_scramble(move_count=None):
  """Return a random 3x3x3 scramble as a space-separated move string.

  e.g. "L B' D' L' F U' B D' ...". Defaults to 25 moves, capped at MAX_MOVE_COUNT.
  """
  if move_count is None:
    move_count = DEFAULT_MOVE_COUNT
  try:
    count = int(move_count)
  except (TypeError, ValueError) as e:
    raise ValueError(f"Invalid move_count: '{move_count}'. Must be an integer.") from e
  if count < 0:
    raise ValueError(f"move_count must be >= 0, got {count}")
  if count > MAX_MOVE_COUNT:
    count = MAX_MOVE_COUNT
  return display(get_random_moves(count))
