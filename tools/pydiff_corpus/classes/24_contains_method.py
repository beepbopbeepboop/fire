class Team:
    def __init__(self, members):
        self.members = members

    def __contains__(self, name):
        return name in self.members


class Range:
    def __init__(self, low: int, high: int):
        self.low = low
        self.high = high

    def __contains__(self, value: int) -> bool:
        return self.low <= value < self.high


def main():
    t = Team(["ann", "bob", ""])
    print("ann" in t)
    print("cy" in t)
    print("" in t)
    print("cy" not in t)
    print(None in t)
    e = Team([])
    print("ann" in e)
    r = Range(0, 10)
    print(0 in r)
    print(9 in r)
    print(10 in r)
    print(-1 in r)
    print(5 in Range(5, 5))
    print(3 in Range(-4, -1))
    print(0 in Range(0, 1))


main()
