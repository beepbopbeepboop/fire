#!/usr/bin/env python3
"""Pin: in the PER-FILE (`do_imports=False`) compile -- the shape the
bootstrap `--dump` stages use -- a bare `from helper import CONST` must read
the defining module's value when `helper.py` declares it with an UNANNOTATED
scalar literal (`CONST = 41`).

Before the fix, `module_loader._ml_py_global_ctype` answered '' for every
unannotated RHS except a whole-RHS plain string literal or a whole-RHS call to
a same-file `def`, so `CONST = 41` wrote no export entry and the importer kept
its "undeclared -> 0" placeholder:

    _t1 = (int64_t)0;  /* ct param or undeclared: CONST */

-- a silent wrong answer (prints 0 where CPython prints 41), while the SAME
fixture with `CONST: int = 41` printed 41 and `NAME = 'x'` already worked.
The root cause is the classifier, not the export plumbing: the defining
module already types an unannotated int literal `int` (`_gscan_declare_global`'s
IntLiteral row) and already emits `int helper__mojo_global_get_CONST (void)`.

Each case below is built the way `build_stdlib_dylib.compile_module_to_c`
builds one dylib module (its own translation unit, no entry points), linked
against `runtime/fire_runtime.c`, RUN, and its stdout compared with CPython on
the same two files. The unannotated int case also asserts the importer's C
reads the defining module's accessor (so a "fix" that merely guesses the value
would not pass), and the annotated int/float/str and unannotated str cases are
here so the classifier cannot regress the shapes that already worked.

The arithmetic RHS (`N = 40 + 1`) is deliberately NOT asserted: deciding it
needs constant folding the text scanner does not do, and it stays open (the
same silent-0 gap, recorded in the planner doc).

Run: python3 tools/memslot.py --gb 8 --label imported-global-unannotated -- \
         python3 test_codegen_imported_global_unannotated_scalar.py
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import module_loader  # noqa: E402
from build_config import find_gcc  # noqa: E402
from build_stdlib_dylib import compile_module_to_c  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402

RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')
ENTRY_SRC = 'int main(void) { return 0; }\n'

# name -> (helper.py, main.py, expected stdout, importer accessor to require)
CASES = {
    # The bug: unannotated integer literal, imported by name.
    'unannotated_int': (
        'CONST = 41\n',
        'from helper import CONST\nprint(CONST)\n',
        '41\n',
        'helper__mojo_global_get_CONST',
    ),
    # The same gap for the other literal shapes the definer's own
    # `_gscan_declare_global` rows type (`double` / `int`), so a later reader
    # of this file does not have to rediscover them.
    'unannotated_float': (
        'PI = 3.5\n',
        'from helper import PI\nprint(PI)\n',
        '3.5\n',
        'helper__mojo_global_get_PI',
    ),
    # Measured-green before the fix; kept so the new literal rows cannot
    # regress the string path they replace.
    'unannotated_str': (
        "NAME = 'x'\n",
        'from helper import NAME\nprint(NAME)\n',
        'x\n',
        'helper__mojo_global_get_NAME',
    ),
    # A bool global: the accessor is a C `int`, but the imported VALUE must
    # print as CPython's True/False (the importer's `print` reads the export's
    # `py_bool` bit, not the accessor's C type), both the unannotated and the
    # annotated spelling, both polarities.
    'unannotated_bool': (
        'FLAG = True\nOFF = False\n',
        'from helper import FLAG, OFF\nprint(FLAG)\nprint(OFF)\n',
        'True\nFalse\n',
        'helper__mojo_global_get_FLAG',
    ),
    'annotated_bool': (
        'FLAG: bool = True\nOFF: bool = False\n',
        'from helper import FLAG, OFF\nprint(FLAG)\nprint(OFF)\n'
        'print(FLAG == True)\n',
        'True\nFalse\nTrue\n',
        'helper__mojo_global_get_FLAG',
    ),
    # The annotated forms the planner doc measured green.
    'annotated_scalars': (
        "CONST: int = 41\nRATIO: float = 1.5\nLABEL: str = 'tag'\n",
        'from helper import CONST, RATIO, LABEL\n'
        'print(CONST)\nprint(RATIO)\nprint(LABEL)\n',
        '41\n1.5\ntag\n',
        'helper__mojo_global_get_CONST',
    ),
}


def _write(td: str, rel: str, src: str) -> str:
    path = os.path.join(td, rel)
    with open(path, 'w') as f:
        f.write(src)
    return path


def _cpython_stdout(td: str, entry: str) -> str:
    env = dict(os.environ)
    env['PYTHONPATH'] = td + (os.pathsep + env['PYTHONPATH']
                              if env.get('PYTHONPATH') else '')
    r = subprocess.run([sys.executable, entry], capture_output=True, text=True,
                       cwd=td, env=env, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _run_case(name: str, helper_src: str, main_src: str, want: str,
              accessor: str) -> None:
    gcc = find_gcc()
    with tempfile.TemporaryDirectory() as td:
        helper_path = _write(td, 'helper.py', helper_src)
        main_path = _write(td, 'main.py', main_src)
        # Oracle: the fixture itself must be a valid program, or a compile
        # refusal below would be a harness mistake rather than a compiler bug.
        assert _cpython_stdout(td, main_path) == want, f'[{name}] fixture'

        objs = []
        main_c = ''
        for module, src, path in (('helper', helper_src, helper_path),
                                  ('main', main_src, main_path)):
            c_text = compile_module_to_c(src, path, module)
            assert c_text.strip(), f'[{name}] compile_module_to_c({module}) empty'
            if module == 'main':
                main_c = c_text
            c_file = os.path.join(td, module + '.gen.c')
            with open(c_file, 'w') as f:
                f.write(c_text)
            obj = c_file + '.o'
            r = subprocess.run([gcc, '-fgimple', f'-I{RUNTIME_DIR}', '-c',
                                c_file, '-o', obj],
                               capture_output=True, text=True,
                               timeout=COMPILE_TIMEOUT_S)
            assert r.returncode == 0, (
                f'[{name}] gcc -fgimple rejected {module}.py:\n'
                f'{r.stderr[:2000]}\n---\n{c_text}')
            objs.append(obj)

        # The defect's C signature: the importer must dereference the name
        # through the DEFINING module's accessor, not keep the placeholder
        # the undeclared-name fallback writes.
        assert accessor in main_c, (
            f'[{name}] the importer\'s C never names {accessor}:\n{main_c}')
        bare = accessor.split('__mojo_global_get_', 1)[1]
        assert 'ct param or undeclared: ' + bare not in main_c, (
            f'[{name}] {bare} is still read as an undeclared name:\n{main_c}')

        entry_c = _write(td, 'entry.c', ENTRY_SRC)
        exe = os.path.join(td, 'prog')
        r = subprocess.run([gcc, '-o', exe, *objs, entry_c, RUNTIME_C],
                           capture_output=True, text=True,
                           timeout=COMPILE_TIMEOUT_S)
        assert r.returncode == 0, (
            f'[{name}] link failed (the importer\'s extern and the definer\'s '
            f'accessor disagree):\n{r.stderr[:2000]}')
        r = subprocess.run([exe], capture_output=True, text=True,
                           timeout=RUN_TIMEOUT_S)
        assert r.returncode == 0, (name, r.returncode, r.stdout, r.stderr)
        assert r.stdout == want, (
            f'[{name}] the built program printed {r.stdout!r}; CPython '
            f'printed {want!r}')


def test_unannotated_scalar_globals_read_the_definers_accessor():
    for name, (helper_src, main_src, want, accessor) in CASES.items():
        _run_case(name, helper_src, main_src, want, accessor)


def test_classifier_types_every_literal_the_definer_types():
    # The rule at the one place it is decided, with the C types the defining
    # module's accessors really return for the same RHS (measured through
    # `compile_module_to_c` on 2026-11-23: `int` for `41` / `0x29` / `True`,
    # `double` for `1.5` / `1e9`). A sign is NOT a literal here: the definer
    # types `-41` from `_quick_type` as `int64_t`, so claiming `int` for it
    # would make the importer's extern disagree with the accessor.
    for rhs in ('41', '0', '1_000', '0x29', '0o17', '0b101', 'True', 'False'):
        assert module_loader._ml_py_literal_ctype(rhs) == 'int', rhs
    # The C `int` boundary, decided by VALUE the way the defining module
    # decides it (measured 2026-11-23 through compile_module_to_c): the
    # literal is a signed 64-bit word, so values above 2147483647 (and 2^64
    # wraparounds that land back inside the range) widen to `int64_t`.
    for rhs in ('2147483647', '0x7fffffff', '0o17777777777',
                '0b1111111111111111111111111111111', '0xffffffffffffffff',
                '18446744073709551615', '0xffffffff80000000'):
        assert module_loader._ml_py_literal_ctype(rhs) == 'int', rhs
    for rhs in ('2147483648', '0x80000000', '0x8000000000000000',
                '0xffffffff7fffffff', '1000000000000000000000000000000'):
        assert module_loader._ml_py_literal_ctype(rhs) == 'int64_t', rhs
    for rhs in ('3.5', '.5', '1.', '1e9', '1.5e-3'):
        assert module_loader._ml_py_literal_ctype(rhs) == 'double', rhs
    assert module_loader._ml_py_literal_ctype("'x'") == 'char *'
    for rhs in ('-41', '+41', '-1.5', '40 + 1', '1e', '1j', '1_', '_1',
                "'a' + b", 'true', 'CONST'):
        assert module_loader._ml_py_literal_ctype(rhs) == '', rhs
    # And through the export rule itself: an unannotated literal is typed by
    # its own shape; an annotation still decides alone.
    assert module_loader._ml_py_global_ctype('', '41', {}) == 'int'
    assert module_loader._ml_py_global_ctype('', '3.5', {}) == 'double'
    assert module_loader._ml_py_global_ctype('', "True", {}) == 'int'
    assert module_loader._ml_py_global_ctype('bool', 'True', {}) == 'int'
    assert module_loader._ml_py_global_ctype('str', "'x'", {}) == 'char *'


def test_augmented_reassignment_withholds_the_export():
    # `A = 9` then `A /= 2` makes the defining module's accessor `double`
    # (measured through compile_module_to_c: its
    # `_phase17_apply_augmented_global_types` widens AFTER the literal row;
    # `C = 3; C += 1` comes out `int64_t`, and the ANNOTATED `A: int = 9;
    # A /= 2` comes out `double` too). No export is better than an `int`
    # extern that reads a double register as an int: the unexported read keeps
    # the old stub, a wrong extern reads garbage. The widening itself is
    # recorded as bugs/CODEGEN_augmented_global_import_type.md.
    import module_loader as ml
    assert ml._ml_augmented_assign_target('A /= 2') == 'A'
    assert ml._ml_augmented_assign_target('    B //= 3') == 'B'
    assert ml._ml_augmented_assign_target('C >>= 1') == 'C'
    assert ml._ml_augmented_assign_target('D @= m') == 'D'
    # Not augmented assignments: plain, comparison, comment, string, arg.
    assert ml._ml_augmented_assign_target('E = 1') == ''
    assert ml._ml_augmented_assign_target('E == 1') == ''
    assert ml._ml_augmented_assign_target('# E += 1') == ''
    assert ml._ml_augmented_assign_target('print("E += 1")') == ''

    with tempfile.TemporaryDirectory() as td:
        helper_path = _write(td, 'helper.py', 'A = 9\nA /= 2\n')
        main_path = _write(td, 'main.py', 'from helper import A\nprint(A)\n')
        exports = ml.ModuleLoader().load_module_from_path(helper_path)
        assert 'A' not in exports, exports.get('A')
        main_c = compile_module_to_c(
            'from helper import A\nprint(A)\n', main_path, 'main')
        assert 'extern int helper__mojo_global_get_A' not in main_c, main_c


def test_scalar_lines_inside_a_multiline_string_are_not_exports():
    # A module that embeds a whole generated program in a triple-quoted string
    # carries `LITERAL = 3` on its own column-0 line -- test_formal_x86_64_dylib
    # .py's `BODY_MODULE` is the real instance in this tree. Exporting it
    # declares an accessor the defining module never emits (an undefined
    # symbol at link time), so a delimiter/string-aware scan must skip it while
    # still exporting the real literal after it.
    import module_loader as ml
    with tempfile.TemporaryDirectory() as td:
        gen_path = _write(td, 'gen.py',
                          'BODY = """\nLITERAL = 3\nPI = 1.5\n"""\nREAL = 7\n')
        exports = ml.ModuleLoader().load_module_from_path(gen_path)
        assert 'LITERAL' not in exports, exports.get('LITERAL')
        assert 'PI' not in exports, exports.get('PI')
        assert exports.get('REAL', {}).get('c_return_type') == 'int', exports
        main_path = _write(td, 'main.py',
                           'from gen import LITERAL, REAL\nprint(LITERAL, REAL)\n')
        main_c = compile_module_to_c(
            'from gen import LITERAL, REAL\nprint(LITERAL, REAL)\n',
            main_path, 'main')
        assert 'gen__mojo_global_get_REAL' in main_c, main_c
        assert 'gen__mojo_global_get_LITERAL' not in main_c, main_c


def test_bool_literal_export_is_int_typed_like_the_accessor():
    # `FLAG = True` is exported with the type its definer's accessor returns
    # (`int`), so a truthiness read is right instead of the old silent 0. The
    # bool-ness travels as the export's `py_bool` bit and is what makes the
    # importer's `print` render True (see the bool CASES above, which run it).
    with tempfile.TemporaryDirectory() as td:
        helper_path = _write(td, 'helper.py', 'FLAG = True\n')
        main_path = _write(td, 'main.py',
                           'from helper import FLAG\nprint(FLAG)\n')
        exports = module_loader.ModuleLoader().load_module_from_path(helper_path)
        assert exports.get('FLAG', {}).get('py_bool') is True, exports
        main_c = compile_module_to_c(
            'from helper import FLAG\nprint(FLAG)\n', main_path, 'main')
        assert 'extern int helper__mojo_global_get_FLAG (void);' in main_c, main_c
        assert not re.search(r'ct param or undeclared: FLAG', main_c), main_c


def main() -> int:
    test_unannotated_scalar_globals_read_the_definers_accessor()
    test_classifier_types_every_literal_the_definer_types()
    test_augmented_reassignment_withholds_the_export()
    test_scalar_lines_inside_a_multiline_string_are_not_exports()
    test_bool_literal_export_is_int_typed_like_the_accessor()
    print(f'PASS: an unannotated scalar global imported by name reads the '
          f'defining module\'s value in the per-file compile '
          f'({len(CASES)} programs linked and run, each compared with CPython)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
