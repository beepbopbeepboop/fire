def find_index(items: list, target: object) -> int:
    for i in range(len(items)):
        if items[i] == target:
            print("found at", i)
            break
    else:
        print("not found")
        return -1
    return i


def main():
    print(find_index([3, 1, 4], 4))
    print(find_index([3, 1, 4], 9))
    print(find_index([], 0))
    print(find_index(["a", 0, None], None))
    for ch in "":
        print("never", ch)
    else:
        print("empty loop else runs")
    for ch in "ab":
        if ch == "z":
            break
    else:
        print("no break for ab")
    for n in [0, 1]:
        if n:
            break
    else:
        print("never breaks")
    print("last n", n)


main()
