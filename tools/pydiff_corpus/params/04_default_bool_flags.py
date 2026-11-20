def repeat_text(text, times=1, upper=False):
    out = text * times
    if upper:
        out = out.upper()
    return out


def main():
    print(repeat_text("ab"))
    print(repeat_text("ab", 3))
    print(repeat_text("ab", 0))
    print(repeat_text("ab", 2, True))
    print(repeat_text("", 5))
    print(repeat_text("x", upper=True))
    print(repeat_text("x", times=-1))
    print(repeat_text("Mi", 2, upper=False))
    print(repeat_text("q", 1, 0))


main()
