"""A module-level global read inside a generator body: the `<module>_globals.<field>` read of
`_cpx_ident_expr`, the ported field leaf.
"""

LIMIT = 3


def gen(n: int):
    for i in range(n):
        yield i + LIMIT


def main():
    for v in gen(3):
        print(v)


main()
