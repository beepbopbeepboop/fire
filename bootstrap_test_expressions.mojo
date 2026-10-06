"""Test expressions and operators."""

def arithmetic():
    a = 10
    b = 3
    return a + b * 2 - a / 2

def comparisons():
    x = 5
    y = 10
    if x < y and y > 0 or x == 5:
        return True
    return False

def bitwise():
    a = 12
    b = 10
    return (a & b) | (a ^ b)
