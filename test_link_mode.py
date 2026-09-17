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


CASES = [
    test_bare_submodule_import_value_read,
    test_bare_submodule_import_call,
    test_from_submodule_import_symbol_value_read,
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
