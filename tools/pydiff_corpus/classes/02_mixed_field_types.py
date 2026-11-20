class Record:
    def __init__(self, count: int, label: str, tags: list, meta: dict, extra, ok: bool):
        self.count = count
        self.label = label
        self.tags = tags
        self.meta = meta
        self.extra = extra
        self.ok = ok

    def describe(self):
        return self.label + ":" + str(self.count)


def main():
    r = Record(7, "alpha", [1, "two", 3], {"k": 9}, None, True)
    print(r.count)
    print(r.label)
    print(r.tags)
    print(r.meta["k"])
    print(r.extra)
    print(r.ok)
    print(r.describe())
    e = Record(0, "", [], {}, "set", False)
    print(e.count)
    print(repr(e.label))
    print(e.tags)
    print(len(e.meta))
    print(e.extra)
    print(e.ok)
    print(type(e.extra).__name__)
    print(type(r.tags).__name__)


main()
