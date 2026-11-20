def make_stack():
    items = []

    def push(x):
        items.append(x)
        return len(items)

    def pop():
        if len(items) == 0:
            return None
        return items.pop()

    def size():
        return len(items)

    return push, pop, size


def main():
    push_a, pop_a, size_a = make_stack()
    push_b, pop_b, size_b = make_stack()
    print(size_a())
    print(size_b())
    print(push_a(1))
    print(push_a("two"))
    print(push_b(0))
    print(size_a())
    print(size_b())
    print(pop_a())
    print(pop_b())
    print(pop_b())
    print(pop_a())
    print(pop_a())
    print(size_a(), size_b())


main()
