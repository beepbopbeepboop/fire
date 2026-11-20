def add_one(x):
    return x + 1


def times_three(x):
    return x * 3


def to_text(x):
    return "<" + str(x) + ">"


def compose(f, g):
    def both(x):
        return f(g(x))
    return both


def run_chain(fns, value):
    for fn in fns:
        value = fn(value)
    return value


def main():
    a = compose(add_one, times_three)
    print(a(2))
    print(a(0))
    print(a(-1))
    b = compose(to_text, add_one)
    print(b(9))
    print(run_chain([add_one, times_three], 4))
    print(run_chain([], 4))
    print(run_chain([to_text, to_text], 1))
    print(run_chain([times_three, add_one, to_text], -2))


main()
