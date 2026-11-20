def main():
    text = "a'b"
    print(f"{text!r}")
    print(f"{text!s}")
    print(f"{42!r}")
    print(f"{None!r}")
    print(f"{[1, 'two']!r}")
    print(f"{1.5!r:>6}")
    print(f"{'q'!r:^7}")
    print(f"{text!a}")
    print(f"{'é'!a}")
    print(f"{'line\n'!r}")
    print(f"{True!r}")
    print(f"{''!r}")
    print(f"{(1,)!r}")


main()
