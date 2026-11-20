class Person:
    def __init__(self, name: str):
        self.name = name
        self._age = 0

    def get_age(self) -> int:
        return self._age

    def set_age(self, value: int) -> bool:
        if value < 0 or value > 150:
            return False
        self._age = value
        return True

    def birthday(self):
        return self.set_age(self._age + 1)


def main():
    p = Person("ann")
    print(p.get_age())
    print(p.set_age(30))
    print(p.get_age())
    print(p.set_age(-1))
    print(p.get_age())
    print(p.set_age(151))
    print(p.set_age(150))
    print(p.get_age())
    print(p.birthday())
    print(p.get_age())
    q = Person("")
    print(q.name == "")
    print(q.birthday())
    print(q.get_age())
    print(p.set_age(0))
    print(p.get_age() == 0)


main()
