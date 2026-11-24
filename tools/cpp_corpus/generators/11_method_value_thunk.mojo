"""A struct method used as a VALUE inside a generator (`f = self.helper`, then called): the
callable-member thunk of `_cpx_member_expr`, a std::function over a forwarded call.
"""


struct Scaler:
    var k: int

    def helper(self) -> int:
        return self.k * 2

    def run(self, n: int):
        f = self.helper
        for i in range(n):
            yield f() + i


def main():
    var s = Scaler(4)
    total = 0
    for v in s.run(3):
        total += v
    print(total)


main()
