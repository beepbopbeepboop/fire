def half(n):
    return n / 2

def g():
    x = 9
    x /= 2
    return x

def h():
    x = 3.0
    y = x * 0.5
    return y

def main():
    print(half(9))
    x = 9
    x = x / 2
    print(x)
    print(g())
    print(h())
main()
