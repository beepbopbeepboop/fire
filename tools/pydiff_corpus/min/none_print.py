def find(items, target):
    i = 0
    for x in items:
        if x == target:
            return i
        i += 1
    return None

def main():
    print(find([5, 0], 9))
    print(find([5, 0], 5))
    d = {"a": 1}
    print(d.get("zz"))
    x = None
    print(x)
    print([None, 1])
    print([0, 1])
    print(f"{x}")
    print(str(None))
main()
