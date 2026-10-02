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

WHERE the fixture packages are written must not change any verdict. Every
case below except one uses `tempfile.TemporaryDirectory()`, so its location
follows `$TMPDIR` — which on some machines is a directory INSIDE this
checkout and on others is the system temp dir. That used to be enough to
flip `bare_submodule_import_call` from pass to fail, because
`_lower_method_call`'s generic module-qualified-call branch was gated on
"is this file under the compiler's own source directory", so a fixture
written there was refused the resolution and answered a literal `0`. The
gate is now `_is_selfhost_source_file`, which asks whether the file is one
of the compiler's OWN modules rather than merely under its install
directory — but "the other cases happen to run in whichever location
`$TMPDIR` names" is not a guarantee, so
`test_bare_submodule_import_call_inside_source_tree` pins the hard case
explicitly: it builds the same package at a path under this checkout, so
the invariant is tested in BOTH locations no matter how the suite is
invoked.
"""
import os
import shutil
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


def _cpython_run(td: str, entry: str, as_module: bool = False) -> tuple[int, str]:
    """CPython's OWN exit code and stdout for the same file. Every case below
    asserts the compiled program matches THIS, not a hand-written literal — a
    literal here would just be the bug's current wrong answer frozen into the
    test.

    `cwd=td` plus `PYTHONPATH=td`, not `cwd=td` alone: running
    `python3 <td>/p/main.py` puts only `<td>/p` on `sys.path`, so the
    `pkg/__init__.py`-style layouts the compiled pipeline resolves through
    the package root would fail under CPython with `ModuleNotFoundError` and
    the baseline would be empty for exactly the cases that need it. With both
    set, `from p.sub import tri` means the same thing to the two engines.

    `as_module=True` runs `python3 -m <entry>` instead of `python3 <path>`,
    which is the only way a `from . import SUB` baseline can work at all: run
    as a plain script, a relative import has no parent package and CPython
    exits 1 before executing a single statement (`ImportError: attempted
    relative import with no known parent package`). `-m` gives the file the
    package context the compiled pipeline gives it."""
    env = dict(os.environ)
    env['PYTHONPATH'] = (td + os.pathsep + env['PYTHONPATH']
                         if env.get('PYTHONPATH') else td)
    argv = ([sys.executable, '-m', entry[:-3].replace('/', '.')]
            if as_module else [sys.executable, os.path.join(td, entry)])
    result = subprocess.run(argv,
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


def test_bare_submodule_import_call_inside_source_tree() -> bool:
    """`test_bare_submodule_import_call`'s exact package, built at a path
    INSIDE this checkout instead of in `$TMPDIR`.

    This is the case that pinned the flake. `_lower_method_call`'s generic
    module-qualified-call branch was gated on "does the file being compiled
    sit under the compiler's own source directory", so a fixture written
    inside the checkout was denied the resolution and
    `base2.doubleval(21)` fell through to the generic scalar-receiver stub
    as a literal `0` — silently, exit 0, no diagnostic — while the very same
    source built in `/tmp` called the real definition. Every other case in
    this file takes its location from `tempfile.TemporaryDirectory()`, i.e.
    from `$TMPDIR`, so whether the registered `linkmode` step passed was
    decided by the caller's environment rather than by the compiler; two
    workers saw it red in their own fresh worktrees while every integrator
    round was green, with no source difference at all.

    Duplicating the package rather than parameterising the case above is
    deliberate: `_build_and_run` takes the fixture directory as an argument
    already, so a shared helper would hide the one thing this case exists to
    state, which is the directory it runs in.
    """
    pkg = {
        'pkg2/__init__.py': '',
        'pkg2/base2.py': 'def doubleval(x):\n    return x * 2\n',
        'pkg2/main.py': (
            'from . import base2\n'
            'print(base2.doubleval(21))\n'
        ),
    }
    # `build/` is git-ignored; a fixture left behind would be an untracked
    # file in the tree, and `checked_run`'s cache key is content-addressed
    # over `extra` (not over the tree), so a stale directory is exactly the
    # kind of state this case must not depend on. Removed either way.
    root = os.path.join(REPO, 'build', 'test_link_mode')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='inside_source_tree_', dir=root)
    try:
        rc, stdout = _build_and_run(pkg, 'pkg2/main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'pkg2/main.py', as_module=True)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '42')
    if not ok:
        print(f"  ✗ bare_submodule_import_call_inside_source_tree: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
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
# `imports.resolve` can find. These do not: a bare top-level `.py`
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

# The `import insp` sibling of `_INSP_PY`, with a METHOD so the
# module-qualified-constructor case below also exercises a method call
# through a free-function parameter — the shape of
# bugs/hard/CODEGEN_method_call_on_struct_param_mistyped.md's last
# remaining row (that doc is deleted as of this fix; see the 2026-09-30
# section of bugs/hard/README.md).
_LABEL_PY = (
    'class Parameter:\n'
    '    def __init__(self, v, n):\n'
    '        self.v = v\n'
    '        self.n = n\n'
    '    def label(self):\n'
    '        return self.v\n'
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


def test_bare_import_sibling_struct_ctor_through_module() -> bool:
    """`import insp` + `insp.Parameter(...)` — a struct constructed through
    its OWNING MODULE object rather than its bare name — then handed to a
    free function that calls a METHOD on it.

    `_register_link_imports` (mojo/backend_gimple/emit_resolve.py) scanned
    only `FromImportStmt`, so a module reached this way was never a
    candidate for `_link_inline_modules` and never appeared in this
    translation unit at all: the struct had no field table here,
    `_lower_method_call`'s qualified-constructor check had nothing to
    resolve against, and `insp.Parameter('v', 7)` lowered to
    `_t7 = _t2;  /* int64_t.Parameter() stubbed */` — the module HANDLE
    echoed back as the constructed object. `show` then received a literal
    `0` and printed `0`, exit 0, where CPython prints `v`.

    The single sharpest thing about this shape is that the `from` spelling
    of the SAME import already worked: `_compile_two_files_...` aside, the
    byte-for-byte same program with `from insp import Parameter` printed `v`
    through this very pipeline. One mechanism (`_link_inline_modules` +
    `_classify_unresolved_export`), two spellings of one import, one of them
    not wired up. `f3.py` below is the control for exactly that, and it is
    here so this case cannot be "fixed" by regressing the other one.
    """
    pkg = {
        'insp.py': _LABEL_PY,
        'f3.py': (
            'import insp\n'
            '\n'
            'def show(p):\n'
            '    return p.label()\n'
            '\n'
            'def main():\n'
            '    print(show(insp.Parameter(\'v\', 7)))\n'
            '\n'
            'main()\n'
        ),
        'f3b.py': (
            'from insp import Parameter\n'
            '\n'
            'def show(p):\n'
            '    return p.label()\n'
            '\n'
            'def main():\n'
            '    print(show(Parameter(\'v\', 7)))\n'
            '\n'
            'main()\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f3.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f3.py')
        rc2, stdout2 = _build_and_run(pkg, 'f3b.py', td)
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == 'v'
          and rc2 == 0 and stdout2.strip() == 'v')
    if not ok:
        print(f"  ✗ bare_import_sibling_struct_ctor_through_module: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r}) "
              f"| from-import control rc={rc2} stdout={stdout2!r}")
    return ok


def test_bare_import_sibling_struct_field_through_module() -> bool:
    """The same module-qualified construction, but the field is read off
    the result directly instead of through a parameter. A louder symptom
    for the same single cause, and worth its own case because a fix that
    only repaired the parameter-typing half would leave it red: `x.v`
    lowered to `_mojo_dispatch_getattr` on the module handle and raised
    `AttributeError: v`, exit 1.
    """
    pkg = {
        'insp2.py': _LABEL_PY,
        'f4.py': (
            'import insp2\n'
            '\n'
            'def main():\n'
            '    x = insp2.Parameter(\'v\', 7)\n'
            '    print(x.v)\n'
            '\n'
            'main()\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f4.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f4.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == 'v')
    if not ok:
        print(f"  ✗ bare_import_sibling_struct_field_through_module: rc={rc} "
              f"stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_module_scoped_cross_module_struct_ctor_both_import_spellings() -> bool:
    """A cross-module struct CONSTRUCTOR called at MODULE scope, in BOTH
    import spellings, with the field read straight off the result.

    the module-scope cross-module struct constructor (its bug doc is deleted
    by this fix; the mechanism is recorded in the pre-pass's own comment in
    `module_gen.py` and in `bugs/hard/README.md`'s 2026-10-02 entry). Both
    arms printed the `Parameter *`'s own pointer
    bits as a decimal with exit 0, where CPython prints `v`, and the
    function-scoped spelling of the same two lines was correct throughout —
    which is what made it look scope-dependent rather than like a missing set
    of call sites.

    The mechanism, measured in one `compile_linked` dump of the module-scope
    case against the function-scoped one: the cross-module constructor
    FIELD-TYPE hint pre-pass collects its call sites by walking
    `FunctionDef` bodies only, so a module-level `insp.Parameter('v', 7)` was
    in no collected set. With no hint, the IMPORTED module compiled
    `self.v = v` at the `int64_t` default while the client's own `x.v` was
    typed `char *` from the string literal, and the value round-tripped
    through an integer. It was not the import seam (both spellings were
    equally affected, and both are correct inside a function) and not
    module scope alone (the same-file case is correct at module scope).

    Both arms are asserted, and the module-scope `show(...)` variant is in
    `test_module_scoped_cross_module_ctor_arg_through_a_param` — a fix that
    only repaired the direct-field-read spelling would leave that one red.
    """
    pkg = {
        'insp.py': _LABEL_PY,
        'f5.py': (
            'import insp\n'
            '\n'
            'x = insp.Parameter(\'v\', 7)\n'
            'print(x.v)\n'
        ),
        'f5b.py': (
            'from insp import Parameter\n'
            '\n'
            'x = Parameter(\'v\', 7)\n'
            'print(x.v)\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f5.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f5.py')
        rc2, stdout2 = _build_and_run(pkg, 'f5b.py', td)
        py_rc2, py_stdout2 = _cpython_run(td, 'f5b.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and rc2 == 0 and py_rc2 == 0 and stdout2 == py_stdout2
          and stdout.strip() == 'v' and stdout2.strip() == 'v')
    if not ok:
        print(f"  ✗ module_scoped_cross_module_struct_ctor_both_import_spellings: "
              f"bare rc={rc} stdout={stdout!r} (CPython rc={py_rc} "
              f"{py_stdout!r}) | from rc={rc2} stdout={stdout2!r} "
              f"(CPython rc={py_rc2} {py_stdout2!r})")
    return ok


def test_module_scoped_cross_module_ctor_arg_through_a_param() -> bool:
    """The same module-scope construction, but the object is passed to a
    free function that calls a METHOD on it — the shape
    `test_bare_import_sibling_struct_ctor_through_module` covers inside a
    function body, and the one that reached the constructor-field-hint
    pre-pass's *sibling* contract too. Both import spellings again, because
    the missing call sites were in a collector shared by both.

    Without a field-type hint the imported module's `__init__` typed `v`
    `int64_t`, and `show` then received the boxed pointer: `v` came back as a
    decimal address.
    """
    pkg = {
        'insp.py': _LABEL_PY,
        'f6.py': (
            'import insp\n'
            '\n'
            'def show(p):\n'
            '    return p.label()\n'
            '\n'
            'print(show(insp.Parameter(\'v\', 7)))\n'
        ),
        'f6b.py': (
            'from insp import Parameter\n'
            '\n'
            'def show(p):\n'
            '    return p.label()\n'
            '\n'
            'print(show(Parameter(\'v\', 7)))\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'f6.py', td)
        py_rc, py_stdout = _cpython_run(td, 'f6.py')
        rc2, stdout2 = _build_and_run(pkg, 'f6b.py', td)
        py_rc2, py_stdout2 = _cpython_run(td, 'f6b.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and rc2 == 0 and py_rc2 == 0 and stdout2 == py_stdout2
          and stdout.strip() == 'v' and stdout2.strip() == 'v')
    if not ok:
        print(f"  ✗ module_scoped_cross_module_ctor_arg_through_a_param: "
              f"bare rc={rc} stdout={stdout!r} (CPython rc={py_rc} "
              f"{py_stdout!r}) | from rc={rc2} stdout={stdout2!r} "
              f"(CPython rc={py_rc2} {py_stdout2!r})")
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


def test_builtin_open_is_not_ambiguous_from_transitive_siblings() -> bool:
    """A bare `open(...)` that is the BUILTIN must build, even when two
    transitively-imported siblings each define their own `open`.

    `gen_module_impl`'s transitive-discovery loop used to register every
    inlined sibling's top-level FunctionDef names into
    `_own_imported_func_home` as well as into `_imported_func_home`. The
    first of those two is documented as "THIS exact gen_module call's own
    FromImportStmt scan — operating only on `stmts`, never shared across
    temp_gens"; a sibling's *definition* is neither, and colliding two of
    them flipped the key to `_AMBIGUOUS_FUNC_HOME`, which
    `_func_qualifier` turns into a hard refusal for EVERY reference to
    that name in the whole program. Measured on
    `/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`, whose bare
    `open(...)` uses are the builtin and which imports no `open` at all:
    six unrelated siblings (codecs, tokenize, bz2, lzma,
    compression.zstd._zstdfile, tarfile) each define one, and the file's
    OWN compile unit is clean — the whole program was refused by this one
    message. See
    bugs/COMPILE_FAIL_open_is_ambiguous_from_transitive_registrations.md.

    The sibling bodies here PRINT when called, so "the builtin was used"
    is asserted by their absence and not merely by the build succeeding —
    a fix that silently picked one sibling's `open` would otherwise pass.

    `f.read()`'s VALUE is deliberately not asserted: the compiled
    file-read surface is a separate gap from the qualifier resolution
    under test (measured: it answers 0 for both engines' `hello`), and
    freezing today's wrong value here would lock that gap in. What is
    asserted is what this fix is about — the build succeeds, and the
    builtin ran rather than either sibling's shadow."""
    pkg = {
        'q/__init__.py': '',
        'q/data.txt': 'hello\n',
        'q/a.py': ('def open(name, mode="r"):\n'
                   '    print("A_OPEN_CALLED")\n'
                   '    return "A"\n'),
        'q/b.py': ('def open(name, mode="r"):\n'
                   '    print("B_OPEN_CALLED")\n'
                   '    return "B"\n'),
        'q/main.py': (
            'import q.a\n'
            'import q.b\n'
            '\n'
            'def main():\n'
            '    f = open("q/data.txt")\n'
            '    print("OPEN_OK")\n'
            '\n'
            'main()\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'q/main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'q/main.py')
    ok = (rc == 0 and stdout == 'OPEN_OK\n'
          and 'OPEN_CALLED' not in stdout
          and py_rc == 0 and py_stdout == stdout)
    if not ok:
        print(f"  ✗ builtin_open_is_not_ambiguous_from_transitive_siblings: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} "
              f"{py_stdout!r})")
    return ok


def test_unannotated_param_with_disagreeing_call_sites() -> bool:
    """An UNANNOTATED parameter whose call sites disagree on the argument's
    type — here int vs str — used to be typed `char *` and SIGSEGV.

    `module_gen.py`'s Pass 1.3d resolves such a parameter to `char *` /
    `double` when the set of types observed at its call sites is unanimous. It
    observed a `char *` from `f("s")` and NOTHING from `f(1)`: `_arg_scalar_type`
    answers for a float or a string literal and has no answer for an integer
    one. So the set was `{'char *'}` — one *observing* call site, vacuously
    unanimous — and `f(1)`'s silence counted as agreement. The parameter came
    out `char * f(char *)`, `f(1)` passed `(char *)1`, and `mojo_print` strlen'd
    a small integer: exit -11, no output, for a program CPython prints
    `1` / `s`.

    Two defects had to be fixed together, because fixing only the first turns a
    crash into a silent wrong answer: an integer argument must count as an
    observation (`int64_t`), and a slot that is then left at the `int64_t`
    default while provably MAY hold a string needs the runtime's own
    discriminator at the point a C string is required (`mojo_cstr_or_int_str`,
    which asks `mojo_boxed_is_str`). That second half has to follow the value
    wherever it goes, so all four shapes that move it are here: read directly,
    copied to a local, returned and printed at the call site, and returned
    through a forwarding hop.

    **In this file, not `test_gimple_runner.py`, which is where
    `bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md` said
    this belonged.** Measured, and the reason is structural: that runner's
    `compile_to_gimple` is the single-translation-unit path, where the whole-
    program call-site walk never runs and the parameter is left at `int64_t`
    by the default rather than by the bug. All four shapes passed there before
    the fix and after it — a test there could not have failed. This file goes
    through `driver.compile_program`, the pipeline `fire.py build` actually
    uses, and both shapes exit -11 at the parent commit.
    """
    cases = [
        # read directly
        ('def g(x):\n    print(x)\n\n\ng(1)\ng("s")\n', '1\ns\n'),
        # copied to a local first
        ('def h(x):\n    y = x\n    print(y)\n\n\nh(1)\nh("s")\n', '1\ns\n'),
        # returned and printed at the call site
        ('def f(x):\n    return x\n\n\nprint(f(1))\nprint(f("s"))\n', '1\ns\n'),
        # returned through a forwarding hop
        ('def f(x):\n    return x\n\n\ndef g(x):\n    return f(x)\n\n\n'
         'print(g(1))\nprint(g("s"))\n', '1\ns\n'),
    ]
    ok = True
    for i, (src, want) in enumerate(cases):
        with tempfile.TemporaryDirectory() as td:
            rc, stdout = _build_and_run({'prog.py': src}, 'prog.py', td)
            py_rc, py_stdout = _cpython_run(td, 'prog.py')
        if not (rc == 0 and py_rc == 0 and stdout == py_stdout == want):
            ok = False
            print(f"  ✗ unannotated_param_disagreeing_call_sites[{i}]: "
                  f"rc={rc} stdout={stdout!r} "
                  f"(CPython rc={py_rc} {py_stdout!r}, want {want!r})")
    return ok


CASES = [
    test_bare_submodule_import_value_read,
    test_bare_submodule_import_call,
    test_bare_submodule_import_call_inside_source_tree,
    test_from_submodule_import_symbol_value_read,
    test_sibling_function_import_call_is_inlined,
    test_sibling_class_attribute_function_scoped,
    test_sibling_class_attribute_module_scoped,
    test_sibling_class_constructor_field_function_scoped,
    test_bare_import_sibling_struct_ctor_through_module,
    test_bare_import_sibling_struct_field_through_module,
    test_module_scoped_cross_module_struct_ctor_both_import_spellings,
    test_module_scoped_cross_module_ctor_arg_through_a_param,
    test_dotted_sibling_import_qualifier_agrees,
    test_builtin_open_is_not_ambiguous_from_transitive_siblings,
    test_unannotated_param_with_disagreeing_call_sites,
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
