#!/usr/bin/env python3
"""Regression test: an imported function whose annotated return resolves to a
multi-token pointer C type must keep that type on the importer's extern.

Bug: the 2026-11-12 self-host `fire.o` step broke with `assignment to
'char *' from 'int64_t' ... [-Wint-conversion]` inside `gen_module_impl`
(the bug doc `CODEGEN_gen_module_impl_char_pointer_assigned_from_int64`,
deleted with this fix per the tree's delete-on-fix convention). The
importer's import-extern preamble — the empty-parameter arm of the
import-extern block in `gen_module_impl` (mojo/backend_gimple/module_gen.py,
added by ea91ca4c8) — clobbered an already-resolved pointer return type to
`int64_t`. Its shape test
(`not any(c in _sig_ret for c in ('*', ' '))`) treated every multi-token C type
(`char *`, `MojoList *`) as "unresolved" and replaced it, although
`sym_info['c_return_type']` is the loader's RESOLVED C type (computed through
`_mojo_type_to_c`, which returns a valid C type or `int64_t` — never the raw
annotation). The importer then called the `int64_t`-typed extern and stored the
result into a local a `dict[str, str]` subscript store forces to `char *`, so
gcc rejected the unit:

    error: assignment to 'char *' from 'int64_t' {aka 'long long int'}
        makes pointer from integer without a cast [-Wint-conversion]

The real instance is `_forced = dispatch_table_global_ctype(check_name)` at
module_gen.py:16860 (`mojo.middle.types.dispatch_table_global_ctype` returns
`str | None`, externed `int64_t ... (int64_t)` instead of `char * ... (int64_t)`),
and the same store at 15372 (`self._global_c_decl_types[_gn] = _forced`,
`_global_c_decl_types` annotated `dict[str, str]` at gimple_codegen.py:2614) is
what forces `_forced` to `char *`.

The reduced program keeps that exact shape: the home module defines
`ctype(name) -> str | None` (ONE unannotated parameter, so the importer's text
scan resolves no parameter list and the empty-parameter arm fires; an annotated
`char *` return), and the importer assigns the call's result to a local that is
also stored into a `dict[str, str]`-typed module global (the same `char *`
forcing). The importer is compiled through the single-module entry point the
doc's Scope item 1 sanctions (`build_stdlib_dylib.compile_module_to_c`) and the
verdict is taken with `gcc -fgimple -Os -g -ftrivial-auto-var-init=zero` per
the doc's Acceptance. Pre-fix the generated extern read
`extern int64_t home_ctype_9f63a2 (int64_t);` and gcc failed with exactly the
doc's error; post-fix it reads `extern char * home_ctype_9f63a2 (int64_t);`
and the unit compiles.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from build_config import find_gcc  # noqa: E402
from build_stdlib_dylib import compile_module_to_c  # noqa: E402

HOME_SRC = (
    'def ctype(name) -> str | None:\n'
    '    if name == "x":\n'
    '        return "v"\n'
    '    return None\n'
)

MAIN_SRC = (
    'from home import ctype\n'
    '\n'
    'TABLE: dict[str, str] = {}\n'
    '\n'
    'def store(names):\n'
    '    _declared = {}\n'
    '    for name in names:\n'
    '        _forced = ctype(name)\n'
    '        if _forced is not None and name not in _declared:\n'
    '            _declared[name] = True\n'
    '            TABLE[name] = _forced\n'
    '\n'
    'def main():\n'
    '    store(["x", "y"])\n'
    '    print(TABLE["x"])\n'
    '\n'
    'main()\n'
)


def main() -> int:
    gcc = find_gcc()
    with tempfile.TemporaryDirectory() as td:
        home_path = os.path.join(td, 'home.py')
        main_path = os.path.join(td, 'main.py')
        with open(home_path, 'w') as fh:
            fh.write(HOME_SRC)
        with open(main_path, 'w') as fh:
            fh.write(MAIN_SRC)

        # Oracle: the reduced program must itself be valid, or the test
        # would report a compiler failure for a harness mistake.
        py = subprocess.run([sys.executable, main_path], capture_output=True,
                            text=True, cwd=td, timeout=60)
        if py.returncode != 0 or not py.stdout:
            print(f"FAIL: CPython on the fixture exited {py.returncode} "
                  f"printing {py.stdout!r} ({py.stderr[:400]}) — the fixture "
                  f"itself is wrong, not the compiler")
            return 1
        want = py.stdout

        c_text = compile_module_to_c(MAIN_SRC, main_path, 'main')
        if not c_text or not c_text.strip():
            print("FAIL: compile_module_to_c produced no C")
            return 1

        # Non-vacuity: the fixture must actually fire the import-extern
        # path (the imported `ctype` declared as an extern in the
        # importer's C). If import resolution ever stops reaching the
        # loader, the gcc verdict below would pass for the wrong reason.
        m = re.search(
            r'^(\s*extern\s+(?:[\w* ]+?)\s+home_ctype\w*\s*\([^;]*);', c_text,
            re.M)
        if not m:
            print("FAIL: no `extern ... home_ctype...` in the importer's C — "
                  "the fixture did not fire the import-extern path; the test "
                  "is vacuous")
            return 1
        print(f"  extern: {m.group(1).strip()}")

        c_file = os.path.join(td, 'main.gen.c')
        obj_file = os.path.join(td, 'main.gen.o')
        with open(c_file, 'w') as fh:
            fh.write(c_text)
        cc = subprocess.run(
            [gcc, '-fgimple', '-Os', '-g', '-ftrivial-auto-var-init=zero',
             '-I', str(ROOT / 'runtime'), '-c', c_file, '-o', obj_file],
            capture_output=True, text=True, timeout=300)
        if cc.returncode != 0:
            print(f"FAIL: gcc -fgimple -Os -g -ftrivial-auto-var-init=zero "
                  f"rejected the importer's C:\n{cc.stderr[:2000]}")
            return 1

    print("PASS: imported annotated `char *` return kept on the importer's "
          "extern; the importer's C compiles (CPython oracle: "
          f"{want.strip()!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
