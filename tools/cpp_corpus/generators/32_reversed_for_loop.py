"""`for x in reversed(items)` inside a generator body: the reversed-list iteration of `_cpf_named_target_call_iter2`
(the copy, the element declaration, the counted loop and the element read).
"""


def backwards(n: int):
    items = [1, 2, 3]
    for x in reversed(items):
        yield x + n


def main():
    for v in backwards(1):
        print(v)


main()
