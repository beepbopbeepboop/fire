def main():
    s: str = "hello"
    empty: str = ""
    flag: bool = True
    off: bool = False
    nothing = None
    print(f"[{s}]")
    print(f"[{empty}]")
    print(f"[{flag}]")
    print(f"[{off}]")
    print(f"[{nothing}]")
    print(f"{flag and 'yes'}")
    print(f"{off or 'fallback'}")
    print(f"{nothing is None}")
    print(f"{s!r}")
    print(f"{nothing!r}")
    print(f"{off!r}")
    print(f"{s!s}")
    items: list = [s, empty, None, 3]
    print(f"{items}")


main()
