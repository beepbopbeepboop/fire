"""
Simple test input for bootstrap verification.
This file will be compiled through all three stages to verify correctness.
"""

def add(x, y):
    return x + y

def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)

def main():
    a = add(2, 3)
    b = factorial(5)
    print(a)
    print(b)

if __name__ == '__main__':
    main()
