def digit_sum(n: int) -> int:
    n = abs(n)
    total = 0
    while n > 0:
        total += n % 10
        n //= 10
    return total


def reverse_digits(n):
    sign = -1 if n < 0 else 1
    n = abs(n)
    rev = 0
    while n:
        rev = rev * 10 + n % 10
        n = n // 10
    return sign * rev


def is_palindrome(text: str) -> bool:
    i = 0
    j = len(text) - 1
    while i < j:
        if text[i] != text[j]:
            return False
        i += 1
        j -= 1
    return True


def main():
    print(digit_sum(0), digit_sum(9051), digit_sum(-123))
    print(reverse_digits(120), reverse_digits(-907), reverse_digits(0))
    print(is_palindrome(""), is_palindrome("a"), is_palindrome("abba"), is_palindrome("abc"))
    print(is_palindrome("ab" * 3))
    print(reverse_digits(digit_sum(99)))
    steps = 0
    n = 27
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    print("collatz steps", steps)
    print("final", n)


main()
