"""Regression tests for bug:COMPILE_FAIL_Tools_scripts_summarize_stats

A closure FACTORY — a nested `def F(...)` whose body is `def C(...): ...;
return C` — called from inside a compiled generator, e.g. summarize_stats.py's
`calc_histogram_table(k)` passed as `Table(..., calc_histogram_table(k), ...)`.
Before this landed, the call was an unresolved callee and the whole generator
refused. The factory now compiles to a `static` C++ function that returns the
closure boxed as an int64 `MojoBoundMethod` (see `_try_compile_closure_factory`
in mojo/backend_gimple/cpp_async.py).
"""

import os
import subprocess
import tempfile

import gimple_codegen

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_INC = os.path.join(_HERE, 'runtime')

FACTORY_SRC = (
    'class Table:\n'
    '    def __init__(self, title: str, calc, mode: int):\n'
    '        self.title = title; self.calc = calc; self.mode = mode\n'
    '\n'
    'def outer():\n'
    '    def calc_hist(key: int, den: int):\n'
    '        def calc(stats: int) -> int:\n'
    '            return stats * key + den\n'
    '        return calc\n'
    '\n'
    '    def iter_tables(base: int):\n'
    '        for i in range(2):\n'
    '            yield Table("t", calc_hist(i + base, 2), i)\n'
    '\n'
    '    for t in iter_tables(5):\n'
    '        print(t.title, t.mode)\n'
    '\n'
    'outer()\n')

# The closure assigns through `nonlocal`, so it needs a shared cell rather than
# a by-value copy. That is outside the factory model and must stay refused.
NONLOCAL_SRC = (
    'class Table:\n'
    '    def __init__(self, title: str, calc, mode: int):\n'
    '        self.title = title; self.calc = calc; self.mode = mode\n'
    '\n'
    'def outer():\n'
    '    def calc_hist(key: int):\n'
    '        n = 0\n'
    '        def calc(stats: int) -> int:\n'
    '            nonlocal n\n'
    '            n += 1\n'
    '            return stats + key + n\n'
    '        return calc\n'
    '\n'
    '    def iter_tables(base: int):\n'
    '        for i in range(2):\n'
    '            yield Table("t", calc_hist(i + base), i)\n'
    '\n'
    '    for t in iter_tables(5):\n'
    '        print(t.title, t.mode)\n'
    '\n'
    'outer()\n')

# Calls the factory's result directly: `calc_hist(1, 2)(10)`, a call through
# the closure a factory returns (12 = 10 * 1 + 2).
CALL_OF_CALL_SRC = (
    'def t0():\n'
    '    def calc_hist(key: int, den: int):\n'
    '        def calc(stats: int) -> int:\n'
    '            return stats * key + den\n'
    '        return calc\n'
    '    def gen():\n'
    '        yield calc_hist(1, 2)(10)\n'
    '    return next(gen())\n'
    '\n'
    'def main():\n'
    '    print(t0())\n')


def _compile_cpp(src):
    return gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)[1]


def _refusal(src):
    try:
        _compile_cpp(src)
    except RuntimeError as e:
        return str(e)
    return None


def test_generator_closure_factory_compiles_to_static_helper():
    cpp = _compile_cpp(FACTORY_SRC)
    assert ('static int64_t _mojogen_iter_tables_h_calc_hist (int64_t key, int64_t den) {'
            in cpp), cpp
    assert '_mojogen_iter_tables_h_calc_hist((i + base), 2)' in cpp, cpp


