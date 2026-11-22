#!/usr/bin/env python3
"""Regression test for the unknown-declaration check (unknown_decl_check.py).

A read of a name that nothing in the module, the stdlib prelude or the
builtins binds must be rejected at the use site, in the modular layout
(`file:line:col: error: use of unknown declaration 'NAME'`, the source line,
and a caret run). Every binding form a valid program can use must NOT be
rejected: a false positive here turns a compiling program into a build error.

Pinned against the real compiler (tools/mojo) on
test/mojo-integration/kgen_lsp_check_parse_error.mojo in the modular tree.
"""

import os
import sys
import tempfile

import unknown_decl_check
from fire_compiler import Parser, py_tokenize
from gimple_codegen import compile_to_gimple


def _compile(src):
    tmpdir = os.environ.get("TMPDIR", ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".mojo", dir=tmpdir, delete=False, mode="w"
    ) as f:
        f.write(src)
        fn = f.name
    try:
        return compile_to_gimple(src, do_imports=True, filename=fn)
    finally:
        try:
            os.unlink(fn)
        except OSError:
            pass


def test_unknown_name_reports_modular_layout():
    src = (
        "# header\n"
        "\n"
        "def broken():\n"
        "    var x = this_name_does_not_exist\n"
    )
    try:
        _compile(src)
    except SyntaxError as e:
        msg = str(e)
    else:
        raise AssertionError("expected an unknown-declaration error")
    lines = msg.split("\n")
    assert lines[0].endswith(
        ":4:13: error: use of unknown declaration 'this_name_does_not_exist'"
    ), msg
    assert lines[1] == "    var x = this_name_does_not_exist", msg
    assert lines[2] == " " * 12 + "^" + "~" * 23, msg


def test_every_name_is_reported_in_source_order():
    src = (
        "def f():\n"
        "    var a = first_missing\n"
        "    var b = second_missing\n"
    )
    try:
        _compile(src)
    except SyntaxError as e:
        msg = str(e)
    else:
        raise AssertionError("expected errors")
    assert msg.index("first_missing") < msg.index("second_missing"), msg


def _reads(src):
    """Unknown reads of `src`, from the parsed AST alone (no codegen)."""
    stmts = Parser(py_tokenize(src)).with_filename("t.mojo").parse_module()
    return [n.name for n in unknown_decl_check.unknown_reads(stmts)]


def test_valid_bindings_are_not_reported():
    # Every declaration form a valid module can use must bind its name.
    src = (
        "import os.path\n"
        "from std.math import sqrt as root\n"
        "comptime LIMIT = 4\n"
        "alias Pair = Int\n"
        "struct Box[T: AnyType]:\n"
        "    var value: Self.T\n"
        "    def get(self) -> Self.T:\n"
        "        return self.value\n"
        "def use[N: Int](a: Int, b: Int) -> Int:\n"
        "    var total = 0\n"
        "    var (p, q) = (a, b)\n"
        "    for i, j in range(N):\n"
        "        total += i + j\n"
        "    for k in range(LIMIT):\n"
        "        total += k\n"
        "    with open(\"x\") as fh:\n"
        "        total += 1\n"
        "    try:\n"
        "        total += p\n"
        "    except err:\n"
        "        total += 0\n"
        "    if (w := total) > 0:\n"
        "        total += w\n"
        "    var sq = [m * m for m in range(q)]\n"
        "    total += len(sq) + root(1.0) > 0 and os.path != 0\n"
        "    return total\n"
    )
    assert _reads(src) == [], _reads(src)


def test_string_contents_do_not_bind_a_name():
    src = (
        "def f():\n"
        "    var s = \"ghost_name\"\n"
        "    var t = ghost_name\n"
    )
    assert _reads(src) == ["ghost_name"], _reads(src)


def test_wildcard_import_disables_the_check():
    src = (
        "from std.math import *\n"
        "def f():\n"
        "    var x = sqrt(2.0)\n"
    )
    assert _reads(src) == [], _reads(src)


def test_compiler_builtins_are_not_reported():
    # `conforms_to` is lowered by the compiler and declared by no source
    # file; it must be a known name, or every comptime assert that uses it
    # becomes a build error (regression seen when this check was merged).
    src = (
        "def f[T: AnyType]():\n"
        "    comptime assert conforms_to(T, Copyable), \"no\"\n"
    )
    assert _reads(src) == [], _reads(src)


