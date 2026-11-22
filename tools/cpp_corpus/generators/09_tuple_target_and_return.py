"""Tuple targets and a `return` inside a generator body: `_cpp_stmt`'s
MultiAssignStmt/ReturnStmt arms and the `_cpp_last_has_return_value` path
that stores the return value in the promise slot.
"""


def pairs(xs):
    total = 0
    for x in xs:
        lo, hi = x, x * 2
        total += lo + hi
        yield total
    return total


def main():
    for v in pairs([1, 2, 3]):
        print(v)


main()
