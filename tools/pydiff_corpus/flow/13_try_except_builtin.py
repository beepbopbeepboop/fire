def safe_int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return -1


def lookup(d: dict, key: object):
    try:
        return d[key]
    except KeyError:
        return "missing"


def fetch(lst: list, i: int):
    try:
        return lst[i]
    except IndexError:
        return "out of range"


def divide(a, b):
    try:
        return a // b
    except ZeroDivisionError:
        return "div by zero"


def main():
    print(safe_int("42"))
    print(safe_int("x1"))
    print(safe_int(""))
    print(safe_int(" 7 "))
    d = {"a": 1}
    print(lookup(d, "a"))
    print(lookup(d, "zz"))
    print(lookup(d, 0))
    lst = [10, 20]
    print(fetch(lst, 1))
    print(fetch(lst, 99))
    print(fetch(lst, -2))
    print(fetch(lst, -3))
    print(divide(7, 2))
    print(divide(7, 0))
    print(divide(-7, 2))
    print(divide(7.0, 0))


main()