def test_compile_time_type_builtins_are_not_reported():
    # `type_of(x)` / `__type_of(x)` are compiler-provided compile-time type
    # builtins: the argument is consulted for its STATIC TYPE, no source file
    # declares them, and the compiled path lowers them by name. A bracket
    # argument is where this went wrong: `taker[type_of(x)]` was refused as
    # "use of unknown declaration 'type_of'" before elaboration (the bug was
    # found while landing CODEGEN_nested_bracket_generic_call_stubs_to_zero).
    src = (
        "def taker[T: AnyType](x: Int) -> Int:\n"
        "    return 0\n"
        "def helper[w: Int](x: Int) -> Int:\n"
        "    var a = taker[type_of(x)](x)\n"
        "    var b = taker[__type_of(x)](x)\n"
        "    return a + b\n"
    )
    assert _reads(src) == [], _reads(src)


def test_awaitable_protocol_constructors_are_not_reported():
    # `create_future()` / `Future()` / `Event()` are the Awaitable protocol's
    # no-arg constructors; no source file declares them and the compiled path
    # lowers them by name to the `__mojo_future_new` / `__mojo_event_new`
    # shims (mojo/backend_gimple/emit_calls.py, emit_methods.py,
    # mojo/middle/coro.py). The unknown-decl pass landed in 0d277236a
    # whitelisting only `create_future`, and refused the gate's
    # coro-future-await job's bare `Event()` as "use of unknown declaration
    # 'Event'" (job red on master from that commit on).
    src = (
        "import asyncio\n"
        "def f():\n"
        "    var a = create_future()\n"
        "    var b = Future()\n"
        "    var c = Event()\n"
    )
    assert _reads(src) == [], _reads(src)


def test_python_source_names_resolve_lazily():
    # A `.py` file reading an unbound name in code that never runs is valid
    # Python (NameError only if executed); the Mojo diagnostic must not fire.
    src = (
        "def f():\n"
        "    raise NotImplementedError\n"
        "    return ghost_name\n"
    )
    stmts = Parser(py_tokenize(src)).with_filename("t.py").parse_module()
    unknown_decl_check.check_module(stmts, src, "t.py")
    try:
        unknown_decl_check.check_module(stmts, src, "t.mojo")
    except SyntaxError:
        return
    raise AssertionError("the .mojo spelling must still be rejected")


def test_alias_declaration_value_is_not_a_read():
    # `alias LIMIT = some_unknown_name` declares LIMIT; its value is a
    # compile-time expression this pass does not model, so the unknown name in
    # it must NOT be reported. Reporting it made an alias whose value is not
    # foldable a hard error, so a `where` clause consuming it could not stay
    # undecided.
    src = (
        "alias LIMIT = some_unknown_name\n"
        "def f[x: Int]() where x < LIMIT:\n"
        "    pass\n"
    )
    assert _reads(src) == [], _reads(src)


def test_alias_declaration_targets_are_not_reads():
    # A generic alias declares its bracket parameters, which the parser leaves
    # in the subscript's index; a subscript target elsewhere is a mutation of
    # a value read, but in an alias declaration every name is a declaration.
    src = "alias Pair[T] = T\n"
    assert _reads(src) == [], _reads(src)


def test_plain_module_assignment_value_is_still_a_read():
    # The control: only an `alias` declaration is exempt. A plain module-level
    # assignment is an executable read of its value.
    src = "LIMIT = some_unknown_name\n"
    assert _reads(src) == ["some_unknown_name"], _reads(src)


if __name__ == "__main__":
    test_unknown_name_reports_modular_layout()
    test_every_name_is_reported_in_source_order()
    test_valid_bindings_are_not_reported()
    test_string_contents_do_not_bind_a_name()
    test_wildcard_import_disables_the_check()
    test_compiler_builtins_are_not_reported()
    test_compile_time_type_builtins_are_not_reported()
    test_awaitable_protocol_constructors_are_not_reported()
    test_python_source_names_resolve_lazily()
    test_alias_declaration_value_is_not_a_read()
    test_alias_declaration_targets_are_not_reads()
    test_plain_module_assignment_value_is_still_a_read()
    print("ok")
