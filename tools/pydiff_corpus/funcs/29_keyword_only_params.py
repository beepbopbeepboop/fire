def make_box(w, *, h=1, label="box"):
    return label + str(w) + "x" + str(h)


def join_all(*parts, sep=" "):
    return sep.join(parts)


def main():
    print(make_box(2))
    print(make_box(2, h=3))
    print(make_box(2, label="b", h=0))
    print(make_box(0, h=-1))
    try:
        make_box(2, 3)
    except TypeError:
        print("TypeError for positional h")
    print(join_all("a", "b"))
    print(join_all("a", "b", sep="-"))
    print(join_all(sep="?"))
    print(join_all("", "", sep=""))
    try:
        join_all("a", "b", "c", sepp="x")
    except TypeError:
        print("TypeError for typo")


main()
