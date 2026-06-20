def do_calc(operand1, operand2, operator):
  try:
    op1 = float(operand1)
  except (TypeError, ValueError) as e:
    raise ValueError(f"Invalid operand1: '{operand1}'. Must be a number.") from e
  try:
    op2 = float(operand2)
  except (TypeError, ValueError) as e:
    raise ValueError(f"Invalid operand2: '{operand2}'. Must be a number.") from e

  if operator == "add":
    ans = op1 + op2
  elif operator == "subtract":
    ans = op1 - op2
  elif operator == "multiply":
    ans = op1 * op2
  elif operator == "divide":
    if op2 == 0:
      raise ZeroDivisionError("Cannot divide by zero")
    ans = op1 / op2
  elif operator == "exponent":
    ans = op1**op2
  else:
    raise ValueError(f"Unsupported operator: '{operator}'. "
                     f"Valid operators are: add, subtract, multiply, divide, exponent")

  return check_int(ans)


def check_int(num):
  if num.is_integer():
    return int(num)
  else:
    return num
