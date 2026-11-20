class Light:
    ORDER = ["red", "green", "yellow"]

    def __init__(self):
        self.state = "red"
        self.changes = 0

    def advance(self) -> str:
        i = Light.ORDER.index(self.state)
        self.state = Light.ORDER[(i + 1) % len(Light.ORDER)]
        self.changes += 1
        return self.state

    def can_go(self) -> bool:
        return self.state == "green"

    def force(self, state: str):
        if state not in Light.ORDER:
            return False
        self.state = state
        return True


def main():
    light = Light()
    print(light.state)
    print(light.can_go())
    print(light.advance())
    print(light.can_go())
    print(light.advance())
    print(light.advance())
    print(light.advance())
    print(light.changes)
    print(light.force("yellow"))
    print(light.force("blue"))
    print(light.force(""))
    print(light.state)
    other = Light()
    print(other.state)
    print(other.changes)
    print(Light.ORDER[-1])


main()
