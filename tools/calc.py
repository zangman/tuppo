def do_calc(operand1, operand2, operator):
  op1 = float(operand1)
  op2 = float(operand2)
  if operator == "add":
    ans = op1 + op2
  elif operator == "subtract":
    ans = op1 - op2
  elif operator == "multiply":
    ans = op1 * op2
  elif operator == "divide":
    ans = op1 / op2
  elif operator == "exponent":
    ans = op1**op2
  else:
    ans = 42

  return check_int(ans)


def check_int(num):
  if num.is_integer():
    return int(num)
  else:
    return num

