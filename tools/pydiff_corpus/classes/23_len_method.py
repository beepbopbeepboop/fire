class Bag:
    def __init__(self, items):
        self.items = items

    def __len__(self):
        return len(self.items)


class Empty:
    def __len__(self):
        return 0


class Word:
    def __init__(self, text: str):
        self.text = text

    def __len__(self) -> int:
        return len(self.text)


def main():
    b = Bag([1, 2, 3])
    print(len(b))
    print(len(Bag([])))
    print(len(Bag(["", None])))
    print(len(Empty()))
    print(bool(Empty()))
    print(bool(Bag([0])))
    w = Word("hello")
    print(len(w))
    print(len(Word("")))
    print(len(Word("a b")))
    total = 0
    for obj in [b, Word("xy"), Empty()]:
        total += len(obj)
    print(total)
    print(len(b) == len(Bag([9, 9, 9])))
    print(len(Bag(["x"])) - 1)


main()
