"""Regression for bug COMPILE_FAIL_Tools_cases_generator_analyzer: positional
class capture patterns (`case C(x):`) lower as isinstance + getattr + bind.

Both the interpreter (`fire.py run`) and the compiled path (`fire.py build`)
must agree, matching CPython 3.14 semantics."""

class Op:
    __match_args__ = ('n',)
    def __init__(self, n: int):
        self.n = n

def f(x: Op) -> int:
    match x:
        case Op(n):
            return n
        case _:
            return -1

print("Interpreter:", f(Op(3)))
print("not Op:", f(3))
