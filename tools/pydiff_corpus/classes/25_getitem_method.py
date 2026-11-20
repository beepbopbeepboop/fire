class Pair:
    def __init__(self, first, second):
        self.first = first
        self.second = second

    def __getitem__(self, index):
        if index == 0:
            return self.first
        if index == 1:
            return self.second
        raise IndexError("pair index out of range")


class Shifted:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, i):
        return self.data[i + 1]


def main():
    p = Pair("left", 2)
    print(p[0])
    print(p[1])
    print(p[0] == "left")
    q = Pair(None, "")
    print(q[0] is None)
    print(repr(q[1]))
    s = Shifted([10, 20, 30])
    print(s[0])
    print(s[1])
    print(s[-1 + 1])
    try:
        print(p[2])
    except IndexError:
        print("caught")
    total = 0
    for i in range(2):
        total += 0
    print(total)
    print(len([p[0], p[1]]))


main()
