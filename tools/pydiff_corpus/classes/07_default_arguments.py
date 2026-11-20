class Printer:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def render(self, text, times=1, upper=False, sep=" "):
        out = []
        for _ in range(times):
            s = text.upper() if upper else text
            out.append(self.prefix + s)
        return sep.join(out)

    def count_calls(self, values=None):
        if values is None:
            values = []
        return len(values)


def main():
    p = Printer(">")
    print(p.render("hi"))
    print(p.render("hi", 2))
    print(p.render("hi", 2, True))
    print(p.render("hi", 3, upper=True, sep="|"))
    print(p.render("", 1))
    print(p.render("x", 0))
    print(p.render("x", times=0, sep="-") == "")
    print(p.count_calls())
    print(p.count_calls([1, "a", None]))
    print(p.count_calls([]))
    q = Printer("")
    print(q.render("b", 2, sep=","))


main()
