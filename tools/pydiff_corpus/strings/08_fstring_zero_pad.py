def pad(n: int) -> str:
    return f"{n:03d}"


def main():
    print(pad(5))
    print(pad(42))
    print(pad(1234))
    print(pad(0))
    print(f"{-5:04d}")
    print(f"{7:+d}")
    print(f"{-7:+d}")
    print(f"{7: d}")
    print(f"{3.5:07.2f}")
    print(f"{-3.5:07.2f}")
    print(f"{'7':0>3}")
    print(f"{0:02d}:{5:02d}:{59:02d}")


main()
