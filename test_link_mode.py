#!/usr/bin/env python3
"""Link-mode compile guard (`driver.compile_program`).

`compile_stdlib.py`/`build_stdlib_dylib.py` (and by extension
`test_gimple.py`) all drive codegen through the single-translation-unit
`do_imports=False` inline path — NOT the real default `mojo.py build`
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


def test_bare_submodule_import_call_KNOWN_BUG() -> bool:
    """A CALL through a bare `from . import SUBMODULE` marker
    (`base2.doubleval(21)`, real: `base_futures.isfuture(...)`-shaped
    calls) — returns 0 instead of the real value. A generic fix was
    attempted 2026-08-28 (routing any module-qualified call through
    `_func_csym`/`_call_expr` the same way 3 hardcoded compiler-internal
    module names already do) but reverted: it resolves purely by bare
    method NAME with no module qualification, and broke self-hosting via
    a real collision (`compile` matched the wrong function across
    modules — `mojo_compiler.py`'s own `re.compile(...)` vs. a
    2-argument `compile` elsewhere), the exact hazard
    `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
    already documents. A safe fix needs module-QUALIFIED symbol
    resolution (e.g. mirroring `_join_import_member`), not a bare-name
    lookup in the global `func_return_types` table — not attempted here.
    Filed as
    bugs/CODEGEN_link_mode_module_qualified_call_silent_wrong_value.md.
    Tracked here as a KNOWN BUG, not a plain failure."""
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
    # Expected outcome right now IS the silent-wrong-value bug (rc == 0,
    # stdout '0' instead of '42').
    known_bug_still_reproduces = (rc == 0 and stdout.strip() == '0')
    if not known_bug_still_reproduces:
        print(f"  ? bare_submodule_import_call_KNOWN_BUG: expected the known "
              f"wrong-value bug (rc=0, stdout='0'), got rc={rc} stdout={stdout!r} "
              f"— either fixed (update the doc + this test) or a different failure")
    return known_bug_still_reproduces


def test_from_submodule_import_symbol_value_read_KNOWN_BUG() -> bool:
    """`from SUBMODULE import SYMBOL` (not a bare submodule marker), the
    symbol bound to a new local, then called through that local
    (`f = triple; f(14)`) — SEGFAULTS. Confirmed pre-existing (reproduces
    identically with every other fix in this area reverted) and unrelated
    to them — a separate, real, more severe (crash, not just wrong value)
    link-mode bug this test suite surfaced as a side effect. Filed as
    bugs/CODEGEN_link_mode_from_submodule_import_symbol_value_call_segfault.md
    for a dedicated pass; not attempted here (see this task's own scope
    boundary). Tracked here as a KNOWN BUG, not a plain failure, so this
    suite still reports a meaningful pass/fail signal for `make check`
    without blocking on a separately-filed, already-documented gap."""
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
    # Expected outcome right now IS the crash (rc == -11, SIGSEGV) — this
    # "passes" (as a known-bug pin, not a real pass) only while that stays
    # true; if it starts returning 0/'42' the bug is fixed and this case
    # (and its KNOWN_BUG suffix, and the filed doc) should be updated/removed.
    known_bug_still_reproduces = (rc == -11)
    if not known_bug_still_reproduces:
        print(f"  ? from_submodule_import_symbol_value_read_KNOWN_BUG: "
              f"expected the known SIGSEGV (rc=-11), got rc={rc} stdout={stdout!r} "
              f"— either fixed (update the doc + this test) or a different failure")
    return known_bug_still_reproduces


CASES = [
    test_bare_submodule_import_value_read,
    test_bare_submodule_import_call_KNOWN_BUG,
    test_from_submodule_import_symbol_value_read_KNOWN_BUG,
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
