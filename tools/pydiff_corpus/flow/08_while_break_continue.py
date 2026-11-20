def first_over(limit: int) -> int:
    i = 0
    while True:
        i += 1
        if i * i > limit:
            break
    return i


def sum_odd_until(n: int) -> int:
    total = 0
    k = 0
    while k < n:
        k += 1
        if k % 2 == 0:
            continue
        total += k
    return total


def main():
    print(first_over(10))
    print(first_over(0))
    print(first_over(-5))
    print(sum_odd_until(10))
    print(sum_odd_until(0))
    print(sum_odd_until(-3))
    count = 0
    while count < 100:
        count += 7
        if count > 30:
            break
    print("count", count)
    n = 5
    while n > -4:
        n -= 2
    print("n", n)


main()
