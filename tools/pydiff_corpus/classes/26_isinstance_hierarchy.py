class Base:
    pass


class Middle(Base):
    pass


class Leaf(Middle):
    pass


class Other:
    pass


def check(obj) -> str:
    if isinstance(obj, Leaf):
        return "leaf"
    if isinstance(obj, Middle):
        return "middle"
    if isinstance(obj, Base):
        return "base"
    return "unrelated"


def main():
    objs = [Base(), Middle(), Leaf(), Other()]
    for o in objs:
        print(check(o))
    print(isinstance(Leaf(), Base))
    print(isinstance(Base(), Leaf))
    print(isinstance(Other(), Base))
    print(isinstance(None, Base))
    print(isinstance(0, Base))
    print(issubclass(Leaf, Base))
    print(issubclass(Base, Leaf))
    print(isinstance(Leaf(), (Other, Middle)))
    print(isinstance("", (int, str)))
    print(isinstance(True, int))


main()
