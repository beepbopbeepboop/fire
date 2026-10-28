def main():
    d = {}
    k = 3000000000
    d[k] = "big"
    # Later assignment makes k char*; the earlier subscript must not
    # bit-cast 3000000000 to (char*)3000000000.
    k = "3000000000"
    print(d[k])
main()
