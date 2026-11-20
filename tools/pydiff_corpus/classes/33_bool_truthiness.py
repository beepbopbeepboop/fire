class Inbox:
    def __init__(self, messages):
        self.messages = messages

    def __bool__(self):
        return len(self.messages) > 0


class Flag:
    def __init__(self, on: bool):
        self.on = on

    def __bool__(self) -> bool:
        return self.on


def main():
    empty = Inbox([])
    full = Inbox(["hi", ""])
    print(bool(empty))
    print(bool(full))
    print(not empty)
    if empty:
        print("empty has mail")
    else:
        print("empty has no mail")
    print(bool(Flag(True)))
    print(bool(Flag(False)))
    print(Flag(False) or "fallback")
    print(Flag(True) and "yes")
    print(bool(None))
    count = 0
    for box in [empty, full, Flag(False), Flag(True)]:
        if box:
            count += 1
    print(count)


main()
