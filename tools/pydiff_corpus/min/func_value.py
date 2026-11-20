def double(x):
    return x * 2

def apply(f, v):
    return f(v)

def main():
    print(apply(double, 5))
    table = {"d": double}
    print(table["d"](4))
    fs = [double, double]
    print(fs[0](3))
    g = double
    print(g(7))
main()
