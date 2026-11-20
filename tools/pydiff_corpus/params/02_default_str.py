def greet(name="world", punct="!"):
    return "hello " + name + punct


def main():
    print(greet())
    print(greet("bob"))
    print(greet(punct="?"))
    print(greet("", "."))
    print(greet("amy", ""))
    print(len(greet("")))
    print(greet(name="zed", punct="..."))
    print(greet("x", punct=""))


main()
