"""`and`/`or` whose operands are words or strings inside a generator body: the word-holding
struct of `_cpx_binary_op`'s `or`/`and` arms, and the string `or` with a word left operand.
"""


def pick(words: list[str], n: int):
    for i in range(n):
        w = words[i] or "none"
        count = i or 7
        flag = i and 3
        yield w
        yield count + flag


def main():
    for s in pick(["a", ""], 2):
        print(s)


main()
