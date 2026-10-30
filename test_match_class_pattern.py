"""Regression for bug CODEGEN_match_class_pattern: case C(): must be isinstance."""

class Op:
    def __init__(self, n: int):
        self.n = n

def f(x: Op) -> int:
    match x:
        case Op():
            return 1
        case _:
            return 0

print(f(Op(3)))
print(f(3))
