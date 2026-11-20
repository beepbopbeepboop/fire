#!/usr/bin/env python3
"""Regression test for generic elaboration recursion diagnostics.

- Direct self-recursion must still be refused with the existing wording.
- Mutually recursive generic instantiation must be refused (not silently
  compiled to a stub that answers 0, and not hang).
- Finite instantiation chains must still build and run.
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FIRE = [sys.executable, os.path.join(ROOT, 'fire.py')]


def _build_and_run(source, *, timeout=600):
    # 600 s, not 120: the FIRST `fire.py build` on a cold tree compiles the
    # runtime and the modules it needs, and was measured at 121 s on this
    # machine (a loaded box with other lanes) against 20-35 s once that cache
    # exists — so a 120 s per-build cap failed the job on first run and passed
    # it on every later one. The suite's own job timeout (3600 s) still bounds
    # a genuine hang, including the four builds this file makes.
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 't.mojo')
        exe = os.path.join(d, 'a.out')
        with open(src, 'w') as f:
            f.write(source)
        p = subprocess.run(
            FIRE + ['build', src, '-o', exe],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        out = p.stdout
        if p.returncode != 0:
            return p.returncode, out, None
        r = subprocess.run(
            [exe],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return 0, out, r


def test_direct_self_recursion_still_refused():
    src = (
        'def self_recursion[i: Int]() -> Int:\n'
        '    var x = self_recursion[i + 1]()\n'
        '    return x\n'
        '\n'
        'def main():\n'
        '    print(self_recursion[0]())\n'
    )
    rc, out, _ = _build_and_run(src)
    assert rc != 0, 'direct self-recursion compiled (expected diagnostic):\n' + out
    assert "self recursive call to 'self_recursion' will cause an infinite loop" in out, out


def test_mutual_recursion_refused():
    src = (
        'def a[i: Int]() -> Int:\n'
        '    return b[i + 1]()\n'
        '\n'
        'def b[i: Int]() -> Int:\n'
        '    return a[i + 1]()\n'
        '\n'
        'def main():\n'
        '    print(a[1]())\n'
    )
    rc, out, _ = _build_and_run(src)
    assert rc != 0, 'mutual recursion compiled (expected diagnostic):\n' + out
    assert ('infinite recursion' in out) or ('self recursive call' in out), out


def test_finite_chain_builds_and_runs():
    # A finite generic instantiation chain must still build and run.
    src = (
        'def b() -> Int:\n'
        '    return 7\n'
        '\n'
        'def a[i: Int]() -> Int:\n'
        '    return b()\n'
        '\n'
        'def main():\n'
        '    print(a[1]())\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'finite chain failed to build:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)
    assert r.stdout.strip() == '7', r.stdout


def test_finite_chain_few_levels_deep_builds():
    # Finite instantiations a few levels deep, below the recursion cap, build.
    src = (
        'def c[i: Int]() -> Int:\n'
        '    return 5\n'
        '\n'
        'def b[i: Int]() -> Int:\n'
        '    return c[1]()\n'
        '\n'
        'def a[i: Int]() -> Int:\n'
        '    return b[1]()\n'
        '\n'
        'def main():\n'
        '    print(a[1]())\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'finite chain (few levels) failed to build:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)


def test_intrinsic_name_bracket_arg_builds():
    # The measured stdlib shape this refusal must NOT catch: a comptime VALUE
    # bracket argument (the intrinsic's name) plus a `type_of(...)` type
    # argument, inside a concrete instantiation. Before the fix the "not a
    # concrete type" test refused `llvm_intrinsic["llvm.sin", type_of(x)]`,
    # `_llvm_unary_fn["llvm.sqrt"]`, `_truncate[.uint32]` and 23 real stdlib
    # files with it. The shipped lowering is the documented stub.
    src = (
        'def intrinsic[name: StaticString](x: Int) -> Int:\n'
        '    return 0\n'
        '\n'
        'def taker[T: AnyType](x: Int) -> Int:\n'
        '    return 0\n'
        '\n'
        'def helper[w: Int](x: Int) -> Int:\n'
        '    var a = intrinsic["llvm.sin"](x)\n'
        '    return a + taker[type_of(x)](x)\n'
        '\n'
        'def main():\n'
        '    print(helper[1](3))\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'comptime-value bracket argument refused:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)


def test_string_spelling_bracket_arg_builds():
    # `instruction + " $0, $1;"` is the inlined-assembly name idiom: a string
    # expression, fixed once its operand is, not a progressing index. It is a
    # BinaryOp, so the arithmetic-shape test alone would refuse it.
    src = (
        'def asmish[text: StaticString](x: Int) -> Int:\n'
        '    return 0\n'
        '\n'
        'def wrapper[w: Int](x: Int) -> Int:\n'
        '    return asmish["mov" + " $0, $1;"](x)\n'
        '\n'
        'def main():\n'
        '    print(wrapper[1](3))\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'string-spelling bracket argument refused:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)


def test_concrete_unrenderable_type_arg_is_not_refused():
    # The refusal is for an argument that can recurse without bound (`i + 1`,
    # `i * 2`): a bracketed generic call inside an elaborated instantiation
    # whose bracket argument PROGRESSES is an unbounded instantiation. A string
    # literal and a `.uint32` dot-value are fixed comptime data, so the call must
    # NOT be refused, and it must be MATERIALIZED, not stubbed to 0:
    # std/math/math.mojo's `llvm_intrinsic["llvm.*", ...]` and
    # std/builtin/_format_float.mojo's `_truncate[.uint32](...)`. The callees add
    # distinct constants, so a stub (0) or a swapped call cannot give the answer:
    # tag["abc"](5) = 105, ident[.uint32](5) = 15, plus i = 1 -> 121.
    src = (
        'def tag[s: StaticString](x: Int) -> Int:\n'
        '    return x + 100\n'
        '\n'
        'def ident[dt: DType](x: Int) -> Int:\n'
        '    return x + 10\n'
        '\n'
        'def wrap[i: Int](x: Int) -> Int:\n'
        '    return tag["abc"](x) + ident[.uint32](x) + i\n'
        '\n'
        'def main():\n'
        '    print(wrap[1](5))\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'concrete unrenderable type argument was refused:\n' + out
    assert 'will cause an infinite loop' not in out and 'cannot materialize' not in out, out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)
    assert r.stdout.strip() == '121', r.stdout


def test_nested_bracketed_call_in_instantiation_is_materialized():
    # The nested-bracket stub bug (fixed; its doc is deleted): `ident[7](x)`
    # inside the elaborated body of `wrap[1]` used to stub to `(int64_t)0`, so
    # the program printed 1 (ident[7](5) = 12, plus i = 1 -> 13 expected). The
    # nested call is a generic VALUE-parameter instantiation, which the in-TU
    # pass refuses by design, so it takes the `.o` route, and that route's
    # isolated unit must be able to see `ident` and link its object.
    src = (
        'def ident[n: Int](x: Int) -> Int:\n'
        '    return x + n\n'
        '\n'
        'def wrap[i: Int](x: Int) -> Int:\n'
        '    return ident[7](x) + i\n'
        '\n'
        'def main():\n'
        '    print(wrap[1](5))\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'nested bracketed call failed to build:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)
    assert r.stdout.strip() == '13', r.stdout


def test_nested_bracketed_calls_two_levels_and_shared_callee():
    # The same mechanism one level further down: `top` elaborates `mid`, and
    # `mid` elaborates `ident`, so `ident`'s object reaches the final link
    # through two isolated units. `top` also calls `ident[7]` itself, so the
    # one callee object is linked by two different parents.
    #   mid[2](5) = ident[7](5) * 2 = 24, ident[7](5) = 12, i = 1 -> 37
    src = (
        'def ident[n: Int](x: Int) -> Int:\n'
        '    return x + n\n'
        '\n'
        'def mid[k: Int](x: Int) -> Int:\n'
        '    return ident[7](x) * k\n'
        '\n'
        'def top[i: Int](x: Int) -> Int:\n'
        '    return mid[2](x) + ident[7](x) + i\n'
        '\n'
        'def main():\n'
        '    print(top[1](5))\n'
    )
    rc, out, r = _build_and_run(src)
    assert rc == 0, 'two-level nested calls failed to build:\n' + out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)
    assert r.stdout.strip() == '37', r.stdout


def test_generic_instance_sees_its_home_modules_imports():
    # An elaborated generic FUNCTION is its own compilation unit. It used to see none of
    # the imports of the module that wrote it, so `rand(p)` in the body below bound to
    # the C library's `rand()` ("too many arguments to function 'rand'"), the link-mode
    # build threw, `fire.py build` swallowed it and fell back to the inline whole-closure
    # compile of std.random (60 levels deep; 15+ minutes and 7 GB). The instance now
    # gets the imports it calls plainly, so the build stays in link mode and finishes.
    src = (
        'from std.random import rand\n'
        '\n'
        'def fill_it[dtype: DType, name: StaticString](size: Int) raises:\n'
        '    var p = List(length=size, fill=Scalar[dtype](0))\n'
        '    rand(p)\n'
        '    print(name, size)\n'
        '\n'
        'def main() raises:\n'
        '    fill_it[.int8, "int8"](300)\n'
    )
    rc, out, r = _build_and_run(src, timeout=1500)
    assert rc == 0, 'generic instance calling an imported function failed to build:\n' + out
    assert 'cannot compile in-process' not in out, 'fell back to the inline path:\n' + out
    assert 'too many arguments to function' not in out, out
    assert r is not None and r.returncode == 0, (out, None if r is None else r.stdout)
    assert 'int8 300' in r.stdout, r.stdout


if __name__ == '__main__':
    tests = [
        test_direct_self_recursion_still_refused,
        test_mutual_recursion_refused,
        test_finite_chain_builds_and_runs,
        test_finite_chain_few_levels_deep_builds,
        test_intrinsic_name_bracket_arg_builds,
        test_string_spelling_bracket_arg_builds,
        test_concrete_unrenderable_type_arg_is_not_refused,
        test_nested_bracketed_call_in_instantiation_is_materialized,
        test_nested_bracketed_calls_two_levels_and_shared_callee,
        test_generic_instance_sees_its_home_modules_imports,
    ]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('all passed')
