"""A generator METHOD on a struct: `_gen_cpp_generator_unit`'s struct_name /
receiver path and the `self.base` reads inside the body (`IdentExpr` + the
MemberExpr arm with a struct-typed base).
"""


struct Box:
    var base: int

    def items(self, n: int):
        for i in range(n):
            yield self.base + i


def main():
    var b = Box(10)
    total = 0
    for v in b.items(3):
        total += v
    print(total)


main()
