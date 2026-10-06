"""Test loops and iteration."""

def sum_n(n):
    total = 0
    for i in range(n):
        total = total + i
    return total

def while_countdown(n):
    while n > 0:
        n = n - 1
    return n

def nested_loops():
    result = 0
    for i in range(3):
        for j in range(2):
            result = result + 1
    return result
