"""Regression test for a `var` that redeclares a name bound in an enclosing block.

Mojo makes `var x` inside a block a NEW variable, and a plain `x = ...` is a
rebinding. The compiled path types a Python-style local once per function
(`_declare_var` is first-decl-wins), so before `emit_infra._bind_local_decl`
the inner declaration reused the outer C variable and its type:

    var it = 0                  # int64_t
    if True:
        var it = iter(items)    # MojoList *

became `it = items;` with the outer `int64_t` storage, which gcc rejects. This
is the `test/collections/test_linked_list.mojo` stdlib-syntax red.

The test checks two things: the shadow gets its own C variable (gcc accepts the
file), and the outer binding comes back when the block closes, so a read after
the block still sees the outer variable.
"""
import re

from build_stdlib_dylib import compile_module_to_c
from compile_stdlib import _gcc_syntax_cached


def _c_for(src):
    return compile_module_to_c(src, 'shadow.mojo', 'shadow', linkable=False)


def _gcc_clean(c_src):
    rc, err = _gcc_syntax_cached(c_src)
    assert rc == 0, f"gcc rejected the generated C:\n{err[:1200]}"


def test_redeclared_var_in_block_gets_its_own_storage():
    src = (
        "def f() -> Int:\n"
        "    var items = [1, 2, 3]\n"
        "    var it = 0\n"
        "    if True:\n"
        "        var it = iter(items)\n"
        "        _ = it.__next__()\n"
        "    return it\n"
    )
    c_src = _c_for(src)
    _gcc_clean(c_src)
    assert re.search(r"^  int64_t it;$", c_src, re.M), "the outer `it` was retyped"
    shadow = re.search(r"^  \w+ \* (_shadow\d+_it);$", c_src, re.M)
    assert shadow, "the inner `var it` did not get its own pointer-typed C variable"
    assert re.search(rf"{shadow.group(1)} = \w+;", c_src), (
        "the inner `it` is never assigned through its own variable")


def test_outer_binding_is_restored_after_the_block():
    src = (
        "def f() -> Int:\n"
        "    var x = 1\n"
        "    if True:\n"
        "        var x = String(\"s\")\n"
        "        print(x)\n"
        "    var y = x + 1\n"
        "    return y\n"
    )
    c_src = _c_for(src)
    _gcc_clean(c_src)
    shadow = re.search(r"char \* (_shadow\d+_x);", c_src)
    assert shadow, "the inner `var x` did not get its own C variable"
    # The read AFTER the block must name the outer `int` variable, not the
    # shadow: `x + 1` on the shadow would be a pointer-plus-int.
    assert not re.search(rf"{shadow.group(1)} \+ 1", c_src), (
        "a read after the block still sees the shadowing variable")
    assert re.search(r"= x \+ 1;", c_src), (
        "the read after the block does not name the outer `x`")


def test_each_branch_gets_its_own_shadow():
    src = (
        "def g() -> Int:\n"
        "    var n = 2\n"
        "    if n > 5:\n"
        "        var n = 3.5\n"
        "        print(n)\n"
        "    else:\n"
        "        var n = 7\n"
        "        print(n)\n"
        "    return n\n"
    )
    c_src = _c_for(src)
    _gcc_clean(c_src)
    assert re.search(r"double (_shadow\d+_n);", c_src), "no float shadow of `n`"
    assert re.search(r"int (_shadow\d+_n);", c_src), "no int shadow of `n` in else"
    assert re.search(r"return _t\d+;", c_src)


if __name__ == '__main__':
    test_redeclared_var_in_block_gets_its_own_storage()
    test_outer_binding_is_restored_after_the_block()
    test_each_branch_gets_its_own_shadow()
    print("PASS: block-scoped var redeclaration")
