class Oops(Exception):
    pass


def level3(n: int) -> int:
    print("level3 start")
    try:
        if n > 2:
            raise Oops("too deep " + str(n))
        return n
    finally:
        print("level3 finally")


def level2(n: int) -> int:
    try:
        return level3(n + 1)
    finally:
        print("level2 finally")


def level1(n: int) -> int:
    try:
        return level2(n + 1)
    except Oops as e:
        print("level1 caught:", e)
        return -1


def main():
    print(level1(-1))
    print(level1(1))
    print(level1(5))
    try:
        level3(9)
    except Oops:
        print("main caught")
    print("end")


main()
