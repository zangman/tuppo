import pytest
from calc import do_calc, check_int

# ── Happy path: all operators ───────────────────────────────────────


class TestDoCalc:

  def test_add_integers(self):
    assert do_calc(2, 3, "add") == 5

  def test_add_floats(self):
    assert do_calc(1.5, 2.3, "add") == 3.8

  def test_subtract_integers(self):
    assert do_calc(10, 4, "subtract") == 6

  def test_subtract_negative_result(self):
    assert do_calc(3, 10, "subtract") == -7

  def test_multiply_integers(self):
    assert do_calc(3, 4, "multiply") == 12

  def test_multiply_by_zero(self):
    assert do_calc(5, 0, "multiply") == 0

  def test_divide_exact(self):
    assert do_calc(10, 2, "divide") == 5

  def test_divide_float_result(self):
    assert do_calc(7, 2, "divide") == 3.5

  def test_exponent_integers(self):
    assert do_calc(2, 3, "exponent") == 8

  def test_exponent_float_to_int(self):
    # 4 ** 0.5 = 2.0 -> check_int converts to 2
    assert do_calc(4, 0.5, "exponent") == 2
    assert isinstance(do_calc(4, 0.5, "exponent"), int)

  def test_exponent_float_result(self):
    # 3 ** 1.5 = 5.196... -> stays float
    assert do_calc(3, 1.5, "exponent") == pytest.approx(5.196152422706632)
    assert isinstance(do_calc(3, 1.5, "exponent"), float)

  def test_string_numeric_inputs(self):
    assert do_calc("3", "4", "add") == 7


# ── Error cases ──────────────────────────────────────────────────────


class TestDoCalcErrors:

  def test_divide_by_zero(self):
    with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
      do_calc(10, 0, "divide")

  def test_invalid_operator(self):
    with pytest.raises(ValueError, match="Unsupported operator: 'modulo'"):
      do_calc(1, 2, "modulo")

  def test_invalid_operand1(self):
    with pytest.raises(ValueError, match="Invalid operand1"):
      do_calc("abc", 2, "add")

  def test_invalid_operand2(self):
    with pytest.raises(ValueError, match="Invalid operand2"):
      do_calc(1, "xyz", "add")


# ── check_int helper ─────────────────────────────────────────────────


class TestCheckInt:

  def test_whole_number(self):
    assert check_int(5.0) == 5
    assert isinstance(check_int(5.0), int)

  def test_fraction(self):
    assert check_int(3.14) == 3.14
    assert isinstance(check_int(3.14), float)

  def test_zero(self):
    assert check_int(0.0) == 0
    assert isinstance(check_int(0.0), int)