def test_generator_closure_factory_cpp_is_valid():
    from build_config import find_gxx
    cpp = _compile_cpp(FACTORY_SRC)
    with tempfile.NamedTemporaryFile('w', suffix='.cpp', delete=False) as f:
        f.write(cpp)
    try:
        r = subprocess.run([find_gxx(), '-std=c++20', '-fsyntax-only',
                            f'-I{_RUNTIME_INC}', f.name],
                           capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr


def test_generator_closure_factory_value_is_callable():
    # The value the factory returns is a live closure: calling it through the
    # runtime's int64 function-value dispatch (`mojo_fnptr_call_1`, the same
    # path a plain function value takes) yields `stats * key + den` for the
    # captured key/den, and each factory call keeps its own captures.
    from build_config import find_gcc, find_gxx
    cpp = _compile_cpp(FACTORY_SRC)
    harness = cpp + (
        '\nextern "C" void Table___init__(Table *t, char *, int64_t calc, int64_t mode)'
        ' { t->calc = calc; t->mode = mode; }\n'
        '#include <cstdio>\n'
        'int main() {\n'
        '    int64_t f1 = _mojogen_iter_tables_h_calc_hist(5, 2);\n'
        '    int64_t f2 = _mojogen_iter_tables_h_calc_hist(3, 4);\n'
        '    printf("%lld %lld\\n", (long long)mojo_fnptr_call_1((void *)(intptr_t)f1, 10),\n'
        '           (long long)mojo_fnptr_call_1((void *)(intptr_t)f2, 10));\n'
        '    return 0;\n'
        '}\n')
    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, 'factory_main.cpp')
        rt_obj = os.path.join(d, 'fire_runtime.o')
        exe_path = os.path.join(d, 'factory_main')
        with open(src_path, 'w') as f:
            f.write(harness)
        # `mojo_bound_method_new` and the registry live in fire_runtime.c.
        r = subprocess.run([find_gcc(), '-O0', '-w', f'-I{_RUNTIME_INC}', '-c',
                            os.path.join(_RUNTIME_INC, 'fire_runtime.c'), '-o', rt_obj],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([find_gxx(), '-std=c++20', '-w', f'-I{_RUNTIME_INC}',
                            src_path, rt_obj, '-o', exe_path],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = subprocess.run([exe_path], capture_output=True, text=True)
    # 10*5+2 and 10*3+4: each factory call keeps its own captured key/den.
    assert out.stdout.strip() == '52 34', out.stdout + out.stderr


def test_closure_factory_with_nonlocal_closure_still_refused():
    msg = _refusal(NONLOCAL_SRC)
    assert msg is not None, 'nonlocal closure factory compiled: a by-value copy is wrong for it'
    assert "unresolved callee 'calc_hist(...)'" in msg, f"unexpected msg: {msg!r}"


def test_closure_factory_call_of_call_compiles():
    # `calc_hist(1, 2)(10)` calls the factory's closure directly, so it goes
    # through the same int64 function-value dispatch as the call above, not a
    # C++ call on the boxed int64 (which would be a hard g++ error).
    cpp = _compile_cpp(CALL_OF_CALL_SRC)
    assert 'mojo_fnptr_call_1((void *)(_mojogen_gen_h_calc_hist(1, 2)), 10);' in cpp, cpp
    from build_config import find_gxx
    with tempfile.NamedTemporaryFile('w', suffix='.cpp', delete=False) as f:
        f.write(cpp)
    try:
        r = subprocess.run([find_gxx(), '-std=c++20', '-fsyntax-only',
                            f'-I{_RUNTIME_INC}', f.name],
                           capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr


# The real summarize_stats.py shape after the closure-factory fix: a generator
# yields a struct whose list field is a LITERAL of struct instances,
# `Section("sec", [Table(...)])`. The struct constructor's extern signature takes
# a `MojoList *` for that parameter, but the argument used to be lowered as a raw
# C++ brace list `{...}`, which is invalid at a pointer-typed argument position.
LIST_OF_STRUCTS_SRC = (
    'class Table:\n'
    '    def __init__(self, title: str, mode: int):\n'
    '        self.title = title; self.mode = mode\n'
    '\n'
    'class Section:\n'
    '    def __init__(self, name: str, tables: list):\n'
    '        self.name = name; self.tables = tables\n'
    '\n'
    'def outer():\n'
    '    def iter_sections(base: int):\n'
    '        for i in range(2):\n'
    '            yield Section("sec", [Table("t", i + base)])\n'
    '\n'
    '    for s in iter_sections(5):\n'
    '        print(s.name)\n'
    '\n'
    'outer()\n')


def test_generator_list_literal_of_structs_ctor_arg_is_valid_cpp():
    # A list literal of struct instances at a struct-constructor argument must
    # lower to a real MojoList* (the same arg convention a compiled-generator
    # call uses), never a raw brace-init list.
    from build_config import find_gxx
    cpp = _compile_cpp(LIST_OF_STRUCTS_SRC)
    assert '{[&]() -> Table *' not in cpp, cpp
    with tempfile.NamedTemporaryFile('w', suffix='.cpp', delete=False) as f:
        f.write(cpp)
    try:
        r = subprocess.run([find_gxx(), '-std=c++20', '-fsyntax-only',
                            f'-I{_RUNTIME_INC}', f.name],
                           capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr


# The closure's RETURN type is a str here. A closure value is modeled as a
# `std::function<int64_t(...)>` (`_CPP_CALLABLE_CTYPE`), so a non-int64 return
# (or a non-int64 parameter, e.g. summarize_stats.py's `calc(stats: Stats) ->
# Rows`) has no typed slot to live in. Until typed callable values land, the
# factory must stay refused with the honest unresolved-callee message. Measured:
# the same body returning `len(...)` (an int) compiles; only the str return
# refuses. When typed callables land, this test flips to a compile check.
STR_RETURN_SRC = (
    'class Table:\n'
    '    def __init__(self, title: str, calc, mode: int):\n'
    '        self.title = title; self.calc = calc; self.mode = mode\n'
    '\n'
    'def outer():\n'
    '    def calc_hist(key: int):\n'
    '        def calc(hist: int) -> str:\n'
    '            return f"<= {hist:,d}"\n'
    '        return calc\n'
    '\n'
    '    def iter_tables(base: int):\n'
    '        for i in range(2):\n'
    '            yield Table("t", calc_hist(i + base), i)\n'
    '\n'
    '    for t in iter_tables(5):\n'
    '        print(t.title, t.mode)\n'
    '\n'
    'outer()\n')


def test_closure_factory_with_non_int64_return_still_refused():
    msg = _refusal(STR_RETURN_SRC)
    assert msg is not None, 'str-returning closure factory compiled: no typed callable slot exists for it'
    assert "unresolved callee 'calc_hist(...)'" in msg, f"unexpected msg: {msg!r}"
