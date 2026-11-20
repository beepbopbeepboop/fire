def collect(item, bucket=None):
    if bucket is None:
        bucket = []
    bucket.append(item)
    return bucket


def main():
    print(collect(1))
    print(collect(2))
    first = collect("a", [])
    print(first)
    second = collect("b", ["x", "y"])
    print(second)
    print(len(collect(3, [])))
    print(collect(4, first))
    print(first is collect(5, first))
    print(len(first))
    print(first)


main()
