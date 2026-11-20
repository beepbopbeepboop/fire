def parse_pair(text):
    try:
        left, right = text.split(",")
        try:
            a = int(left)
            b = int(right)
            return a // b
        except ValueError:
            print("bad number in", text)
            return None
    except ZeroDivisionError:
        print("zero divisor in", text)
        return "inf"
    except ValueError:
        print("bad pair shape", text)
        return "shape"


def main():
    print(parse_pair("10,2"))
    print(parse_pair("10,x"))
    print(parse_pair("10,0"))
    print(parse_pair("10"))
    print(parse_pair("-9,4"))
    print(parse_pair(",,"))
    print(parse_pair("7,-2"))


main()
