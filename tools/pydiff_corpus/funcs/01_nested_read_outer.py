def make_greeter(greeting):
    name_suffix = "!"

    def greet(name):
        return greeting + ", " + name + name_suffix

    return greet


def main():
    hello = make_greeter("Hello")
    print(hello("Ada"))
    print(hello(""))
    hi = make_greeter("Hi")
    print(hi("Bob"))
    print(hello("Ada"))
    empty = make_greeter("")
    print(empty("x"))
    print(len(empty("")))
    print(len(hi("")))


main()
