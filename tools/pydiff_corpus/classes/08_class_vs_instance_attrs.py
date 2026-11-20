class Config:
    MAX_SIZE = 100
    NAME = "config"

    def __init__(self, size: int):
        self.size = size

    def limit_left(self):
        return Config.MAX_SIZE - self.size

    def is_full(self) -> bool:
        return self.size >= self.MAX_SIZE


def main():
    a = Config(10)
    b = Config(100)
    print(Config.MAX_SIZE)
    print(a.MAX_SIZE)
    print(a.size)
    print(b.size)
    print(a.limit_left())
    print(b.limit_left())
    print(a.is_full())
    print(b.is_full())
    print(Config.NAME)
    print(b.NAME)
    a.size = 0
    print(a.size)
    print(a.limit_left())
    print(Config(-5).limit_left())
    print(Config(0).is_full())


main()
