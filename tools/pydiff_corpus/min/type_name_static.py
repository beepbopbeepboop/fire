def main():
    print(type(1).__name__, type(1.5).__name__, type("s").__name__, type(True).__name__)
    print(type((1, 2)).__name__, type([1]).__name__, type({1: 2}).__name__, type({1}).__name__, type(None).__name__)
    s = "abc"
    f = 2.5
    b = 1 < 2
    d = {"a": 1}
    print(type(s).__name__, type(f).__name__, type(b).__name__, type(d).__name__)
    print(type(s) == type("x"))
main()
