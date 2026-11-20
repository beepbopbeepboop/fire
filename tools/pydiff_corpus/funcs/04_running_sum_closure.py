def make_accumulator(start):
    total = start

    def accumulate(x):
        nonlocal total
        total = total + x
        return total

    return accumulate


def run_all(fn, values):
    out = []
    for v in values:
        out.append(fn(v))
    return out


def main():
    acc = make_accumulator(100)
    print(acc(1))
    print(acc(-50))
    print(acc(0))
    print(run_all(acc, [10, 20]))
    fresh = make_accumulator(0)
    print(run_all(fresh, [0, 0, 0]))
    print(run_all(fresh, []))
    print(run_all(make_accumulator(-1), [1, 1]))
    print(acc(0))


main()
