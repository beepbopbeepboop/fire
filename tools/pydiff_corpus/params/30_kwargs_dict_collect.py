def configure(name, retries=3, *extra, verbose=False, **options):
    print("name", name, "retries", retries)
    print("extra", len(extra), extra)
    print("verbose", verbose)
    for k in sorted(options.keys()):
        print("opt", k, options[k])
    return len(options)


def main():
    print(configure("a"))
    print(configure("b", 0, verbose=True))
    print(configure("c", 1, 2, 3, mode="fast", level=-1))
    print(configure(name="d", color=None))
    print(configure("e", retries=-2, zero=0, empty=""))
    print(configure("f", verbose=False, z=[]))
    print(configure("g", *[9, 8], **{"x": 1}))


main()
