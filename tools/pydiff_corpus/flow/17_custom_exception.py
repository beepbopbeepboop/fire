class BadInput(Exception):
    pass


class LimitError(Exception):
    def __init__(self, value, limit):
        Exception.__init__(self, "value " + str(value) + " exceeds " + str(limit))
        self.value = value
        self.limit = limit


def check(x: int) -> int:
    if x < 0:
        raise BadInput("negative: " + str(x))
    if x > 100:
        raise LimitError(x, 100)
    return x * 2


def run(x: int):
    try:
        return check(x)
    except BadInput as e:
        print("bad input:", e)
        return None
    except LimitError as e:
        print("limit:", e, e.value, e.limit)
        return -1


def main():
    print(run(5))
    print(run(-3))
    print(run(101))
    print(run(0))
    try:
        raise BadInput("plain")
    except Exception as e:
        print("caught base:", e)
    print("after")


main()
