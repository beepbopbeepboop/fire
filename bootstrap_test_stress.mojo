"""Stress test: many small functions."""

def f1(x):
    return x + 1

def f2(x):
    return x * 2

def f3(x):
    return x - 1

def f4(x):
    return x / 2

def f5(x):
    return x % 2

def f6(a, b):
    if a > b:
        return a
    return b

def f7(a, b):
    if a < b:
        return a
    return b

def chain(x):
    x = f1(x)
    x = f2(x)
    x = f3(x)
    x = f4(x)
    return x

def compose():
    result = 0
    for i in range(10):
        result = f1(result)
        if f5(i) == 0:
            result = f2(result)
    return result
