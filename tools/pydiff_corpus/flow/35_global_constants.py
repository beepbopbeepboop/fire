LIMIT = 10
GREETING = "hello"
SCALE = 2.5
FLAGS = [True, False]
EMPTY = ""
NOTHING = None


def within(x: int) -> bool:
    return x <= LIMIT


def shout() -> str:
    return GREETING.upper() + "!"


def scaled(n):
    return n * SCALE


def read_flags() -> bool:
    return FLAGS[0] and not FLAGS[1]


def main():
    print(within(3), within(10), within(11))
    print(shout())
    print(scaled(4), scaled(0))
    print(read_flags())
    print(EMPTY or "fallback")
    print(NOTHING is None)
    print(LIMIT + len(GREETING))
    print(FLAGS)
    print(-LIMIT, LIMIT // 3, LIMIT % 3)


main()
