import pytest
from rubiks_scramble import DEFAULT_MOVE_COUNT, MAX_MOVE_COUNT, get_scramble

VALID_MOVES = {
  "F",
  "F'",
  "B",
  "B'",
  "L",
  "L'",
  "R",
  "R'",
  "U",
  "U'",
  "D",
  "D'",
}

# WCA axes: F/B share one, L/R another, U/D another
_AXIS = {}
for _faces, _axis in (("FB", "fb"), ("LR", "lr"), ("UD", "ud")):
  for _face in _faces:
    _AXIS[_face] = _axis
    _AXIS[_face + "'"] = _axis

# ── Happy path ──────────────────────────────────────────────────────


class TestGetScramble:

  def test_default_move_count(self):
    assert len(get_scramble().split()) == DEFAULT_MOVE_COUNT

  def test_none_uses_default(self):
    assert len(get_scramble(None).split()) == DEFAULT_MOVE_COUNT

  def test_zero_moves_returns_empty(self):
    assert get_scramble(0) == ""

  @pytest.mark.parametrize("count", [1, 7, 25, 100])
  def test_custom_move_count(self, count):
    assert len(get_scramble(count).split()) == count

  def test_string_input(self):
    assert len(get_scramble("10").split()) == 10

  def test_all_moves_valid(self):
    moves = get_scramble(50).split()
    assert set(moves) <= VALID_MOVES

  def test_no_consecutive_same_axis(self):
    moves = get_scramble(50).split()
    for prev, cur in zip(moves, moves[1:], strict=False):
      assert _AXIS[prev] != _AXIS[cur], f"consecutive moves on same axis: {prev} {cur}"

  def test_scrambles_differ(self):
    assert get_scramble() != get_scramble()


# ── Error cases ─────────────────────────────────────────────────────


class TestGetScrambleErrors:

  def test_invalid_move_count_string(self):
    with pytest.raises(ValueError, match="Invalid move_count"):
      get_scramble("abc")

  def test_negative_move_count(self):
    with pytest.raises(ValueError, match="move_count must be >= 0"):
      get_scramble(-1)


# ── Cap ─────────────────────────────────────────────────────────────


class TestMoveCountCap:

  def test_huge_count_capped(self):
    assert len(get_scramble(9999).split()) == MAX_MOVE_COUNT
