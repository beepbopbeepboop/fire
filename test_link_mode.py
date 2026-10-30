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
`“COMPILE_FAIL: asyncio/futures.py”` did.

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
    """Regression test for “COMPILE_FAIL: asyncio/futures.py” (FIXED,
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
    “CODEGEN (link-mode): a CALL through an imported module marker”,
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
# CODEGEN_method_call_on_struct_param_mistyped's last
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


def test_bare_import_sibling_function_call_through_module() -> bool:
    """`import SIBLING` + `SIBLING.free_fn(...)` — the FUNCTION reached
    through a bare module marker — the sibling of the two struct cases
    above. `import SIBLING` used to record `imported_symbols['SIBLING']` for
    the MODULE and nothing for its members, so `_func_mangleable` answered
    False for `SIBLING.fn`; the call now registers the member with the
    DEFINING module's own parsed signature
    (`funcs_shared.register_imported_symbol`, shared with
    `_register_link_imports`' three inline table writes).

    The call used to reach the extern preamble's `weak` "unavailable in
    compiled mode" stub, printing `deep_fn: unavailable in compiled
    mode` INTO THE PROGRAM'S OWN STDOUT and then returning 0 — exit 0, a
    wrong answer, and the only diagnostic on the wrong stream.

    It is TWO defects, and fixing either alone leaves it broken, which is
    why the doc recorded a "partial fix that is NOT enough" verbatim:

      * **the module was never inlined.** `_inline_bare_import_struct`
        asked only `_source_defines_struct`, so a bare marker reached
        through a FUNCTION added nothing to `_link_inline_modules` and the
        definition was in neither this translation unit nor any dylib on
        the link line. It now calls the shared `_classify_unresolved_export`
        — the same classifier the `from M import X` spelling uses, which
        already answers for a plain top-level function.
      * **the member was never registered.** `import deep` records
        `imported_symbols['deep']` — for the MODULE, not its members — so
        the re-dispatched bare call found no `imported_symbols['deep_fn']`,
        `_func_mangleable` was False, `_func_csym` produced the bare
        `_safe_name('deep_fn')` with no qualifier and no overload suffix,
        and `_lower_named_call`'s `_is_unknown` branch emitted the stub.
        The call site now registers the member, with the signature from
        the DEFINING module's own parsed FunctionDef
        (`_resolved_export_entry`), because `module_loader`'s text scan
        answers `int64_t deep_fn (void)` for an unannotated
        `def deep_fn(x)` and that, as the only prototype in the file,
        rejects its own call site.

    With only the second half, the call site emits the correctly QUALIFIED,
    overload-suffixed `deep_deep_fn_9f63a2` and the link fails on it
    (`ld: symbol(s) not found`); with only the first, it still calls the
    unqualified stub. Both halves are here, and `from_deep_import_deep_fn`
    below is the control for the `from` spelling.
    """
    pkg = {
        '_deepmod.py': (
            'def deep_fn(x):\n'
            '    return x + 7\n'
            '\n'
            'def other(x):\n'
            '    return x * 100\n'
        ),
        'bimp.py': (
            'import _deepmod\n'
            '\n'
            'def main():\n'
            '    print(_deepmod.deep_fn(1))\n'
            '\n'
            'main()\n'
        ),
        'bimpf.py': (
            'from _deepmod import deep_fn\n'
            '\n'
            'def main():\n'
            '    print(deep_fn(1))\n'
            '\n'
            'main()\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'bimp.py', td)
        py_rc, py_stdout = _cpython_run(td, 'bimp.py')
        rc2, stdout2 = _build_and_run(pkg, 'bimpf.py', td)
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '8'
          and rc2 == 0 and stdout2.strip() == '8')
    if not ok:
        print(f"  ✗ bare_import_sibling_function_call_through_module: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r}) "
              f"| from-import control rc={rc2} stdout={stdout2!r}")
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
    COMPILE_FAIL_open_is_ambiguous_from_transitive_registrations.

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
    `CODEGEN_polymorphic_unannotated_param_vacuous_unanimity` said
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
        # A CONTAINER argument alongside a `char *` one. A container literal at
        # a call site used to contribute no observation at all, so the slot saw
        # `{'char *'}` — unanimous — and `f([1, 2])` stored the list through a
        # `char *` formal, which `mojo_print` then strlen'd over the list
        # HEADER's bytes (`X\n`). The pointer now vetoes the resolution, as for
        # every other disagreeing pair, and the printed value comes back right
        # in both orders.
        ('def f(x):\n    print(x)\n\n\nf("s")\nf([1, 2])\n', 's\n[1, 2]\n'),
        ('def f(x):\n    print(x)\n\n\nf([1, 2])\nf("s")\n', '[1, 2]\ns\n'),
        # A FLOAT beside an INTEGER at the same parameter. The slot stays an
        # int64_t (a double and an int have no common C type), so the float
        # used to be truncated to the integer its bits name: `f(2.5)` printed
        # `2`. The float is now boxed at its call site and the print asks the
        # box, while the plain integer beside it still prints as itself. Both
        # orders, because the slot's answer must not depend on which call
        # comes first.
        ('def f(x):\n    print(x)\n\n\nf(2.5)\nf(1)\n', '2.5\n1\n'),
        ('def f(x):\n    print(x)\n\n\nf(1)\nf(2.5)\n', '1\n2.5\n'),
        # The same float-possible slot FORWARDED into a second function. `g`
        # only ever sees an identifier at its one call site, so its own
        # call-site walk observes no double and nothing marks its parameter;
        # the float has to reach it through `f`'s parameter, which does carry
        # the property. Without the forwarding hop `g(x)` printed the box's
        # address (`4312044272` for `f(2.5)`). Both orders, as above.
        ('def g(x):\n    print(x)\n\n\ndef f(x):\n    g(x)\n\n\n'
         'f(2.5)\nf(1)\n', '2.5\n1\n'),
        ('def g(x):\n    print(x)\n\n\ndef f(x):\n    g(x)\n\n\n'
         'f(1)\nf(2.5)\n', '1\n2.5\n'),
        # `/` on the float-possible slot. Python's true division is always a
        # float for an int or a float operand, so the answer is a double box
        # whichever the parameter holds: `x / 2` was `1` / `0` (the truncated
        # integer quotient) where CPython gives `1.25` / `0.5`. Both orders.
        ('def f(x):\n    print(x / 2)\n\n\nf(2.5)\nf(1)\n', '1.25\n0.5\n'),
        ('def f(x):\n    print(x / 2)\n\n\nf(1)\nf(2.5)\n', '0.5\n1.25\n'),
        # The parameter as the RIGHT operand (the divisor).
        ('def f(x):\n    print(2 / x)\n\n\nf(2.5)\nf(1)\n', '0.8\n2.0\n'),
        # A zero divisor raises ZeroDivisionError (the runtime's
        # `mojo_div_double`), not a SIGFPE and not an `inf` answer.
        ('def f(x):\n    try:\n        print(x / 0)\n    except ZeroDivisionError:\n'
         '        print("zde")\n\n\nf(2.5)\nf(1)\n', 'zde\nzde\n'),
    ]
    # The two pairs that used to be a HARD GCC ERROR and are now only wrong:
    #
    #   prog.py:6:3: error: pointer value used where a floating-point was
    #   expected
    #     6 | f([1, 2])
    #
    # A `double` parameter and a list argument in the same program, so the
    # unanimity contract resolved the slot to `double` and the list's
    # `MojoList *` went to a `double` formal. `float_only` and `list_only` are
    # here too, because the fix is a VETO on a non-scalar observation and the
    # two single-kind programs are what prove it did not disturb either.
    #
    # What is asserted is BUILDABILITY, and deliberately so: the values these
    # print are still wrong (a pointer decimal for the list), which is the
    # runtime-tag row of bug CODEGEN_polymorphic_param_non_str_kinds_print_wrong
    # (the float beside an integer is fixed, in `cases` above). Asserting
    # the wrong text would pin a bug; asserting only that it COMPILES is the
    # whole content of this row, and it was a hard failure before.
    builds_only = [
        'def f(x):\n    print(x)\n\n\nf(2.5)\nf([1, 2])\n',
        'def f(x):\n    print(x)\n\n\nf([1, 2])\nf(2.5)\n',
        'def f(x):\n    print(x)\n\n\nf(2.5)\n',
        'def f(x):\n    print(x)\n\n\nf([1, 2])\n',
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
    for i, src in enumerate(builds_only):
        try:
            with tempfile.TemporaryDirectory() as td:
                rc, _stdout = _build_and_run({'prog.py': src}, 'prog.py', td)
        except Exception as e:
            ok = False
            print(f"  ✗ unannotated_param_container_does_not_break_the_build"
                  f"[{i}]: did not compile: {str(e)[:200]}")
            continue
        if rc != 0:
            ok = False
            print(f"  ✗ unannotated_param_container_does_not_break_the_build"
                  f"[{i}]: compiled but exited {rc}")
    # ARITHMETIC on the float-possible parameter (bug
    # CODEGEN_polymorphic_param_non_str_kinds_print_wrong). `x OP n` with
    # `+`, `-`, `*`, `//`, `%` is answered by `_float_param_arith`: the integer
    # answer when the argument was an integer, and a double box holding the
    # answer when it was a float, picked at run time. Each expectation is the
    # CPython answer, so this pins the real double read, not the old truncation.
    # `print(x)` is pinned by `cases` above. A DOUBLE operand beside the
    # parameter (`x * 2.5`) makes the answer a double whatever the parameter
    # holds, so it is boxed outright: `f(1)` prints `2.5`, not the integer.
    arithmetic = [
        ('def f(x):\n    print(x * 2)\n\n\nf(2.5)\nf(1)\n', '5.0\n2\n'),
        ('def f(x):\n    print(x * 2)\n\n\nf(1)\nf(2.5)\n', '2\n5.0\n'),
        ('def f(x):\n    print(x + 1)\n\n\nf(2.5)\nf(1)\n', '3.5\n2\n'),
        ('def f(x):\n    print(x - 1)\n\n\nf(2.5)\nf(1)\n', '1.5\n0\n'),
        ('def f(x):\n    print(x * 2.5)\n\n\nf(2.5)\nf(1)\n', '6.25\n2.5\n'),
        ('def f(x):\n    print(x * 2.5)\n\n\nf(1)\nf(2.5)\n', '2.5\n6.25\n'),
        ('def f(x):\n    print(2.5 * x)\n\n\nf(2.5)\nf(1)\n', '6.25\n2.5\n'),
        ('def f(x):\n    print(x + 0.5)\n\n\nf(2.5)\nf(1)\n', '3.0\n1.5\n'),
        # `//` and `%`: floor division and modulo, the two remaining float
        # arithmetic arms (`_FLOAT_PARAM_OPS`) beside the float-possible param.
        ('def f(x):\n    print(x // 2)\n\n\nf(2.5)\nf(1)\n', '1.0\n0\n'),
        ('def f(x):\n    print(x % 2)\n\n\nf(2.5)\nf(1)\n', '0.5\n1\n'),
    ]
    for i, (src, want) in enumerate(arithmetic):
        with tempfile.TemporaryDirectory() as td:
            rc, stdout = _build_and_run({'prog.py': src}, 'prog.py', td)
            py_rc, py_stdout = _cpython_run(td, 'prog.py')
        if not (rc == 0 and py_rc == 0 and stdout == py_stdout == want):
            ok = False
            print(f"  ✗ unannotated_param_arithmetic_operand[{i}]: "
                  f"rc={rc} stdout={stdout!r} "
                  f"(CPython rc={py_rc} {py_stdout!r}, want {want!r})")
    return ok


def test_transitive_struct_method_is_not_variadic_stubbed() -> bool:
    """A struct method reached from a TRANSITIVELY imported module must not
    be auto-stubbed as a bare `int64_t f (...)`.

    The auto-stub's guard (`_MOJO_STUB_<Struct>_<method>`) is DEFINED by the
    stub itself, so nothing can suppress it afterwards — and the real
    definition that follows it, emitted by the module that actually owns the
    struct, is then a hard compile failure rather than a wrong answer:

        error: conflicting types for 'lm_helper_Thing_show';
               have 'int64_t(Thing *)'

    Two properties of the fixture are load-bearing and neither is incidental:

    * the struct is defined THREE modules deep, so the root's call site is
      lowered before the defining module is inlined into the same
      translation unit — which is why neither `func_return_types` lookup in
      the auto-stub's condition could have answered "this method WILL be
      defined here", and why the answer had to come from
      `_struct_method_names` instead;
    * the METHOD is a non-dunder one. A dunder goes through a different
      mangling path (`lm_helper_Thing___init__`) and was already fine, so a
      `__init__`-only fixture would have proved nothing about the defect.

    `_build_and_run` raises out of `driver.compile_program` on a gcc failure
    (it does not catch `CalledProcessError`), and `main()` turns that into a
    FAIL for this case — so before the fix this row failed at the COMPILE,
    not on an answer.
    """
    pkg = {
        'lm/__init__.py': '',
        'lm/helper.py': (
            'class Thing:\n'
            '    def __init__(self, value):\n'
            '        self.value = value\n'
            '\n'
            '    def show(self):\n'
            '        return self.value\n'
        ),
        'lm/mid.py': (
            'from lm.helper import Thing\n'
            '\n'
            'def make(n):\n'
            '    return Thing(n)\n'
        ),
        'lm/main.py': (
            'import lm.mid\n'
            '\n'
            'def main():\n'
            '    t = lm.mid.make(7)\n'
            '    print(t.show())\n'
            '\n'
            'main()\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'lm/main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'lm/main.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout == '7\n')
    if not ok:
        print(f"  ✗ transitive_struct_method_is_not_variadic_stubbed: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_failed_import_attempt_does_not_poison_later_spelling() -> bool:
    """A failed imported-module attempt must not poison a later import of
    the same file under a different spelling.

    Measured 2026-10-23 in the c_analyzer/c_parser cluster (non-formal
    campaign, failed-import-attempt poisoning cluster): building
    `Tools/c-analyzer/c_parser/parser/__init__.py` on master, the failed
    `..info` attempt left (a) its guard entries in `_compiling_file_paths`
    (the set is add-only, and the attempt's OWN nested import of
    `c_parser/parser/_regexes.py` planted that file's path), and (b) stale
    spelling-CLAIM knowledge published under the attempt's corpse spelling.
    A later import of `_regexes.py` under the sibling spelling was then
    guard-REFUSED and compiled "with nothing", so `_common.py:50` emitted
    its call under the corpse suffix `parser__regexes__ind_15d274`
    ((int64_t,int64_t,char*)) while the real definition is
    `parser__regexes__ind_0f1876` — implicit declaration plus seven
    dangling toplevels in the generated C (the fixed tree unifies all 35
    `_ind` references on 0f1876; see build/remes/r16fix3.log and
    bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md).

    The fix (mojo/backend_gimple/emit_resolve.py, `_compile_imported_module`
    except handler) snapshots the attempt's guard entries, its
    `_sub_toplevels` tail, and the three spelling-CLAIM registries, and
    discards the attempt's additions on failure. The SIGNATURE registries
    are deliberately NOT rolled back: their values are spelling-isolated,
    and rolling them back measured a NEW error — `conflicting types for
    'info_get_default_storage_9f63a2'` on r13 — because the survivor
    spelling's forward declaration then fell back to int64 instead of the
    char* the failed attempt had inferred.

    This fixture is the minimal mirror. `t/poison.py`'s
    `bad(items: list)` carries the measured `.iterutil` refusal shape
    (`items = iter(items); next(items)` on a receiver typed `MojoList *`
    has no lowering in this codegen) — a DETERMINISTIC content refusal, so
    the attempt fails identically on master and on the fixed tree, and the
    only thing the fix changes is what the failure LEAVES BEHIND.
    `from .shared import S` plants the guard entry on `t/shared.py`
    during the attempt. `t/sub/mod.py` takes S THROUGH poison
    (`from ..poison import S` — a used name is what makes link mode
    attempt the import at all; S still resolves after the failure because
    its home is `t/shared.py`, which compiles fresh under the sibling
    spelling) and `s` from shared under that sibling spelling `..shared`.

    On master the leftover guard entry REFUSES `..shared`, so mod's
    `s("x")` call site emits `implicit declaration of 'shared_s_...'`
    plus `assignment to 'char *' from 'int'` and the build fails with no
    binary. On the fixed tree the attempt rolls its state back, `..shared`
    compiles for real, and the binary prints `s X!` like CPython.
    """
    pkg = {
        't/__init__.py': '',
        't/sub/__init__.py': '',
        't/shared.py': (
            'S = "s"\n'
            '\n'
            '\n'
            'def s(text):\n'
            '    return text.upper() + "!"\n'
        ),
        't/poison.py': (
            'from .shared import S\n'
            '\n'
            '\n'
            'def bad(items: list):\n'
            '    items = iter(items)\n'
            '    return next(items)\n'
        ),
        't/sub/mod.py': (
            'from ..poison import S\n'
            'from ..shared import s\n'
            '\n'
            '\n'
            'def run():\n'
            '    print(S, s("x"))\n'
        ),
        't/__main__.py': (
            'from .sub.mod import run\n'
            '\n'
            '\n'
            'run()\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 't/__main__.py', td)
        py_rc, py_stdout = _cpython_run(td, 't/__main__.py', as_module=True)
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout == 's X!\n')
    if not ok:
        print(f"  ✗ failed_import_attempt_does_not_poison_later_spelling: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_byteorder_conditional_toplevel_emits_only_the_host_branch() -> bool:
    """A top-level `if sys.byteorder == ...:` conditional whose branches
    SWAP a class definition and a plain assignment over the same two names
    (the `ctypes/_endian.py` shape) must resolve to the host's branch at
    emission — neither branch may be left to run time.

    Pre-fix, two defects stacked on this shape. (1) `comptime.eval_const`
    folded `sys.platform` but not `sys.byteorder`, so the top-level
    conditional was unresolvable and BOTH branches emitted; the dead
    branch's plain assignment (`BigEndianStructure = Structure` at
    _endian.py:63) referenced a module global the live branch's `class
    BigEndianStructure` never registers as a lookable member — one gcc
    error on this minimal shape (`'struct _root_toplev' has no member
    named 'BE'; did you mean 'LE'`), the pair at _endian.py:63:27/:70:27
    on the real file (build/remes/r10repro_prefix_765117ff.log,
    build/remes/r10.log). (2) The fold alone was not enough: the emission
    loop then ran the IfStmt as a RUNTIME branch — re-evaluating
    `sys.byteorder` at run time (`_mojo_dispatch_getattr(sys,
    "byteorder")`, an AttributeError: the compiled stdlib's sys has no
    such attribute), degrading the class refs to `(int64_t)0` zero stubs
    and dropping the class defs as `/* TODO: StructDef */` — a hard gcc
    error before the fold, a SILENT miscompile after it. The emission
    loop now runs over the same `_flatten_resolved_conditionals(stmts)`
    the Phase-1.7 scan uses (module_gen.py): the taken branch's
    statements dispatch as top-level statements, the other branch never
    emits, and an unresolved condition still falls through to the
    runtime-branch path unchanged.

    The asserts pin the REAL value, host-conditional: the live branch's
    `answer = 7` inlines as a genuine top-level global that `f()` reads
    back, so the binary prints `7` where CPython on the same text prints
    `7` (on a big-endianness host the live branch is the `answer = 8`
    one, and both the CPython run and the expected literal track the
    host's own `sys.byteorder`). Every regression route through the two
    pre-fix defects changes the observable: a fold regression re-emits
    BOTH branches and the later `answer = 8` wins (prints `8`); an
    emission-flatten regression leaves the IfStmt as a RUNTIME branch,
    which re-evaluates `sys.byteorder` at run time (`_mojo_dispatch_
    getattr(sys, "byteorder")` — AttributeError, the compiled stdlib's
    sys has no such attribute) and dies before printing anything. Pre-fix
    the tree cannot build this file at all (the single gcc error above;
    build/remes/r10d1_prefix_765117ff.log), so `rc == 0` is itself part of
    the pin and `stdout == py_stdout` is the outer one. The value is
    deliberately read off a PLAIN global rather than off the branch
    class: a plain assignment in the DEAD branch whose target is the live
    branch's class is what trips the pre-fix error, and on the fixed tree
    that same assignment claims the class's name as a value global in the
    name-claim view, diverting a static class-attribute read off that
    name to a dispatch on a NULL receiver (measured: `AttributeError: v`,
    isolated to that single element by four one-element probes). The class
    name used as a VALUE is a separate, documented, feature-sized
    zero-stub gap (this doc's own 2026-08-26 entry: `class ref X as value`
    → `(int64_t)0`) and is not pinned here."""
    pkg = {
        'main.py': (
            'import sys\n'
            '\n'
            '\n'
            'class Base:\n'
            '    pass\n'
            '\n'
            '\n'
            'if sys.byteorder == "little":\n'
            '    class BE(Base):\n'
            '        v = 1\n'
            '\n'
            '    answer = 7\n'
            '\n'
            'elif sys.byteorder == "big":\n'
            '    BE = Base\n'
            '\n'
            '    answer = 8\n'
            '\n'
            '\n'
            'def f():\n'
            '    return answer\n'
            '\n'
            '\n'
            'r = f()\n'
            '\n'
            '\n'
            'print(r)\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'main.py')
    exp = '7' if sys.byteorder == 'little' else '8'
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == exp)
    if not ok:
        print(f"  ✗ byteorder_conditional_toplevel_emits_only_the_host_branch: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_class_redefinition_does_not_crash_class_attr_emission() -> bool:
    """A SAME-HOME class redefinition whose LATER copy drops the class
    attribute must not crash the class-attr emission loop.

    `class Box:` defined twice in one module (Python: the second binding
    replaces the first), the first carrying `tag = 1`, the second bare. In
    gen_module_impl's struct-identity pass the second Box is a same-home
    redefinition, NOT a cross-module collision, so it gets no
    `_struct_cname_by_id` entry and keeps the bare name `Box`. The class-
    attr registration keys `tag` under the owner's (first Box's) name. The
    LATER class-attr EMISSION loop then walks the second, field-less Box
    with that same non-empty `_class_attrs['Box']` map:
    `_own_class_field_index([], 'tag') == -1`, and the old
    `range(-1, 0)` read `fields[-1]` on the empty list — a hard
    `IndexError: list index out of range` that killed the whole build.

    Measured: on BOTH `566ba1c9` (master) and `8c48013c` (the row-16 fix),
    this exact single-file shape died with `IndexError: list index out of
    range` at the emission's `field = _as_list(s.fields)[_pick]`, before
    producing any binary. The row-16 fix (failed-import rollback) did not
    introduce the bug — it un-poisoned the self-import guard so that whole-
    program closures (e.g. `Lib/importlib/resources/readers.py`) carried
    same-named class pairs into the shared stmt mirror and reached this loop
    77+ times, one per affected module; the minimal single-file shape above
    is the same crash with the closure stripped away.

    The fix is a `continue` when `_own_idx < 0`: a struct object that does
    not declare `aname` in its own `.fields` emits nothing for it (the
    owner, which does declare it, emits it once). This is the non-empty-
    `fields` no-op the old code already performed implicitly, minus the
    empty-list index. Asserting `1` (not just a clean build) pins the REAL
    value: `Box.tag` is read from the first Box's emitted class attribute
    before the redefinition replaces the binding — a vacuous pass would
    print `0` if the attribute were dropped."""
    pkg = {
        'main.py': (
            'class Box:\n'
            '    tag = 1\n'
            '\n'
            '\n'
            'def f():\n'
            '    return Box.tag\n'
            '\n'
            '\n'
            'r = f()\n'
            '\n'
            '\n'
            'class Box:\n'
            '    """redefinition, no class attributes"""\n'
            '\n'
            '\n'
            'print(r)\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'main.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '1')
    if not ok:
        print(f"  ✗ class_redefinition_does_not_crash_class_attr_emission: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_set_ctor_walks_boxed_global_container() -> bool:
    """A `set(...)` / `frozenset(...)` whose argument is a module-GLOBAL
    container must walk the container, not the boxed pointer word it is
    stored in. Globals are stored at C level as int64_t (boxed pointers);
    the read side hands the caller a raw int64_t temp with the real kind
    only recoverable via `_actual_types`. Every consumer of such a read
    must resolve the actual type and cast — `len()` had the arm
    (the `_actual_types` + `_coerce_to_type` block in
    `_lower_builtin_len`), but the set-constructor lowering
    (`_lower_ctor_from_iterable`'s `kind == 'set'` arm) substituted the
    ALREADY-lowered boxed temp as a plain name while registering
    `var_types[name] = <pointer type>` over int64_t storage: the
    comprehension's own cast block (the `_get_actual_type` one that fires
    when recorded type != actual type) never fired, because recorded ==
    actual, and the walk passed the word raw. Measured (2026-10-24,
    `fb774c7a`): `s = frozenset(names)` with a top-level
    `names = ['a', 'b']` died at gcc — `passing argument 1 of
    'mojo_list_len' makes pointer from integer` (build/remes/
    kw63_minprefix_fb774c7a.log); the real shape, `iskeyword =
    frozenset(kwlist).__contains__` in Lib/keyword.py:63, is the exact
    same pair (build/remes/kw63_keyword_prefix_fb774c7a.log — the new
    first gcc error on rows 6/22/24/25). The two siblings died in the same
    class: `set(<global dict>)` at `mojo_dict_iter_new` (build/remes/
    kw63_dictprefix_fb774c7a.log) and `frozenset(<global set>)` at
    `mojo_set_copy` (build/remes/kw63_setprefix_fb774c7a.log).

    The asserts pin the REAL values on all three arms of the fix, and the
    CPython comparison on the same text is the outer pin: `frozenset` of
    the 2-element list global, `set` of the 2-key dict global (Python
    iterates the KEYS), and `frozenset` of the set global (the slot-copy
    arm) all read back 2. Pre-fix the file cannot build at all (the gcc
    error above on the first boxed-global walk), so `rc == 0` is part of
    the pin; the no-false-green hazard here is a walk that COMPILES but
    iterates zero or garbage slots (the pre-R5 opaque fallback emitted an
    empty container) — the three lengths against CPython close that."""
    pkg = {
        'main.py': (
            'names = ["a", "b"]\n'
            '\n'
            '\n'
            'd = {"k1": 1, "k2": 2}\n'
            '\n'
            '\n'
            's0 = frozenset([9, 8])\n'
            '\n'
            '\n'
            'ks = frozenset(names)\n'
            '\n'
            '\n'
            'dk = set(d)\n'
            '\n'
            '\n'
            'cp = frozenset(s0)\n'
            '\n'
            '\n'
            'print(len(ks), len(dk), len(cp))\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'main.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '2 2 2')
    if not ok:
        print(f"  ✗ set_ctor_walks_boxed_global_container: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_nested_def_is_not_a_module_level_fn_export() -> bool:
    """A nested `def` (a closure inside a function body) must not be
    registered as a module-level function export by the importer's
    text scan. Measured 2026-10-24 as the `os_fsdecode`/`os_fsencode`
    0-arg-stub class on rows 10/24/25: in Lib/os.py, `fsencode`/
    `fsdecode` are nested defs inside a factory (`def _fscodec(): ...
    def fsdecode(filename): ...`), bound at module level by
    `fsencode, fsdecode = _fscodec()`; the scan's stripped-line `def `
    match used to register the nested def as a top-level export, and —
    because its parameter extraction keeps only ANNOTATED params
    (`if ':' in param`) while stdlib's nested defs are unannotated —
    the entry came out `int64_t fsdecode (void)`. The importer then
    emitted `extern int64_t os_fsdecode (void);` for `os.fsdecode(x)`:
    gcc's `too many arguments ... expected 0, have 1` at
    Lib/ntpath.py:317/373/387/461 and Lib/posixpath.py:266/278/325
    (11 lines in build/remes/r24post_kwfix.log; the pre-fix dump in
    build/remes/fsdec_ntpath_prefix_6b80a973.ci) — and the prototype
    was doubly wrong: the C function a nested def compiles to is named
    after the ENCLOSING function (closure_lifted_name: `outer_inner`),
    so the `module_name` symbol the extern names does not exist at
    all. The module-level binding is a VALUE, and its cross-module
    call belongs to the dynamic dispatch path, which refuses loudly.
    The fix is the indent block stack in module_loader's
    `_scan_source`: a `def`/`fn` whose innermost open block is a
    function is a nested closure and is skipped; module-level defs
    inside module-level control flow and class methods (innermost
    block 'other') register exactly as before, and the overload-
    COUNTING pre-pass deliberately still sees nested defs, so a
    module-level def that merely shares a name with a nested one keeps
    its measured variadic treatment byte for byte.

    The asserts: (1) the mechanism — the scan of the exact os.py shape
    must not export the nested `f`, and must still export the
    module-level factory `_mk`, a def under module-level control flow
    (`ctrl` under `if True:`), and a class method (`C.m`) — pre-fix
    the entry was `int64_t f (void)` (measured on os.py itself: the
    61-entry scan carried `fsdecode`/`fsencode` as `(void)`; the
    fixed scan is 55 entries). (2) The build-level same-name shadow —
    the exact os.py shape — builds and RUNS, now asserting CPython's
    real answer (42) for BOTH halves of the class. Pre-module-fix the
    build itself died at gcc with `too many arguments to function
    'a_os_f'; expected 0, have 1` (build/remes/fsdec_
    osname_prefix_765117ff.log). The module-side half — the enclosing
    `return f` resolving to the module GLOBAL `f` (the emitted C
    showed `_mk` reading `_root_globals.f`) — is FIXED 2026-10-24 in
    `module_shared.bare_global_read_plan` (assert (4) below; the C
    pair build/remes/shadow_modulefix_{prefix,postfix}_d20e7984.ci
    shows the body move to `_funcptr__mk_f`). Re-measured with that
    fix in, the binary STILL segfaulted with no output — the
    ENTRY-side call site: `a_os.f(41)` lowered to a NULL fnptr call
    (`_t2 = (int64_t)0; /* ct param or undeclared: f */` then
    `mojo_fnptr_call_1(NULL, 41)`). The function-object-value
    call-site half is FIXED 2026-10-24 in emit_methods' `_mgc` path:
    when the receiver module is compiled into the binary and the
    attribute is a `void *` (fnptr) global of that module, the call
    registers the module's synthesized
    `_<mod>__mojo_global_get_<attr>` accessor (the
    `_imported_global_accessors` table `_lower_IdentExpr` checks
    before the NULL placeholder) instead of the bare reconstruction
    falling to the placeholder — the postfix C pair for the current
    tree shows `_t2 = a_os__mojo_global_get_f ();` then
    `mojo_fnptr_call_1(_t2, _t3)`. This was the pin's known-bad
    crash-outcome; per the suite's pin rule the moment the shape
    stopped crashing the assertion flipped to CPython's value (42),
    re-measured against the CPython reference — a pin still asserting
    a crash on a non-crashing tree would be a false green in reverse.
    What this test does NOT yet cover: the non-shadow FROM-import
    spelling (`from a_ns import g; g(41)`) answers a silent 0 (weak
    extern stub) where CPython prints 42 — the false-green policy for
    that spelling is an owner decision, deliberately left unchanged.
    (3) The non-shadow MEMBER spelling (`g = _mk()`, the call
    `a_ns.g(41)`) must stay on the loud dispatch refusal — exit 1,
    stdout empty, stderr `Unhandled exception: NotImplementedError:
    ... not compiled into this binary` — and never on a silent
    numeric answer (CPython prints 42; a fix that compiled this shape
    to a quiet 0 would be the row-10-fold false-green this class is
    named for). (4) The module-side name resolution — the standalone
    compile of the shadow source's `_mk` body must read the LIFTED
    CLOSURE (`_funcptr__mk_f`) and must NOT read the module global
    (`_root_globals.f`): fixed 2026-10-24 in `module_shared.
    bare_global_read_plan` (a name locally bound by a nested `def` in
    the current function is local in real Python scoping; the global
    read must not win the bare read — the nested def never enters
    `var_types`, so the old local-shadowing escape could never see
    it). Pre-fix this assert fails on the global read; post-fix the
    body matches the non-shadow shape's (both resolve to the lifted
    closure) and the CPython answer for the module-side half is the
    function object itself — the value the lifted closure IS."""
    shadow_src = (
        'def _mk():\n'
        '    def f(x):\n'
        '        return x + 1\n'
        '    return f\n'
        'f = _mk()\n'
    )
    scan_src = (
        'def _mk():\n'
        '    def f(x):\n'
        '        return x + 1\n'
        '    return f\n'
        'f = _mk()\n'
        'if True:\n'
        '    def ctrl(x):\n'
        '        return x\n'
        'class C:\n'
        '    def m(self):\n'
        '        return 1\n'
    )
    exports = {}
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'a_os.py')
        with open(path, 'w') as fh:
            fh.write(scan_src)
        import module_loader
        exports = module_loader.load_module_from_path(path)
    nested_ok = (exports.get('f') is None and exports.get('_mk') is not None
                 and exports.get('ctrl') is not None
                 and exports.get('m') is not None)
    # (4) Module-side name resolution, fixed 2026-10-24 on tree d20e7984
    # (this assert is NEW with that fix; (2) below pins the runtime —
    # since the 2026-10-24 dispatch arm it asserts CPython's 42):
    # a bare read of a name locally bound by a nested `def` in the
    # ENCLOSING function itself must resolve to the nested def (its lifted
    # closure), not to a same-named module global. Measured pre-fix: the
    # `_mk` body emitted `_t1 = _root_globals.f;` (entry shape: `_a_os_
    # globals.f` at build/remes/shadow_modulefix_prefix_d20e7984.ci:1055) —
    # the global is still zero when `_mk` runs, so the value handed to the
    # caller is NULL; post-fix the body emits `_t1 = _funcptr__mk_f;`
    # (shadow_modulefix_postfix_d20e7984.ci:1057, the lifted closure
    # `closure_lifted_name` `_mk_f` behind the `_funcptr_` static). Root
    # cause, measured by a gen-table probe at the real call site (the
    # Intercepting `_callable_value_symbol` in the fix commit message): in
    # the shadow shape `bare_global_read_plan` answers gwins=True inside
    # `_mk` while the non-shadow shape answers gwins=False — and in BOTH
    # shapes `_callable_value_symbol` returns None and `_all_closures
    # ['_mk']['f']` is the lifted name `_mk_f`. The nested def NEVER enters
    # `var_types` (it is hoisted to its lifted C function; no C local is
    # declared for it in the enclosing body), so `bare_global_read_plan`'s
    # local-shadowing escape `(name in _func_declared_globals or name not in
    # var_types)` could never see it, and the same-named module global won
    # the bare read. The fix adds the one missing scope check: a name in
    # `_all_closures[current_func_name]` (this function's own nested defs)
    # is local in real Python scoping and the global read must not win —
    # `wins=False` routes the read to the `_closure_info_for_ident` arm that
    # already answers the non-shadow shape correctly (that arm is what
    # emitted `_funcptr__mk_f` before the fix — the two shapes' tables are
    # identical apart from the global's presence).
    module_side_ok = False
    mk_body = ''
    try:
        import gimple_codegen
        code = gimple_codegen.compile_to_gimple(shadow_src, do_imports=False,
                                                filename='a_os.py')
        i = code.index('void * _mk (void)\n{')
        mk_body = code[i:code.index('\n}', i)]
        module_side_ok = ('_funcptr__mk_f' in mk_body
                          and '_root_globals.f' not in mk_body)
    except Exception as e:
        mk_body = f'<exception {type(e).__name__}: {str(e)[:80]}>'
    pkg = {'a_os.py': shadow_src,
           'main.py': 'import a_os\nprint(a_os.f(41))\n'}
    binary_exists = False
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.py', td)
        binary_exists = os.path.exists(os.path.join(td, 'prog'))
    # Re-measured 2026-10-24 after the entry-side dispatch arm landed
    # (pre-arm on the current tree: rc == -11, no output — the crash
    # pin this assertion used to be): the shape no longer crashes, so
    # per the pin rule the assertion is CPython's real value (42).
    build_ok = rc == 0 and stdout.strip() == '42' and binary_exists
    pkg_ns = {'a_ns.py': shadow_src.replace('f = _mk()', 'g = _mk()'),
              'main_ns.py': 'import a_ns\nprint(a_ns.g(41))\n'}
    err_ns = ''
    with tempfile.TemporaryDirectory() as td:
        rc_ns, stdout_ns = _build_and_run(pkg_ns, 'main_ns.py', td)
        result = subprocess.run([os.path.join(td, 'prog')],
                                capture_output=True, text=True,
                                timeout=60, cwd=td)
        err_ns = result.stderr
    refusal_ok = (rc_ns == 1 and stdout_ns.strip() == ''
                  and err_ns.startswith(
                      'Unhandled exception: NotImplementedError:'))
    ok = nested_ok and build_ok and refusal_ok and module_side_ok
    if not ok:
        print(f"  ✗ nested_def_is_not_a_module_level_fn_export: "
              f"scan f={exports.get('f')!r} "
              f"_mk={'present' if exports.get('_mk') else 'MISSING'} "
              f"ctrl={'present' if exports.get('ctrl') else 'MISSING'} "
              f"m={'present' if exports.get('m') else 'MISSING'}; "
              f"shadow: rc={rc} stdout={stdout!r} binary={binary_exists}; "
              f"noshadow: rc={rc_ns} stdout={stdout_ns!r} "
              f"stderr={err_ns[:60]!r}; "
              f"module_side={module_side_ok} mk_body={mk_body[:120]!r}")
    return ok


def test_imported_function_trailing_default_argument_is_padded() -> bool:
    """Regression for `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`.

    `from lib import f; f(1)` where `lib.f(a, b=7)` must compile and print `8`,
    not the pre-fix "too few arguments to function 'lib_f' expected 2 have 1"
    GCC error. Root cause: `module_loader`'s text scan of the defining module
    built its `exports[name]` record from the C parameter list only, and the
    C list strips default values (`'String = ""'` -> `'String'`), so the
    record carried no defaults at all. The cross-module call padding in
    `_lower_named_call` consults `gen._func_param_defaults` for trailing
    defaults, and that table is populated by the DEFINING module's own
    `gen_module` pass — which never runs for an imported module compiled
    through the link-mode/inline path, so the pad site saw an empty list and
    emitted a 3-arg call against a 4-parameter prototype (the exact
    `compile_to_gimple(src, do_imports=False, filename=filename)` arity
    error that blocks `mojoc`).

    The fix is to record the defaulted parameter names in the export record
    at the scan site (the same AST-derived shape `module_spec_gen.py` and
    `gen_module`'s Pass 10 already use), so the importer's pad site has the
    defaults to pad from. Asserting CPython's real answer (8) pins the value;
    pre-fix the build itself fails at gcc, so `rc == 0` is part of the pin.
    """
    pkg = {
        'lib.py': 'def f(a, b=7):\n    return a + b\n',
        'main.py': (
            'from lib import f\n'
            'print(f(1))\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.py', td)
        py_rc, py_stdout = _cpython_run(td, 'main.py')
    ok = (rc == 0 and py_rc == 0 and stdout == py_stdout
          and stdout.strip() == '8')
    if not ok:
        print(f"  ✗ imported_function_trailing_default_argument_is_padded: "
              f"rc={rc} stdout={stdout!r} (CPython rc={py_rc} {py_stdout!r})")
    return ok


def test_string_argument_to_stringslice_param_is_wrapped_in_a_span() -> bool:
    """A String passed to a `StringSlice` parameter must reach the callee as a Span
    (the {_data, _len} fat pointer the callee reads), not as the bare char * that
    the call site used to cast to `Span *`.

    Before the fix, `get_sign(text)` lowered to `(Span *)(int64_t)text`: the callee
    read `x->_data` from the character bytes and segfaulted (exit 139, no output).
    The fix wraps the argument in a `_alloc_Span` whose _data and _len (mojo_strlen)
    describe the String. The expected value is `-1.0`, which real Mojo prints for
    this program (`tools/mojo run`, 2026-10-28). The branch sits before the generic
    `char *` -> pointer cast, which otherwise shadows it."""
    pkg = {
        'main.mojo': (
            'from std.collections.string import StringSlice\n'
            '\n'
            'def get_sign(x: StringSlice[_]) -> Tuple[Float64, type_of(x)]:\n'
            '    if x[byte=0] == "-":\n'
            '        return (-1.0, x[byte=1:])\n'
            '    return (1.0, x)\n'
            '\n'
            'def main():\n'
            '    var text = String("-abc")\n'
            '    var s = get_sign(text)\n'
            '    print(s[0])\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.mojo', td)
    ok = rc == 0 and stdout.strip() == '-1.0'
    if not ok:
        print(f"  ✗ string_argument_to_stringslice_param_is_wrapped_in_a_span: "
              f"rc={rc} stdout={stdout!r}")
    return ok


def test_same_module_call_to_generic_with_default_binds_instantiation() -> bool:
    """A same-module call to a module-level generic function, in a link-mode
    build, must bind the instantiation — not the weak "unavailable in compiled
    mode" extern stub (CODEGEN: cross-module call to a generic binds the stub).

    `use_a` in `gen.mojo` calls its OWN module's generic `pick` with the
    bracket parameter omitted: `pick(10)`, where `result_type` has the default
    `NoneType` and no argument can bind it. The link-mode build compiles
    `gen.mojo` as a module, which strips generic functions out of the emitted
    text and instantiates them per call site. The inferred elaboration declined
    (`infer_type_args` left `result_type` unbound although the template defaults
    it), so the call fell through to a bare `pick (10)` with no definition. The
    weak extern stub then answered, printing `pick: unavailable in compiled
    mode` into the program's stdout and returning 0 — a silent wrong answer
    with exit 0.

    Asserting the exact stdout pins both halves: `use_a()` must be 11 (the
    instantiated body), and the stub's diagnostic must not appear anywhere.
    `pick[Int](5)` from `main` already worked and stays pinned at 6.
    """
    pkg = {
        'gen.mojo': (
            '@inline(.always)\n'
            'def pick[result_type: AnyType = NoneType](x: Int) -> Int:\n'
            '    return x + 1\n'
            '\n'
            'def use_a() -> Int:\n'
            '    return pick(10)\n'
        ),
        'main.mojo': (
            'from gen import use_a, pick\n'
            '\n'
            'def main():\n'
            '    print(use_a())\n'
            '    print(pick[Int](5))\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'main.mojo', td)
    ok = (rc == 0 and stdout == '11\n6\n'
          and 'unavailable in compiled mode' not in stdout)
    if not ok:
        print(f"  ✗ same_module_call_to_generic_with_default_binds_instantiation: "
              f"rc={rc} stdout={stdout!r}")
    return ok


def test_two_modules_specialize_one_generic_differently() -> bool:
    """Regression test for bugs/CODEGEN_dylib_generic_inline_copies_share_one_symbol.md.

    Two modules instantiate the same generic function with DIFFERENT type
    arguments (`scale[2]` in `a`, `scale[3]` in `b`). The body depends on the
    parameter, so each caller must get its own specialization. Today every
    parameter, so each caller must get its own specialization. Before the fix
    the sibling generic was never registered in the inline do_imports=True
    path, so both bracketed calls lowered to a zero stub and printed `0`, a
    silent miscompile (CPython: 20 and 30)."""
    pkg = {
        'pkg/__init__.py': '',
        'pkg/gen.py': (
            'def scale[k: Int](x: Int) -> Int:\n'
            '    return x * k\n'
        ),
        'pkg/a.py': (
            'from pkg.gen import scale\n'
            '\n'
            'def fa() -> Int:\n'
            '    return scale[2](10)\n'
        ),
        'pkg/b.py': (
            'from pkg.gen import scale\n'
            '\n'
            'def fb() -> Int:\n'
            '    return scale[3](10)\n'
        ),
        'pkg/main.py': (
            'from pkg.a import fa\n'
            'from pkg.b import fb\n'
            '\n'
            'print(fa())\n'
            'print(fb())\n'
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        rc, stdout = _build_and_run(pkg, 'pkg/main.py', td)
    ok = rc == 0 and stdout == '20\n30\n'
    if not ok:
        print(f"  ✗ two_modules_specialize_one_generic_differently: rc={rc} "
              f"stdout={stdout!r} (expected '20\\n30\\n')")
    return ok


CASES = [
    test_nested_def_is_not_a_module_level_fn_export,
    test_set_ctor_walks_boxed_global_container,
    test_byteorder_conditional_toplevel_emits_only_the_host_branch,
    test_class_redefinition_does_not_crash_class_attr_emission,
    test_string_argument_to_stringslice_param_is_wrapped_in_a_span,
    test_transitive_struct_method_is_not_variadic_stubbed,
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
    test_bare_import_sibling_function_call_through_module,
    test_module_scoped_cross_module_struct_ctor_both_import_spellings,
    test_module_scoped_cross_module_ctor_arg_through_a_param,
    test_dotted_sibling_import_qualifier_agrees,
    test_builtin_open_is_not_ambiguous_from_transitive_siblings,
    test_unannotated_param_with_disagreeing_call_sites,
    test_failed_import_attempt_does_not_poison_later_spelling,
    test_imported_function_trailing_default_argument_is_padded,
    test_same_module_call_to_generic_with_default_binds_instantiation,
    test_two_modules_specialize_one_generic_differently,
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
