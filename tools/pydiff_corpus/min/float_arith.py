def main():
    x = 9
    x /= 2
    print(x)
    y = 13
    y += 0.5
    print(y)
    print(7 / 2)
    print(1e-9 > 0)
    if 0.0001:
        print("tiny truthy")
    print(3 == 3.0)
    print(round(2.5), round(3.5))
main()
