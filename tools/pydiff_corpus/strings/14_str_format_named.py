def describe(name: str, age: int) -> str:
    return "{name} is {age} years old".format(name=name, age=age)


def main():
    print(describe("Ann", 30))
    print(describe("", 0))
    print("{x}+{y}={z}".format(x=1, y=2, z=3))
    print("{key}".format(key=None))
    print("{a:>5}|".format(a="r"))
    print("{p:.1f}".format(p=2.25))
    d = {"first": "Jo", "last": "Li"}
    print("{first} {last}".format(**d))
    print("{0[0]} {0[1]}".format(["zero", "one"]))
    print("{o.real}".format(o=5))
    print("{w:{f}}|".format(w="x", f="^5"))
    print("{n} {n}".format(n=-0.0))


main()
