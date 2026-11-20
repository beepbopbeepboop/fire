def find(items, target):
    for item in items:
        if item == target:
            return item
    return None


def main():
    r = find([1, 2, 3], 2)
    print(r is None, r is not None)
    r = find([1, 2, 3], 9)
    print(r is None, r is not None)
    print(repr(find(["", 0], "")))
    print(find(["", 0], 0) is None)
    print(None is None)
    print(None is not None)
    print(0 is None)
    print("" is None)
    print(False is None)
    x = None
    print(x == None)
    print(x is None)
    v = []
    print(v is None)
    print(v is not None)
    y = 0
    print(y is not None and y == 0)


main()
