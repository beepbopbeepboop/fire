#!/usr/bin/env python3
"""Regression test: an imported function whose parameters are only PARTLY
annotated must get the DEFINER's arity on the importer's extern.

Bug (fixed 2026-11-12; the `CODEGEN_imported_function_extern_arity_mismatch
from_dropped_unannotated_params` bug doc was deleted with the fix):
`module_loader`'s text scan of a module's `def` line keeps only ANNOTATED
parameters (`if ':' in param`), so the importer's scanned signature is SHORTER
than the definition whenever any parameter is unannotated. The import-extern
preamble in `gen_module_impl` (mojo/backend_gimple/module_gen.py) re-typed that
parameter list only from the definer's committed `_home_def_param_types` store
(`definer_only=True`), which is empty in the ordinary single-module compile
(the definition is in another translation unit). The extern kept the dropped
arity while the call sites — whose mangled suffix comes from
`_effective_param_types` — passed the definer's argument count:

    error: too many arguments to function 'home_prefold_ab0ffa';
        expected 1, have 2
    error: passing argument 1 of 'home_prefold_ab0ffa' makes pointer from
        integer without a cast [-Wint-conversion]

The reduced instance is the doc's `gmi_prefold_toplevel_comptime` shape (one
unannotated leading parameter, one annotated list parameter): 1 scanned vs 2
defined. The importer is compiled through the single-module entry point the
doc sanctions (`build_stdlib_dylib.compile_module_to_c`) and the verdict is
`gcc -fgimple -Os -g -ftrivial-auto-var-init=zero`, per its Done-when.
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
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402

# `state` is the parameter the text scan drops (no annotation); `node_list`
# is the one it keeps. Exactly the 1-scanned-vs-2-defined shape.
HOME_SRC = (
    'def prefold(state, node_list: list) -> int:\n'
    '    total = state\n'
    '    for n in node_list:\n'
    '        total += n\n'
    '    return total\n'
)

MAIN_SRC = (
    'from home import prefold\n'
    '\n'
    'def go():\n'
    '    print(prefold(10, [1, 2, 3]))\n'
    '\n'
    'go()\n'
)


def _extern_params(c_text: str) -> str:
    """The parenthesised parameter list of the `home_prefold` extern."""
    m = re.search(
        r'^\s*extern\s+[\w* ]+?\s+home_prefold\w*\s*\(([^;]*)\)\s*;',
        c_text, re.M)
    return m.group(1) if m else ''


def main() -> int:
    gcc = find_gcc()
    failures = []
    with tempfile.TemporaryDirectory() as td:
        home_path = os.path.join(td, 'home.py')
        main_path = os.path.join(td, 'main.py')
        with open(home_path, 'w') as fh:
            fh.write(HOME_SRC)
        with open(main_path, 'w') as fh:
            fh.write(MAIN_SRC)

        # Oracle: the reduced program must itself be valid, or a compiler
        # refusal below would be a harness mistake.
        py = subprocess.run([sys.executable, main_path], capture_output=True,
                            text=True, cwd=td, timeout=RUN_TIMEOUT_S)
        if py.returncode != 0 or not py.stdout.strip():
            print(f"FAIL: CPython on the fixture exited {py.returncode} "
                  f"printing {py.stdout!r} ({py.stderr[:400]}) — the fixture "
                  f"itself is wrong, not the compiler")
            return 1
        want = py.stdout.strip()

        c_text = compile_module_to_c(MAIN_SRC, main_path, 'main')
        if not c_text or not c_text.strip():
            print("FAIL: compile_module_to_c produced no C")
            return 1

        # Non-vacuity: the fixture must fire the import-extern path. Without
        # this, the gcc verdict below could pass for the wrong reason.
        params = _extern_params(c_text)
        if not params:
            print("FAIL: no `extern ... home_prefold...` in the importer's C — "
                  "the fixture did not fire the import-extern path; the test "
                  "is vacuous")
            return 1
        print(f"  extern params: ({params})")

        # The extern must carry the DEFINER's two parameters, not the text
        # scan's one. A comma count is enough and reports the failure before
        # gcc's less specific message does.
        n_params = len([p for p in params.split(',') if p.strip()])
        if n_params != 2:
            failures.append(
                f"extern declares {n_params} parameter(s) ({params!r}); the "
                f"definition has 2 (the scan dropped the unannotated one)")

        c_file = os.path.join(td, 'main.gen.c')
        obj_file = os.path.join(td, 'main.gen.o')
        with open(c_file, 'w') as fh:
            fh.write(c_text)
        cc = subprocess.run(
            [gcc, '-fgimple', '-Os', '-g', '-ftrivial-auto-var-init=zero',
             '-I', str(ROOT / 'runtime'), '-c', c_file, '-o', obj_file],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if cc.returncode != 0:
            failures.append(
                "gcc -fgimple -Os -g -ftrivial-auto-var-init=zero rejected the "
                f"importer's C:\n{cc.stderr[:2000]}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  " + f)
        return 1

    print("PASS: imported partly-unannotated function kept the definer's "
          f"arity on the importer's extern; the importer's C compiles "
          f"(CPython oracle: {want!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
