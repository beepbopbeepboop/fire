class Box:
    def __init__(self, value, items):
        self.value = value
        self.items = items


def bump(box: Box):
    box.value += 1


def replace_value(box, new_value):
    box.value = new_value
    return box.value


def rebind(box):
    box = Box("new", [])
    return box.value


def add_item(box, item):
    box.items.append(item)
    return len(box.items)


def main():
    b = Box(10, [])
    bump(b)
    print(b.value)
    print(replace_value(b, "x"))
    print(rebind(b))
    print(b.value)
    print(add_item(b, 1))
    print(add_item(b, "two"))
    print(b.items)
    c = Box(0, [])
    bump(c)
    bump(c)
    d = b
    d.value = -5
    print(b.value)
    print(b is d)


main()
