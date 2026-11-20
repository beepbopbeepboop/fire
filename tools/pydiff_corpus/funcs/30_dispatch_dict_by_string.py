def op_add(a, b):
    return a + b


def op_div(a, b):
    return a // b if b else None


def op_neg(a, b):
    return -a


def run(name, a, b):
    ops = {"add": op_add, "div": op_div, "neg": op_neg}
    fn = ops.get(name)
    if fn is None:
        return "unknown " + name
    return fn(a, b)


def main():
    print(run("add", 7, 2))
    print(run("div", 7, 2))
    print(run("div", 7, 0))
    print(run("neg", 7, 0))
    print(run("nope", 1, 1))
    print(run("", 0, 0))
    print(run("add", "x", "y"))
    print(run("add", [1], [2, 3]))
    for key in ["add", "neg"]:
        print(key, run(key, -1, -1))


main()
