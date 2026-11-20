def get_name(flag):
    if flag == 1:
        return "ann"
    if flag == 2:
        return ""
    return None


def get_count(flag: int) -> int:
    if flag == 1:
        return 5
    if flag == 2:
        return 0
    return -1


def get_items(flag):
    if flag == 1:
        return [1]
    return []


def main():
    for f in [1, 2, 3]:
        print(get_name(f) or "anonymous")
    for f in [1, 2, 3]:
        c = get_count(f)
        print(c or 99)
    for f in [1, 2, 3]:
        print(len(get_items(f) or [0]))
    print(get_count(2) if get_count(2) is not None else "never")
    print(get_name(2) == "")
    print(get_name(3) == "")
    print(bool(get_items(3)))
    print(bool(get_count(3)))


main()
