def safe_int(s):
    try:
        return int(s)
    except ValueError:
        return -1

def main():
    print(safe_int("12"))
    print(safe_int("x"))
    d = {"a": 1}
    try:
        print(d["zz"])
    except KeyError:
        print("no key")
    try:
        print([1, 2][99])
    except IndexError:
        print("no index")
    try:
        print(1 // 0)
    except ZeroDivisionError:
        print("div zero")
    finally:
        print("finally")
main()
