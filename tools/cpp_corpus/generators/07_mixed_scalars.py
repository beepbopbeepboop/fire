"""Scalar literals, a comparison chain and a subscript inside a generator:
`_cpp_expr`'s FloatLiteral/BoolLiteral/CompareChain/SubscriptExpr arms, with a
`return` arm that is not a plain `yield` loop.
"""


def pick(words, idxs):
    for i in idxs:
        if i < len(words) and idxs[i] >= 0 and words[i] != "":
            yield words[i]


def stats(xs):
    total = 0.0
    for x in xs:
        total = total + x
        if total > 2.0:
            break
    yield total
    yield True


def main():
    for w in pick(["a", "bb", "", "ccc"], [0, 1, 2, 3]):
        print(w)
    for v in stats([0.5, 1.0, 2.5, 9.0]):
        print(v)


main()
