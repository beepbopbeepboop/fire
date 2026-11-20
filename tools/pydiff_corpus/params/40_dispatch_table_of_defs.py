def op_add(a, b):
    return a + b


def op_sub(a, b):
    return a - b


def op_div(a, b):
    if b == 0:
        return None
    return a // b


def run(table, name, a, b):
    fn = table.get(name)
    if fn is None:
        return "unknown"
    return fn(a, b)


def main():
    table = {"add": op_add, "sub": op_sub, "div": op_div}
    print(run(table, "add", 2, 3))
    print(run(table, "sub", 2, 3))
    print(run(table, "div", -7, 2))
    print(run(table, "div", 5, 0))
    print(run(table, "mul", 1, 1))
    print(run(table, "add", "a", "b"))
    print(run(table, "add", 0, 0))
    print(run(table, "sub", -1, -1))
    print(sorted(table.keys()))


main()
