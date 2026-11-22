"""A generator METHOD on a struct: `_gen_cpp_generator_unit`'s struct_name /
receiver path and the `self.base` reads inside the body (`IdentExpr` + the
MemberExpr arm with a struct-typed base).

Spelled in the Python-parseable forms, on purpose, and each form lowers
byte-identically to the Mojo-only spelling it replaces: the dialect routes the
`struct` and `class` keywords to one StructDef (fire_compiler.py,
`_parse_struct` accepts either) and reads a bare `base: int` as the same
field as `var base: int`, so `class Box:` + `base: int` + `b = Box(10)` is the
same program as `struct Box:` + `var base: int` + `var b = Box(10)` — but
every `.py` in the tree must also parse as Python, and none of the `struct`/
`var` forms do (the AST estate guards in `test_formal_sweep_truth.py` and the
zlib row in `test_refusal_taxonomy.py` walk the whole tree, and a file that
does not parse is a finding, not a skip).
"""


class Box:
    base: int

    def items(self, n: int):
        for i in range(n):
            yield self.base + i


def main():
    b = Box(10)
    total = 0
    for v in b.items(3):
        total += v
    print(total)


main()
