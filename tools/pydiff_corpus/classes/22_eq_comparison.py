class Money:
    def __init__(self, cents: int, currency: str):
        self.cents = cents
        self.currency = currency

    def __eq__(self, other):
        if not isinstance(other, Money):
            return False
        return self.cents == other.cents and self.currency == other.currency


class Tag:
    def __init__(self, name):
        self.name = name


def main():
    a = Money(150, "usd")
    b = Money(150, "usd")
    c = Money(150, "eur")
    d = Money(-0, "usd")
    e = Money(0, "usd")
    print(a == b)
    print(a == c)
    print(a is b)
    print(a != c)
    print(d == e)
    print(a == 150)
    print(a == None)
    print(Money(0, "") == Money(0, ""))
    t1 = Tag("x")
    t2 = Tag("x")
    print(t1 == t2)
    print(t1 == t1)
    print(t1 is t1)
    print(t1 is t2)
    print([a] == [b])
    print(a in [c, b])


main()
