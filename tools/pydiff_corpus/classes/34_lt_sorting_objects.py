class Version:
    def __init__(self, major: int, minor: int, tag: str):
        self.major = major
        self.minor = minor
        self.tag = tag

    def __lt__(self, other):
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        return self.tag < other.tag

    def text(self):
        return str(self.major) + "." + str(self.minor) + self.tag


def main():
    vs = [
        Version(1, 10, ""),
        Version(1, 2, "b"),
        Version(0, 9, ""),
        Version(1, 2, "a"),
        Version(-1, 0, "neg"),
    ]
    ordered = sorted(vs)
    for v in ordered:
        print(v.text())
    print(vs[0].text())
    print(Version(1, 2, "a") < Version(1, 2, "b"))
    print(Version(2, 0, "") < Version(1, 9, "z"))
    print(Version(1, 1, "") < Version(1, 1, ""))
    print(Version(1, 1, "") > Version(1, 1, ""))
    print(min(vs).text())
    print(max(vs).text())
    print(len(ordered))


main()
