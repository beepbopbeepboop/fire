def build_loop(n: int) -> str:
    out = ""
    for i in range(n):
        out += str(i)
    return out


def build_join(n: int) -> str:
    parts = []
    for i in range(n):
        parts.append(str(i * i))
    return ",".join(parts)


def main():
    print(build_loop(0) == "")
    print(build_loop(1))
    print(build_loop(12))
    print(build_join(0) == "")
    print(build_join(1))
    print(build_join(6))
    acc = ""
    for w in ["a", "", "bc"]:
        acc = acc + w + "."
    print(acc)
    print(len(acc))
    chars = []
    for c in "xyz":
        chars.insert(0, c)
    print("".join(chars))
    print("".join([]) == "")


main()
