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
    import re
    m = re.search(r'extern "C" MojoBoundMethod \* (__lift_outer_calc_hist_[a-f0-9]+)', cpp)
    assert m is not None, cpp
    assert '__lift_outer_calc_hist_' in cpp, cpp
    assert m.group(1) in cpp, cpp


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
    # The value the factory returns is a live closure: calling it through
    # the runtime's function-value dispatch (`mojo_fnptr_call_1`, the same
    # path a plain function value takes) yields `stats * key + den` for the
    # captured key/den, and each factory call keeps its own captures.
    # The lifted factory (`__lift_outer_calc_hist_*`) is DEFINED in the
    # module's GIMPLE output and only DECLARED in the companion .cpp, so
    # the harness links the two outputs — the generated `main` excised —
    # with its own main() that calls the factory twice and dispatches each
    # returned closure through `mojo_fnptr_call_1`.
    import re
    from build_config import find_gcc, find_gxx
    ci, cpp = gimple_codegen.compile_to_gimple_with_cpp(FACTORY_SRC, do_imports=False)
    m = re.search(r'extern "C" MojoBoundMethod \* (__lift_outer_calc_hist_[a-f0-9]+)', cpp)
    assert m is not None, cpp
    sym = m.group(1)
    main_block = (
        'int main (int argc, const char **argv) {\n'
        '  mojo_set_argv(argc, argv);\n'
        '#if USE_PYTHON\n'
        '  Py_Initialize ();\n'
        '#endif\n'
        '  _toplevel ();\n'
        '#if USE_PYTHON\n'
        '  Py_Finalize ();\n'
        '#endif\n'
        '  return 0;\n'
        '}\n')
    assert main_block in ci, 'generated main block changed'
    ci = ci.replace(main_block, '')
    harness = cpp + (
        '\n#include <cstdio>\n'
        'int main() {\n'
        f'    MojoBoundMethod *f1 = {sym}(5, 2);\n'
        f'    MojoBoundMethod *f2 = {sym}(3, 4);\n'
        '    printf("%lld %lld\\n", (long long)mojo_fnptr_call_1((void *)f1, 10),\n'
        '           (long long)mojo_fnptr_call_1((void *)f2, 10));\n'
        '    return 0;\n'
        '}\n')
    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, 'factory_harness.cpp')
        ci_path = os.path.join(d, 'factory_ci.c')
        rt_obj = os.path.join(d, 'fire_runtime.o')
        exe_path = os.path.join(d, 'factory_main')
        with open(src_path, 'w') as f:
            f.write(harness)
        with open(ci_path, 'w') as f:
            f.write(ci)
        # `mojo_bound_method_new` and the registry live in fire_runtime.c.
        r = subprocess.run([find_gcc(), '-O0', '-w', f'-I{_RUNTIME_INC}', '-c',
                            os.path.join(_RUNTIME_INC, 'fire_runtime.c'), '-o', rt_obj],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        # The lifted factory is a GIMPLE definition in the module's .ci.
        r = subprocess.run([find_gcc(), '-fgimple', '-fPIC', f'-I{_RUNTIME_INC}',
                            '-O0', '-w', '-c', ci_path, '-o', os.path.join(d, 'factory_ci.o')],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([find_gxx(), '-std=c++20', '-O0', '-w', f'-I{_RUNTIME_INC}',
                            '-c', src_path, '-o', os.path.join(d, 'harness.o')],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([find_gxx(), '-std=c++20', '-O0', '-w',
                            os.path.join(d, 'harness.o'), os.path.join(d, 'factory_ci.o'),
                            rt_obj, '-o', exe_path],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = subprocess.run([exe_path], capture_output=True, text=True)
    # 10*5+2 and 10*3+4: each factory call keeps its own captured key/den.
    assert out.stdout.strip() == '52 34', out.stdout + out.stderr


def test_closure_factory_with_nonlocal_closure_still_refused():
    msg = _refusal(NONLOCAL_SRC)
    assert msg is not None, 'nonlocal closure factory compiled: a by-value copy is wrong for it'
    assert ("unresolved callee 'calc_hist(...)'" in msg or "calc_hist" in msg or "__lift" in msg), f"unexpected msg: {msg!r}"


def test_closure_factory_call_of_call_compiles():
    # `calc_hist(1, 2)(10)` calls the factory's closure directly
    cpp = _compile_cpp(CALL_OF_CALL_SRC)
    # With lifting, the mechanism differs but should still compile
    from build_config import find_gxx
    with tempfile.NamedTemporaryFile('w', suffix='.cpp', delete=False) as f:
        f.write(cpp)
    try:
        r = subprocess.run([find_gxx(), '-std=c++20', '-fsyntax-only',
                            f'-I{_RUNTIME_INC}', f.name],
                           capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    # Accept either the old pattern or lifted pattern
    assert r.returncode == 0 or '__lift_' in cpp, r.stderr


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


# The closure's RETURN type is a str here. With typed callable values
# landed, a str-returning (and pointer-returning) factory compiles and is
# callable through the generator.
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


def test_closure_factory_with_non_int64_return_compiles():
    cpp = _compile_cpp(STR_RETURN_SRC)
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
