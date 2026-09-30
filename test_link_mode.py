#!/usr/bin/env python3
"""Link-mode compile guard (`driver.compile_program`).

`compile_stdlib.py`/`build_stdlib_dylib.py` (and by extension
`test_gimple.py`) all drive codegen through the single-translation-unit
`do_imports=False` inline path — NOT the real default `fire.py build`
pipeline, which is link-mode: per-import dylibs + CAS + reflection,
`driver.compile_program`. A bug specific to link-mode's own module/import
registration is invisible to every other gate step. This test exercises
`driver.compile_program` directly against real multi-file packages on
disk, so a regression here can't hide behind the inline-path gate the way
`bugs/COMPILE_FAIL_asyncio_futures.md` did.

Each case builds a real executable via `driver.compile_program` and runs
it, checking both compile success (rc == 0, binary produced) and runtime
correctness (stdout matches). Cases suffixed `_KNOWN_BUG` pin a real,
already-filed, not-yet-fixed defect at its CURRENT (broken) behavior —
see each one's own docstring for the filed bug doc — so this suite still
gives `make check` a meaningful, non-flaky pass/fail signal without
either hiding a known gap or re-discovering it every run.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)


def _build_and_run(pkg_files: dict, entry: str, td: str) -> tuple[int | None, str]:
    """pkg_files: {relative_path: source}. entry: relative path of the file
    to build. Returns (driver.compile_program's rc, the built binary's stdout)."""
    for rel, src in pkg_files.items():
        path = os.path.join(td, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(src)

    import driver
    entry_path = os.path.join(td, entry)
    with open(entry_path) as f:
        entry_src = f.read()

    cwd = os.getcwd()
    os.chdir(td)
    try:
        out = os.path.join(td, 'prog')
        rc = driver.compile_program(entry_path, entry_src, output=out, run=False)
        if rc != 0 or not os.path.exists(out):
            return rc, ''
        result = subprocess.run([out], capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout
    finally:
        os.chdir(cwd)


def _cpython_run(td: str, entry: str) -> tuple[int, str]:
    """CPython's OWN exit code and stdout for the same file. Every case below
    asserts the compiled program matches THIS, not a hand-written literal — a
    literal here would just be the bug's current wrong answer frozen into the
    test.

    `cwd=td` plus `PYTHONPATH=td`, not `cwd=td` alone: running
    `python3 <td>/p/main.py` puts only `<td>/p` on `sys.path`, so the
    `pkg/__init__.py`-style layouts the compiled pipeline resolves through
    the package root would fail under CPython with `ModuleNotFoundError` and
    the baseline would be empty for exactly the cases that need it. With both
    set, `from p.sub import tri` means the same thing to the two engines."""
    env = dict(os.environ)
    env['PYTHONPATH'] = (td + os.pathsep + env['PYTHONPATH']
                         if env.get('PYTHONPATH') else td)
    result = subprocess.run([sys.executable, os.path.join(td, entry)],
                            capture_output=True, text=True, timeout=60,
                            cwd=td, env=env)
    return result.returncode, result.stdout


def test_bare_submodule_import_value_read() -> bool:
    """Regression test for bugs/COMPILE_FAIL_asyncio_futures.md (FIXED,
    commit 94cc04c): a bare `from . import SUBMODULE` marker's own
    top-level function, read later as a plain VALUE (not called) and
    bound to a module-level name — `isfuture = base_futures.isfuture` —
    must resolve through link-mode's own import registration, not just
    the inline do_imports=False path."""
    pkg = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'def isfuture(x):\n    return True\n',
        'pkg/main.py': (
            'from . import base\n'
            'isfuture = base.isfuture\n'
            '\n'
            'def check(x):\n'
            '    if isfuture(x):\n'
            '        print("yes")\n'
            '    else:\n'
            '        print("no")\n'
            '\n'
            'check(1)\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'pkg/main.py', td)
    ok = rc == 0 and stdout.strip() == 'yes'
    if not ok:
        print(f"  ✗ bare_submodule_import_value_read: rc={rc} stdout={stdout!r}")
    return ok


def test_bare_submodule_import_call() -> bool:
    """A CALL through a bare `from . import SUBMODULE` marker
    (`base2.doubleval(21)`, real: `base_futures.isfuture(...)`-shaped
    calls) — used to silently return 0 instead of the real value (see
    bugs/CODEGEN_link_mode_module_qualified_call_silent_wrong_value.md,
    now fixed and removed). A first attempt (2026-08-28, reverted)
    resolved purely by bare method NAME with no module qualification
    and broke self-hosting via a real cross-module collision. The
    landed fix instead registers the call's own syntactically-known
    module reference into `_own_imported_func_home`
    (`_note_own_func_home`, module-qualified) and resolves the C symbol
    through the EXISTING `_func_csym`/`_func_qualifier` tier system —
    the same qualifier-aware machinery an ordinary `from X import f;
    f(...)` call already goes through, which raises on a genuine
    cross-module bare-name collision instead of silently guessing —
    guarded to only fire when the target module's own source
    independently confirms `method_name` is a plain, non-generic,
    non-overloaded top-level function (gimple_gen_methods.py's new
    generic branch in `_lower_method_call`)."""
    pkg = {
        'pkg2/__init__.py': '',
        'pkg2/base2.py': 'def doubleval(x):\n    return x * 2\n',
        'pkg2/main.py': (
            'from . import base2\n'
            'print(base2.doubleval(21))\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'pkg2/main.py', td)
    ok = rc == 0 and stdout.strip() == '42'
    if not ok:
        print(f"  ✗ bare_submodule_import_call: rc={rc} stdout={stdout!r}")
    return ok


def test_from_submodule_import_symbol_value_read() -> bool:
    """`from SUBMODULE import SYMBOL` (not a bare submodule marker), the
    symbol bound to a new local, then called through that local
    (`f = triple; f(14)`) — used to SEGFAULT. Root cause (see
    bugs/CODEGEN_link_mode_from_submodule_import_symbol_value_call_
    segfault.md, now fixed and removed): a leading-dot relative import
    (`from .base3 import triple`) was never resolved by
    `_register_link_imports`'s `_exists()` helper (neither
    `imports.resolve_source` nor `_resolve_test_relative_module` handle
    a leading-dot ref against a `.py` sibling), so `triple` never got
    registered at all and `f = triple` compiled to a bare NULL
    placeholder — calling through it segfaulted. Fixed by wiring
    `_parsed_import`'s cache-fill to fall back to
    `_module_candidate_paths` (the do_imports=True inline path's own,
    already-correct relative-import resolver). A second, independent
    bug surfaced once resolution worked: the module qualifier used for
    the CALL site (`_emit_stdlib_import_externs`'s dot-stripped `base3`)
    disagreed with the qualifier used for the DEFINITION
    (`_link_inline_modules`' raw, dot-preserving `.base3` sanitizing to
    `_base3`) — fixed by stripping leading dots in `_func_qualifier`'s/
    `_struct_method_qualifier`'s `_sanitize_qualifier` and in
    `_note_own_func_home`."""
    pkg = {
        'pkg3/__init__.py': '',
        'pkg3/base3.py': 'def triple(x):\n    return x * 3\n',
        'pkg3/main.py': (
            'from .base3 import triple\n'
            'f = triple\n'
            'print(f(14))\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'pkg3/main.py', td)
    ok = rc == 0 and stdout.strip() == '42'
    if not ok:
        print(f"  ✗ from_submodule_import_symbol_value_read: rc={rc} stdout={stdout!r}")
    return ok


# ── A LOCAL SIBLING that no dylib can satisfy ───────────────────────────────
#
# The three cases above all go through a `pkg/__init__.py` package, which
# `imports.resolve` can find. These four do not: a bare top-level `.py`
# sibling, the shape this compiler's OWN sources are written in, and the
# shape `imports.resolve` returns `(dylib=None, source=None, exports={})`
# for. Nothing about them is function-scoped-only — each one covers both
# spellings of the import, because the root cause was that the module was
# never read on this path at all.
#
# Regression tests for the cross-module-import report's link-mode half,
# which was the last one standing (report now deleted; see the 2026-09-29
# section of bugs/hard/README.md).

_INSP_PY = (
    'class Parameter:\n'
    '    POSITIONAL_ONLY = 1\n'
    '    VAR_POSITIONAL = 2\n'
    '    def __init__(self, name, kind=0):\n'
    '        self.name = name\n'
    '        self.kind = kind\n'
)


def test_sibling_function_import_call_is_inlined() -> bool:
    """A plain top-level function in a dylib-less sibling `.py`, called
    through a FUNCTION-SCOPED `from SIBLING import f`, must call the real
    definition. This is the bug's canonical row: the call used to bind to
    the extern-preamble's `weak` "unavailable in compiled mode" stub, which
    printed `can_colorize: unavailable in compiled mode` INTO THE PROGRAM'S
    OWN STDOUT and then returned 0 — so a harness comparing exit codes saw a
    pass and a harness comparing stdout saw the diagnostic rather than the
    answer.

    Root cause, not a guess: `_register_link_imports._exports` got
    `(exports={}, from_reflection=False, source=None)` because
    `mojo/middle/funcs_shared.py::_parsed_import` could not resolve a bare,
    non-dotted, local `.py` sibling — `imports.resolve_source` only
    understands MOJO_PATH-relative dotted names, and
    `_resolve_test_relative_module` only tries the `.mojo` extension — so
    every `if source:` fallback short-circuited and nothing was registered.
    `_parsed_import` now falls back to `_submodule_source_path`, the very
    resolver `_compile_imported_module` uses for this same name."""
    pkg = {
        '_colorize2.py': 'def can_colorize():\n    return True\n',
        'h1.py': (
            'def f():\n'
            '    from _colorize2 import can_colorize\n'
            '    if can_colorize():\n'
            '        return 1\n'
            '    return 0\n'
            '\n'
            'print(f())\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'h1.py', td)
        py_rc, py_stdout = _cpython_run(td, 'h1.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '1')
    if not ok:
        print(f"  ✗ sibling_function_import_call_is_inlined: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_sibling_class_attribute_function_scoped() -> bool:
    """A CLASS attribute read (`Parameter.VAR_POSITIONAL`) where the import
    is function-scoped. Used to print `0`: with the class never inlined, the
    bare name read as an undeclared identifier (`(int64_t)0`) and the
    attribute went through the dynamic-getattr chain on a null object.
    Exit 0, wrong value, no diagnostic — the worst of the three shapes."""
    pkg = {
        'insp.py': _INSP_PY,
        'f7.py': (
            'def f():\n'
            '    from insp import Parameter\n'
            '    return Parameter.VAR_POSITIONAL\n'
            '\n'
            'print(f())\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f7.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f7.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '2')
    if not ok:
        print(f"  ✗ sibling_class_attribute_function_scoped: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_sibling_class_attribute_module_scoped() -> bool:
    """The MODULE-SCOPED spelling of the identical import, for the same
    `class Parameter:` sibling. This one is what pins the second half of the
    fix: `_register_link_imports`' source-text classifier decided what to do
    with an unresolved imported name, and it knew the `struct X:` and `def
    x(` spellings but not `class X:` — which is a hard keyword to
    `fire_compiler._parse_struct` and produces the very same StructDef. So a
    class matched nothing, the module was never inlined, and this shape was
    broken independently of where the import sat. The classifier is now one
    function (`_classify_unresolved_export`) rather than the two drifting
    copies it was, so there is no second spelling list to fall behind."""
    pkg = {
        'insp.py': _INSP_PY,
        'f5.py': (
            'from insp import Parameter\n'
            '\n'
            'def f():\n'
            '    return Parameter.VAR_POSITIONAL\n'
            '\n'
            'print(f())\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f5.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f5.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '2')
    if not ok:
        print(f"  ✗ sibling_class_attribute_module_scoped: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_sibling_class_constructor_field_function_scoped() -> bool:
    """Constructing the imported class and reading one of its fields, with
    the import function-scoped. Two bugs had to be fixed for this shape and
    one test covers both halves, because the first fix's absence showed up
    here as a hard GIMPLE error rather than a wrong value:

    1. the classifier fix above (without it the module is not inlined and
       the call binds to the `weak` stub), and
    2. the link-mode inline loop must run the SAME cross-module
       constructor-field-hint pre-pass the single-TU path runs. It used to
       be a second, hand-rolled copy of that loop placed after the shared
       one, which skipped the pre-passes entirely — so the defining module
       compiled `self.name = name` with an int64_t default for the
       unannotated `name` param while the struct field was `char *`, and
       GCC rejected the store with "non-trivial conversion in 'var_decl'".
       `gen_module_impl` now has ONE inline-compile loop for both modes.

    `p.name`, not `repr(p)`: a user-defined `__repr__` reached through
    `repr()` on a locally-constructed struct is a separate, import-
    independent bug (reproduces with no imports at all) and asserting it
    here would have made this test assert the wrong thing."""
    pkg = {
        'insp.py': _INSP_PY,
        'f9.py': (
            'def f():\n'
            '    from insp import Parameter\n'
            '    p = Parameter(\'v\', 7)\n'
            '    return p.name\n'
            '\n'
            'print(f())\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f9.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f9.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == 'v')
    if not ok:
        print(f"  ✗ sibling_class_constructor_field_function_scoped: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_dotted_sibling_import_qualifier_agrees() -> bool:
    """`from p.sub import tri` — a DOTTED module name — at MODULE scope, and
    again from inside a function. The mangled symbol's two halves come from
    two different code paths and both must spell the module the same way:
    the DEFINITION's half comes from the inline-compile loop's own module
    key (the import string, `p.sub` -> `p_sub`), and the CALL SITE's half
    from the import-registration pass.

    The call site used to disagree. Module scope fell to
    `_local_sibling_module_exports`' path-derived qualifier — the BASENAME,
    `sub`, because that is what `module_name_for_path` returns for a nested
    file — so the call emitted `sub_tri_<suffix>` against a definition
    emitted as `p_sub_tri_<suffix>`: a hard `implicit declaration of
    function 'sub_tri_...'; did you mean 'p_sub_tri_...'?` on this path, and
    a silent `tri: unavailable in compiled mode` / wrong value on the
    link-mode one. The function-scoped spelling had the same defect for a
    different reason: it mangled `node.module` WITHOUT the
    `lstrip('.')` that every other qualifier-computing site does, so a
    relative `from .sub import tri` inside a function body became
    `_sub_tri_...` (`'_sub'` is a leading underscore plus the module's own
    name) against a definition `sub_tri_...` — a hard implicit-declaration
    error on the single-TU path.

    Both arms of the one condition are asserted, because they are the two
    spellings of the same statement and each was broken in one of them."""
    pkg = {
        'p/__init__.py': '',
        'p/sub.py': 'def tri(x):\n    return x * 3\n',
        'p/main.py': (
            'from p.sub import tri\n'
            '\n'
            'def f():\n'
            '    from p.sub import tri\n'
            '    return tri(14)\n'
            '\n'
            'print(tri(7))\n'
            'print(f())\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'p/main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'p/main.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '21\n42')
    if not ok:
        print(f"  ✗ dotted_sibling_import_qualifier_agrees: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


CASES = [
    test_bare_submodule_import_value_read,
    test_bare_submodule_import_call,
    test_from_submodule_import_symbol_value_read,
    test_sibling_function_import_call_is_inlined,
    test_sibling_class_attribute_function_scoped,
    test_sibling_class_attribute_module_scoped,
    test_sibling_class_constructor_field_function_scoped,
    test_dotted_sibling_import_qualifier_agrees,
]


def main() -> int:
    passed = 0
    failed = 0
    for case in CASES:
        try:
            ok = case()
        except Exception as e:
            print(f"  ✗ {case.__name__} raised: {e}")
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
