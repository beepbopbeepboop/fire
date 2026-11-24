"""A method taken as a value from a struct LOCAL (not `self`) inside a generator: the object-based
callable-member thunk of `_cpx_member_expr`.
"""


struct Scaler:
    var k: int

    def helper(self) -> int:
        return self.k * 2


def run(n: int):
    var s = Scaler(3)
    f = s.helper
    for i in range(n):
        yield f() + i


def main():
    for v in run(3):
        print(v)


main()
