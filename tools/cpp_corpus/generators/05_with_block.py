"""`with` inside a generator body: `_cpp_with_stmt` and the `__enter__`/
`__exit__` call sequence it emits (`MemberExpr` + `CallExpr` arms).
"""


def heads(path):
    with open(path) as f:
        for line in f:
            yield line


def main():
    n = 0
    for line in heads("/dev/null"):
        n += 1
    print(n)


main()
