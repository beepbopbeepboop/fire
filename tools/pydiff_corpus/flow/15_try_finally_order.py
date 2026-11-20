def steps(flag: bool) -> str:
    print("start")
    try:
        print("body")
        if flag:
            return "returned"
        print("after if")
    finally:
        print("cleanup")
    print("end")
    return "fell through"


def nested(n: int):
    try:
        try:
            print("inner try", n)
            return 100 // n
        finally:
            print("inner finally")
    except ZeroDivisionError:
        print("outer caught")
        return -1
    finally:
        print("outer finally")


def main():
    print(steps(True))
    print(steps(False))
    print(nested(4))
    print(nested(0))


main()
