def apply_all(ops, a, b):
    results = []
    for op in ops:
        results.append(op(a, b))
    return results


def main():
    ops = [
        lambda a, b: a + b,
        lambda a, b: a - b,
        lambda a, b: a * b,
        lambda a, b: a // b if b != 0 else None,
    ]
    print(ops[0](7, 3))
    print(ops[1](7, 3))
    print(ops[2](7, 3))
    print(ops[3](7, 3))
    print(ops[3](7, 0))
    print(apply_all(ops, 0, 0))
    print(apply_all(ops, -1, 1))
    print(apply_all([], 5, 5))
    print(len(ops))
    print(apply_all(ops[:1], "x", "y"))


main()
