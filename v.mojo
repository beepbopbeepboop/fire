__enum Mistyped(ImplicitlyCopyable, Writable):
    case a
    case b(Int)

    comptime _enum_is_exhaustive = 5


def main():
    var value: Mistyped = .b(1)
    print(value, Mistyped.a)
