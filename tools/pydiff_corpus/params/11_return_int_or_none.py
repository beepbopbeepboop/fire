def find_index(items, target):
    i = 0
    for x in items:
        if x == target:
            return i
        i += 1
    return None


def main():
    data = [5, 0, -1, 7, 0]
    print(find_index(data, 5))
    print(find_index(data, 0))
    print(find_index(data, -1))
    print(find_index(data, 99))
    print(find_index([], 1))
    idx = find_index(data, 7)
    if idx is None:
        print("not found")
    else:
        print("found at", idx)
    idx = find_index(data, 42)
    if idx is None:
        print("not found")
    else:
        print("found at", idx)
    print(find_index([False, 0], False))


main()
