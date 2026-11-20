def add_zero(items):
    items.append(0)


def clear_all(items):
    items.clear()


def replace_with_copy(items):
    items = items + ["copy"]
    return items


def main():
    a = []
    add_zero(a)
    print(a)
    add_zero(a)
    print(len(a))
    b = ["x", 1]
    add_zero(b)
    print(b)
    print(add_zero([]) is None)
    result = replace_with_copy(b)
    print(b)
    print(result)
    clear_all(b)
    print(b, len(b))
    clear_all(a)
    print(a == [], result)


main()
